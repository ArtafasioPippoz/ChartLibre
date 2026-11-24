"""Prediction models that outlive their analysis: a fitted model kept with what it needs to score new rows.

A model is a SavedModel: its response, its features (each with its kind and, for a category, the levels it was fitted
with), and predict(frame) -> a table of predictions. It is kept in the project (the __models__ table, see
app/data/repo/project.py) in one of two forms:

* portable - a JSON state a kind writes and reads itself (a linear model as its terms and coefficients, a tree as its
  nodes): readable, safe to open anywhere;
* pickled - the scikit-learn (or other) estimator and its encoding as a pickle: any estimator, but a pickle runs
  code when it is loaded, so it is loaded only on a computer that trusts it - the rule of the stored functions
  (app/data_operations/sympy_store.py): saved here, or accepted when asked. Its fingerprint is in user.json.

Applying a model never changes it: unseen category levels and missing values give an empty prediction and are
counted in the notes the call returns, not hidden.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pickle
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from app.utils.config import get_value, set_value

CONTINUOUS, NOMINAL = "continuous", "nominal"
#: user.json key: the fingerprints of the pickled models this computer runs.
TRUST_KEY = "trusted_models"
PORTABLE, PICKLED = "json", "pickle"


class ModelError(ValueError):
    """A model that cannot be saved, loaded or applied, in words for the user."""


class UntrustedModel(PermissionError):
    """A pickled model this computer was not told to run: made elsewhere and never accepted here."""


@dataclass
class Feature:
    """One column a model reads: its name, its kind, and the levels of a category as fitted."""

    name: str
    kind: str = CONTINUOUS
    levels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "levels": list(self.levels)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Feature:
        return cls(str(data["name"]), str(data.get("kind") or CONTINUOUS), [str(v) for v in data.get("levels") or []])


@dataclass
class Prediction:
    """What applying a model gave: the table of predictions (one row per input row, same index) and the notes."""

    table: pd.DataFrame
    notes: list[str] = field(default_factory=list)


class SavedModel:
    """The contract. A kind subclasses it, sets KIND and says how it predicts and how it is written.

    A portable kind overrides state() and from_state(); a pickled kind keeps FORM = PICKLED and is written whole.
    """

    KIND: ClassVar[str] = ""
    FORM: ClassVar[str] = PICKLED
    #: Kind name -> class, filled by register().
    REGISTRY: ClassVar[dict[str, type[SavedModel]]] = {}

    def __init__(self, response: str, features: list[Feature], *, response_kind: str = CONTINUOUS,
                 levels: list[str] | None = None, summary: Mapping[str, Any] | None = None,
                 source_table: str = "") -> None:
        self.response = response
        self.features = list(features)
        self.response_kind = response_kind
        #: A category response's levels, in the order of its probabilities.
        self.levels = list(levels or [])
        #: The numbers of the fit's report worth keeping (R², misclassification, rows...).
        self.summary: dict[str, Any] = dict(summary or {})
        self.source_table = source_table

    # -- what a kind provides -------------------------------------------------
    def predict_matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        """The predictions for *frame*, whose feature columns are already checked and coerced (Prediction, and
        Prob(level) for a category). Raise nothing for a missing value: leave the cell empty."""
        raise NotImplementedError

    def state(self) -> dict[str, Any]:
        """A portable kind's fitted part as JSON-able data."""
        raise NotImplementedError

    @classmethod
    def from_state(cls, header: Mapping[str, Any], state: Mapping[str, Any]) -> SavedModel:
        raise NotImplementedError

    # -- applying -------------------------------------------------------------
    def predict(self, data: pd.DataFrame) -> Prediction:
        """Score *data*: the features by name (a missing column is an error naming it), unseen levels and missing
        values counted in the notes."""
        missing = [f.name for f in self.features if f.name not in data.columns]
        if missing:
            raise ModelError(f"The table has no column {', '.join(missing)}, which this model reads.")
        frame = data.copy()
        notes: list[str] = []
        for feature in self.features:
            column = frame[feature.name]
            if feature.kind == NOMINAL:
                text = column.astype("string")
                unseen = text.notna() & ~text.isin(feature.levels)
                if unseen.any():
                    seen = sorted(set(text[unseen].dropna().astype(str)))[:5]
                    notes.append(f"{int(unseen.sum())} row(s) have a {feature.name} the model never saw "
                                 f"({', '.join(seen)}): no prediction.")
                frame[feature.name] = text.where(~unseen)
            else:
                numbers = pd.to_numeric(column, errors="coerce")
                bad = numbers.isna() & column.notna()
                if bad.any():
                    notes.append(f"{int(bad.sum())} row(s) have a {feature.name} that is not a number: no prediction.")
                frame[feature.name] = numbers
        empty = frame[[f.name for f in self.features]].isna().any(axis=1)
        if empty.any():
            notes.append(f"{int(empty.sum())} row(s) have a missing value in a column the model reads: no prediction.")
        table = self.predict_matrix(frame.loc[~empty]).reindex(frame.index)
        return Prediction(table, notes)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.KIND, "response": self.response, "response_kind": self.response_kind,
                "features": [f.to_dict() for f in self.features], "levels": list(self.levels),
                "summary": dict(self.summary), "source_table": self.source_table}

    @classmethod
    def register(cls, kind_class: type[SavedModel]) -> type[SavedModel]:
        """Class decorator: make a kind known by name."""
        if not kind_class.KIND:
            raise ModelError("A model kind needs a KIND.")
        cls.REGISTRY[kind_class.KIND] = kind_class
        return kind_class


