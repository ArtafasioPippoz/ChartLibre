"""An analysis as a function call: its dialog driven without a window, the report and what it wrote handed back.

    result = run_analysis(repo, "Fit Y by X", "table", {"x": ["a"], "y": ["b"]}, {"degree": 2})
    result.report_html, result.report_text, result.tables, result.figures, result.operation_id

This is the engine the assistant's run_analysis tool used, taken out of it: the analysis dialogs stay the one
implementation, and everything that wants an analysis - the assistant, the SymPy workpad (workpad names Analysis,
Chart), a saved function, a script - goes through here. Nothing is shown: the dialog is built, filled, run as its OK
runs it (one Undo step, the history row, the tables, the figure) and closed.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

#: How long an analysis may run before the call gives up waiting.
ANALYSIS_TIMEOUT_S = 600


class AnalysisError(ValueError):
    """An analysis that could not be run, in the words of its dialog (the problems it listed) or of the lookup."""


@dataclass
class AnalysisResult:
    """What one run gave back."""

    name: str
    #: The table it analysed.
    source: str
    roles: dict[str, list[str]]
    parameters: dict[str, Any]
    model: str
    report_html: str
    report_text: str
    #: The tables it wrote, by name; the figures it drew, by id.
    tables: list[str] = field(default_factory=list)
    figures: list[int] = field(default_factory=list)
    #: Its row of the project's history (__operations__), None when the run recorded none.
    operation_id: int | None = None
    seconds: float = 0.0
    #: The project it ran on (so the object can read its tables and run again).
    #: Private, so a workpad's filter keeps it out of reach of the user's own commands.
    _repo: Any = field(default=None, repr=False, compare=False)
    draw_on: str = "new_figure"

    def __repr__(self) -> str:
        return (f"{self.name} on {self.source}. Tables written: {', '.join(self.tables) or 'none'}. "
                f"Figures: {', '.join(map(str, self.figures)) or 'none'}.\n\n{self.report_text}")

    @property
    def report(self) -> str:
        """The report, as HTML."""
        return self.report_html

    def table(self, name: str | None = None) -> Any:
        """One of the tables it wrote as a DataFrame: *name*, or the first."""
        if not self.tables:
            raise AnalysisError(f"{self.name} wrote no table.")
        chosen = name or self.tables[0]
        if chosen not in self.tables:
            raise AnalysisError(f"{self.name} wrote: {', '.join(self.tables)}; not '{chosen}'.")
        return self._repo.query_df(f"SELECT * FROM {_quote(chosen)}")

    def code(self) -> str:
        """The call that makes this analysis again."""
        return call_text("Analysis", self.name, self.source, self.roles, self.parameters,
                         model=self.model, draw_on=self.draw_on)

    def rerun(self, table: str | None = None, **parameters: Any) -> AnalysisResult:
        """The same analysis again - on *table* when given (its columns must have the same names), with
        *parameters* changed where given."""
        return run_analysis(self._repo, self.name, table or self.source, self.roles, {**self.parameters, **parameters},
                            model=self.model, draw_on=self.draw_on)


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def call_text(function: str, name: str, table: str, roles: Mapping[str, Any], parameters: Mapping[str, Any], *,
              model: str = "", draw_on: str = "new_figure") -> str:
    """A call as Python source: Analysis("Fit Y by X", "t", {"x": ["a"]}, degree=2)."""
    arguments = [repr(name), repr(table), repr({key: list(value) for key, value in dict(roles).items()})]
    arguments += [f"{key}={value!r}" for key, value in dict(parameters).items()]
    if model:
        arguments.append(f"model={model!r}")
    if draw_on != "new_figure":
        arguments.append(f"draw_on={draw_on!r}")
    return f"{function}({', '.join(arguments)})"


def closest(name: str, known: Iterable[str]) -> str:
    """The one of *known* meant by *name* - "box_plot" for Box Plot, "body mass" for body_mass_g; else *name*."""
    def words(text: str) -> list[str]:
        return [word for word in re.split(r"[^a-z0-9]+", str(text).lower()) if word]

    wanted = words(name)
    choices = list(known)
    for test in (lambda have: have == wanted,
                 lambda have: [w for w in have if w not in ("plot", "chart")] == [w for w in wanted
                                                                                  if w not in ("plot", "chart")],
                 lambda have: bool(wanted) and all(word in have for word in wanted)):
        found = [choice for choice in choices if test(words(choice))]
        if len(found) == 1:
            return found[0]
    return name


def plain_text(html: str) -> str:
    """A report's HTML as text."""
    from PySide6.QtGui import QTextDocument

    document = QTextDocument()
    document.setHtml(html)
    return document.toPlainText().strip()


