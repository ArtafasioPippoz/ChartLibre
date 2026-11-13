"""An analysis as a function call (app/analysis_api.py): the dialog driven without a window."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app import analysis_api
from app.data.sqlite_repo import SqliteRepo


@pytest.fixture
def repo(qapp, tmp_path):
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"group": list("aaabbbccc") * 4, "value": rng.normal(10, 1, 36)})
    project = SqliteRepo(db_path=tmp_path / "a.dhub")
    project.import_dataframe(frame, table_name="t", normalize_columns=False)
    yield project
    project.close()


def test_an_analysis_runs_and_hands_back_its_report(repo) -> None:
    result = analysis_api.run_analysis(repo, "Are there differences?", "t",
                                       {"response": ["value"], "group": ["group"]})
    assert result.name == "Are there differences?" and result.source == "t"
    assert result.report_text and "<" in result.report_html
    assert result.operation_id is not None  # it is in the project's history
    assert [record.id for record in repo.operations()][-1] == result.operation_id
    assert result.roles == {"response": ["value"], "group": ["group"]}


def test_names_are_read_loosely_and_wrong_ones_say_what_there_is(repo) -> None:
    assert analysis_api.find_analysis("are there differences")[0] == "Are there differences?"
    assert analysis_api.find_table(repo, "T") == "t"
    assert analysis_api.find_columns(repo, "t", ["Value"]) == ["value"]
    with pytest.raises(analysis_api.AnalysisError, match="No analysis named"):
        analysis_api.find_analysis("nothing like it")
    with pytest.raises(analysis_api.AnalysisError, match="No table named"):
        analysis_api.run_analysis(repo, "Are there differences?", "missing", {})
    with pytest.raises(analysis_api.AnalysisError, match="Not columns of t"):
        analysis_api.run_analysis(repo, "Are there differences?", "t", {"response": ["nope"]})


def test_missing_roles_are_the_dialogs_own_problems(repo) -> None:
    with pytest.raises(analysis_api.AnalysisError):
        analysis_api.run_analysis(repo, "Are there differences?", "t", {})


def test_the_callables_take_a_list_of_columns_and_give_an_object(repo) -> None:
    changed: list[list[int]] = []
    analysis, _chart = analysis_api.make_callables(lambda: repo, on_change=changed.append)
    result = analysis("Are there differences?", "t", roles={"response": ["value"], "group": ["group"]})
    assert result.report and changed == [result.figures]
    assert result.code().startswith("Analysis('Are there differences?', 't', {")
    assert "'response': ['value']" in result.code()
    again = result.rerun()
    assert again.operation_id != result.operation_id and again.report_text
    with pytest.raises(analysis_api.AnalysisError, match="several roles"):
        analysis("Are there differences?", "t", ["value"])


def test_a_chart_is_made_described_and_drawn(repo, tmp_path) -> None:
    _analysis, chart = analysis_api.make_callables(lambda: repo)
    made = chart("Scatter Plot", "t", ["value"], x="value", title="Values")
    assert made.figure_id and made.chart_type == "Scatter Plot"
    assert made.code() == "Chart('Scatter Plot', 't', ['value'], x='value', title='Values')"
    data = made.png(tmp_path / "c.png")
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and (tmp_path / "c.png").exists()
    with pytest.raises(analysis_api.AnalysisError, match="No chart type"):
        chart("Not a chart", "t", ["value"])


def test_the_module_level_names_need_a_project(repo) -> None:
    analysis_api.use_project(None)
    with pytest.raises(analysis_api.AnalysisError, match="No project"):
        analysis_api.Analysis("Are there differences?", "t")
    analysis_api.use_project(repo)
    try:
        assert analysis_api.Chart("Scatter Plot", "t", ["value"], x="value").figure_id
    finally:
        analysis_api.use_project(None)
