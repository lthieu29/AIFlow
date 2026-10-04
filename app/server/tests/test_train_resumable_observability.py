"""Exercise the real optimizer boundary without CUDA or model downloads."""

import ast
import json
import math
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


def optimizer_boundary(tmp_path, grad_norm):
    source = Path(__file__).resolve().parents[2] / "colab/train_resumable.py"
    main = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    loop = next(node for node in ast.walk(main) if isinstance(node, ast.For)
                and isinstance(node.target, ast.Name) and node.target.id == "group_start")
    checkpoint = next(node for node in main.body if isinstance(node, ast.FunctionDef)
                      and node.name == "checkpoint")
    progress = next(node for node in checkpoint.body if isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "write_json")
    calls = []

    class Loss:
        def __init__(self, value):
            self.value = value

        def __float__(self):
            return float(self.value)

        def detach(self):
            return self

        def __truediv__(self, divisor):
            return Loss(self.value / divisor)

        def backward(self):
            calls.append(("backward", self.value))

    dataset = SimpleNamespace(collate=lambda _: {})
    measured = iter([(Loss(2), {"text_loss": 1.0, "audio_loss": 3.0, "acc_cb0": 0.2}),
                     (Loss(4), {"text_loss": 3.0, "audio_loss": 5.0, "acc_cb0": 0.4})])
    namespace = {
        "order": [0, 1], "start": 0, "config": {"accumulation": 16, "bf16": False},
        "train_data": dataset, "model": object(), "params": [object()],
        "compute_loss": lambda *_: next(measured), "step": 0, "total": 1, "ep": 0,
        "folder": tmp_path, "torch": SimpleNamespace(
            autocast=lambda *_, **__: nullcontext(), bfloat16=object(),
            isfinite=lambda value: math.isfinite(float(value)),
            nn=SimpleNamespace(utils=SimpleNamespace(clip_grad_norm_=lambda *_: grad_norm))),
        "optimizer": SimpleNamespace(step=lambda: calls.append("optimizer"),
                                     zero_grad=lambda **_: None),
        "scheduler": SimpleNamespace(step=lambda: calls.append("scheduler")),
        "write_json": lambda path, value: path.write_text(json.dumps(value), encoding="utf-8"),
    }
    # Preserve the production progress dictionary instead of recreating its fields in a mock.
    progress_code = compile(ast.Module(body=[progress], type_ignores=[]), str(source), "exec")

    def write_checkpoint(next_epoch, next_offset):
        namespace.update(next_epoch=next_epoch, next_offset=next_offset)
        exec(progress_code, namespace)

    class Dataset:
        collate = staticmethod(dataset.collate)

        def __getitem__(self, index):
            return index

    namespace["train_data"] = Dataset()
    namespace["checkpoint"] = write_checkpoint
    code = compile(ast.Module(body=[loop], type_ignores=[]), str(source), "exec")
    return lambda: exec(code, namespace), calls


@pytest.mark.parametrize("grad_norm", [0.25, 0.0], ids=["finite-nonzero", "zero-allowed"])
def test_optimizer_step_records_actual_mean_metrics_and_gradient_norm(tmp_path, capsys, grad_norm):
    run, calls = optimizer_boundary(tmp_path, grad_norm)
    run()
    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert progress == {"step": 1, "total_steps": 1, "epoch": 1, "next_sample": 0,
                        "checkpoint": True, "last_mean_loss": 3.0, "text_loss": 2.0,
                        "audio_loss": 4.0, "acc_cb0": pytest.approx(0.3),
                        "grad_norm": grad_norm, "nonzero_gradients": grad_norm > 0}
    assert calls == [("backward", 1.0), ("backward", 2.0), "optimizer", "scheduler"]
    log = capsys.readouterr().out
    assert "loss 3.0000 text_loss 2.0000 audio_loss 4.0000 acc_cb0 0.3000" in log
    assert f"nonzero_gradients {grad_norm > 0}" in log


@pytest.mark.parametrize("grad_norm", [float("nan"), float("inf")])
def test_nonfinite_gradient_stops_before_optimizer_and_checkpoint(tmp_path, grad_norm):
    run, calls = optimizer_boundary(tmp_path, grad_norm)
    with pytest.raises(RuntimeError, match="Gradient không hữu hạn"):
        run()
    assert "optimizer" not in calls
    assert "scheduler" not in calls
    assert not (tmp_path / "progress.json").exists()
