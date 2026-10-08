"""Offline legacy notebook contracts; no models, GPU work or training data approval."""
import ast
import json
import runpy
import shutil
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

CELLS = Path(__file__).resolve().parents[2] / "colab/cells"


class Tensor:
    def __init__(self, values): self.values = list(values)
    def __len__(self): return len(self.values)
    def __getitem__(self, key):
        value = self.values[key]
        return Tensor(value) if isinstance(key, slice) else value
    def __setitem__(self, key, value):
        if isinstance(key, Tensor):
            for index, selected in enumerate(key.values):
                if selected: self.values[index] = value
        else:
            self.values[key] = value.values if isinstance(value, Tensor) else value
    def __eq__(self, value): return Tensor(item == value for item in self.values)
    def __ne__(self, value): return Tensor(item != value for item in self.values)
    def nonzero(self, as_tuple=False):
        return ([index for index, value in enumerate(self.values) if value],)
    def long(self): return Tensor(int(value) for value in self.values)
    def tolist(self): return self.values


def preprocess():
    tree = ast.parse((CELLS / "04e_train_loop.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_preprocess")
    fake_torch = SimpleNamespace(long=int, tensor=lambda values, dtype: Tensor(values),
                                 full_like=lambda values, fill: Tensor([fill] * len(values)))
    namespace = {"torch": fake_torch}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "legacy-preprocess", "exec"), namespace)
    return namespace["_preprocess"]


def test_padding_is_excluded_from_training_labels():
    tokenizer = SimpleNamespace(pad_token_id=0, encode=lambda text: [1, 2, 3],
                                convert_tokens_to_ids=lambda token: 2)
    result = preprocess()({"phones": "test", "codes": [1]}, tokenizer, max_len=6)
    assert result["labels"].tolist() == [-100, 2, 3, -100, -100, -100]
    assert result["attention_mask"].tolist() == [1, 1, 1, 0, 0, 0]


def test_long_encoded_audio_cannot_silently_truncate_training_labels():
    tokenizer = SimpleNamespace(pad_token_id=0, encode=lambda text: list(range(8)),
                                convert_tokens_to_ids=lambda token: 2)
    with pytest.raises(ValueError, match="token"):
        preprocess()({"phones": "test", "codes": [1]}, tokenizer, max_len=6)


def test_missing_speech_boundary_cannot_create_all_masked_labels():
    tokenizer = SimpleNamespace(pad_token_id=0, encode=lambda text: [1, 3],
                                convert_tokens_to_ids=lambda token: 2)
    with pytest.raises(ValueError, match="Tokenizer"):
        preprocess()({"phones": "test", "codes": [1]}, tokenizer, max_len=6)


def resume_checkpoint():
    tree = ast.parse((CELLS / "04e_train_loop.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_resume_checkpoint")
    namespace = {"json": json}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "legacy-resume", "exec"), namespace)
    return namespace["_resume_checkpoint"]


def test_compatible_resume_selects_latest_checkpoint(tmp_path):
    identity = {"dataset_sha256": "original", "base_model": "base", "hyperparams": {"lr": .01}, "precision": "fp32"}
    resume = resume_checkpoint()
    assert resume(tmp_path, identity) is None
    (tmp_path / "checkpoint-500").mkdir()
    (tmp_path / "checkpoint-1000").mkdir()
    assert resume(tmp_path, identity) == str(tmp_path / "checkpoint-1000")


@pytest.mark.parametrize("field, changed", [("dataset_sha256", "different"), ("base_model", "other"),
                                          ("hyperparams", {"lr": .02}), ("precision", "bf16")])
def test_changed_resume_provenance_preserves_checkpoint_and_refuses_resume(tmp_path, field, changed):
    identity = {"dataset_sha256": "original", "base_model": "base", "hyperparams": {"lr": .01}, "precision": "fp32"}
    resume = resume_checkpoint()
    resume(tmp_path, identity)
    checkpoint = tmp_path / "checkpoint-500"
    checkpoint.mkdir()
    (checkpoint / "weights.bin").write_bytes(b"preserve")
    before = (tmp_path / "resume-identity.json").read_bytes()
    with pytest.raises(RuntimeError, match="Voice ID"):
        resume(tmp_path, {**identity, field: changed})
    assert (checkpoint / "weights.bin").read_bytes() == b"preserve"
    assert (tmp_path / "resume-identity.json").read_bytes() == before


