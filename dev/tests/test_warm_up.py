"""The warm-up imports the scientific libraries on the main thread, never on one of its own."""
from __future__ import annotations

import threading

from app.utils import warm_up


def test_the_warm_up_imports_on_the_calling_thread_one_module_per_turn(qapp, monkeypatch) -> None:
    """A warm-up thread, mid-import while the window was shown, crashed PySide6 (2026-11-11)."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(warm_up, "MODULES", ("json", "csv", "html"))
    monkeypatch.setattr(warm_up, "PAUSE_MS", 0)
    monkeypatch.setattr(warm_up, "_started", False)
    monkeypatch.setattr(warm_up, "_pending", [])
    monkeypatch.setattr(warm_up.importlib, "import_module",
                        lambda name: seen.append((name, threading.current_thread().name)))
    threads_before = threading.active_count()

    warm_up.warm_up_gradually()
    assert [name for name, _thread in seen] == ["json"]  # one now, the rest when the event loop turns
    assert threading.active_count() == threads_before  # no thread of its own
    for _turn in range(10):
        qapp.processEvents()
    assert [name for name, _thread in seen] == ["json", "csv", "html"]
    assert {thread for _name, thread in seen} == {threading.current_thread().name}

    warm_up.warm_up_gradually()  # once per process
    assert len(seen) == 3


def test_finish_now_imports_what_is_left_before_a_worker_starts(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(warm_up, "MODULES", ("json", "csv"))
    monkeypatch.setattr(warm_up, "_started", False)
    monkeypatch.setattr(warm_up, "_pending", [])
    monkeypatch.setattr(warm_up.importlib, "import_module", seen.append)
    warm_up.finish_now()
    assert seen == ["json", "csv"]
    warm_up.finish_now()
    assert seen == ["json", "csv"]
