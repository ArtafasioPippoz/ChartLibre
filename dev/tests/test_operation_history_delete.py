"""Project history: Delete forgets the listed operations, after a confirmation."""
from __future__ import annotations

from app.data.sqlite_repo import SqliteRepo
from app.dialogs import operation_history_dialog as module
from app.dialogs.operation_history_dialog import OperationHistoryDialog


def _record(repo: SqliteRepo, name: str) -> None:
    repo.record_operation(operation=name, dialog="d", parameters={}, entries={}, sources=[], results=[],
                          app_version="1")


def test_delete_asks_and_forgets(qapp, tmp_path, monkeypatch) -> None:
    repo = SqliteRepo(db_path=tmp_path / "h.dhub")
    _record(repo, "Fit")
    _record(repo, "Smooth")
    dialog = OperationHistoryDialog(repo, None)
    assert dialog._delete_button.isEnabled() and len(dialog._records) == 2

    monkeypatch.setattr(module, "ask", lambda *_a, **_k: False)
    dialog._delete_history()
    assert len(repo.operations()) == 2  # said no: nothing forgotten

    monkeypatch.setattr(module, "ask", lambda *_a, **_k: True)
    dialog._delete_history()
    assert repo.operations() == [] and not dialog._delete_button.isEnabled()
    repo.close()
