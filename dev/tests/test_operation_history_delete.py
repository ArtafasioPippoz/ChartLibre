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


def test_an_operation_is_copied_as_python_and_kept_as_a_function(qapp, tmp_path, monkeypatch) -> None:
    import numpy as np
    import pandas as pd
    from PySide6.QtWidgets import QApplication

    from app import analysis_api
    from app.workpad.engine import Workpad

    rng = np.random.default_rng(3)
    repo = SqliteRepo(db_path=tmp_path / "f.dhub")
    repo.import_dataframe(pd.DataFrame({"group": list("aaabbbccc") * 4, "value": rng.normal(10, 1, 36)}),
                          table_name="t", normalize_columns=False)
    result = analysis_api.run_analysis(repo, "Are there differences?", "t",
                                       {"response": ["value"], "group": ["group"]})
    dialog = OperationHistoryDialog(repo, None)
    assert dialog._record_combo.currentData() == result.operation_id  # the last one, picked
    dialog.copy_code()
    code = QApplication.clipboard().text()
    assert code.startswith("Analysis('Are there differences?', 't', {'response': ['value'], 'group': ['group']}")
    assert "**{'Box Plot': True" in code  # a parameter that is not a Python name

    monkeypatch.setattr(module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("compare", True)))
    dialog.save_as_function()
    assert [row["name"] for row in repo.analysis_functions()] == ["compare"]
    pad = Workpad(lambda: repo)
    again = pad.run("compare().report_text")[1]
    assert again and "Are there differences?" in repr(pad.run("compare()")[1])
    assert pad.run("functions()")[1] == {"compare": "Are there differences? on t"}
    dialog.done(0)
    repo.close()