# ----------------------------------------------------------------------
# Fingerprints and trust
# ----------------------------------------------------------------------
def fingerprint(kind: str, form: str, payload: bytes) -> str:
    """What a model runs - its kind and payload - as one hash: changed elsewhere, it is a new model."""
    return hashlib.sha256(b"\0".join((kind.encode(), form.encode(), payload))).hexdigest()


def _trusted() -> set[str]:
    value = get_value(TRUST_KEY, [])
    return {str(item) for item in value} if isinstance(value, list) else set()


def trust(fingerprints: list[str]) -> None:
    """Remember on this computer that these pickled models may run."""
    known = _trusted()
    new = set(fingerprints) - known
    if new:
        set_value(TRUST_KEY, sorted(known | new))


def is_trusted(fingerprint_: str) -> bool:
    return fingerprint_ in _trusted()


# ----------------------------------------------------------------------
# Writing and reading a model in a project
# ----------------------------------------------------------------------
def dump(model: SavedModel) -> tuple[str, bytes]:
    """(form, payload) of *model*: JSON bytes for a portable kind, a pickle for the others."""
    if model.FORM == PORTABLE:
        return PORTABLE, json.dumps(model.state(), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return PICKLED, pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)


def save_model(repo: Any, name: str, model: SavedModel, *, replace: bool = False) -> str:
    """Keep *model* in the project under *name*; returns the name. A pickled one is trusted here (it was made here)."""
    clean = str(name).strip()
    if not clean:
        raise ModelError("A model needs a name.")
    if not replace and any(row["name"] == clean for row in repo.models()):
        raise ModelError(f"A model called {clean} exists.")
    form, payload = dump(model)
    fingerprint_ = fingerprint(model.KIND, form, payload)
    from app import APP_VERSION

    repo.save_model_record(
        name=clean, kind=model.KIND, form=form, payload=payload, fingerprint=fingerprint_,
        header={"response": model.response, "response_kind": model.response_kind, "levels": model.levels,
                "features": [f.to_dict() for f in model.features], "summary": model.summary,
                "source_table": model.source_table, "app_version": str(APP_VERSION),
                "created": datetime.now(UTC).isoformat(timespec="seconds")})
    if form == PICKLED:
        trust([fingerprint_])
    return clean


def load_model(repo: Any, name: str) -> SavedModel:
    """The model *name* of the project, or ModelError / UntrustedModel saying why not."""
    row = repo.model_record(name)
    if row is None:
        known = ", ".join(r["name"] for r in repo.models()) or "none"
        raise ModelError(f"No model called {name}. Models: {known}.")
    kind = row["kind"]
    if row["form"] == PORTABLE:
        cls = SavedModel.REGISTRY.get(kind)
        if cls is None:
            raise ModelError(f"{name} is a model of kind {kind}, which this ChartLibre does not know.")
        return cls.from_state(row["header"], json.loads(bytes(row["payload"]).decode("utf-8")))
    if fingerprint(kind, row["form"], bytes(row["payload"])) != row["fingerprint"]:
        raise ModelError(f"{name} was changed after it was saved: it is not loaded.")
    if not is_trusted(row["fingerprint"]):
        raise UntrustedModel(f"{name} is a pickled model made on another computer ({kind}, ChartLibre "
                             f"{row['header'].get('app_version', '?')}); trust it to run it.")
    try:
        model = pickle.loads(bytes(row["payload"]))  # noqa: S301 - trusted by its fingerprint, as above
    except Exception as error:
        raise ModelError(f"{name} could not be loaded ({type(error).__name__}: {error}). It was made with "
                         f"ChartLibre {row['header'].get('app_version', '?')}.") from error
    if not isinstance(model, SavedModel):
        raise ModelError(f"{name} is not a model.")
    return model


