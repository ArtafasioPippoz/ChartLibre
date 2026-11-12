"""The ‹ › arrows on the Axis, Series and Overlays pages step the axis of all three."""
from __future__ import annotations

import time

from app.data.sqlite_repo import SqliteRepo
from app.main_window.main_window import MainWindow


def _spin(qapp, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)


def test_the_arrows_change_the_axis_everywhere(qapp, tmp_path) -> None:
    import pandas as pd

    repo = SqliteRepo(db_path=tmp_path / "s.dhub")
    repo.import_dataframe(pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]}), table_name="t", normalize_columns=False)
    figure_id = repo.create_figure_descriptor(name="two", nrows=1, ncols=2)
    first = second = 0
    for index in range(2):
        axis_id = repo.create_axis_descriptor(figure_id=figure_id, axis_index=index, chart_type="Scatter Plot",
                                              title=f"A{index}", x_label="x", y_label="y", options={})
        repo.create_series_descriptor(axis_id=axis_id, series_index=0, name=f"s{index}",
                                      sql_query='SELECT "x", "y" FROM "t"', roles={"x": "x", "y": "y"}, style={})
        first, second = (axis_id, second) if index == 0 else (first, axis_id)
    window = MainWindow(repo, tmp_path / "s.dhub")
    try:
        window.resize(1200, 800)
        window.show()
        window._left_panel.select("chart_properties")
        _spin(qapp, 0.8)
        axis = window._axis_widget
        assert axis.current_axis_id() == first and not axis.axis_stepper._previous.isEnabled()

        window._series_widget.axis_stepper._next.click()  # from the Series page
        _spin(qapp, 0.2)
        assert axis.current_axis_id() == second
        assert window._series_widget._current_axis_id == second
        assert not window._overlay_widget.axis_stepper._next.isEnabled()

        window._overlay_widget.axis_stepper._previous.click()  # and back, from Overlays
        _spin(qapp, 0.2)
        assert axis.current_axis_id() == first
    finally:
        window.close()



def test_the_span_is_off_with_one_axis(qapp) -> None:
    from app.widgets.chart_properties.axis_properties import AxisPropertiesWidget

    page = AxisPropertiesWidget()
    page._axis_combo.setEnabled(True)
    page._pages.setEnabled(True)  # off without a figure
    page._axis_combo.addItem("A", 1)
    page._update_axis_action_buttons()
    assert not page._row_span_spin.isEnabled() and not page._col_span_spin.isEnabled()
    page._axis_combo.addItem("B", 2)
    page._update_axis_action_buttons()
    assert page._row_span_spin.isEnabled() and page._col_span_spin.isEnabled()
