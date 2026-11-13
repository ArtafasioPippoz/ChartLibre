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
    assert result.name == "Are there differences?" and result.table == "t"
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
