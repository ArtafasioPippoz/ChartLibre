"""Add noise to a series or a table's columns: for testing a fit, an outlier rule, a filter, with a known truth.

The engine is app.analysis.random_data.add_noise (the same one the Random data window's trend and function use
for their noise). The original series stay as they are; the noisy one is drawn beside them. The report says how
big the noise really is: its standard deviation, the signal-to-noise ratio obtained, the correlation with the
original. The same seed gives the same noise; several series get independent noise, or the same noise term when
"One noise for all the series" is ticked (for testing correlated errors).
"""
from __future__ import annotations

import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
from scipy import stats

from app import SVG
from app.analysis import random_data as rd
from app.plugin_api.data_operations.dialog_base import DataOperationDialogBase, OperationModel
from app.plugin_api.data_operations.parameter_spec import BoolParam, ChoiceParam, FloatParam, IntParam
from app.plugin_api.data_operations.results import XYResult
from app.utils import report_html
from app.utils.i18n import _

KIND_OF_MODEL: dict[str, str] = {
    "Additive": rd.NOISE_ADDITIVE,
    "Proportional": rd.NOISE_PROPORTIONAL,
    "Growing with X": rd.NOISE_GROWING,
    "Outliers": rd.NOISE_OUTLIERS,
    "Random walk": rd.NOISE_WALK,
    "Missing values": rd.NOISE_MISSING,
}
NOISE_MODELS: dict[str, OperationModel] = {name: OperationModel() for name in KIND_OF_MODEL}

#: The shapes offered for the noise. Location and scale are not asked: the amount sets the size, and the noise is
#: centred (see rd.add_noise), so only a shape parameter means anything.
SHAPES: tuple[tuple[str, str, str | None], ...] = (
    ("normal", "Normal", None), ("uniform", "Uniform", None), ("laplace", "Laplace", None),
    ("logistic", "Logistic", None), ("t", "Student t", "df"), ("exponential", "Exponential", None),
    ("lognormal", "Lognormal", "sigma"), ("gamma", "Gamma", "shape"),
)
_WITH_SHAPE = {"t": "df", "lognormal": "sigma", "gamma": "shape"}
_SPREAD_MODELS = ("Additive", "Growing with X", "Random walk")
_SHAPED_MODELS = ("Additive", "Proportional", "Growing with X", "Random walk")


@dataclass(slots=True)
class NoiseResult(XYResult):
    """One series with its noise."""

    source_name: str
    result_name: str
    model: str
    x: np.ndarray
    y: np.ndarray
    noise: np.ndarray
    sigma: float
    snr_db: float
    correlation: float
    metadata: dict[str, Any] = field(default_factory=dict)


