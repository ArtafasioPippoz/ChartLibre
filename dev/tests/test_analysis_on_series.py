"""Analyses of a chart's series come back as calls: Copy as Python, Export script, Run again."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app import analysis_api
from app.data.sqlite_repo import SqliteRepo


@pytest.fixture
def project(qapp, tmp_path):
    repo = SqliteRepo(db_path=tmp_path / "s.dhub")
    t = np.linspace(0.0, 10.0, 80)
    repo.import_dataframe(pd.DataFrame({"t": t, "a": np.sin(t) + 0.1 * np.cos(9 * t)}), table_name="sig",
                          normalize_columns=False)
    yield repo
    repo.close()


def test_a_series_analysis_is_run_recorded_and_written_as_a_call(project) -> None:
    result = analysis_api.run_analysis(project, "Smoothing", "sig", {"x": ["t"], "y": ["a"]})
    assert result.tables
    records = project.operations()
    assert len(records) == 1
    code = analysis_api.history_code(records)
    assert code.startswith("Analysis('Smoothing', 'sig', {'x': ['t'], 'y': ['a']}") and "#" not in code
    script = analysis_api.history_script(records, "s.dhub")
    compile(script, "script", "exec")
    again = analysis_api.run_records(project, records)
    assert isinstance(again[0], analysis_api.AnalysisResult), again
    assert len(project.operations()) == 2


def test_the_copied_code_runs_in_the_workpad(project) -> None:
    from app.utils.workpad import Workpad

    analysis_api.run_analysis(project, "Smoothing", "sig", {"x": ["t"], "y": ["a"]})
    code = analysis_api.history_code(project.operations())
    pad = Workpad(lambda: project)
    outcome = pad.run(code)
    assert "error" not in repr(outcome).lower()[:200], outcome
    assert len(project.operations()) == 2


def test_the_windows_own_choices_are_in_the_call_and_run_again(project) -> None:
    """A smoothing's method is not a parameter: it travels as entries, and a re-run uses it."""
    analysis_api.run_analysis(project, "Smoothing", "sig", {"x": ["t"], "y": ["a"]},
                              entries={"method_combo": "Savitzky-Golay Filter (SciPy)"})
    records = project.operations()
    assert records[0].entries["method_combo"] == "Savitzky-Golay Filter (SciPy)"
    code = analysis_api.history_code(records, project)
    assert "entries={'method_combo': 'Savitzky-Golay Filter (SciPy)'}" in code, code
    again = analysis_api.run_records(project, records)
    assert isinstance(again[0], analysis_api.AnalysisResult), again
    assert project.operations()[-1].entries["method_combo"] == "Savitzky-Golay Filter (SciPy)"
