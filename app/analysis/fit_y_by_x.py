"""Fit Y by X: one response against one factor, the analysis chosen by the two columns' types (AN-03).

As JMP's platform of the same name:

==============  ==============  =====================================================
Y               X               Analysis
==============  ==============  =====================================================
continuous      continuous      Bivariate: the least-squares line, correlations
continuous      nominal         Oneway: means, ANOVA / Welch / Kruskal-Wallis, and
                                the pairs compared - Tukey HSD, Games-Howell
                                (unequal variances), Dunn with Holm (ranks)
nominal         nominal         Contingency: counts, row shares, chi-squared, Fisher
nominal         continuous      Logistic: the probability of each level along X
==============  ==============  =====================================================

An ordinal column counts as continuous when it is the response and as
nominal (groups) when it is the factor. The tests themselves are the ones
of app.analysis.statistics; the two post hoc comparisons beyond Tukey are
here.
"""
from __future__ import annotations

from typing import Any

import itertools
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from app.analysis import statistics as st
from app.analysis.models import CONTINUOUS, NOMINAL, PORTABLE, Feature, SavedModel
from app.utils.coercion import column_of, to_numbers

BIVARIATE, ONEWAY, CONTINGENCY, LOGISTIC = "Bivariate", "Oneway", "Contingency", "Logistic"


@dataclass(slots=True)
class FitYByXResult:
    y: str
    x: str
    kind: str
    #: Report tables, in the order shown: title -> frame.
    tables: dict[str, pd.DataFrame]
    #: What the chart draws (the fitted line, the probability curves); empty when the raw data suffice.
    curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    notes: list[str] = field(default_factory=list)
    #: The fitted model as a SavedModel (portable, JSON): keep it, or score new rows with it.
    model: Any = None


def analysis_for(y_continuous: bool, x_continuous: bool) -> str:
    if y_continuous:
        return BIVARIATE if x_continuous else ONEWAY
    return LOGISTIC if x_continuous else CONTINGENCY


def fit_y_by_x(frame: pd.DataFrame, y: str, x: str, *, y_continuous: bool, x_continuous: bool) -> FitYByXResult:
    kind = analysis_for(y_continuous, x_continuous)
    data = frame[[y, x]].copy()
    if y_continuous:
        data[y] = to_numbers(column_of(data, y))
    if x_continuous:
        data[x] = to_numbers(column_of(data, x))
    complete = data.dropna()
    left_out = len(data) - len(complete)
    if len(complete) < 3:
        raise ValueError(f"'{y}' by '{x}': {len(complete)} complete rows are too few.")
    builder = {BIVARIATE: _bivariate, ONEWAY: _oneway, CONTINGENCY: _contingency, LOGISTIC: _logistic}[kind]
    result = builder(complete[y], complete[x], y, x)
    if left_out:
        result.notes.append(f"{left_out} row(s) with a missing value left out.")
    return result


# ----------------------------------------------------------------------
# Continuous by continuous
# ----------------------------------------------------------------------

def _bivariate(yv: pd.Series, xv: pd.Series, y: str, x: str) -> FitYByXResult:
    import statsmodels.api as sm

    xs, ys = xv.to_numpy(float), yv.to_numpy(float)
    fit = sm.OLS(ys, sm.add_constant(xs)).fit()
    interval = fit.conf_int(0.05)
    estimates = pd.DataFrame({
        "Term": ["Intercept", x],
        "Estimate": fit.params,
        "Std Error": fit.bse,
        "t Ratio": fit.tvalues,
        "pvalue": fit.pvalues,
        "Lower 95%": interval[:, 0],
        "Upper 95%": interval[:, 1],
    })
    summary = pd.DataFrame({
        "Measure": ["RSquare", "RSquare Adj", "Root Mean Square Error", "Mean of Response", "Observations"],
        "Value": [fit.rsquared, fit.rsquared_adj, float(np.sqrt(fit.mse_resid)), float(ys.mean()), float(ys.size)],
    })
    correlation = pd.DataFrame(st.correlation_tests(xs, ys))
    grid = np.linspace(xs.min(), xs.max(), 100)
    band = fit.get_prediction(sm.add_constant(grid, has_constant="add")).summary_frame(alpha=0.05)
    curve = pd.DataFrame({x: grid, "Fit": band["mean"].to_numpy(), "Lower 95% mean": band["mean_ci_lower"].to_numpy(),
                          "Upper 95% mean": band["mean_ci_upper"].to_numpy()})
    kept = FitYByXModel(y, x, BIVARIATE, {
        "intercept": float(fit.params[0]), "slope": float(fit.params[1]), "mse": float(fit.mse_resid),
        "df": float(fit.df_resid), "n": float(xs.size), "xbar": float(xs.mean()),
        "sxx": float(np.sum((xs - xs.mean()) ** 2)), "r2": float(fit.rsquared)})
    return FitYByXResult(y, x, BIVARIATE, {"Summary of fit": summary, "Linear fit": estimates,
                                           "Correlation": correlation}, curve, model=kept)


