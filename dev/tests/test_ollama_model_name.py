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


def test_the_models_are_a_drop_down_list_of_what_ollama_has(qapp, monkeypatch) -> None:
    from app.dialogs.settings_dialog import SettingsDialog, _EditableChoice
    from app.plugin_api.ai import http_chat

    # The provider classes are loaded from their files afresh: the HTTP helper they import is the one to replace.
    monkeypatch.setattr(http_chat, "get_json", lambda url, **kw: {"models": [{"name": "llama3.2:latest"},
                                                                          {"name": "qwen2.5:3b"}], "version": "x"})
    dialog = SettingsDialog(None)
    edit, _value = dialog._assistant_options["Ollama"]["accurate_model"]
    assert isinstance(edit, _EditableChoice)
    assert [edit.itemText(i) for i in range(edit.count())] == ["", "llama3.2:latest", "qwen2.5:3b"]
    edit.setText("qwen2.5:3b")
    assert edit.text() == "qwen2.5:3b"
    address, _value = dialog._assistant_options["Ollama"]["address"]
    assert not isinstance(address, _EditableChoice)  # the address stays a line
    dialog.done(0)


def test_with_ollama_off_there_are_no_choices_and_the_models_stay_lines(monkeypatch) -> None:
    from app.plugin_api.ai.http_chat import ProviderHTTPError

    def fail(self):
        raise ProviderHTTPError("down")

    monkeypatch.setattr(OllamaProvider, "installed", fail)
    provider = OllamaProvider()
    assert provider.option_choices("accurate_model") == [] and provider.option_choices("fast_model") == []
