"""Verify the Transformers 5 embedding contract before PEFT attaches adapters.

The pinned VieNeu model calls its shared embedding text_embeddings, while
Transformers 5.13.1 EmbeddingAccessMixin defaults to embed_tokens. No GPU required.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_trainer_exposes_shared_frozen_embedding_before_peft_checkpoint_hook():
    source = Path(__file__).resolve().parents[2] / "colab/train_resumable.py"
    main = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    start = next(i for i, node in enumerate(main.body) if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                 and node.value.func.id == "load_v3_turbo_checkpoint")
    stop = next(i for i, node in enumerate(main.body) if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "attach_lora")
    calls = []

    class Parameter:
        requires_grad = True

        def requires_grad_(self, value):
            self.requires_grad = value

    class Embedding:
        def __init__(self):
            self.weight = Parameter()
            self.hooks = []

        def parameters(self):
            return iter([self.weight])

        def register_forward_hook(self, hook):
            self.hooks.append(hook)

    class Model:
        def __init__(self):
            self.config = SimpleNamespace(use_cache=True)
            self.text_embeddings = Embedding()
            self.semantic_backbone = SimpleNamespace(
                embed_tokens=self.text_embeddings,
                gradient_checkpointing_enable=lambda: calls.append("checkpointing"))

        def parameters(self):
            return self.text_embeddings.parameters()

        def get_input_embeddings(self):
            # Relevant supported Transformers EmbeddingAccessMixin fallback.
            name = getattr(self, "_input_embed_layer", "embed_tokens")
            if hasattr(self, name):
                return getattr(self, name)
            raise NotImplementedError("get_input_embeddings not auto-handled")

        def enable_input_require_grads(self):
            self.get_input_embeddings().register_forward_hook(
                lambda module, inputs, output: output.requires_grad_(True))

    model = Model()
    embedding, weight = model.text_embeddings, model.text_embeddings.weight
    with pytest.raises(NotImplementedError):
        model.get_input_embeddings()

    def attach(loaded, **kwargs):
        assert loaded is model
        assert calls == ["checkpointing"]
        assert loaded.get_input_embeddings() is loaded.semantic_backbone.embed_tokens is embedding
        assert list(loaded.get_input_embeddings().parameters()) == [weight]
        assert not weight.requires_grad
        # PEFT invokes the inherited input-gradient hook for checkpointed models.
        loaded.enable_input_require_grads()
        calls.append("attach")
        return object()

    namespace = {"args": SimpleNamespace(base="pinned-local-base"),
                 "load_v3_turbo_checkpoint": lambda *args, **kwargs: model,
                 "torch": SimpleNamespace(float32=object()), "attach_lora": attach}
    exec(compile(ast.Module(body=main.body[start:stop+1], type_ignores=[]), str(source), "exec"), namespace)
    assert calls == ["checkpointing", "attach"]
    assert model.text_embeddings is embedding and embedding.weight is weight
    output = Parameter()
    output.requires_grad_(False)
    embedding.hooks[0](embedding, (), output)
    assert output.requires_grad
    assert not weight.requires_grad
    assert not model.config.use_cache
