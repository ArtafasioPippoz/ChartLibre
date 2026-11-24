"""Random data and Add noise are in the catalog and callable as analyses (run_analysis, the workpad, the assistant)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app import analysis_api
from app.analysis import catalog
from app.data.sqlite_repo import SqliteRepo


_ENTRIES = catalog.build_catalog()


@pytest.fixture
def project(qapp, tmp_path):
    repo = SqliteRepo(db_path=tmp_path / "r.dhub")
    t = np.linspace(0.0, 10.0, 200)
    repo.import_dataframe(pd.DataFrame({"t": t, "a": np.sin(t)}), table_name="sig", normalize_columns=False)
    yield repo
    repo.close()


def test_both_are_found_by_what_someone_would_search_for() -> None:
    for words, name in (("random numbers distribution", "Random data"), ("casuale", "Random data"),
                        ("noise", "Add noise"), ("rumore", "Add noise"), ("outliers snr", "Add noise")):
        assert name in [entry.name for entry in catalog.search(_ENTRIES, words)], words


def test_both_serve_the_goal_prepare_the_data() -> None:
    entries = {entry.name: entry for entry in _ENTRIES}
    for name in ("Random data", "Add noise"):
        assert "prepare" in entries[name].goals, name


def test_random_data_is_run_as_an_analysis_and_recorded_with_its_seed(project) -> None:
    result = analysis_api.run_analysis(project, "Random data", "sig", {}, {"dist": "normal", "n": 500, "seed": 9})
    assert result.tables and result.figures and "Seed" in result.report_text
    [record] = project.operations()
    assert record.operation == "Random data"


def test_add_noise_is_run_as_an_analysis_on_a_series(project) -> None:
    result = analysis_api.run_analysis(project, "Add noise", "sig", {"x": ["t"], "y": ["a"]},
                                       {"amount": 0.2, "seed": 4})
    assert result.tables
    assert [r.operation for r in project.operations()] == ["Add noise"]
