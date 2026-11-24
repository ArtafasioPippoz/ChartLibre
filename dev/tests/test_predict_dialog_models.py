"""Predict with a saved model: the models renamed, deleted, exported, imported and trusted from its window."""
from __future__ import annotations

import pandas as pd
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog

from app.analysis import models
from app.data.sqlite_repo import SqliteRepo
from app.dialogs import predict_dialog
from dev.tests.test_saved_models import _line, _Pickled


@pytest.fixture
def repo(tmp_path, monkeypatch):
    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    project = SqliteRepo(db_path=tmp_path / "m.dhub")
    project.import_dataframe(pd.DataFrame({"x": [1.0, 2.0], "g": ["a", "b"]}), table_name="t", normalize_columns=False)
    project.trusted = trusted  # type: ignore[attr-defined]
    yield project
    project.close()


def test_rename_delete_export_and_import_from_the_window(qapp, repo, tmp_path, monkeypatch) -> None:
    models.save_model(repo, "line", _line())
    dialog = predict_dialog.PredictDialog(repo)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("slope", True))
    dialog._rename_button.click()
    assert dialog._model_combo.currentData() == "slope"
    target = tmp_path / "slope.clmodel"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog._export_button.click()
    assert target.exists()
    monkeypatch.setattr(predict_dialog, "ask", lambda *a, **k: True)
    dialog._delete_button.click()
    assert repo.models() == [] and not dialog._apply.isEnabled() and not dialog._rename_button.isEnabled()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    dialog._import_button.click()
    assert dialog._model_combo.currentData() == "slope" and dialog._apply.isEnabled()
    dialog.apply()
    assert dialog.created_table_name == "t_slope"
    dialog.close()


def test_an_untrusted_model_is_asked_about_before_it_runs(qapp, repo, monkeypatch) -> None:
    models.save_model(repo, "p", _line(_Pickled))
    repo.trusted.clear()  # as if made on another computer
    dialog = predict_dialog.PredictDialog(repo)
    answers = [False, True]
    asked: list[str] = []
    monkeypatch.setattr(predict_dialog, "ask", lambda parent, key, **k: (asked.append(key), answers.pop(0))[1])
    dialog.apply()
    assert asked == ["model.trust"] and dialog.created_table_name is None  # refused: nothing ran
    dialog.apply()
    assert dialog.created_table_name == "t_p" and not models.needs_trust(repo, "p")
    dialog.close()