def catalogue() -> dict[str, Any]:
    """The table analyses by name: their discovery entries."""
    from app.scanners.data_operation_scanner import data_operations, reads_roles

    return {str(entry["value"]): entry for entry in data_operations if reads_roles(entry)}


def analysis_names() -> list[str]:
    return sorted(catalogue())


def find_analysis(name: str) -> tuple[str, Any]:
    """(the analysis' own name, its entry) for a name written loosely, or an AnalysisError that lists the real ones."""
    known = catalogue()
    found = closest(name, known)
    if found not in known:
        raise AnalysisError(f"No analysis named '{name}'. They are: {', '.join(sorted(known))}.")
    return found, known[found]


def find_table(repo: Any, table: str) -> str:
    """The table named (loosely), or the error that names the real ones."""
    names = [str(name) for name in repo.list_user_tables()["Table"]]
    found = closest(table, names)
    if found not in names:
        raise AnalysisError(f"No table named '{table}'. Tables: {', '.join(names) or 'none'}.")
    return found


def find_columns(repo: Any, table: str, names: Iterable[str]) -> list[str]:
    """The columns named (loosely), or the error that names the real ones."""
    known = [str(name) for name in repo.get_columns(table) if name not in ("Hide", "Selected")]
    found = [closest(name, known) for name in names]
    wrong = [name for name in found if name not in known]
    if wrong:
        raise AnalysisError(f"Not columns of {table}: {', '.join(wrong)}. Columns: {', '.join(known)}.")
    return found


def _list_of_columns(value: Any) -> list[str]:
    """Columns as a list, also when written as text: "['a', 'b']" or "a, b"."""
    if isinstance(value, str):
        return [part.strip(" '\"") for part in value.strip("[] ").split(",") if part.strip(" '\"")]
    return [str(item) for item in value]


