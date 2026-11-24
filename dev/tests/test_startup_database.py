"""Which database a run opens when there is none to reopen."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.utils import config, startup


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder))
    return folder


def test_a_last_project_that_is_gone_starts_a_new_untitled_one(tmp_path: Path, home: Path) -> None:
    gone = tmp_path / "Documents" / "Thesis.dhub"
    config.set_value("last_database", str(gone))

    opened = startup.select_database()

    assert opened is not None and Path(opened).resolve() == (home / "Untitled.dhub").resolve()
    assert not gone.exists()  # no empty file under the lost project's name


def test_a_new_project_never_reopens_an_earlier_untitled_one(home: Path) -> None:
    (home / "Untitled.dhub").write_bytes(b"")
    (home / "Untitled 2.dhub").write_bytes(b"")

    assert startup._new_database_path() == home / "Untitled 3.dhub"


def test_a_last_project_that_is_there_is_opened(tmp_path: Path) -> None:
    project = tmp_path / "Thesis.dhub"
    project.write_bytes(b"")
    config.set_value("last_database", str(project))

    assert startup.select_database() == project.resolve()


# ----------------------------------------------------------------------
# Closing the untitled project
# ----------------------------------------------------------------------
def _untitled_window(qapp, home: Path, *, with_table: bool):
    import pandas as pd

    from app.data.sqlite_repo import SqliteRepo
    from app.main_window import main_window as main_window_module

    path = startup._default_database(None)
    assert path is not None and config.is_untitled_database(path)
    repo = SqliteRepo(db_path=path)
    if with_table:
        repo.import_dataframe(pd.DataFrame({"a": [1.0, 2.0]}), table_name="t", normalize_columns=False)
    window = main_window_module.MainWindow(repo=repo, db_path=path)
    window.show()
    qapp.processEvents()
    return path, window


def test_an_empty_untitled_project_is_deleted_on_close_without_a_question(qapp, home: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: pytest.fail("nothing to ask about an empty project"))
    path, window = _untitled_window(qapp, home, with_table=False)
    window.close()
    assert not path.exists()
    assert not config.is_untitled_database(path)


def test_an_untitled_project_with_work_asks_and_cancel_keeps_it_open(qapp, home: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    path, window = _untitled_window(qapp, home, with_table=True)
    try:
        assert window.close() is False
        assert path.exists() and window.isVisible()
    finally:
        monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Discard)
        trashed: list[str] = []
        monkeypatch.setattr("PySide6.QtCore.QFile.moveToTrash",
                            staticmethod(lambda name: trashed.append(name) or Path(name).unlink() or True))
        window.close()
    assert trashed == [str(path)]  # Don't Save: to the Trash, not deleted for good
    assert not config.is_untitled_database(path)


def test_save_names_the_untitled_project_and_deletes_the_draft(qapp, home: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    target = home / "Thesis.dhub"
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    path, window = _untitled_window(qapp, home, with_table=True)
    monkeypatch.setattr(window, "_ask_for_missing_project_info", lambda: None)
    window.close()
    assert target.exists() and not path.exists()