# ----------------------------------------------------------------------
# Continuous by groups
# ----------------------------------------------------------------------

def _groups(yv: pd.Series, xv: pd.Series) -> dict[str, np.ndarray]:
    keys = xv.astype(str)
    return {str(level): yv[keys == level].to_numpy(float) for level in sorted(keys.unique(), key=_natural)}


def _natural(text: str) -> tuple:
    try:
        return (0, float(text), "")
    except ValueError:
        return (1, 0.0, text)


def games_howell(groups: Mapping[str, np.ndarray]) -> pd.DataFrame:
    """Every pair of groups without assuming equal variances (Games & Howell 1976).

    Welch's standard error and degrees of freedom per pair, the p-value and
    the 95% interval from the studentized range for all k groups.
    """
    samples = {name: values for name, values in groups.items() if values.size >= 2}
    k = len(samples)
    rows = []
    for (a, va), (b, vb) in itertools.combinations(samples.items(), 2):
        ma, mb = va.mean(), vb.mean()
        sa, sb = va.var(ddof=1) / va.size, vb.var(ddof=1) / vb.size
        se = np.sqrt(sa + sb)
        df = (sa + sb) ** 2 / (sa ** 2 / (va.size - 1) + sb ** 2 / (vb.size - 1))
        q = abs(ma - mb) / se * np.sqrt(2)
        critical = stats.studentized_range.ppf(0.95, k, df) / np.sqrt(2) * se
        rows.append({"pair": f"{a} - {b}", "difference": ma - mb, "pvalue": float(stats.studentized_range.sf(q, k, df)),
                     "ci_low": ma - mb - critical, "ci_high": ma - mb + critical})
    return pd.DataFrame(rows)


def holm(pvalues: np.ndarray) -> np.ndarray:
    """Holm's step-down adjustment."""
    pvalues = np.asarray(pvalues, dtype=float)
    order = np.argsort(pvalues)
    m = pvalues.size
    adjusted = np.empty(m)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[index]))
        adjusted[index] = running
    return adjusted


def dunn(groups: Mapping[str, np.ndarray]) -> pd.DataFrame:
    """Dunn's test on the ranks (Kruskal-Wallis' pairs), with ties corrected and Holm's adjustment."""
    samples = {name: values for name, values in groups.items() if values.size}
    everything = np.concatenate(list(samples.values()))
    ranks = stats.rankdata(everything)
    n = everything.size
    _values, ties = np.unique(everything, return_counts=True)
    tie_term = float(np.sum(ties ** 3 - ties)) / (12.0 * (n - 1))
    mean_ranks, sizes, start = {}, {}, 0
    for name, values in samples.items():
        mean_ranks[name] = ranks[start:start + values.size].mean()
        sizes[name] = values.size
        start += values.size
    rows = []
    for a, b in itertools.combinations(samples, 2):
        se = np.sqrt((n * (n + 1) / 12.0 - tie_term) * (1.0 / sizes[a] + 1.0 / sizes[b]))
        z = (mean_ranks[a] - mean_ranks[b]) / se
        rows.append({"pair": f"{a} - {b}", "mean rank difference": mean_ranks[a] - mean_ranks[b], "z": z,
                     "pvalue (unadjusted)": float(2 * stats.norm.sf(abs(z)))})
    table = pd.DataFrame(rows)
    if len(table):
        table["pvalue"] = holm(table["pvalue (unadjusted)"].to_numpy())
    return table