# ----------------------------------------------------------------------
# A model as a file: out of one project, into another
# ----------------------------------------------------------------------
#: The file's own mark and version, its first key.
FILE_MARK = "chartlibre_model"
FILE_SUFFIX = ".clmodel"


def needs_trust(repo: Any, name: str) -> bool:
    """True for a pickled model this computer has not accepted yet (made elsewhere, or imported from a file)."""
    row = repo.model_record(name)
    return row is not None and row["form"] == PICKLED and not is_trusted(row["fingerprint"])


def trust_model(repo: Any, name: str) -> None:
    """Accept the pickled model *name* on this computer: it may run from now on."""
    row = repo.model_record(name)
    if row is not None:
        trust([row["fingerprint"]])


def rename_model(repo: Any, old: str, new: str) -> str:
    """Give the model *old* the name *new*; never over another model."""
    clean = str(new).strip()
    if not clean:
        raise ModelError("A model needs a name.")
    names = {row["name"] for row in repo.models()}
    if old not in names:
        raise ModelError(f"No model called {old}.")
    if clean != old and clean in names:
        raise ModelError(f"A model called {clean} exists.")
    repo.rename_model(old, clean)
    return clean


def export_model(repo: Any, name: str, path: Any) -> Path:
    """Write the model *name* to a file (JSON; a pickled payload inside as base64), as it is kept in the project."""
    row = repo.model_record(name)
    if row is None:
        raise ModelError(f"No model called {name}.")
    target = Path(path)
    if target.suffix != FILE_SUFFIX:
        target = target.with_name(target.name + FILE_SUFFIX)
    target.write_text(json.dumps({
        FILE_MARK: 1, "name": row["name"], "kind": row["kind"], "form": row["form"], "header": row["header"],
        "fingerprint": row["fingerprint"],
        "payload": base64.b64encode(bytes(row["payload"])).decode("ascii"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return target


def import_model(repo: Any, path: Any, name: str | None = None) -> str:
    """Add the model of a file to the project; returns the name it took (numbered when the name is taken).

    Nothing of the file is run: a pickled model stays untrusted - and unloaded - until this computer accepts it
    (trust_model). A file whose payload does not match its fingerprint was changed, and is refused.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        payload = base64.b64decode(data["payload"], validate=True)
        kind, form, header = str(data["kind"]), str(data["form"]), dict(data["header"])
        mark = data[FILE_MARK]
    except Exception as error:
        raise ModelError(f"{Path(path).name} is not a model file ({type(error).__name__}).") from error
    if mark != 1 or form not in (PORTABLE, PICKLED):
        raise ModelError(f"{Path(path).name} was written by a newer ChartLibre: it is not read.")
    fingerprint_ = fingerprint(kind, form, payload)
    if fingerprint_ != str(data.get("fingerprint", "")):
        raise ModelError(f"{Path(path).name} was changed after it was exported: it is not imported.")
    taken = {row["name"] for row in repo.models()}
    stem = str(name or data.get("name") or Path(path).stem).strip() or "model"
    clean, number = stem, 2
    while clean in taken:
        clean, number = f"{stem} {number}", number + 1
    repo.save_model_record(name=clean, kind=kind, form=form, payload=payload, fingerprint=fingerprint_,
                           header=header)
    return clean


def predict_table(repo: Any, name: str, source: str | pd.DataFrame) -> Prediction:
    """Apply the model *name* to a table of the project (by name) or to a DataFrame."""
    model = load_model(repo, name)
    frame = source if isinstance(source, pd.DataFrame) else repo.query_df(f'SELECT * FROM "{source}"')
    return model.predict(frame)


def numbers(values: Any) -> np.ndarray:
    """A helper for kinds: a column as floats."""
    return np.asarray(pd.to_numeric(pd.Series(values), errors="coerce"), dtype=float)


__all__ = [
    "CONTINUOUS", "NOMINAL", "PICKLED", "PORTABLE", "Feature", "ModelError", "Prediction", "SavedModel",
    "UntrustedModel", "dump", "fingerprint", "is_trusted", "load_model", "predict_table", "save_model", "trust",
]
_ = Callable  # kept for kinds that type their predict hooks