class AddNoiseDialog(DataOperationDialogBase):
    """Add random noise of a kind, a shape and a size to the selected series."""

    DESTINATIONS = (DataOperationDialogBase.DEST_SAME_AXIS, DataOperationDialogBase.DEST_NEW_AXIS,
                    DataOperationDialogBase.DEST_NEW_FIGURE)
    DEFAULT_DESTINATION = DataOperationDialogBase.DEST_SAME_AXIS

    MODELS = NOISE_MODELS
    MODEL_TOOLTIP = "The kind of noise."

    Name: str = "Add noise"
    Description = "Add random noise, outliers or missing values to a series, to test what comes after"

    RUN_IN_BACKGROUND = True

    PARAMS = (
        ChoiceParam("amount_mode", "Amount given as", tooltip="The size of the noise: its standard deviation in "
                    "the units of the series, a fraction of the series' own standard deviation or range, or the "
                    "signal-to-noise ratio in dB.", default_value=rd.AMOUNT_ABSOLUTE,
                    choices=(("Standard deviation", rd.AMOUNT_ABSOLUTE), ("Fraction of the series' sd",
                             rd.AMOUNT_RELATIVE_SD), ("Fraction of the range", rd.AMOUNT_RELATIVE_RANGE),
                             ("Signal-to-noise (dB)", rd.AMOUNT_SNR)), visible_for={"model": _SPREAD_MODELS}),
        FloatParam("amount", "Amount", tooltip="Read as the choice above says. Proportional: the fraction of "
                   "each value (0.1 is 10%). Outliers: how many standard deviations a point is moved by.",
                   default_value=1.0, minimum=0.0, maximum=1.0e9, decimals=4, step=0.1),
        FloatParam("fraction", "Fraction of the points", tooltip="Between 0 and 1.", default_value=0.05,
                   minimum=0.0, maximum=1.0, decimals=3, step=0.01,
                   visible_for={"model": ("Outliers", "Missing values")}),
        FloatParam("power", "Growth power", tooltip="The noise grows as X to this power: 1 linearly, 2 as a "
                   "square. It is zero at the smallest X and the full amount at the largest.", default_value=1.0,
                   minimum=0.1, maximum=10.0, decimals=2, step=0.5, visible_for={"model": ("Growing with X",)}),
        ChoiceParam("shape", "Shape", tooltip="The distribution of the noise, centred and scaled to the amount.",
                    choices=tuple((label, key) for key, label, _p in SHAPES), default_value="normal",
                    visible_for={"model": _SHAPED_MODELS}),
        FloatParam("df", "Degrees of freedom", default_value=5.0, minimum=2.1, maximum=1000.0, decimals=1, step=1.0,
                   visible_for={"model": _SHAPED_MODELS, "shape": ("t",)}),
        FloatParam("sigma", "Log sigma", default_value=0.5, minimum=0.01, maximum=5.0, decimals=2, step=0.1,
                   visible_for={"model": _SHAPED_MODELS, "shape": ("lognormal",)}),
        FloatParam("shape_k", "Shape k", default_value=2.0, minimum=0.1, maximum=1000.0, decimals=2, step=0.5,
                   visible_for={"model": _SHAPED_MODELS, "shape": ("gamma",)}),
        BoolParam("keep_offset", "Keep the offset", tooltip="A skewed noise is centred on 0 so the signal does "
                  "not drift; tick to leave its mean where the distribution has it.", default_value=False,
                  visible_for={"model": _SHAPED_MODELS}),
        BoolParam("shared", "One noise for all the series", tooltip="The same noise term added to every series "
                  "(they need the same number of points): for testing correlated errors. Unticked: independent.",
                  default_value=False),
        IntParam("seed", "Seed", tooltip="The same seed adds the same noise. Random: a new seed each time a "
                 "setting changes (the report says which).", default_value=0, minimum=0, maximum=2**31 - 1,
                 special_text="Random"),
    )

    Icon = SVG.RANDOM_DATA
    Keywords = ("noise rumore add aggiungi random casuale outliers anomalie missing mancanti snr "
                "signal-to-noise heteroscedastic eteroschedastico random walk")
    Goals: ClassVar[list[str]] = ["prepare"]
    Category = "Transform"
    Order = 95
    WINDOW_SIZE = (760, 660)

    RESULT_TABLE_PREFIX = "Noise"
    RESULT_TABLE_VARIANT = "model"
    RESULT_COLUMNS = (("Series", "left"), ("Kind", "left"), ("Points", "right"), ("Noise sd", "right"),
                      ("SNR (dB)", "right"), ("Correlation", "right"))

    _drawn_seed: int | None = None

    def parameters_changed(self) -> None:
        self._drawn_seed = None
        super().parameters_changed()

    def _seed(self, values: dict[str, Any]) -> int:
        if int(values["seed"]) > 0:
            return int(values["seed"])
        if self._drawn_seed is None:
            self._drawn_seed = int(np.random.randint(1, 2**31 - 1))  # the global generator, so a test can fix it
        return self._drawn_seed

    def series_settings(self) -> Any:
        values = dict(self.parameter_values())
        values["seed"] = self._seed(values)
        return self.current_model(), values

    # ------------------------------------------------------------------
    def compute_series(self, name: str, data: tuple[np.ndarray, np.ndarray], settings: Any) -> NoiseResult:
        model, params = settings
        x, y = np.asarray(data[0]), np.asarray(data[1], dtype=float)
        kind = KIND_OF_MODEL[model]
        seed = int(params["seed"])
        if not params.get("shared"):
            seed = (seed + zlib.crc32(name.encode())) % (2**32)  # each series its own noise, the same every time
        shape = str(params.get("shape", "normal"))
        extra = {_WITH_SHAPE[shape]: float(params["shape_k" if shape == "gamma" else _WITH_SHAPE[shape]])} \
            if shape in _WITH_SHAPE else None
        try:
            x_numeric = np.asarray(x, dtype=float)
        except (TypeError, ValueError):
            x_numeric = None  # dates and the like: the index stands for X
        noisy = rd.add_noise(
            y, kind, amount=float(params["amount"]), mode=str(params.get("amount_mode", rd.AMOUNT_ABSOLUTE)),
            distribution_key=shape, parameters=extra, keep_offset=bool(params.get("keep_offset", False)),
            x=x_numeric, power=float(params.get("power", 1.0)), fraction=float(params.get("fraction", 0.05)),
            seed=seed)
        both = np.isfinite(y) & np.isfinite(noisy.values)
        correlation = float(np.corrcoef(y[both], noisy.values[both])[0, 1]) \
            if both.sum() > 2 and np.std(y[both]) > 0 and np.std(noisy.values[both]) > 0 else float("nan")
        added = noisy.noise[np.isfinite(noisy.noise)]
        metadata: dict[str, Any] = {"seed": int(params["seed"]), "points": int(y.size),
                                    "emptied": int(np.isnan(noisy.values).sum() - np.isnan(y).sum())}
        if added.size > 2 and np.std(added) > 0:
            metadata["noise sd obtained"] = float(np.std(added))
            metadata["noise mean"] = float(np.mean(added))
            if kind == rd.NOISE_ADDITIVE and shape == "normal":
                metadata["Shapiro-Wilk p of the noise"] = float(stats.shapiro(added[:5000]).pvalue)
        return NoiseResult(source_name=name, result_name=f"{name} - {_(model).lower()}", model=model, x=x,
                           y=noisy.values, noise=noisy.noise, sigma=noisy.sigma, snr_db=noisy.snr_db,
                           correlation=correlation, metadata=metadata)

    # ------------------------------------------------------------------
    def resolve_target_axis_id(self, selected_axis_id: int, results: Sequence[Any]) -> int:
        return self.resolve_destination_axis(
            selected_axis_id, chart_type="Scatter Plot", title=_("Add noise"),
            figure_name=self.result_figure_name(results, _("Add noise")),
            options={"grid": True, "linestyle": "-", "marker": ""})

    def result_row(self, result: NoiseResult) -> tuple[str, ...]:
        number = report_html.format_number
        return (result.source_name, _(result.model), f"{result.y.size:,}",
                "" if not np.isfinite(result.sigma) else number(result.sigma),
                "" if not np.isfinite(result.snr_db) else f"{result.snr_db:.1f}",
                "" if not np.isfinite(result.correlation) else f"{result.correlation:.4f}")

    def how_to_read(self, results: Sequence[Any]) -> list[str]:
        lines = [_("The original series are left as they are; the noisy ones are new. The signal-to-noise ratio is "
                   "the variance of the original over the mean square of the noise actually added, in dB: 20 dB is "
                   "noise a tenth of the signal.")]
        if results and results[0].metadata:
            lines.append(_("Seed {seed}: the same seed adds the same noise.").format(seed=results[0].metadata["seed"]))
        return lines
