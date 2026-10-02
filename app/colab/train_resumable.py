"""Colab LoRA trainer with full optimizer-boundary checkpoints, using pinned VieNeu primitives."""
import argparse
import math
import random
import sys
from importlib.metadata import version
from pathlib import Path
import numpy as np
import torch
from voice_training import UPSTREAM, read_json, write_json, sha256

sys.path.insert(0, str(UPSTREAM / "src"))
sys.path.insert(0, str(UPSTREAM / "finetune"))
from vieneu_lora import V3TurboLoraDataset, attach_lora, compute_loss, load_rows, save_adapter
from vieneu_lora.lora import export_merged, merge_lora_into
from vieneu._v3_turbo_engine.hub_load_v3_turbo import load_v3_turbo_checkpoint
from transformers import AutoTokenizer, get_scheduler
from peft import get_peft_model_state_dict, set_peft_model_state_dict

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--epochs", type=int, required=True)
    args = parser.parse_args()
    folder = Path(args.run_dir)
    data = folder / "train.parquet"
    config = {"format": 1, "epochs": args.epochs, "data_sha256": sha256(data), "base": args.base,
              "batch": 1, "accumulation": 16, "lr": 0.0002, "seed": 42,
              "torch": str(torch.__version__), "bf16": torch.cuda.is_bf16_supported(),
              "packages": {name: version(name) for name in ("transformers", "peft", "numpy", "safetensors", "pyarrow")}}
    path = folder / "trainer-state.pt"
    if (folder / "trainer-config.json").exists() and read_json(folder / "trainer-config.json") != config:
        raise RuntimeError("Dataset, base, epochs, precision hoặc môi trường đã đổi. Dùng đúng cấu hình để resume.")
    write_json(folder / "trainer-config.json", config)
    (folder / "environment.txt").write_text("\n".join(f"{name}=={value}" for name, value in {"torch": config["torch"], **config["packages"]}.items()), encoding="utf-8")
    random.seed(42); np.random.seed(42); torch.manual_seed(42); torch.cuda.manual_seed_all(42)
    tokenizer = AutoTokenizer.from_pretrained(args.base, subfolder="update", trust_remote_code=True)
    model = load_v3_turbo_checkpoint(args.base, subfolder="update", device="cuda", dtype=torch.float32)
    model.config.use_cache = False
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.semantic_backbone.gradient_checkpointing_enable()
    peft = attach_lora(model, r=16, alpha=32, dropout=0.05, target="backbone")
    rows = load_rows(data)
    np.random.default_rng(42).shuffle(rows)
    eval_count = max(1, int(len(rows) * 0.03))
    train_data = V3TurboLoraDataset(rows[eval_count:], tokenizer, model.config, max_length=1024)
    eval_data = V3TurboLoraDataset(rows[:eval_count], tokenizer, model.config, max_length=1024)
    if len(train_data) + len(eval_data) != len(rows):
        raise RuntimeError("Dataset có đoạn vượt giới hạn token. Sửa/chia đoạn và duyệt lại, không âm thầm bỏ.")
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=config["lr"], weight_decay=0.01, betas=(0.9, 0.95))
    steps_per_epoch = math.ceil(len(train_data) / config["accumulation"])
    total = steps_per_epoch * args.epochs
    scheduler = get_scheduler("cosine", optimizer, num_warmup_steps=int(total * 0.05), num_training_steps=total)
    epoch, offset, step = 0, 0, 0
    if path.exists():
        # Only our own checkpoint under the private Drive run directory is loaded.
        state = torch.load(path, map_location="cpu", weights_only=False)
        if state["config"] != config:
            raise RuntimeError("Checkpoint không khớp cấu hình.")
        set_peft_model_state_dict(peft, state["adapter"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        epoch, offset, step = state["epoch"], state["offset"], state["step"]
        random.setstate(state["python_rng"]); np.random.set_state(state["numpy_rng"])
        torch.set_rng_state(state["torch_rng"]); torch.cuda.set_rng_state_all(state["cuda_rng"])

    def checkpoint(next_epoch, next_offset):
        state = {"config": config, "adapter": {k: v.detach().cpu().clone() for k, v in get_peft_model_state_dict(peft).items()},
                 "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                 "epoch": next_epoch, "offset": next_offset, "step": step,
                 "python_rng": random.getstate(), "numpy_rng": np.random.get_state(),
                 "torch_rng": torch.get_rng_state(), "cuda_rng": torch.cuda.get_rng_state_all()}
        temporary = path.with_suffix(".tmp")
        torch.save(state, temporary)
        temporary.replace(path)
        write_json(folder / "progress.json", {"step": step, "total_steps": total, "epoch": next_epoch,
                                               "next_sample": next_offset, "checkpoint": True})

    optimizer.zero_grad(set_to_none=True)
    model.train()
    for ep in range(epoch, args.epochs):
        order = np.random.default_rng(42 + ep).permutation(len(train_data)).tolist()
        start = offset if ep == epoch else 0
        for group_start in range(start, len(order), config["accumulation"]):
            indices = order[group_start:group_start + config["accumulation"]]
            losses = []
            for idx in indices:
                batch = {k: v.to("cuda") for k, v in train_data.collate([train_data[idx]]).items()}
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=config["bf16"]):
                    loss, _ = compute_loss(model, batch, 1.0, 8.0)
                if not torch.isfinite(loss):
                    raise RuntimeError("Loss không hữu hạn. Giữ checkpoint trước, kiểm tra dữ liệu.")
                (loss / len(indices)).backward()
                losses.append(float(loss.detach()))
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step(); scheduler.step(); optimizer.zero_grad(set_to_none=True)
            step += 1
            next_offset = group_start + len(indices)
            checkpoint(ep + 1 if next_offset == len(order) else ep, 0 if next_offset == len(order) else next_offset)
            print(f"step {step}/{total} loss {sum(losses)/len(losses):.4f}", flush=True)
            if (folder.parent.parent / "cancel.request").exists():
                raise RuntimeError("Đã dừng ở checkpoint đầy đủ. Có thể resume cùng run.")
        model.eval()
        with torch.no_grad():
            values = []
            for idx in range(len(eval_data)):
                batch = {k: v.to("cuda") for k, v in eval_data.collate([eval_data[idx]]).items()}
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=config["bf16"]):
                    loss, _ = compute_loss(model, batch, 1.0, 8.0)
                values.append(float(loss))
            write_json(folder / f"evaluation-{ep+1}.json", {"epoch": ep+1, "loss": sum(values)/len(values)})
        model.train()
        # Eval must not alter the RNG boundary used by the saved checkpoint.
        checkpoint(ep + 1, 0)
    save_adapter(peft, folder / "adapter", tokenizer)
    export_merged(merge_lora_into(peft), tokenizer, args.base, folder / "merged", subfolder="update")

if __name__ == "__main__":
    main()
