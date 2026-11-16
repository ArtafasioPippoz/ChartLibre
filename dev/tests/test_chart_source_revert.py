"""Analysis on a chart's axis read as a table: Preview, Revert, Preview again (it said "no such table")."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.data.sqlite_repo import SqliteRepo
from dev.tests._helpers import wait_for_job

DEMO = Path(__file__).resolve().parents[2] / "demo" / "Penguins - species compared across four chart types.dhub"


@pytest.mark.skipif(not DEMO.exists(), reason="the demo project is not built here")
def test_preview_revert_preview_with_data_from_a_chart(qapp, tmp_path) -> None:
    from app.data_operations.fit_y_by_x_dialog import FitYByXDialog

    path = tmp_path / "p.dhub"
    shutil.copy(DEMO, path)
    repo = SqliteRepo(db_path=path)
    repo.list_user_tables()  # opens the connection
    (figure,) = [row[0] for row in repo._con.execute(
        "SELECT id FROM __figure_descriptors__ WHERE name LIKE '%bill dim%'").fetchall()]
    dialog = FitYByXDialog(repo=repo, figure_id=int(figure))
    failures: list[str] = []
    dialog.show_failure = lambda error, *, headline="": failures.append(str(error))  # type: ignore[method-assign]
    try:
        dialog.source_chart_radio.setChecked(True)
        dialog.preview()
        wait_for_job(qapp, dialog)
        dialog.revert_entries()
        names = [dialog._table_combo.itemText(i) for i in range(dialog._table_combo.count())]
        assert names == ["penguins"]  # the Preview's tables are not offered as the user's
        dialog.preview()
        wait_for_job(qapp, dialog)
        assert failures == []
    finally:
        dialog.close()
        repo.close()