def run_analysis(repo: Any, analysis: str, table: str, roles: Mapping[str, Any] | None = None,
                 parameters: Mapping[str, Any] | None = None, *, model: str = "", draw_on: str = "new_figure",
                 current_figure: Callable[[], int | None] = lambda: None,
                 keep_waiting: Callable[[], bool] = lambda: True,
                 timeout: float = ANALYSIS_TIMEOUT_S) -> AnalysisResult:
    """Run *analysis* on *table* as its dialog's OK would, and return what it gave.

    *roles* maps each role of the analysis (see describe_analysis) to its columns; *parameters* are its parameter
    values by name; *model* one of its models; *draw_on* where the figure goes ("new_figure", or what its
    destination list offers). *current_figure* gives the figure the window shows (for a destination on it);
    *keep_waiting* lets a caller cancel a long run. Raises AnalysisError for what is wrong with the request.
    """
    from PySide6.QtWidgets import QApplication

    from app.scanners.data_operation_scanner import import_class_from_file

    name, entry = find_analysis(analysis)
    table = find_table(repo, table)
    casting = {str(key): find_columns(repo, table, _list_of_columns(columns))
               for key, columns in dict(roles or {}).items()}
    values = dict(parameters or {})
    tables_before = set(repo.list_user_tables()["Table"].astype(str))
    operations_before = {record.id for record in repo.operations()}
    cls = import_class_from_file(entry)
    if cls is None:  # its file went, or did not load: the log says why
        raise AnalysisError(f"The analysis '{name}' could not be loaded; the log says why.")
    started = time.monotonic()
    dialog = cls(repo=repo, table=table)
    try:
        if dialog.reads_chart():  # the dialog remembers it was last used on a chart: here, a table is named
            dialog.source_table_radio.setChecked(True)
            dialog._load_tables(table)
        if dialog.table != table:
            raise AnalysisError(f"No table named '{table}'.")
        dialog.current_figure_id = current_figure()
        dialog.roles_widget.set_casting(casting)
        for form in dialog.parameter_forms():
            form.set_values(values)
        if model and getattr(dialog, "model_combo", None) is not None:
            index = dialog.model_combo.findData(model)
            if index < 0:
                raise AnalysisError(f"'{model}' is not one of {name}'s models.")
            dialog.model_combo.setCurrentIndex(index)
        combo = getattr(dialog, "destination_combo", None)
        if combo is not None and combo.findData(draw_on) >= 0:
            combo.setCurrentIndex(combo.findData(draw_on))
        problems = dialog.problems()
        if problems:
            raise AnalysisError("; ".join(problems))
        dialog.ok()
        deadline = time.monotonic() + timeout
        while dialog.job_running and time.monotonic() < deadline and keep_waiting():
            QApplication.processEvents()
            time.sleep(0.01)
        if dialog.job_running:
            dialog.stop()
            raise RuntimeError("The analysis was stopped before it finished.")
        report_html = str(getattr(dialog.results_widget(), "_html", "") or "")
        figures = list(dialog.created_figure_ids)
    finally:
        dialog.close()
    written = sorted(set(repo.list_user_tables()["Table"].astype(str)) - tables_before)
    new_operations = [record.id for record in repo.operations() if record.id not in operations_before]
    return AnalysisResult(
        name=name, source=table, roles=casting, parameters=values, model=model, report_html=report_html,
        report_text=plain_text(report_html), tables=written, figures=[int(figure) for figure in figures],
        operation_id=new_operations[-1] if new_operations else None, seconds=time.monotonic() - started,
        _repo=repo, draw_on=draw_on)


def describe_analysis(analysis: str) -> str:
    """An analysis' roles, parameters and models in words (what Analysis() accepts)."""
    from app.plugin_api.data_operations.parameter_spec import BoolParam, ChoiceParam, FloatParam, IntParam
    from app.scanners.data_operation_scanner import import_class_from_file

    name, entry = find_analysis(analysis)
    cls = import_class_from_file(entry)
    lines = [f"## {name} - {entry.get('description', '')}"]
    for role in getattr(cls, "ROLES", ()):
        most = f"at most {role.maximum}" if role.maximum else "any number"
        lines.append(f"  role {role.key} ({role.label}): {', '.join(role.kinds)}; at least {role.minimum}, "
                     f"{most} - {role.tooltip or role.label}")
    for param in getattr(cls, "PARAMS", ()):
        if isinstance(param, ChoiceParam):
            kind = "one of " + ", ".join(str(value) for _label, value in param.labelled_choices())
        elif isinstance(param, (IntParam, FloatParam)):
            kind = f"number {param.minimum}..{param.maximum}"
        elif isinstance(param, BoolParam):
            kind = "true/false"
        else:
            kind = "text"
        lines.append(f"  parameter {param.name}: {kind}, default {param.default!r}")
    models = list(getattr(cls, "MODELS", {}) or {})
    if models:
        lines.append(f"  models: {', '.join(models)}")
    return "\n".join(lines)