def _oneway(yv: pd.Series, xv: pd.Series, y: str, x: str) -> FitYByXResult:
    groups = _groups(yv, xv)
    rows = []
    for level, values in groups.items():
        n = values.size
        sd = values.std(ddof=1) if n > 1 else np.nan
        se = sd / np.sqrt(n) if n > 1 else np.nan
        half = stats.t.ppf(0.975, n - 1) * se if n > 1 else np.nan
        rows.append({"Level": level, "N": n, "Mean": values.mean(), "Std Dev": sd, "Std Err": se,
                     "Lower 95%": values.mean() - half, "Upper 95%": values.mean() + half})
    tables = {"Means": pd.DataFrame(rows), "Tests": pd.DataFrame(st.group_tests(groups))}
    notes = []
    if len(groups) > 2:
        tables["Tukey HSD (equal variances)"] = pd.DataFrame(st.tukey_hsd(groups))
        tables["Games-Howell (unequal variances)"] = games_howell(groups)
        tables["Dunn, Holm-adjusted (ranks)"] = dunn(groups)
    if len(groups) > 30:
        notes.append(f"'{x}' has {len(groups)} levels: is it really a grouping column?")
    sizes = {level: float(values.size) for level, values in groups.items()}
    within = sum(float(np.sum((values - values.mean()) ** 2)) for values in groups.values())
    dof = float(sum(values.size for values in groups.values()) - len(groups))
    kept = FitYByXModel(y, x, ONEWAY, {
        "levels": list(groups), "means": {level: float(values.mean()) for level, values in groups.items()},
        "sizes": sizes, "mse": within / dof if dof > 0 else float("nan"), "df": dof}, levels=list(groups))
    return FitYByXResult(y, x, ONEWAY, tables, notes=notes, model=kept)


# ----------------------------------------------------------------------
# Groups by groups
# ----------------------------------------------------------------------

def _contingency(yv: pd.Series, xv: pd.Series, y: str, x: str) -> FitYByXResult:
    counts = st.contingency_table(xv.astype(str), yv.astype(str))
    shares = counts.div(counts.sum(axis=1), axis=0) * 100.0
    counts_out = counts.reset_index().rename(columns={counts.index.name or "index": x})
    shares_out = shares.reset_index().rename(columns={shares.index.name or "index": x})
    tests = pd.DataFrame(st.contingency_tests(counts))
    kept = FitYByXModel(y, x, CONTINGENCY, {
        "levels": [str(level) for level in counts.index],
        "classes": [str(level) for level in counts.columns],
        "shares": (counts.div(counts.sum(axis=1), axis=0)).to_numpy(float).tolist()},
        levels=[str(level) for level in counts.columns])
    return FitYByXResult(y, x, CONTINGENCY, {"Counts": counts_out, "Row shares (%)": shares_out, "Tests": tests},
                         model=kept)


# ----------------------------------------------------------------------
# Groups by continuous
# ----------------------------------------------------------------------

def _logistic(yv: pd.Series, xv: pd.Series, y: str, x: str) -> FitYByXResult:
    import statsmodels.api as sm

    from app.analysis.explain import roc

    labels = yv.astype(str)
    levels = sorted(labels.unique(), key=_natural)
    if len(levels) < 2:
        raise ValueError(f"'{y}' has a single level: there is nothing to tell apart.")
    xs = xv.to_numpy(float)
    design = sm.add_constant(xs)
    codes = pd.Categorical(labels, categories=levels).codes
    notes = []
    if len(levels) == 2:
        # The probability of the first level, as JMP models it.
        model = sm.Logit((codes == 0).astype(float), design).fit(disp=False)
        names = ["Intercept", x]
        estimates = pd.DataFrame({"Term": names, "Estimate": model.params, "Std Error": model.bse,
                                  "z": model.tvalues, "pvalue": model.pvalues})
        estimates["Odds ratio"] = np.exp(estimates["Estimate"])
        notes.append(f"The estimates are for the log odds of '{levels[0]}' against '{levels[1]}'.")

        def probabilities(values: np.ndarray) -> np.ndarray:
            first = model.predict(sm.add_constant(values, has_constant="add"))
            return np.column_stack([first, 1 - first])
    else:
        model = sm.MNLogit(codes, design).fit(disp=False)
        rows = []
        for column, level in enumerate(levels[1:]):
            for term_index, term in enumerate(["Intercept", x]):
                rows.append({"Term": f"{term} [{level} vs {levels[0]}]",
                             "Estimate": model.params[term_index, column], "Std Error": model.bse[term_index, column],
                             "z": model.tvalues[term_index, column], "pvalue": model.pvalues[term_index, column]})
        estimates = pd.DataFrame(rows)
        estimates["Odds ratio"] = np.exp(estimates["Estimate"])

        def probabilities(values: np.ndarray) -> np.ndarray:
            return np.asarray(model.predict(sm.add_constant(values, has_constant="add")))

    _curves, areas = roc(labels.to_numpy(), probabilities(xs), levels)
    whole = pd.DataFrame({
        "Measure": ["-LogLikelihood (full)", "-LogLikelihood (reduced)", "ChiSquare (LR)", "DF", "Prob>ChiSq",
                    "RSquare (U)", "Observations", *[f"AUC ({level})" for level in areas]],
        "Value": [-model.llf, -model.llnull, model.llr, float(model.df_model), model.llr_pvalue, model.prsquared,
                  float(xs.size), *areas.values()],
    })
    grid = np.linspace(xs.min(), xs.max(), 100)
    curve = pd.DataFrame(probabilities(grid), columns=[f"P({level})" for level in levels])
    curve.insert(0, x, grid)
    coefficients = ([np.asarray(model.params, dtype=float).tolist()] if len(levels) == 2
                    else np.asarray(model.params, dtype=float).T.tolist())
    kept = FitYByXModel(y, x, LOGISTIC, {"coefficients": coefficients, "classes": levels}, levels=list(levels))
    return FitYByXResult(y, x, LOGISTIC, {"Whole model test": whole, "Parameter estimates": estimates}, curve, notes,
                         model=kept)


