"""Saved prediction models: the contract, the project's table, the trust rule, unseen levels and missing values."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.analysis import models
from app.analysis.models import CONTINUOUS, NOMINAL, PICKLED, PORTABLE, Feature, ModelError, SavedModel
from app.data.sqlite_repo import SqliteRepo


@SavedModel.register
class _Line(SavedModel):
    """y = a + b*x per group: a portable kind for the tests."""

    KIND = "test_line"
    FORM = PORTABLE

    def __init__(self, *args, intercepts=None, slope=1.0, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.intercepts = dict(intercepts or {})
        self.slope = slope

    def predict_matrix(self, frame):
        values = frame["x"] * self.slope + frame["g"].map(self.intercepts)
        return pd.DataFrame({"Prediction": values}, index=frame.index)

    def state(self):
        return {"intercepts": self.intercepts, "slope": self.slope}

    @classmethod
    def from_state(cls, header, state):
        return cls(header["response"], [Feature.from_dict(f) for f in header["features"]],
                   intercepts=state["intercepts"], slope=state["slope"], source_table=header.get("source_table", ""))


@SavedModel.register
class _Pickled(_Line):
    KIND = "test_pickled"
    FORM = PICKLED


FEATURES = [Feature("x", CONTINUOUS), Feature("g", NOMINAL, ["a", "b"])]


@pytest.fixture
def repo(tmp_path, monkeypatch):
    trusted: list[str] = []
    monkeypatch.setattr(models, "get_value", lambda key, default=None: list(trusted) if key == models.TRUST_KEY else default)
    monkeypatch.setattr(models, "set_value", lambda key, value: (trusted.clear(), trusted.extend(value)))
    project = SqliteRepo(db_path=tmp_path / "m.dhub")
    project.trusted = trusted  # type: ignore[attr-defined]
    yield project
    project.close()


def _line(cls=_Line):
    return cls("y", FEATURES, intercepts={"a": 1.0, "b": 10.0}, slope=2.0, source_table="t")


def test_a_portable_model_is_saved_listed_loaded_and_applied(repo) -> None:
    assert models.save_model(repo, "line", _line()) == "line"
    assert [(row["name"], row["kind"], row["form"]) for row in repo.models()] == [("line", "test_line", PORTABLE)]
    assert repo.models()[0]["header"]["features"][1] == {"name": "g", "kind": "nominal", "levels": ["a", "b"]}
    prediction = models.predict_table(repo, "line", pd.DataFrame({"x": [1.0, 2.0], "g": ["a", "b"]}))
    assert prediction.table["Prediction"].tolist() == [3.0, 14.0] and prediction.notes == []
    with pytest.raises(ModelError, match="exists"):
        models.save_model(repo, "line", _line())
    models.save_model(repo, "line", _line(), replace=True)
    repo.rename_model("line", "other")
    assert [row["name"] for row in repo.models()] == ["other"]
    repo.delete_model("other")
    assert repo.models() == []


def test_unseen_levels_and_missing_values_are_counted_not_hidden(repo) -> None:
    models.save_model(repo, "line", _line())
    frame = pd.DataFrame({"x": [1.0, np.nan, 3.0, 4.0], "g": ["a", "a", "zzz", "b"]})
    result = models.predict_table(repo, "line", frame)
    assert result.table["Prediction"].isna().tolist() == [False, True, True, False]
    assert result.table.index.tolist() == frame.index.tolist()
    text = " ".join(result.notes)
    assert "never saw" in text and "zzz" in text and "missing value" in text


def test_a_missing_column_is_named(repo) -> None:
    models.save_model(repo, "line", _line())
    with pytest.raises(ModelError, match="no column g"):
        models.predict_table(repo, "line", pd.DataFrame({"x": [1.0]}))
    with pytest.raises(ModelError, match="No model called nope"):
        models.load_model(repo, "nope")


def test_a_pickled_model_runs_where_it_was_made_and_only_where_trusted(repo) -> None:
    models.save_model(repo, "p", _line(_Pickled))
    assert models.load_model(repo, "p").slope == 2.0  # trusted at save: made here
    repo.trusted.clear()  # another computer
    with pytest.raises(models.UntrustedModel):
        models.load_model(repo, "p")
    models.trust([repo.models()[0]["fingerprint"]])
    assert models.load_model(repo, "p").KIND == "test_pickled"


def test_a_pickle_changed_after_saving_is_refused(repo) -> None:
    models.save_model(repo, "p", _line(_Pickled))
    repo._con.execute("UPDATE __models__ SET payload = ? WHERE name = 'p'", (b"not the same",))
    repo._con.commit()
    with pytest.raises(ModelError, match="changed after"):
        models.load_model(repo, "p")


def test_a_model_goes_to_a_file_and_into_another_project(repo, tmp_path) -> None:
    models.save_model(repo, "line", _line())
    path = models.export_model(repo, "line", tmp_path / "line")
    assert path.suffix == models.FILE_SUFFIX and path.exists()
    other = SqliteRepo(db_path=tmp_path / "other.dhub")
    try:
        assert models.import_model(other, path) == "line"
        assert models.import_model(other, path) == "line 2"  # never over a model that is there
        frame = pd.DataFrame({"x": [1.0], "g": ["b"]})
        assert models.load_model(other, "line").predict(frame).table["Prediction"].tolist() == [12.0]
    finally:
        other.close()


def test_an_imported_pickle_waits_to_be_trusted(repo, tmp_path) -> None:
    models.save_model(repo, "p", _line(_Pickled))
    path = models.export_model(repo, "p", tmp_path / "p.clmodel")
    repo.trusted.clear()  # another computer
    name = models.import_model(repo, path, name="from file")
    assert models.needs_trust(repo, name)
    with pytest.raises(models.UntrustedModel):
        models.load_model(repo, name)
    models.trust_model(repo, name)
    assert not models.needs_trust(repo, name) and isinstance(models.load_model(repo, name), _Pickled)


def test_a_file_changed_after_export_or_not_a_model_is_refused(repo, tmp_path) -> None:
    models.save_model(repo, "line", _line())
    path = models.export_model(repo, "line", tmp_path / "line.clmodel")
    path.write_text(path.read_text().replace('"test_line"', '"test_pickled"'))
    with pytest.raises(ModelError, match="changed"):
        models.import_model(repo, path)
    junk = tmp_path / "junk.clmodel"
    junk.write_text("not json")
    with pytest.raises(ModelError, match="not a model file"):
        models.import_model(repo, junk)


def test_rename_never_takes_another_models_name(repo) -> None:
    models.save_model(repo, "a", _line())
    models.save_model(repo, "b", _line())
    with pytest.raises(ModelError, match="exists"):
        models.rename_model(repo, "a", "b")
    assert models.rename_model(repo, "a", " c ") == "c"
    assert [row["name"] for row in repo.models()] == ["b", "c"]