def _roles_of(analysis: str, columns: Any, roles: Mapping[str, Any] | None) -> dict[str, Any]:
    """The roles for a call: *roles* as given, or the list *columns* put in the analysis' only main role."""
    from app.scanners.data_operation_scanner import import_class_from_file

    if roles:
        return dict(roles)
    if columns is None:
        return {}
    if isinstance(columns, Mapping):
        return dict(columns)
    cls = import_class_from_file(find_analysis(analysis)[1])
    required = [role.key for role in getattr(cls, "ROLES", ()) if role.minimum >= 1]
    every = [role.key for role in getattr(cls, "ROLES", ())]
    if len(required) > 1 or (not required and len(every) != 1):
        raise AnalysisError(f"{analysis} has several roles ({', '.join(every)}): give the columns of each, "
                            f'as {{"{every[0]}": [...], ...}}.')
    return {(required or every)[0]: list(columns) if not isinstance(columns, str) else [columns]}


# ----------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------
@dataclass
class ChartResult:
    """A chart made in the project."""

    figure_id: int
    chart_type: str
    table: str
    y: list[str]
    x: str = ""
    title: str = ""
    roles: dict[str, str] = field(default_factory=dict)
    _repo: Any = field(default=None, repr=False, compare=False)

    def code(self) -> str:
        """The call that makes this chart again."""
        arguments = [repr(self.chart_type), repr(self.table), repr(self.y)]
        if self.x:
            arguments.append(f"x={self.x!r}")
        if self.title:
            arguments.append(f"title={self.title!r}")
        arguments += [f"{key}={value!r}" for key, value in self.roles.items() if key != "x"]
        return f"Chart({', '.join(arguments)})"

    def png(self, path: Any = None, *, dpi: int = 100) -> bytes:
        """The chart drawn as PNG bytes; also written to *path* when given."""
        import io

        from matplotlib.figure import Figure

        from app.plugin_api.charts.render_figure import render_figure_from_descriptor

        descriptor = self._repo.load_figure_descriptor(self.figure_id)
        figure = Figure()
        render_figure_from_descriptor(figure=figure, descriptor=descriptor, repo=self._repo)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=dpi)
        data = buffer.getvalue()
        if path is not None:
            from pathlib import Path

            Path(path).write_bytes(data)
        return data


def chart_class(chart_type: str) -> Any:
    """The renderer class of a chart type named loosely, or an AnalysisError that points to the list."""
    from app.scanners.axis_renderer_scanner import get_renderer, renderers
    from app.scanners.data_operation_scanner import import_class_from_file

    entry = get_renderer(closest(chart_type, [str(item["value"]) for item in renderers]))
    if entry is None:
        raise AnalysisError(f"No chart type '{chart_type}'.")
    return import_class_from_file(entry)


