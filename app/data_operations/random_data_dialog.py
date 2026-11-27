"""Random data: a table of random numbers drawn with numpy.random, checked, and drawn.

The window collects the layout, the distribution of each random column with its parameters, the correlation, the
number of rows and the seed; the engine (app.analysis.random_data) draws the table, and app.analysis.random_check
says whether the sample is what it was drawn to be. OK writes the table and draws a figure of panels, chosen in
the Charts tab: for one column the histogram with its fitted curve, the Q-Q plot, the ECDF and a box; for two
the scatter, the joint plot and the 2D histogram; for three the scatter and the pair plot; Y against an evenly
spaced X with the histogram of Y; for Z over a grid the surface, the contour and the histogram of Z. The same seed gives the
same table, so Preview and OK draw the same numbers; a seed left at "Random" is drawn once and kept until a
setting changes.
"""
from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from app import SVG
from app.analysis import random_check as rc
from app.analysis import random_data as rd
from app.analysis.random_data import Axis, ColumnSpec
from app.plugin_api.data_operations.dialog_base import (
    DataOperationDialogBase,
    ResultSeriesSpec,
)
from app.plugin_api.data_operations.parameter_spec import (
    BoolParam,
    ChoiceParam,
    FloatParam,
    IntParam,
    Param,
    TextParam,
)
from app.plugin_api.data_operations.results import TableResult
from app.utils import report_html
from app.utils.logger import applogger
from app.utils.i18n import _

#: The charts of the Charts tab: the chart type, whether it starts ticked, the layouts that offer it.
CHARTS: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("Histogram", True, (rd.LAYOUT_X, rd.LAYOUT_LINE, rd.LAYOUT_GRID)),
    ("Q-Q Plot", True, (rd.LAYOUT_X,)),
    ("ECDF", True, (rd.LAYOUT_X,)),
    ("Box Plot", False, (rd.LAYOUT_X,)),
    ("Scatter Plot", True, (rd.LAYOUT_XY, rd.LAYOUT_XYZ, rd.LAYOUT_LINE)),
    ("Joint Plot", True, (rd.LAYOUT_XY,)),
    ("2D Histogram", False, (rd.LAYOUT_XY,)),
    ("Pair Plot", True, (rd.LAYOUT_XYZ,)),
    ("Surface Plot", True, (rd.LAYOUT_GRID,)),
    ("Contour Plot", True, (rd.LAYOUT_GRID,)),
)

#: The checks are skipped above this many rows (the window would stop for seconds).
CHECK_MAX_ROWS = 100_000
#: The largest seed a spin box holds; 0 is "Random".
MAX_SEED = 2_147_483_647

#: The layouts this window offers: (label, key).
LAYOUTS: tuple[tuple[str, str], ...] = (
    ("One random column (X)", rd.LAYOUT_X),
    ("Two random columns (X, Y)", rd.LAYOUT_XY),
    ("Three random columns (X, Y, Z)", rd.LAYOUT_XYZ),
    ("Evenly spaced X, random Y", rd.LAYOUT_LINE),
    ("Grid of X and Y, random Z", rd.LAYOUT_GRID),
)
LAYOUT_LABELS = {key: label for label, key in LAYOUTS}

#: The layouts that have a 1st, 2nd and 3rd random column.
COLUMN_LAYOUTS: tuple[tuple[str, ...], ...] = (
    tuple(key for _label, key in LAYOUTS),
    (rd.LAYOUT_XY, rd.LAYOUT_XYZ),
    (rd.LAYOUT_XYZ,),
)
COLUMN_LABELS = ("1st column", "2nd column", "3rd column")

#: How each parameter is worded.
PARAMETER_LABELS = {
    "mean": "Mean", "sd": "Standard deviation", "low": "Low", "high": "High", "scale": "Scale", "mu": "Mu",
    "sigma": "Sigma", "shape": "Shape", "a": "a", "b": "b", "df": "Degrees of freedom", "location": "Location",
    "left": "Left", "mode": "Mode", "right": "Right", "n": "Trials", "p": "Probability",
}

#: Spin boxes cannot say "above 0": a parameter that must be positive starts here.
_ABOVE = 1.0e-6


