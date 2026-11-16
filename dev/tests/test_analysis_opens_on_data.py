"""An analysis always opens on its Data page, centred on its window - whatever page it was left on."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data.sqlite_repo import SqliteRepo


def _repo(tmp_path) -> SqliteRepo:
    repo = SqliteRepo(db_path=tmp_path / "d.dhub")
    repo.import_dataframe(pd.DataFrame({"x": np.arange(20.0), "y": np.arange(20.0) ** 2}), table_name="t",
                          normalize_columns=False)
    return repo


def test_the_dialog_opens_on_data_after_being_closed_on_another_page(qapp, tmp_path) -> None:
    from app.data_operations.fit_y_by_x_dialog import FitYByXDialog

    repo = _repo(tmp_path)
    first = FitYByXDialog(repo=repo, table="t")
    try:
        assert first.left_tabs.count() > 1
        first.left_tabs.setCurrentIndex(first.left_tabs.count() - 1)
        first.reject()  # remembers the entries, the tab among them
    finally:
        first.close()
    second = FitYByXDialog(repo=repo, table="t")
    try:
        assert second.left_tabs.currentIndex() == 0 and second.left_tabs.tabText(0) == "Data"
    finally:
        second.close()
        repo.close()


def test_the_dialog_is_centred_on_its_window_and_inside_the_screen(qapp, tmp_path) -> None:
    from PySide6.QtWidgets import QWidget

    from app.data_operations.fit_y_by_x_dialog import FitYByXDialog

    repo = _repo(tmp_path)
    parent = QWidget()
    parent.setGeometry(60, 40, 700, 500)
    parent.show()
    dialog = FitYByXDialog(repo=repo, table="t", parent=parent)
    try:
        dialog.show()
        qapp.processEvents()
        screen = dialog.screen().availableGeometry()
        assert screen.contains(dialog.frameGeometry().topLeft())
        spare = parent.frameGeometry().width() - dialog.frameGeometry().width()
        if spare >= 0 and screen.contains(parent.frameGeometry()):
            assert abs(dialog.frameGeometry().center().x() - parent.frameGeometry().center().x()) <= 2
    finally:
        dialog.close()
        parent.close()
        repo.close()