def make_chart(repo: Any, table: str, chart_type: str, y: Any, x: str = "", title: str = "",
               roles: Mapping[str, str] | None = None, *, undo_label: str | None = None) -> ChartResult:
    """Draw *chart_type* of the columns *y* (against *x*) in a new figure of the project."""
    cls = chart_class(chart_type)
    chart_type = str(cls.Name)
    table = find_table(repo, table)
    y = find_columns(repo, table, _list_of_columns(y))
    required = list(getattr(cls, "RequiredRoles", ()) or ())
    known = {*required, *(getattr(cls, "OptionalRoles", ()) or ())}
    shared = {str(key): str(value) for key, value in dict(roles or {}).items()}
    if x:
        shared.setdefault("x", x)
    unknown = sorted(set(shared) - known)
    if unknown:
        raise AnalysisError(f"{chart_type} has no role {', '.join(unknown)}. Its roles: {', '.join(sorted(known))}.")
    shared = dict(zip(shared, find_columns(repo, table, shared.values()), strict=True))
    # What y's columns fill: y when the chart has it, else its first required role still free (a histogram's x).
    free = [role for role in required if role not in shared]
    drawn = "y" if "y" in known else (free[0] if free else "")
    if not drawn:
        raise AnalysisError(f"{chart_type}'s roles are all given: {', '.join(sorted(known))}.")
    absent = [role for role in free if role not in (drawn, "x")]
    if absent:
        raise AnalysisError(f"{chart_type} also needs: {', '.join(absent)}.")
    use_row = "x" in required and "x" not in shared and drawn != "x"
    repo.snapshot_for_undo(list(repo.DESCRIPTOR_TABLES), label=undo_label or f"Chart of '{table}'")
    figure_id = int(repo.create_figure_descriptor(name=title or f"{table}: {', '.join(y)}"))
    axis_id = int(repo.create_axis_descriptor(figure_id=figure_id, axis_index=0, chart_type=chart_type,
                                              title=title, x_label=shared.get("x", ""),
                                              y_label=y[0] if len(y) == 1 else "", options={"grid": True}))
    for index, column in enumerate(y):
        chosen = {**shared, drawn: column}
        select = [f"{_quote(name)} AS {_quote(role)}" for role, name in chosen.items()]
        if use_row:
            select.insert(0, 'rowid AS "x"')
        series_roles = {role: role for role in chosen} | ({"x": "x"} if use_row else {})
        repo.create_series_descriptor(axis_id=axis_id, series_index=index, name=column,
                                      sql_query=f"SELECT {', '.join(select)} FROM {_quote(table)}",
                                      roles=series_roles, style={})
    return ChartResult(figure_id=figure_id, chart_type=chart_type, table=table, y=y, x=x, title=title,
                       roles={key: value for key, value in shared.items() if key != "x"}, _repo=repo)


# ----------------------------------------------------------------------
# The two callables a script or the workpad uses
# ----------------------------------------------------------------------
_project: Any = None


def use_project(repo: Any) -> None:
    """The project Analysis() and Chart() work on when no repo is given (a script sets it once)."""
    global _project
    _project = repo


def current_project() -> Any:
    if _project is None:
        raise AnalysisError("No project: open one, or call use_project(repo) first.")
    return _project


def make_callables(repo_getter: Callable[[], Any], *, current_figure: Callable[[], int | None] = lambda: None,
                   keep_waiting: Callable[[], bool] = lambda: True,
                   on_change: Callable[[list[int]], None] = lambda figures: None) -> tuple[Callable, Callable]:
    """(Analysis, Chart) bound to a project - the workpad's names, or a script's. *on_change* hears the figures made."""

    def Analysis(name: str, table: str, columns: Any = None, *, roles: Mapping[str, Any] | None = None,  # noqa: N802
                 model: str = "", draw_on: str = "new_figure", **parameters: Any) -> AnalysisResult:
        """Run an analysis: Analysis("Fit Y by X", "table", ["column"], degree=2); see analysis_names()."""
        result = run_analysis(repo_getter(), name, table, _roles_of(name, columns, roles), parameters, model=model,
                              draw_on=draw_on, current_figure=current_figure, keep_waiting=keep_waiting)
        on_change(result.figures)
        return result

    def Chart(chart_type: str, table: str, y: Any, x: str = "", title: str = "",  # noqa: N802
              **roles: str) -> ChartResult:
        """Draw a chart: Chart("Scatter Plot", "table", ["y"], x="x", title="..."); extra keywords are roles."""
        result = make_chart(repo_getter(), table, chart_type, y, x, title, roles)
        on_change([result.figure_id])
        return result

    return Analysis, Chart


def Analysis(name: str, table: str, columns: Any = None, **options: Any) -> AnalysisResult:  # noqa: N802
    """Run an analysis on the project use_project() set; see make_callables."""
    return make_callables(current_project)[0](name, table, columns, **options)


def Chart(chart_type: str, table: str, y: Any, x: str = "", title: str = "", **roles: str) -> ChartResult:  # noqa: N802
    """Draw a chart in the project use_project() set; see make_callables."""
    return make_callables(current_project)[1](chart_type, table, y, x, title, **roles)