def _dist_field(column: int) -> str:
    """The name of column *column*'s distribution choice: "dist", "dist_2", "dist_3"."""
    return "dist" if column == 0 else f"dist_{column + 1}"


def _field_name(parameter: str, key: str, column: int = 0) -> str:
    return f"{parameter}__{key}" if column == 0 else f"{parameter}__{key}__{column + 1}"


def distribution_params(column: int = 0) -> tuple[Param, ...]:
    """One row for each parameter of each distribution of random column *column*, shown while that column's
    layout has it and that distribution is chosen."""
    params: list[Param] = []
    for key, dist in rd.DISTRIBUTIONS.items():
        for p in dist.parameters:
            common: dict[str, Any] = {
                "name": _field_name(p.name, key, column), "label": PARAMETER_LABELS.get(p.name, p.name),
                "visible_for": {"layout": COLUMN_LAYOUTS[column], _dist_field(column): (key,)},
                "section": f"{COLUMN_LABELS[column]}: {dist.label}",
            }
            low = -1.0e9 if p.minimum is None else p.minimum + (_ABOVE if p.open_minimum else 0.0)
            high = 1.0e9 if p.maximum is None else p.maximum - (_ABOVE if p.open_maximum else 0.0)
            if p.integer:
                params.append(IntParam(**common, default_value=int(p.default), minimum=int(np.ceil(low)),
                                       maximum=int(min(high, 1.0e9))))
            else:
                bounded = p.maximum is not None and p.maximum <= 1.0
                params.append(FloatParam(**common, default_value=p.default, minimum=low, maximum=high,
                                         decimals=4, step=0.05 if bounded else 0.1))
    return tuple(params)


class _PValues:
    """The p-values of a repetition as a table: Test (where and which), P."""

    def __init__(self, repeated: rc.Repeated) -> None:
        self.repeated = repeated

    def to_df(self) -> pd.DataFrame:
        rows = [(f"{where} {test}".strip(), p) for (where, test), values in self.repeated.pvalues.items()
                for p in values]
        return pd.DataFrame(rows, columns=["Test", "P"])


@dataclass(slots=True)
class RandomResult(TableResult):
    """One generated table, with how it was made and what the checks said."""

    result_name: str
    generated: rd.Generated
    #: The checks, or None when they were turned off or the table is too big.
    check: rc.TableCheck | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The "source" of a result table's name: a sample has no source series.
    source_name: str = "Sample"
    #: The correlation asked for (a number or a matrix), and the function of x and y a grid sits on, as typed.
    correlation: Any = None
    expression: str = ""
    #: The p-values of a repetition (Repeat above 1), or None.
    repeated: rc.Repeated | None = None

    @property
    def model_name(self) -> str:
        return ", ".join(c.distribution for c in self.generated.columns)

    def to_df(self) -> pd.DataFrame:
        return self.generated.table

    def preview(self, dialog: RandomDataDialog, axis_id: int) -> None:
        table_name = dialog.preview_table_name(axis_id, self)
        dialog.write_result_table(table_name, self)
        dialog.remember_preview_table(table_name)
        pvalues = self._write_pvalues(dialog, table_name)
        if pvalues:
            dialog.remember_preview_table(pvalues)
        dialog.draw_panels(table_name, self, pvalues)

    def apply(self, dialog: RandomDataDialog, axis_id: int) -> None:
        table_name = dialog.result_table_name(axis_id, self)
        dialog.write_result_table(table_name, self)
        applogger.info(f"Saved result table: {table_name}")
        dialog.draw_panels(table_name, self, self._write_pvalues(dialog, table_name))

    def _write_pvalues(self, dialog: RandomDataDialog, table_name: str) -> str | None:
        """The table of a repetition's p-values, beside the sample's (its name and "_P"); None without one."""
        if self.repeated is None or not self.repeated.pooled().size:
            return None
        name = f"{table_name}_P"
        dialog.write_result_table(name, _PValues(self.repeated))
        return name


