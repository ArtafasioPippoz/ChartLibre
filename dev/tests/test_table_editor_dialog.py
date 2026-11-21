"""Hand editing of a table: the cells, the rows, the columns.

Each of these drives the dialog the way the buttons do - set a selection,
call the slot - rather than calling the repository directly, because the
part that can be wrong is the step between them: which row is "the
selected row" once a rowid no longer matches a position.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtCore import Qt

from app.data.sqlite_repo import SqliteRepo
from app.dialogs.table_editor_dialog import TableEditorDialog
from app.logs.logger import applogger

FRAME = pd.DataFrame(
    {
        "name": ["alpha", "beta", "gamma", "delta"],
        "value": [1.0, 2.0, 3.0, 4.0],
    }
)


@pytest.fixture
def repo(tmp_db_path: Path) -> Iterator[SqliteRepo]:
    # The undo sidecar too, not just the database: it lives beside the
    # .dhub and outlives it, so a test that counts undo entries would be
    # counting the ones a previous run of itself left behind - and the
    # store caps the history, so the count stops moving once it is full.
    for suffix in (".dhub", ".dhub-wal", ".dhub-shm", ".dhub.undo.db"):
        tmp_db_path.with_suffix(suffix).unlink(missing_ok=True)
    built = SqliteRepo(db_path=tmp_db_path)
    built.import_dataframe(FRAME, table_name="people", normalize_columns=False)
    yield built
    built.close()


@pytest.fixture
def dialog(qapp, repo: SqliteRepo):
    built = TableEditorDialog(repo, "people", None)
    yield built
    built.close()
    applogger.set_status_bar(None)


def _rows(repo: SqliteRepo) -> list[tuple]:
    return [
        tuple(row)
        for row in _con(repo).execute('SELECT name, value FROM "people" ORDER BY rowid')
    ]


def _columns(repo: SqliteRepo) -> list[str]:
    return [c for c in repo.get_columns("people") if c != "Selected"]  # not the row id column (R-07), nor the flag


def _select_cell(dialog: TableEditorDialog, row: int, column: int) -> None:
    index = dialog._model.index(row, column)
    dialog.view.setCurrentIndex(index)
    dialog.view.selectionModel().select(
        index, dialog.view.selectionModel().SelectionFlag.ClearAndSelect
    )


# ----------------------------------------------------------------------
# Cells
# ----------------------------------------------------------------------


def test_a_cell_edit_reaches_the_database(dialog: TableEditorDialog, repo: SqliteRepo) -> None:
    index = dialog._model.index(1, 1)
    assert dialog._model.setData(index, "22.5", Qt.ItemDataRole.EditRole)

    assert _rows(repo)[1] == ("beta", 22.5)


def test_an_emptied_cell_becomes_null_not_an_empty_string(
    dialog: TableEditorDialog, repo: SqliteRepo
) -> None:
    """In a numeric column, "" would quietly make the column text."""
    dialog._model.setData(dialog._model.index(0, 1), "", Qt.ItemDataRole.EditRole)

    stored = _con(repo).execute(
        'SELECT value FROM "people" ORDER BY rowid LIMIT 1'
    ).fetchone()[0]
    assert stored is None


# ----------------------------------------------------------------------
# Rows
# ----------------------------------------------------------------------


def test_add_row_appends_an_empty_one(dialog: TableEditorDialog, repo: SqliteRepo) -> None:
    dialog._add_row()

    rows = _rows(repo)
    assert len(rows) == 5
    assert rows[-1] == (None, None)


def test_delete_rows_removes_every_selected_one(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    index_a = dialog._model.index(0, 0)
    index_c = dialog._model.index(2, 0)
    selection = dialog.view.selectionModel()
    # setCurrentIndex first: on a view it also *sets* the selection, so
    # calling it afterwards would throw the second cell away.
    dialog.view.setCurrentIndex(index_a)
    selection.select(index_a, selection.SelectionFlag.Select)
    selection.select(index_c, selection.SelectionFlag.Select)

    dialog._delete_rows()

    assert [row[0] for row in _rows(repo)] == ["beta", "delta"]


# ----------------------------------------------------------------------
# Columns
# ----------------------------------------------------------------------


def test_add_column_appends_it(dialog: TableEditorDialog, repo: SqliteRepo) -> None:
    dialog._add_column(name="score", kind="REAL")

    assert _columns(repo) == ["name", "value", "score"]


def test_delete_column_removes_it(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    _select_cell(dialog, 0, 1)
    dialog._delete_column()

    assert _columns(repo) == ["name"]


def test_rename_column_asks_for_the_new_name(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_a, **_k: ("amount", True)))
    _select_cell(dialog, 0, 1)
    dialog._rename_column()

    assert _columns(repo) == ["name", "amount"]


def test_a_duplicate_column_name_is_refused_not_applied(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    warned: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _p, _t, message, *a, **k: warned.append(message)
    )
    dialog._add_column(name="value", kind="REAL")

    assert _columns(repo) == ["name", "value"]
    assert warned and "already a column" in warned[0]


# ----------------------------------------------------------------------
# The managed columns, moved here from the preview's context menu
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Undo
# ----------------------------------------------------------------------


def test_a_whole_session_is_one_undo_entry(
    dialog: TableEditorDialog, repo: SqliteRepo
) -> None:
    """Not one per keystroke.

    A snapshot copies the whole table, so an entry per cell edit would copy
    it again for every number corrected - unusable on anything large. The
    session shares one entry, which UndoStore fills once and then skips.
    """
    before = len(repo.undo_entries())

    dialog._model.setData(dialog._model.index(0, 1), "9.5", Qt.ItemDataRole.EditRole)
    dialog._model.setData(dialog._model.index(1, 1), "8.5", Qt.ItemDataRole.EditRole)
    dialog._model.setData(dialog._model.index(2, 1), "7.5", Qt.ItemDataRole.EditRole)
    dialog._add_row()

    assert len(repo.undo_entries()) == before + 1


# ----------------------------------------------------------------------
# OK and Cancel
# ----------------------------------------------------------------------


def test_ok_keeps_the_changes(dialog: TableEditorDialog, repo: SqliteRepo) -> None:
    dialog._model.setData(dialog._model.index(0, 0), "KEPT", Qt.ItemDataRole.EditRole)
    dialog._add_row()

    dialog.accept()

    names = [row[0] for row in _rows(repo)]
    assert names[0] == "KEPT"
    assert len(names) == 5


def test_cancel_puts_the_table_back(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    original = _rows(repo)
    original_columns = _columns(repo)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    dialog._model.setData(dialog._model.index(0, 0), "LOST", Qt.ItemDataRole.EditRole)
    dialog._add_row()
    dialog._add_column(name="scratch", kind="REAL")
    assert _rows(repo) != original

    dialog.reject()

    assert _rows(repo) == original
    assert _columns(repo) == original_columns




def test_restore_puts_the_table_back_and_keeps_the_editor_open(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *_a, **_k: ("label", True))
    )
    dialog._add_row()
    dialog._rename_from_header(0)
    assert _columns(repo)[0] == "label"
    assert "1 added" in dialog._status.text() and "1 modified" in dialog._status.text()

    dialog._restore()

    assert _rows(repo) == [tuple(r) for r in FRAME.itertuples(index=False)]
    assert _columns(repo)[0] == "name"
    assert "0 added" in dialog._status.text()
    assert not dialog._restore_button.isEnabled()


def test_the_last_row_and_the_last_column_cannot_be_deleted(
    dialog: TableEditorDialog, repo: SqliteRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    said: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, _t, text, *a, **k: said.append(text)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_a, **_k: QMessageBox.StandardButton.Yes))
    dialog.view.selectAll()
    dialog._delete_rows()
    assert len(_rows(repo)) == 4 and said

    _select_cell(dialog, 0, 1)
    dialog._delete_column()
    _select_cell(dialog, 0, 0)
    dialog._delete_column()
    assert _columns(repo) == ["name"]


def _con(repo: SqliteRepo):
    assert repo._con is not None
    return repo._con


def test_read_dates_writes_iso_and_keeps_unreadable(repo: SqliteRepo) -> None:
    import pandas as pd

    repo.import_dataframe(
        pd.DataFrame({"when": ["31/12/2024", "01/02/2025", "soon", "", None]}),
        table_name="dates", normalize_columns=False,
    )
    converted, unread = repo.read_dates("dates", "when")
    assert (converted, unread) == (2, 1)
    values = [row[0] for row in _con(repo).execute('SELECT "when" FROM "dates" ORDER BY rowid')]
    assert values[:3] == ["2024-12-31", "2025-02-01", "soon"]
    # Read again: ISO stays ISO, nothing left to change.
    assert repo.read_dates("dates", "when")[0] == 2


def test_read_dates_with_free_format(repo: SqliteRepo) -> None:
    import pandas as pd

    repo.import_dataframe(
        pd.DataFrame({"when": ["05.03.24 14:30"]}), table_name="dates2", normalize_columns=False
    )
    repo.read_dates("dates2", "when", "format", "DD.MM.YY HH:mm")
    assert _con(repo).execute('SELECT "when" FROM "dates2"').fetchone()[0] == "2024-03-05 14:30:00"


def test_date_tool_dialog_previews(qapp) -> None:
    from app.dialogs.table_tools_dialogs import DateToolDialog

    dialog = DateToolDialog("when", ["31/12/2024", "01/02/2025"])
    assert "2024-12-31" in dialog.preview.text()
    assert not dialog.format.isEnabled()


def test_stored_dates_are_iso_whatever_the_computers_language(repo: SqliteRepo, monkeypatch) -> None:
    """The column holds the same text under any locale: only the reading of month names depends on it."""
    import pandas as pd
    from PySide6.QtCore import QLocale

    from app.utils import import_cleaning

    stored: dict[str, list[str]] = {}
    for name in ("en_US", "it_IT", "de_DE", "fr_FR"):
        monkeypatch.setattr(QLocale, "system", staticmethod(lambda name=name: QLocale(name)))
        import_cleaning._local_names_cache.clear()
        table = f"d_{name}"
        repo.import_dataframe(
            pd.DataFrame({"when": ["2024-01-12", "2024-03-05 14:30:00", "12 March 2024"]}),
            table_name=table, normalize_columns=False,
        )
        repo.read_dates(table, "when", "yearfirst")
        stored[name] = [row[0] for row in _con(repo).execute(f'SELECT "when" FROM "{table}" ORDER BY rowid')]
    import_cleaning._local_names_cache.clear()
    assert len({tuple(values) for values in stored.values()}) == 1
    assert stored["it_IT"] == ["2024-01-12 00:00:00", "2024-03-05 14:30:00", "2024-03-12 00:00:00"]
