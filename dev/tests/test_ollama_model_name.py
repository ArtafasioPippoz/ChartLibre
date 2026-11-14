"""Ollama: a model name typed without its tag is the installed model that has one; a model too big warns."""
from __future__ import annotations

from app.ai_providers import ollama_provider
from app.ai_providers.ollama_provider import OllamaProvider


def _provider(monkeypatch, installed: list[str], accurate: str) -> OllamaProvider:
    provider = OllamaProvider()
    monkeypatch.setattr(OllamaProvider, "installed", lambda self: list(installed))
    monkeypatch.setattr(OllamaProvider, "_installed_cache", None, raising=False)
    monkeypatch.setattr(OllamaProvider, "option", lambda self, key: {"accurate_model": accurate}.get(key, ""))
    return provider


def test_a_name_without_its_tag_finds_the_one_installed_tag(monkeypatch) -> None:
    provider = _provider(monkeypatch, ["llama3.2:latest", "qwen3.8:27b"], "qwen3.8")
    assert provider.models()["accurate"] == "qwen3.8:27b"
    assert "Not installed" not in provider.check("")


def test_exact_latest_and_unknown_names_are_left_alone(monkeypatch) -> None:
    for name, expected in (("llama3.2", "llama3.2"), ("llama3.2:latest", "llama3.2:latest"),
                           ("mistral", "mistral"), ("qwen3.8:27b", "qwen3.8:27b")):
        provider = _provider(monkeypatch, ["llama3.2:latest", "qwen3.8:27b"], name)
        assert provider.models()["accurate"] == expected


def test_two_tags_of_a_name_are_not_guessed(monkeypatch) -> None:
    provider = _provider(monkeypatch, ["qwen3.8:27b", "qwen3.8:7b"], "qwen3.8")
    assert provider.models()["accurate"] == "qwen3.8"
    assert "Not installed" in provider.check("")


def test_a_model_far_bigger_than_the_memory_is_warned_about(monkeypatch) -> None:
    provider = _provider(monkeypatch, ["qwen3.8:27b"], "qwen3.8")
    monkeypatch.setattr(ollama_provider, "get_json", lambda url, **kw: {"models": [
        {"name": "qwen3.8:27b", "size": 18 * 2**30}]})
    monkeypatch.setattr(ollama_provider.os, "sysconf", lambda name: 2**30 if name == "SC_PAGE_SIZE" else 8)
    assert "takes 18.0 GB of this computer's 8 GB" in provider.check("")