@SavedModel.register
class FitYByXModel(SavedModel):
    """The one-predictor model of Fit Y by X, as plain numbers (JSON): a line (continuous by continuous), the group
    means (continuous by groups), the group shares (groups by groups) or a logistic curve (groups by continuous)."""

    KIND = "fit_y_by_x"
    FORM = PORTABLE

    def __init__(self, response: str, predictor: str, case: str, params: dict[str, Any], *,
                 levels: list[str] | None = None, summary: dict[str, float] | None = None,
                 source_table: str = "") -> None:
        numeric_x = case in (BIVARIATE, LOGISTIC)
        super().__init__(response, [Feature(predictor, CONTINUOUS if numeric_x else NOMINAL,
                                            [] if numeric_x else list(params.get("levels", [])))],
                         response_kind=CONTINUOUS if case in (BIVARIATE, ONEWAY) else NOMINAL,
                         levels=levels, summary=summary, source_table=source_table)
        self.case = case
        self.params = params

    def _interval(self, centre: np.ndarray, variance: np.ndarray) -> pd.DataFrame:
        half = stats.t.ppf(0.975, self.params["df"]) * np.sqrt(variance) if self.params["df"] > 0 else np.nan
        return pd.DataFrame({"Prediction": centre, "Lower (95%)": centre - half, "Upper (95%)": centre + half})

    def predict_matrix(self, frame: pd.DataFrame) -> pd.DataFrame:
        name = self.features[0].name
        values = frame[name]
        case, p = self.case, self.params
        if case == BIVARIATE:
            x = values.to_numpy(float)
            variance = p["mse"] * (1 + 1 / p["n"] + (x - p["xbar"]) ** 2 / p["sxx"])
            table = self._interval(p["intercept"] + p["slope"] * x, variance)
        elif case == ONEWAY:
            keys = values.astype(str)
            variance = np.array([p["mse"] * (1 + 1 / p["sizes"][k]) for k in keys])
            table = self._interval(np.array([p["means"][k] for k in keys]), variance)
        elif case == CONTINGENCY:
            rows = np.array([p["shares"][p["levels"].index(str(k))] for k in values])
            table = pd.DataFrame(rows, columns=[f"Prob({c})" for c in p["classes"]])
            table.insert(0, "Prediction", np.asarray(p["classes"], dtype=object)[np.argmax(rows, axis=1)])
        else:
            x = values.to_numpy(float)
            design = np.column_stack([np.ones_like(x), x])
            coefficients = np.asarray(p["coefficients"], dtype=float)
            if coefficients.shape[0] == 1:  # two groups: the probability of the first, as the report models it
                first = 1.0 / (1.0 + np.exp(-(design @ coefficients[0])))
                probabilities = np.column_stack([first, 1.0 - first])
            else:  # several: the first group is the reference
                logits = np.column_stack([np.zeros(len(x)), *[design @ row for row in coefficients]])
                logits -= logits.max(axis=1, keepdims=True)
                probabilities = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
            table = pd.DataFrame(probabilities, columns=[f"Prob({c})" for c in p["classes"]])
            table.insert(0, "Prediction", np.asarray(p["classes"], dtype=object)[np.argmax(probabilities, axis=1)])
        table.index = frame.index
        return table

    def state(self) -> dict[str, Any]:
        return {"case": self.case, "params": self.params}

    @classmethod
    def from_state(cls, header: dict[str, Any], state: dict[str, Any]) -> FitYByXModel:
        return cls(str(header["response"]), header["features"][0]["name"], str(state["case"]), dict(state["params"]),
                   levels=header.get("levels"), summary=header.get("summary"),
                   source_table=str(header.get("source_table", "")))
