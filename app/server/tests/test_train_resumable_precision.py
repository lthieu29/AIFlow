"""Exercise trainer configuration without importing CUDA or downloading weights."""

import argparse
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def trainer_configuration(tmp_path, monkeypatch, native_bf16, previous=None):
    source = Path(__file__).resolve().parents[2] / "colab/train_resumable.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls = []
    captured = {}

    def bf16_supported(including_emulation=True):
        calls.append(including_emulation)
        return True if including_emulation else native_bf16

    class ConfigurationCapturedError(Exception):
        pass

    def write_config(path, value):
        captured.update(value)
        raise ConfigurationCapturedError

    if previous is not None:
        (tmp_path / "trainer-config.json").write_text("{}", encoding="utf-8")
    namespace = {
        "argparse": argparse, "Path": Path, "sha256": lambda _: "dataset-sha",
        "version": lambda _: "pinned", "write_json": write_config, "read_json": lambda _: previous,
        "torch": SimpleNamespace(__version__="2.11.0+cu128", cuda=SimpleNamespace(is_bf16_supported=bf16_supported)),
    }
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), "exec"), namespace)
    monkeypatch.setattr(sys, "argv", ["train_resumable.py", "--run-dir", str(tmp_path), "--base", "pinned-base", "--epochs", "3"])
    if previous is None:
        with pytest.raises(ConfigurationCapturedError):
            namespace["main"]()
    else:
        with pytest.raises(RuntimeError, match="precision"):
            namespace["main"]()
    assert calls == [False]
    return captured


@pytest.mark.parametrize("native_bf16", [False, True], ids=["t4-emulation-only", "native-bf16"])
def test_trainer_uses_only_native_bf16_support(tmp_path, monkeypatch, native_bf16):
    configuration = trainer_configuration(tmp_path, monkeypatch, native_bf16)
    assert configuration["bf16"] is native_bf16


def test_previous_emulated_bf16_checkpoint_requires_fresh_run(tmp_path, monkeypatch):
    configuration = trainer_configuration(tmp_path, monkeypatch, False)
    configuration["bf16"] = True
    trainer_configuration(tmp_path, monkeypatch, False, previous=configuration)
