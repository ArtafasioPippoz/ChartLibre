"""Demo: random numbers drawn, checked and drawn, and noise added to a known signal.

* Random data, one column: 2,000 normal numbers with their histogram and fitted curve, Q-Q plot and ECDF, and the
  checks that say they are what they were drawn to be.
* Random data, two columns: a normal and an exponential with a correlation of 0.7 - the scatter and the joint plot;
  the report compares the correlation found with the one asked.
* Random data, a grid: sin(x) cos(y) plus normal noise, as a surface and its contour, and Moran's I of the noise.
* Random data, repeated: 100 samples checked again and again - the p-values of a good generator are flat, and about
  one test in twenty rejects at 5%.
* Add noise: a clean sine with noise added to a signal-to-noise ratio of 15 dB, drawn beside the original.

Run ``python -m dev.demo.demo_random`` to rebuild the file into ``demo/``. It runs offscreen; the dialogs'
remembered settings go to a throwaway user.json, never to the real one.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.data.demos import DEMO_DIR, DEMO_PROJECTS, DemoProject
from app.data.sqlite_repo import SqliteRepo


def _demo() -> DemoProject:
    return next(demo for demo in DEMO_PROJECTS if demo.builder.endswith(":build_random_demo"))


def clean_signal() -> pd.DataFrame:
    """A sine with a slow trend, 600 points: the truth the noise is added to."""
    x = np.linspace(0.0, 12.0, 600)
    return pd.DataFrame({"time_s": x, "signal": 2.0 + 0.3 * x + np.sin(2.0 * x)})


def _run(app: Any, dialog: Any, **values: Any) -> None:
    """Set *values*, press OK and wait for a background job."""
    dialog._parameter_form_spec.set_values(values)
    if getattr(dialog, "chart_form", None) is not None:
        dialog.chart_form.refresh_visibility()
    dialog.ok()
    deadline = time.monotonic() + 120
    while dialog.job_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def build_random_demo(directory: Path = DEMO_DIR) -> Path:
    """Write the random-data demo into *directory* and return its path."""
    from PySide6.QtWidgets import QApplication

    from app.data_operations.add_noise_dialog import AddNoiseDialog
    from app.data_operations.random_data_dialog import RandomDataDialog
    from app.utils import config

    app = QApplication.instance() or QApplication([])
    real_user_config = config.USER_CONFIG_PATH
    config.USER_CONFIG_PATH = Path(tempfile.mkdtemp(prefix="chartlibre-demo-")) / "user.json"
    try:
        path = Path(directory) / _demo().path_name
        path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm", ".undo.db"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        repo = SqliteRepo(db_path=path)
        repo.import_dataframe(clean_signal(), table_name="clean_signal", normalize_columns=False)

        def random_data(**values: Any) -> None:
            figure_id = int(repo.create_figure_descriptor(name="Random data"))
            repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot", title="Random",
                                        x_label="x", y_label="y", options={})
            dialog = RandomDataDialog(repo=repo, figure_id=figure_id, parent=None)
            try:
                _run(app, dialog, **values)
            finally:
                dialog.close()
            repo.delete_figure(figure_id)  # the window needs a figure to open on; the sample draws its own

        random_data(layout="X", dist="normal", mean__normal=50.0, sd__normal=5.0, n=2000, seed=11)
        random_data(layout="XY", dist="normal", dist_2="exponential", scale__exponential__2=2.0, corr=0.7, n=1500,
                    seed=12)
        random_data(layout="GRID", dist="normal", sd__normal=0.2, x_start=0.0, x_stop=6.28, x_points=40,
                    y_start=0.0, y_stop=6.28, y_points=40, function="sin(x) * cos(y)", seed=13)
        random_data(layout="X", dist="uniform", n=400, seed=14, repeat=100)

        figure_id = int(repo.create_figure_descriptor(name="Signal and its noisy copy"))
        axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type="Scatter Plot",
                                                  title="Signal", x_label="time_s", y_label="signal", options={}))
        repo.create_series_descriptor(axis_id=axis_id, series_index=0, name="signal",
                                      sql_query='SELECT "time_s" AS x, "signal" AS y FROM "clean_signal"',
                                      roles={"x": "x", "y": "y"}, style={"linestyle": "-", "marker": ""})
        dialog = AddNoiseDialog(repo=repo, figure_id=figure_id, parent=None)
        try:
            dialog.series_selector.reload(select_all_series=True)
            _run(app, dialog, amount_mode="snr", amount=15.0, seed=15)
        finally:
            dialog.close()
        repo.close()
        Path(f"{path}.undo.db").unlink(missing_ok=True)
        return path
    finally:
        config.USER_CONFIG_PATH = real_user_config
        del app


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dev.demo.build_demos import describe_demo

    built = build_random_demo()
    describe_demo(_demo(), built)