def test_old_checkpoint_without_provenance_cannot_auto_resume(tmp_path):
    checkpoint = tmp_path / "checkpoint-500"
    checkpoint.mkdir()
    with pytest.raises(RuntimeError, match="thiếu provenance"):
        resume_checkpoint()(tmp_path, {"dataset_sha256": "current"})
    assert checkpoint.is_dir()
    assert not (tmp_path / "resume-identity.json").exists()


def test_vram_cleanup_removes_notebook_globals_and_shared_state_references(monkeypatch):
    # The preceding %run cells assign these names at top level, as well as in _state.
    markers = {name: object() for name in ("model", "trainer", "tokenizer")}
    state = {"lora_model": markers["model"], "base_model": markers["model"],
             "trainer": markers["trainer"], "tokenizer": markers["tokenizer"]}
    monkeypatch.setitem(sys.modules, "cells._shared", SimpleNamespace(_state=state))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    notebook_namespace = dict(markers)
    monkeypatch.setitem(sys.modules, "IPython", SimpleNamespace(get_ipython=lambda: SimpleNamespace(user_ns=notebook_namespace)))
    namespace = {}
    source = (CELLS / "04h_cleanup_vram.py").read_text(encoding="utf-8")
    exec(compile(source, "notebook-cleanup", "exec"), namespace)
    assert not state
    assert not any(name in notebook_namespace for name in markers)


@pytest.mark.parametrize("supported, expected", [(False, "fp32"), (True, "bf16")])
def test_model_precision_tracks_hardware_support(monkeypatch, supported, expected):
    cuda = SimpleNamespace(is_bf16_supported=Mock(return_value=supported))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda, bfloat16="bf16", float32="fp32"))
    model = SimpleNamespace(device="cuda", parameters=lambda: iter([SimpleNamespace(dtype=expected)]))
    load = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(
        AutoModelForCausalLM=SimpleNamespace(from_pretrained=load),
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda _: SimpleNamespace(pad_token="pad", __len__=lambda: 8))))
    class Tokenizer:
        pad_token = "pad"
        def __len__(self): return 8
    sys.modules["transformers"].AutoTokenizer.from_pretrained = lambda _: Tokenizer()
    monkeypatch.setitem(sys.modules, "cells._shared", SimpleNamespace(
        BASE_MODEL="test", RUNTIME={"type": "gpu"}, _state={"mode": "lora"},
        banner=lambda *args: None, require_state=lambda *args: None))
    runpy.run_path(str(CELLS / "04c_load_base_model.py"))
    assert load.call_args.kwargs["dtype"] == expected
    cuda.is_bf16_supported.assert_called_once_with(including_emulation=False)


def test_transcript_paths_do_not_write_outside_audio_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with zipfile.ZipFile("dataset.zip", "w") as archive:
        archive.writestr("transcript.csv", "../outside.wav|hello\n")
    raw = tmp_path / "dataset/raw_audio"
    convert = Mock()
    def reset_dir(path):
        if path.exists(): shutil.rmtree(path)
        path.mkdir(parents=True)
    monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace(files=SimpleNamespace(
        upload=lambda: {"dataset.zip": b"uploaded"})))
    monkeypatch.setitem(sys.modules, "cells._shared", SimpleNamespace(
        DATASET_DIR=raw.parent, RAW_AUDIO_DIR=raw, WORK_DIR=tmp_path, _state={},
        banner=lambda *args: None, ensure_16khz_mono=convert, reset_dir=reset_dir,
        validate_audio_file=lambda _: {"duration": 5}))
    with pytest.raises(SystemExit, match="audio/transcript"):
        runpy.run_path(str(CELLS / "02b_upload_path_a.py"))
    convert.assert_not_called()
    assert not (raw.parent / "outside.wav").exists()
