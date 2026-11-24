"""The SQL workpad is a ChartLibre Developer tool: a project file is opened, a statement runs on it."""
from __future__ import annotations

import pandas as pd

from app.data.sqlite_repo import SqliteRepo
from dev.developer.sql_workpad_dialog import SqlWorkpadDialog


def test_the_dialog_runs_a_select_on_the_picked_project(qapp, tmp_path) -> None:
    path = tmp_path / "w.dhub"
    repo = SqliteRepo(db_path=path)
    repo.import_dataframe(pd.DataFrame({"a": [1, 2, 3]}), table_name="t", normalize_columns=False)
    repo.close()
    dialog = SqlWorkpadDialog(None, path)
    dialog.panel.run('SELECT a FROM "t" ORDER BY a')
    assert dialog.panel._result.rowCount() == 3
    dialog.done(0)
