"""Smoothing results as a table: built from whole arrays, the rows the cell-by-cell version made."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data_operations.smoothing_dialog import SeriesSmoothingDialog, SmoothResult


def _cell_by_cell(results: list[SmoothResult]) -> pd.DataFrame:
    """The table as it was built before: one dictionary per point or cell."""
    rows = []
    for r in results:
        head = {"result_name": r.result_name, "source_name": r.source_name, "method": r.method}
        x, y = np.asarray(r.x, float).reshape(-1), np.asarray(r.y, float).reshape(-1)
        if r.values is not None and r.z is not None:
            z, v = np.asarray(r.z, float).reshape(-1), np.asarray(r.values, float)
            if v.ndim == 3:
                rows += [{**head, "x": float(xv), "y": float(yv), "z": float(zv), "value": float(v[k, j, i])}
                         for k, zv in enumerate(z) for j, yv in enumerate(y) for i, xv in enumerate(x)]
            else:
                rows += [{**head, "x": float(a), "y": float(b), "z": float(c), "value": float(d)}
                         for a, b, c, d in zip(x, y, z, v.reshape(-1), strict=False)]
        elif r.z is not None:
            z = np.asarray(r.z, float)
            if z.ndim == 2:
                rows += [{**head, "x": float(xv), "y": float(yv), "z": float(z[j, i])}
                         for j, yv in enumerate(y) for i, xv in enumerate(x)]
            else:
                rows += [{**head, "x": float(a), "y": float(b), "z": float(c)}
                         for a, b, c in zip(x, y, z.reshape(-1), strict=False)]
        else:
            rows += [{**head, "x": float(a), "y": float(b)} for a, b in zip(r.x, r.y, strict=False)]
    return pd.DataFrame(rows)


def _result(name: str, x, y, z=None, values=None) -> SmoothResult:
    return SmoothResult(source_name="s", result_name=name, method="m", x=np.asarray(x), y=np.asarray(y),
                        z=None if z is None else np.asarray(z), values=None if values is None else np.asarray(values),
                        metadata={})


def test_every_kind_of_result_gives_the_rows_it_gave_point_by_point() -> None:
    rng = np.random.default_rng(1)
    results = [
        _result("curve", [1, 2, 3], [4.0, 5.0, 6.0, 7.0]),
        _result("grid", [0.0, 1.0, 2.0], [10.0, 20.0], z=rng.normal(size=(2, 3))),
        _result("points", [1.0, 2.0], [3.0, 4.0], z=[5.0, 6.0]),
        _result("volume", [0.0, 1.0], [2.0, 3.0, 4.0], z=[5.0, 6.0], values=rng.normal(size=(2, 3, 2))),
        _result("scattered", [0.0, 1.0], [2.0, 3.0], z=[4.0, 5.0], values=[np.nan, 7.0]),
    ]
    for chosen in ([results[0]], [results[1]], [results[3]], results):
        pd.testing.assert_frame_equal(SeriesSmoothingDialog.results_to_dataframe(chosen), _cell_by_cell(chosen))
    assert SeriesSmoothingDialog.results_to_dataframe([]).empty
