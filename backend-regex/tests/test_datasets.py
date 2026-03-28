"""Tests for dataset loader helpers."""

from types import SimpleNamespace
import pytest

from app.ingest import datasets as datasets_module


def test_load_hf_dataset_without_dependency(monkeypatch):
    """Missing datasets dependency should raise a clear RuntimeError."""
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "datasets":
            raise ImportError("missing datasets")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError, match="datasets"):
        datasets_module.load_hf_dataset("kensho/FIND", split="validation")


def test_named_dataset_loaders(monkeypatch):
    """Named helpers should call load_hf_dataset with expected names/splits."""
    calls = []

    def fake_loader(name, split=None, **kwargs):
        calls.append((name, split, kwargs))
        return {"name": name, "split": split}

    monkeypatch.setattr(datasets_module, "load_hf_dataset", fake_loader)

    find = datasets_module.load_find_dataset()
    wiki = datasets_module.load_wikipedia_contradict()
    lb = datasets_module.load_longbench()

    assert find["name"] == "kensho/FIND"
    assert wiki["name"] == "ibm-research/Wikipedia_contradict_benchmark"
    assert lb["name"] == "yanbingzheng/LongBench"
    assert calls[0][1] == "validation"
    assert calls[1][1] == "train"
    assert calls[2][1] == "test"


def test_load_hf_dataset_uses_token_from_settings(monkeypatch):
    """HF token should be resolved from settings when not exported in process env."""
    captured = {}

    class _FakeDatasetsModule:
        @staticmethod
        def load_dataset(name, **kwargs):
            captured["name"] = name
            captured["kwargs"] = kwargs
            return {"ok": True}

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "datasets":
            return _FakeDatasetsModule
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_TOKEN", raising=False)
    monkeypatch.setattr(
        datasets_module,
        "get_settings",
        lambda: SimpleNamespace(hf_token="  \"hf_test_token\"  ", huggingface_hub_token=""),
    )

    datasets_module.load_hf_dataset("kensho/FIND", split="validation")

    assert captured["name"] == "kensho/FIND"
    assert captured["kwargs"]["split"] == "validation"
    assert captured["kwargs"]["token"] == "hf_test_token"