class RandomDataDialog(DataOperationDialogBase):
    DESTINATIONS = (
        DataOperationDialogBase.DEST_NEW_AXIS,
        DataOperationDialogBase.DEST_NEW_FIGURE,
        DataOperationDialogBase.DEST_SAME_AXIS,
    )
    DEFAULT_DESTINATION = DataOperationDialogBase.DEST_NEW_FIGURE
    Name = "Random data"
    Description = "Draw random numbers from a distribution and check them"
    INPUT_MINIMUM_POINTS = 0
    SHOWS_SERIES_SELECTOR = False
    SHOW_DATA = False
    RESULT_TABLE_PREFIX = "Random"
    RESULT_TABLE_VARIANT = None

    PARAMS = (
        ChoiceParam("layout", "Layout", tooltip="The columns the table has and which of them are random.",
                    choices=LAYOUTS),
        IntParam("n", "Rows", tooltip="How many random numbers to draw.", default_value=1000, minimum=1,
                 maximum=rd.MAX_ROWS, step=100, visible_for={"layout": (rd.LAYOUT_X, rd.LAYOUT_XY, rd.LAYOUT_XYZ)}),
        FloatParam("x_start", "X from", tooltip="First value of the evenly spaced X.", default_value=0.0,
                   minimum=-1.0e12, maximum=1.0e12, decimals=6, step=1.0,
                   visible_for={"layout": (rd.LAYOUT_LINE, rd.LAYOUT_GRID)}),
        FloatParam("x_stop", "X to", tooltip="Last value of the evenly spaced X.", default_value=10.0,
                   minimum=-1.0e12, maximum=1.0e12, decimals=6, step=1.0,
                   visible_for={"layout": (rd.LAYOUT_LINE, rd.LAYOUT_GRID)}),
        IntParam("x_points", "X points", tooltip="How many X values. A line has one row for each; a grid has X "
                 "points times Y points.", default_value=500, minimum=2, maximum=rd.MAX_ROWS, step=50,
                 visible_for={"layout": (rd.LAYOUT_LINE, rd.LAYOUT_GRID)}),
        FloatParam("y_start", "Y from", tooltip="First value of the grid's Y.", default_value=0.0,
                   minimum=-1.0e12, maximum=1.0e12, decimals=6, step=1.0, visible_for={"layout": (rd.LAYOUT_GRID,)}),
        FloatParam("y_stop", "Y to", tooltip="Last value of the grid's Y.", default_value=10.0,
                   minimum=-1.0e12, maximum=1.0e12, decimals=6, step=1.0, visible_for={"layout": (rd.LAYOUT_GRID,)}),
        IntParam("y_points", "Y points", tooltip="How many Y values of the grid.", default_value=30, minimum=2,
                 maximum=rd.MAX_ROWS, step=5, visible_for={"layout": (rd.LAYOUT_GRID,)}),
        TextParam("function", "Function of x and y", tooltip="Added to the random Z: Z = f(x, y) + the random "
                  "numbers. Numbers, x, y, pi, e, + - * / ^ and sin cos tan exp log sqrt abs...; empty for none.",
                  placeholder="sin(x) * cos(y)", visible_for={"layout": (rd.LAYOUT_GRID,)}),
        FloatParam("trend_a", "Trend: intercept", tooltip="Y is a + b X plus the random numbers: a.",
                   default_value=0.0, minimum=-1.0e9, maximum=1.0e9, decimals=4, step=0.5,
                   visible_for={"layout": (rd.LAYOUT_LINE,)}),
        FloatParam("trend_b", "Trend: slope", tooltip="Y is a + b X plus the random numbers: b.",
                   default_value=0.0, minimum=-1.0e9, maximum=1.0e9, decimals=4, step=0.1,
                   visible_for={"layout": (rd.LAYOUT_LINE,)}),
        *(ChoiceParam(_dist_field(column), f"Distribution, {COLUMN_LABELS[column]}",
                      tooltip="Where this column's random numbers come from.",
                      visible_for={"layout": COLUMN_LAYOUTS[column]},
                      choices=tuple((dist.label, key) for key, dist in rd.DISTRIBUTIONS.items()))
          for column in range(3)),
        FloatParam("corr", "Correlation", tooltip="Between the two columns, from -1 to 1 (0: independent). A "
                   "Gaussian copula: exactly Pearson's for normal columns, Spearman's close to it for others.",
                   default_value=0.0, minimum=-0.99, maximum=0.99, decimals=3, step=0.1,
                   visible_for={"layout": (rd.LAYOUT_XY,)}),
        FloatParam("corr_xy", "Correlation, 1st and 2nd", tooltip="From -1 to 1 (0: independent). The three "
                   "together must be possible.", default_value=0.0, minimum=-0.99, maximum=0.99, decimals=3,
                   step=0.1, visible_for={"layout": (rd.LAYOUT_XYZ,)}),
        FloatParam("corr_xz", "Correlation, 1st and 3rd", default_value=0.0, minimum=-0.99, maximum=0.99,
                   decimals=3, step=0.1, visible_for={"layout": (rd.LAYOUT_XYZ,)}),
        FloatParam("corr_yz", "Correlation, 2nd and 3rd", default_value=0.0, minimum=-0.99, maximum=0.99,
                   decimals=3, step=0.1, visible_for={"layout": (rd.LAYOUT_XYZ,)}),
        *(param for column in range(3) for param in distribution_params(column)),
        IntParam("seed", "Seed", tooltip="The same seed draws the same numbers. Random: a new seed each time "
                 "a setting changes (the report says which).", default_value=0, minimum=0, maximum=MAX_SEED,
                 special_text="Random"),
        *(BoolParam(chart, chart, default_value=default, tab="charts", visible_for={"layout": layouts})
          for chart, default, layouts in CHARTS),
        IntParam("repeat", "Repeat", tooltip="Draw and check the sample this many times (seeds seed, seed + 1, ...) "
                 "and show how each test's p-values are spread: flat, with about 5% below 0.05, when the numbers "
                 "are as drawn. It shows how little one p = 0.03 means. 1: no repetition.", default_value=1,
                 minimum=1, maximum=rc.MAX_REPEATS, step=10, visible_for={"check": (True,)}),
        BoolParam("check", "Check the sample", tooltip="Test whether the numbers are what they were drawn to be: "
                  "the fit, the moments, normality, the order, the correlation. Skipped above 100,000 rows.",
                  default_value=True),
    )

    Icon = SVG.RANDOM_DATA
    Keywords = ("random casuale numeri casuali distribuzione distribution simulate simula numpy generate genera "
                "sample campione histogram istogramma seed noise rumore")
    Goals: ClassVar[list[str]] = ["prepare", "describe"]
    Category = "Graph"
    Order = 6
    WINDOW_SIZE = (800, 700)
    #: Reads no series or table: analysis_api opens it on a scratch figure and sets only its parameters.
    GENERATES = True

    def __init__(self, **kwargs: Any) -> None:
        #: The seed drawn for "Random", kept until a setting changes so Preview and OK agree.
        self._drawn_seed: int | None = None
        super().__init__(**kwargs)
        self.axis_series_panel.setVisible(False)
        self.mark_results_stale()

    def parameters_changed(self) -> None:
        self._drawn_seed = None
        super().parameters_changed()
        if self.chart_form is not None:
            self.chart_form.refresh_visibility()  # the charts a layout offers

    def parameter_context(self) -> dict[str, Any]:
        """The layout is read by the Charts tab's visibility rules: each layout lists the charts it can draw."""
        form = self._parameter_form_spec
        layout = str(form.values().get("layout", rd.LAYOUT_X)) if form is not None else rd.LAYOUT_X
        return {**super().parameter_context(), "layout": layout}

    def selected_series(self) -> list[Any]:
        return []

    # ---------- the request ----------
    def _column_specs(self, values: dict[str, Any], layout: str) -> list[ColumnSpec]:
        specs = []
        for column in range(rd.RANDOM_COLUMNS[layout]):
            key = str(values[_dist_field(column)])
            specs.append(ColumnSpec(key, {p.name: values[_field_name(p.name, key, column)]
                                          for p in rd.distribution(key).parameters}))
        return specs

    @staticmethod
    def _correlation(values: dict[str, Any], layout: str) -> float | list[list[float]] | None:
        if layout == rd.LAYOUT_XY:
            return float(values["corr"])
        if layout == rd.LAYOUT_XYZ:
            a, b, c = float(values["corr_xy"]), float(values["corr_xz"]), float(values["corr_yz"])
            return [[1.0, a, b], [a, 1.0, c], [b, c, 1.0]]
        return None

    def _seed(self, values: dict[str, Any]) -> int:
        if int(values["seed"]) > 0:
            return int(values["seed"])
        if self._drawn_seed is None:
            self._drawn_seed = int(np.random.SeedSequence().entropy % MAX_SEED) + 1  # type: ignore[operator]
        return self._drawn_seed

    def compute_results(self) -> Sequence[RandomResult]:
        values = self.parameter_values()
        layout, seed = str(values["layout"]), self._seed(values)
        specs = self._column_specs(values, layout)
        options: dict[str, Any] = {}
        if layout in (rd.LAYOUT_X, rd.LAYOUT_XY, rd.LAYOUT_XYZ):
            options["n"] = int(values["n"])
            if layout != rd.LAYOUT_X:
                options["correlation"] = self._correlation(values, layout)
        else:
            options["x_axis"] = Axis(float(values["x_start"]), float(values["x_stop"]), int(values["x_points"]))
            if layout == rd.LAYOUT_LINE:
                options["trend"] = (float(values["trend_a"]), float(values["trend_b"]))
            else:
                options["y_axis"] = Axis(float(values["y_start"]), float(values["y_stop"]), int(values["y_points"]),
                                         name="Y")
                if str(values["function"]).strip():
                    options["function"] = rd.expression_function(str(values["function"]))
        generated = rd.generate(layout, specs, seed=seed, **options)
        result = RandomResult(result_name=f"{_('Random')} {generated.table.columns[-1]}", generated=generated,
                              correlation=options.get("correlation"), expression=str(values.get("function", "")).strip()
                              if layout == rd.LAYOUT_GRID else "")
        checks = {key: options[key] for key in ("correlation", "trend", "function") if key in options}
        if values["check"]:
            if len(generated.table) > CHECK_MAX_ROWS:
                result.notes.append(_("The sample was not checked: it has more than {limit:,} rows.").format(
                    limit=CHECK_MAX_ROWS))
            else:
                result.check = rc.check_generated(generated, **checks)
                repeat = int(values.get("repeat", 1))
                if repeat > 1:
                    result.repeated = rc.repeat_check(
                        lambda s: rc.check_generated(rd.generate(layout, specs, seed=s, **options), **checks),
                        repeat, seed)
        return [result]

    # ---------- drawn ----------
    def resolve_target_axis_id(self, selected_axis_id: int, results: Sequence[Any]) -> int:
        """The panels are drawn as a figure of their own: nothing is added to the selected axis."""
        del results
        return selected_axis_id

    def panels_for(self, table_name: str, result: RandomResult) -> list[tuple[Any, ...]]:
        """The figure's panels for the layout, each ``(chart, title, x label, y label, series, options)``."""
        layout = result.generated.layout
        columns = list(result.generated.table.columns)
        quoted = [f'"{name}"' for name in columns]
        source = f'"{table_name}"'
        name = result.result_name

        def series(select: str, roles: dict[str, str], style: dict[str, Any] | None = None,
                   order: str = "") -> list[tuple[Any, ...]]:
            return [(name, f"SELECT {select} FROM {source}{order}", roles,
                     {**self.generated_style_filter, "seed": result.generated.seed, **(style or {})})]

        def values(column: int) -> list[tuple[Any, ...]]:
            return series(f"{quoted[column]} AS value", {"value": "value"})

        def pair() -> list[tuple[Any, ...]]:
            return series(f"{quoted[0]} AS x, {quoted[1]} AS y", {"x": "x", "y": "y"},
                          {"linestyle": "", "marker": "o", "markersize": 3},
                          " ORDER BY x" if layout == rd.LAYOUT_LINE else "")

        panels: list[tuple[Any, ...]] = []
        if layout == rd.LAYOUT_X:
            dist = rd.distribution(result.generated.columns[0].distribution)
            fit = {} if dist.discrete else {"distribution_fit": rd.theory(dist.key).dist.name}
            panels.append(("Histogram", name, columns[0], _("Density") if fit else _("Count"), values(0),
                           {"grid": True, **fit}))
            if not dist.discrete:
                panels.append(("Q-Q Plot", _("Quantile plot"), _("Theoretical quantiles"), columns[0],
                               values(0), {"distribution": rd.theory(dist.key).dist.name}))
            panels.append(("ECDF", _("Empirical distribution"), columns[0], _("Probability"), values(0),
                           {"grid": True, **fit}))
            panels.append(("Box Plot", _("Box plot"), "", columns[0], values(0), {"grid": True}))
        elif layout in (rd.LAYOUT_XY, rd.LAYOUT_XYZ, rd.LAYOUT_LINE):
            panels.append(("Scatter Plot", name, columns[0], columns[1], pair(), {"grid": True}))
            if layout == rd.LAYOUT_XY:
                panels.append(("Joint Plot", _("Joint distribution"), columns[0], columns[1], series(
                    f"{quoted[0]} AS x, {quoted[1]} AS y", {"x": "x", "y": "y"}), {}))
                panels.append(("2D Histogram", _("Density of the pairs"), columns[0], columns[1], series(
                    f"{quoted[0]} AS x, {quoted[1]} AS y", {"x": "x", "y": "y"}), {}))
            elif layout == rd.LAYOUT_XYZ:
                roles = {f"column_{i + 1}": f"column_{i + 1}" for i in range(3)}
                panels.append(("Pair Plot", _("Pair plot"), "", "", series(
                    ", ".join(f"{quoted[i]} AS column_{i + 1}" for i in range(3)), roles), {}))
            else:
                panels.append(("Histogram", _("Distribution of Y"), columns[1], _("Count"), values(1),
                               {"grid": True}))
        else:  # the grid
            xyz = series(f"{quoted[0]} AS x, {quoted[1]} AS y, {quoted[2]} AS z", {"x": "x", "y": "y", "z": "z"},
                         {"fit_mode": "2D"})
            panels.append(("Surface Plot", name, columns[0], columns[1], xyz, {"grid": True, "projection": "3d"}))
            panels.append(("Contour Plot", _("Contour of Z"), columns[0], columns[1], xyz, {}))
            panels.append(("Histogram", _("Distribution of Z"), columns[2], _("Count"), values(2), {"grid": True}))
        return panels

    def draw_panels(self, table_name: str, result: RandomResult, pvalues_table: str | None = None) -> None:
        """The figure of the sample: the panels ticked in the Charts tab, and after them the p-values of a
        repetition (drawn with the Histogram box)."""
        panels = self.panels_for(table_name, result)
        if pvalues_table:
            panels.append(("Histogram", _("p-values of all the tests"), _("p-value"), _("Count"), [(
                result.result_name, f'SELECT "P" AS value FROM "{pvalues_table}"', {"value": "value"},
                {**self.generated_style_filter, "bins": 20})], {"grid": True}))
        self.create_report_figure(result.result_name, self.format_results([result]), panels)

    # ---------- the report ----------
    def results_subtitle(self, results: Sequence[RandomResult]) -> str:
        return ""

    def result_section(self, result: RandomResult) -> str:
        generated = result.generated
        rows: list[tuple[str, Any]] = [(_("Layout"), _(LAYOUT_LABELS[generated.layout])),
                                       (_("Rows"), f"{len(generated.table):,}"), (_("Seed"), generated.seed)]
        for column in generated.columns:
            dist = rd.distribution(column.distribution)
            parameters = ", ".join(f"{name} = {report_html.format_number(float(value))}"
                                   for name, value in zip((p.name for p in dist.parameters),
                                                          rd.clean_parameters(column.distribution, column.parameters)))
            rows.append((column.name, f"{_(dist.label)} ({parameters})"))
        if result.correlation is not None:
            rows.append((_("Correlation"), self._correlation_text(result.correlation)))
        if result.expression:
            rows.append((_("Function of x and y"), result.expression))
        blocks = [report_html.summary_table(rows)]
        blocks += [report_html.note(note) for note in result.notes]
        if result.check is not None:
            blocks += self._check_blocks(result.check)
        if result.repeated is not None:
            blocks += self._repeat_blocks(result.repeated)
        return report_html.section(result.result_name, *blocks)

    @staticmethod
    def _correlation_text(correlation: Any) -> str:
        if np.isscalar(correlation):
            return f"{float(correlation):g}"
        matrix = np.asarray(correlation, dtype=float)
        names = ("1-2", "1-3", "2-3")
        pairs = ((0, 1), (0, 2), (1, 2))
        return ", ".join(f"{name}: {matrix[i, j]:g}" for name, (i, j) in zip(names, pairs))

    def _check_blocks(self, check: rc.TableCheck) -> list[str]:
        verdict, sentences = check.verdict()
        lines = [_(template).format(**values) for template, values in sentences]
        colour = "#1a7f37" if verdict == "yes" else "#b42318"
        blocks = [f"<p style='font-size:125%; color:{colour}'><b>{html.escape(lines[0])}</b></p>"
                  + "".join(f"<p>{html.escape(line)}</p>" for line in lines[1:])]
        headers = (_("Test"), _("n"), _("Statistic"), _("p-value"), _("Note"))

        def rows(found: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
            return [(html.escape(str(r["test"])), r["n"],
                     "" if not np.isfinite(r["statistic"]) else report_html.format_number(float(r["statistic"])),
                     "" if not np.isfinite(r["pvalue"]) else report_html.format_p_value(float(r["pvalue"])),
                     html.escape(str(r.get("note", "")))) for r in found]

        for column in check.columns:
            blocks.append(report_html.section(f"{column.name}: {_('fit')}", report_html.table(
                headers, rows(column.fit + column.uniformity), align=("left", "right", "right", "right", "left"))))
            blocks.append(report_html.section(f"{column.name}: {_('order')}", report_html.table(
                headers, rows(column.order), align=("left", "right", "right", "right", "left"))))
            blocks.append(report_html.section(f"{column.name}: {_('normality')}", report_html.table(
                headers, rows(column.normality), align=("left", "right", "right", "right", "left"))))
            moments = column.moments
            blocks.append(report_html.section(f"{column.name}: {_('moments')}", report_html.table(
                (_("Statistic"), _("Sample"), _("Theoretical"), _("Z"), _("Note")),
                [(html.escape(str(r.Statistic)), report_html.format_number(float(r.Sample)),
                  report_html.format_number(float(r.Theoretical)) if np.isfinite(r.Theoretical) else "",
                  "" if np.isnan(r.Z) else f"{float(r.Z):.2f}", html.escape(str(r.Note)))
                 for r in moments.itertuples()], align=("left", "right", "right", "right", "left"))))
        for pair in check.pairs:
            tables = [report_html.table(headers, rows(pair.independence), align=("left", "right", "right", "right", "left"))]
            if pair.against_requested:
                tables.append(report_html.note(_("Against the correlation asked for ({requested:g}):").format(
                    requested=pair.requested)))
                tables.append(report_html.table(headers, rows(pair.against_requested),
                                                align=("left", "right", "right", "right", "left")))
            blocks.append(report_html.section(f"{pair.first} / {pair.second}", *tables))
        if check.extra:
            title = _("Neighbouring cells") if check.layout == rd.LAYOUT_GRID else _("Trend")
            blocks.append(report_html.section(title, report_html.table(
                headers, rows(check.extra), align=("left", "right", "right", "right", "left"))))
        return blocks

    def _repeat_blocks(self, repeated: rc.Repeated) -> list[str]:
        summary = repeated.summary()
        rows = [(html.escape(f"{r.Where} {r.Test}".strip()), r.Samples, f"{r.Rejected:.1%}",
                 "" if np.isnan(r.Flat) else report_html.format_p_value(float(r.Flat)))
                for r in summary.itertuples()]
        intro = _("{repeats} samples were drawn (seeds {first} to {last}). When the numbers are as drawn, a test's "
                  "p-values are spread evenly between 0 and 1 and about 5% of them are below 0.05. Over all the "
                  "tests {rate:.1%} were. A test on discrete data, or on a few values, can be off without anything "
                  "being wrong.").format(repeats=repeated.repeats, first=repeated.seed,
                                         last=repeated.seed + repeated.repeats - 1, rate=repeated.rejection_rate())
        return [report_html.section(_("Repeated"), report_html.note(intro), report_html.table(
            (_("Test"), _("Samples"), _("Below 0.05"), _("Spread evenly (p)")), rows,
            align=("left", "right", "right", "right")))]

    def how_to_read(self, results: Sequence[Any]) -> list[str]:
        return []
