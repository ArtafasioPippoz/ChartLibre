"""The assistant's settings: what it may do, what it may send, which provider and model - and the key.

The settings are in user.json; the key is not. It is kept by the system - the
macOS Keychain, the Windows Credential Manager - through the keyring package,
when it is installed; without it the key is read from the provider's
environment variable (ANTHROPIC_API_KEY for Claude) and Settings says so.

tools: What the assistant can do in the project: the tools it is given, and how the application runs them.

The tools are the application's own functions, run here, on the GUI thread,
by the application - never code the model writes. Which ones it is given
follows Settings > Assistant:

* every level - read: the tables, a table's columns and summary (with sample
  rows when allowed), a read-only query, the figures, the analyses there are;
* Analyses - run an analysis as its window's OK would (tables, figure, report,
  history, one Undo step), and draw a chart;
* Everything - change the project's data: a computed column, a statement that
  writes. Each confirmed by the user first, each an Undo step.

Every result goes back to the model as text, kept short.

assistant: One conversation with the assistant: the model's turns off the GUI thread, the tools on it.

A question goes to the provider on a worker thread - first, in Automatic
mode, to the fast model to decide which model answers it. The text streams
in as it is written (kept in a buffer the GUI thread empties every 80 ms: a
worker touches no Qt object). When the model asks for tools, they are run
here, on the GUI thread - they read and change the project, and may ask the
user - and their results go back for the next turn, until the model is done.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
import inspect
import os
import re
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from app.analysis_api import closest as _closest, describe_analysis, make_chart, run_analysis
from app.data.repo._common import is_read_only_select
from app.plugin_api.ai import ACCURATE, FAST, AIProvider, ToolResult, ToolSpec, Turn
from app.plugin_api.data_operations.column_roles import declared_kind, guess_kind
from app.utils.background import BackgroundTask, run_in_background
from app.utils.coercion import to_numbers
from app.utils.config import get_value, set_value
from app.utils.logger import applogger


# --- settings -------------------------------------------------------------------------------------
#: What the assistant may do (Settings > Assistant): read and answer in the panel; that and run analyses;
#: everything, the project's tables and database included - each change confirmed.
READ_ONLY, ANALYSES, EVERYTHING = "read_only", "analyses", "everything"
PERMISSIONS: tuple[tuple[str, str], ...] = (
    (READ_ONLY, "Read only - answers in the panel"),
    (ANALYSES, "Analyses - runs them, answers in the panel"),
    (EVERYTHING, "Everything - the database included, each change confirmed"),
)
#: Auto: the fast model for simple requests, the accurate one for the rest; or always one of them.
AUTO = "auto"
MODES: tuple[tuple[str, str], ...] = ((AUTO, "Automatic"), ("fast", "Fast"), ("accurate", "Accurate"))

PROVIDER_KEY = "assistant_provider"
PERMISSION_KEY = "assistant_permission"
CONSENT_KEY = "assistant_consent"
SAMPLE_ROWS_KEY = "assistant_sample_rows"
MODE_KEY = "assistant_mode"
#: Whether the Assistant has its row in the navigation bar (Settings > Assistant); shown by default.
NAVIGATION_KEY = "assistant_in_navigation"
#: Where the keychain files the keys.
KEYRING_SERVICE = "ChartLibre"
#: The provider's own variable, read when no key is kept: {key name: environment variable}.
ENVIRONMENT_KEYS = {"anthropic_api_key": "ANTHROPIC_API_KEY", "github_models_token": "GITHUB_TOKEN"}


def permission() -> str:
    value = str(get_value(PERMISSION_KEY, READ_ONLY) or READ_ONLY)
    return value if value in dict(PERMISSIONS) else READ_ONLY


def consented() -> bool:
    """Whether the user allowed data to be sent to the provider (Settings > Assistant)."""
    return bool(get_value(CONSENT_KEY, False))


def sample_rows() -> int:
    """How many rows of a table the assistant may send as an example; 0 for none."""
    try:
        return max(0, min(200, int(get_value(SAMPLE_ROWS_KEY, 20))))
    except (TypeError, ValueError):
        return 20


def mode() -> str:
    value = str(get_value(MODE_KEY, AUTO) or AUTO)
    return value if value in dict(MODES) else AUTO


def in_navigation() -> bool:
    return bool(get_value(NAVIGATION_KEY, True))


def set_in_navigation(shown: bool) -> None:
    set_value(NAVIGATION_KEY, bool(shown))


def provider_name() -> str:
    return str(get_value(PROVIDER_KEY, "Claude") or "Claude")


def save(*, provider: str, permission_level: str, consent: bool, rows: int, assistant_mode: str) -> None:
    set_value(PROVIDER_KEY, provider)
    set_value(PERMISSION_KEY, permission_level)
    set_value(CONSENT_KEY, bool(consent))
    set_value(SAMPLE_ROWS_KEY, int(rows))
    set_value(MODE_KEY, assistant_mode)


def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def keychain_available() -> bool:
    """Whether a key can be kept by the system (the keyring package is installed)."""
    return _keyring() is not None


def api_key(key_name: str) -> str:
    """The key kept for *key_name*, else its environment variable; "" when there is neither."""
    keyring = _keyring()
    if keyring is not None:
        try:
            stored = keyring.get_password(KEYRING_SERVICE, key_name)
        except Exception:
            applogger.exception("Could not read the assistant's key from the system keychain")
            stored = None
        if stored:
            return stored
    return os.environ.get(ENVIRONMENT_KEYS.get(key_name, ""), "")


def set_api_key(key_name: str, key: str) -> bool:
    """Keep *key* in the system keychain (or forget it when empty); False when there is no keychain."""
    keyring = _keyring()
    if keyring is None:
        return False
    try:
        if key:
            keyring.set_password(KEYRING_SERVICE, key_name, key)
        else:
            try:
                keyring.delete_password(KEYRING_SERVICE, key_name)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception:
        applogger.exception("Could not keep the assistant's key in the system keychain")
        return False
    return True


# --- tools ----------------------------------------------------------------------------------------
#: The longest text a tool gives back; the rest is said to be cut.
MAX_RESULT = 8000
#: The rows a query gives back at most.
MAX_QUERY_ROWS = 200
#: How long an analysis may run before the tool gives up waiting.
ANALYSIS_TIMEOUT_S = 600


def _cut(text: str, limit: int = MAX_RESULT) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... ({len(text) - limit} characters cut)"


def _assignments(text: str) -> dict[str, str]:
    """"a=1; b=x,y" as {"a": "1", "b": "x,y"}: what any model can write, whatever its schema can say."""
    pairs = (part.split("=", 1) for part in str(text or "").split(";") if "=" in part)
    return {key.strip(): value.strip() for key, value in pairs}


def _column_list(value: Any) -> list[str]:
    """Columns as a list, also when a model wrote the list as text: "['a', 'b']" or "a, b"."""
    if isinstance(value, str):
        return [part.strip(" '\"") for part in value.strip("[] ").split(",") if part.strip(" '\"")]
    return [str(item) for item in value]


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


class AssistantTools:
    """The tools of one conversation, on *repo*.

    *confirm(question)* asks the user before a change and says whether to go ahead; *changed(figure_ids)* tells
    the window the project changed (the figures made, to show); *current_figure* is the figure the window shows.
    """

    def __init__(self, repo: Any, *, confirm: Callable[[str], bool], changed: Callable[[list[int]], None],
                 current_figure: Callable[[], int | None], keep_waiting: Callable[[], bool] = lambda: True) -> None:
        self._repo = repo
        self._confirm = confirm
        self._changed = changed
        self._current_figure = current_figure
        self._keep_waiting = keep_waiting
        self._catalogue: dict[str, Any] | None = None
        #: The longest text given back; a provider with a small model asks for less (AIProvider.MAX_RESULT).
        self.max_result = MAX_RESULT

    # ------------------------------------------------------------------
    # What the model is told
    # ------------------------------------------------------------------

    def specs(self, level: str) -> list[ToolSpec]:
        """The tools for *level* (READ_ONLY, ANALYSES, EVERYTHING)."""
        def spec(name: str, description: str, properties: Mapping[str, Any] | None = None,
                 required: tuple[str, ...] = ()) -> ToolSpec:
            return ToolSpec(name, description, {"type": "object", "properties": dict(properties or {}),
                                                "required": list(required), "additionalProperties": False})

        text = {"type": "string"}
        tools = [
            spec("list_tables", "The project's data tables: name, rows, columns."),
            spec("describe_table", "A table's columns - SQL type, modelling type (continuous, ordinal, nominal), "
                 "missing values and a summary - and, when the user allows it, sample rows.",
                 {"table": text}, ("table",)),
            spec("query", "Run a read-only SQL SELECT on the project (SQLite) and get its rows as CSV.",
                 {"sql": text, "limit": {"type": "integer", "minimum": 1, "maximum": MAX_QUERY_ROWS}}, ("sql",)),
            spec("list_figures", "The project's figures: their axes (chart type, title) and series."),
        ]
        if level in (ANALYSES, EVERYTHING):
            tools += [
                spec("compare_groups", "Is a measure different between groups? The right test is chosen for you; "
                     "draws a figure and returns the answer in words.",
                     {"table": text, "measure": text, "groups": text}, ("table", "measure", "groups")),
                spec("find_impact", "Which columns have the most impact on a result? Draws a figure and returns "
                     "the answer in words.",
                     {"table": text, "result": text, "factors": {"type": "array", "items": text}},
                     ("table", "result", "factors")),
                spec("list_analyses", "The other analyses, one line each. describe_analysis gives one's details."),
                spec("describe_analysis", "One analysis: its column roles, parameters and models.",
                     {"analysis": text}, ("analysis",)),
                spec("run_analysis", "Run an analysis as its window's OK does: it writes its result tables, draws its "
                     "figure (unless draw_on is none), keeps its report and is one Undo step. Returns the report.",
                     {"analysis": text, "table": text,
                      "roles_text": {"type": "string", "description": "Role key = columns: response=mass; x=a,b"},
                      "parameters_text": {"type": "string", "description": "Parameter = value: alpha=0.05; n=3"},
                      "roles": {"type": "object", "additionalProperties": {"type": "array", "items": text},
                                "description": "The same as roles_text, as an object."},
                      "parameters": {"type": "object", "description": "The same as parameters_text, as an object."},
                      "model": {"type": "string", "description": "One of the analysis' models, when it has any."},
                      "draw_on": {"type": "string", "enum": ["new_figure", "new_axis", "same_axis", "none"]}},
                     ("analysis", "table")),
                spec("list_charts", "The chart types by family. With a chart_type: when to use it and its roles; "
                     "with a family: its charts and when to use each.",
                     {"family": text, "chart_type": text}),
                spec("create_chart", "Draw a table's columns as a new figure. y: the columns to draw, one series "
                     "each. x, and roles_text for other roles (group=species; color=sex), as list_charts gives them.",
                     {"table": text, "chart_type": text, "x": text, "y": {"type": "array", "items": text},
                      "roles_text": text, "title": text}, ("table", "chart_type", "y")),
            ]
        if level == EVERYTHING:
            tools += [
                spec("add_column", "Add a column to a table computed by a SQLite expression on each row (the user "
                     "confirms first; one Undo step).",
                     {"table": text, "name": text, "expression": text,
                      "type": {"type": "string", "enum": ["REAL", "INTEGER", "TEXT", ""]}},
                     ("table", "name", "expression")),
                spec("change_data", "Run one SQL statement that changes the data - UPDATE, INSERT, DELETE, CREATE "
                     "TABLE ... AS SELECT. The user confirms first; one Undo step. Say what it does in description.",
                     {"sql": text, "description": text}, ("sql", "description")),
            ]
        return tools

    # ------------------------------------------------------------------
    # Running a call
    # ------------------------------------------------------------------

    def run(self, name: str, arguments: Mapping[str, Any], level: str) -> tuple[str, bool]:
        """Run the tool *name*; (its result as text, whether it failed)."""
        if name not in {spec.name for spec in self.specs(level)}:
            return f"'{name}' is not allowed at this permission level.", True
        handler = getattr(self, f"_tool_{name}")
        parameters = inspect.signature(handler).parameters
        # Names a small model mangles (" roles") trimmed, and arguments the tool does not have left out.
        arguments = {str(key).strip(): value for key, value in dict(arguments).items()}
        arguments = {key: value for key, value in arguments.items() if key in parameters}
        if "table" in parameters:
            # Only one choice: the project's only table, when the model left it out or named a column instead.
            names = [str(table) for table in self._repo.list_user_tables()["Table"]]
            given = str(arguments.get("table") or "")
            if len(names) == 1 and _closest(given, names) not in names:
                arguments["table"] = names[0]
        try:
            inspect.signature(handler).bind(**dict(arguments))
        except TypeError as error:  # an argument missing, or not one of the tool's
            return f"Wrong arguments for {name}: {error}", True
        try:
            return _cut(str(handler(**dict(arguments))), self.max_result), False
        except Exception as error:
            return f"{type(error).__name__}: {error}", True

    # -- read ------------------------------------------------------------

    def _tool_list_tables(self) -> str:
        frame = self._repo.list_user_tables()
        lines = []
        for table in frame["Table"].astype(str):
            columns = self._repo.get_columns(table)
            lines.append(f"{table}: {self._repo.row_count(table)} rows; columns: {', '.join(columns)}")
        return "\n".join(lines) or "The project has no tables."

    def _tool_describe_table(self, table: str) -> str:
        frame = self._repo.query_df(f"SELECT * FROM {_quote(table)}")
        frame = frame[[c for c in frame.columns if not str(c).startswith("_") and c not in ("Hide", "Selected")]]
        declared = {str(row[1]): str(row[2] or "") for row in self._repo.table_info(table)}
        lines = [f"{table}: {len(frame)} rows"]
        for column in frame.columns:
            values = frame[column]
            kind = declared_kind(declared.get(str(column))) or guess_kind(values)
            line = f"- {column} ({declared.get(str(column)) or 'no type'}, {kind}): {int(values.isna().sum())} missing"
            numbers = to_numbers(values).dropna()
            if len(numbers) and len(numbers) >= 0.9 * values.notna().sum():
                line += (f"; min {numbers.min():.6g}, max {numbers.max():.6g}, mean {numbers.mean():.6g}, "
                         f"sd {numbers.std():.6g}")
            else:
                counts = values.astype(str).value_counts()
                line += f"; {len(counts)} distinct; most common: " + ", ".join(
                    f"{value} ({count})" for value, count in counts.head(5).items())
            lines.append(line)
        rows = sample_rows()
        if rows:
            lines.append(f"\nFirst {min(rows, len(frame))} rows (CSV):")
            lines.append(frame.head(rows).to_csv(index=False))
        return "\n".join(lines)

    def _tool_query(self, sql: str, limit: int = 50) -> str:
        # Read-only always, whatever the SQL guard says: the assistant's writes go through change_data.
        ok, reason = is_read_only_select(sql)
        if not ok:
            raise ValueError(f"Only a read-only SELECT: {reason}")
        frame = self._repo.query_df(sql)
        shown = frame.head(max(1, min(int(limit), MAX_QUERY_ROWS)))
        more = f"\n({len(frame) - len(shown)} more rows not shown)" if len(frame) > len(shown) else ""
        return shown.to_csv(index=False) + more

    def _tool_list_figures(self) -> str:
        lines = []
        for figure_id, figure_name in self._repo.load_figures_from_db():
            descriptor = self._repo.load_figure_descriptor(figure_id)
            lines.append(f"Figure {figure_id} '{figure_name}'")
            for axis in (descriptor.axes if descriptor else []):
                series = ", ".join(str(item.name) for item in axis.series)
                lines.append(f"  axis '{axis.title or ''}' ({axis.name}): {series}")
        return "\n".join(lines) or "The project has no figures."

    # -- analyses --------------------------------------------------------

    def catalogue(self) -> dict[str, Any]:
        """The table analyses by name: their discovery entries."""
        if self._catalogue is None:
            from app.analysis_api import catalogue

            self._catalogue = catalogue()
        return self._catalogue

    def _tool_list_analyses(self) -> str:
        return "\n".join(f"{name}: {str(entry.get('description') or '')[:90]}"
                         for name, entry in sorted(self.catalogue().items()))

    def _tool_describe_analysis(self, analysis: str) -> str:
        return describe_analysis(analysis)

    def _table(self, table: str) -> str:
        """The table a model named, or the error that names the real ones."""
        names = [str(name) for name in self._repo.list_user_tables()["Table"]]
        found = _closest(table, names)
        if found not in names:
            raise ValueError(f"No table named '{table}'. Tables: {', '.join(names) or 'none'}.")
        return found

    def _columns(self, table: str, names: Iterable[str]) -> list[str]:
        """The columns a model named, or the error that names the real ones."""
        known = [str(name) for name in self._repo.get_columns(table) if name not in ("Hide", "Selected")]
        found = [_closest(name, known) for name in names]
        wrong = [name for name in found if name not in known]
        if wrong:
            raise ValueError(f"Not columns of {table}: {', '.join(wrong)}. Columns: {', '.join(known)}.")
        return found

    def _tool_compare_groups(self, table: str, measure: str, groups: str) -> str:
        table = self._table(table)
        measure, groups = self._columns(table, [measure, groups])
        return self._tool_run_analysis("Are there differences?", table, {"response": [measure], "group": [groups]})

    def _tool_find_impact(self, table: str, result: str, factors: list[str]) -> str:
        table = self._table(table)
        result = self._columns(table, [result])[0]
        return self._tool_run_analysis("What has the most impact?", table,
                                       {"response": [result],
                                        "factor": [name for name in self._columns(table, _column_list(factors))
                                                   if name != result]})

    def _tool_run_analysis(self, analysis: str, table: str, roles: Mapping[str, list[str]] | None = None,
                           parameters: Mapping[str, Any] | None = None, model: str = "",
                           draw_on: str = "new_figure", roles_text: str = "", parameters_text: str = "") -> str:
        casting = {**{key: value.split(",") for key, value in _assignments(roles_text).items()}, **dict(roles or {})}
        values = {**_assignments(parameters_text), **dict(parameters or {})}
        result = run_analysis(self._repo, analysis, table, casting, values, model=model, draw_on=draw_on,
                              current_figure=self._current_figure, keep_waiting=self._keep_waiting,
                              timeout=ANALYSIS_TIMEOUT_S)
        self._changed(result.figures)
        return (f"{result.name} on {result.source} done. Tables written: {', '.join(result.tables) or 'none'}. "
                f"Figures: {', '.join(map(str, result.figures)) or 'none'}.\nReport:\n{result.report_text}")

    def _chart_class(self, chart_type: str) -> Any:
        from app.scanners.axis_renderer_scanner import get_renderer, renderers
        from app.scanners.data_operation_scanner import import_class_from_file

        entry = get_renderer(_closest(chart_type, [str(item["value"]) for item in renderers]))
        if entry is None:
            raise ValueError(f"No chart type '{chart_type}': list_charts gives them.")
        return import_class_from_file(entry)

    def _tool_list_charts(self, family: str = "", chart_type: str = "") -> str:
        from app.scanners.axis_renderer_scanner import renderers

        if chart_type:
            cls = self._chart_class(chart_type)
            return (f"{chart_type}: {cls.Description}\n{cls.WhenToUse}\nRequired roles: "
                    f"{', '.join(cls.RequiredRoles)}. Optional: {', '.join(cls.OptionalRoles)}.")
        families: dict[str, list[str]] = {}
        for entry in renderers:
            families.setdefault(str(entry.get("category") or ""), []).append(str(entry["value"]))
        if family:
            if family not in families:
                raise ValueError(f"No family '{family}'. They are: {', '.join(sorted(families))}.")
            return "\n".join(f"{name}: {self._chart_class(name).WhenToUse}" for name in families[family])
        return "\n".join(f"{name}: {', '.join(charts)}" for name, charts in sorted(families.items()))

    def _tool_create_chart(self, table: str, chart_type: str, y: list[str], x: str = "", title: str = "",
                           roles_text: str = "") -> str:
        result = make_chart(self._repo, table, chart_type, _column_list(y), x, title, _assignments(roles_text),
                            undo_label=f"Assistant: chart of '{self._table(table)}'")
        self._changed([result.figure_id])
        return (f"Figure {result.figure_id} drawn: {result.chart_type} of {', '.join(result.y)}"
                + (f" against {x}" if x else "") + ".")

    # -- changes ---------------------------------------------------------

    def _tool_add_column(self, table: str, name: str, expression: str, type: str = "") -> str:
        if not self._confirm(f"Add the column '{name}' to '{table}', computed as:\n\n{expression}"):
            return "The user declined the change."
        self._repo.add_column_from_expression(table, name, expression, type or None)
        self._changed([])
        return f"Column '{name}' added to '{table}'."

    #: Statements change_data refuses: the database's structure and its other files.
    _REFUSED = re.compile(r"\b(ATTACH|DETACH|PRAGMA|VACUUM|DROP|ALTER)\b", re.IGNORECASE)

    def _tool_change_data(self, sql: str, description: str) -> str:
        statement = str(sql).strip().rstrip(";").strip()
        if ";" in statement:
            raise ValueError("One statement at a time.")
        if self._REFUSED.search(statement):
            raise ValueError("Not this kind of statement: dropping or altering tables, attaching databases and "
                             "pragmas are not done by the assistant.")
        names = set(re.findall(r'\b(?:UPDATE|INTO|TABLE|FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_ ]*?)"?(?:\s|$|\()',
                               statement, flags=re.IGNORECASE))
        if any(name.startswith("__") for name in names):
            raise ValueError("The application's own tables are not changed by the assistant.")
        if not self._confirm(f"{description}\n\n{statement}"):
            return "The user declined the change."
        rows = self._repo.execute_change(statement, tables=sorted(names), label=f"Assistant: {description[:60]}")
        self._changed([])
        return f"Done: {rows if rows >= 0 else 'some'} rows changed."


# --- assistant ------------------------------------------------------------------------------------
#: Turns of tool calls one question may take before the assistant is stopped (a loop that does not end).
MAX_TOOL_TURNS = 25

SYSTEM = """You are the assistant inside ChartLibre, a desktop application for charts and statistical analysis of \
data kept in a SQLite project, in the manner of JMP.

- Answer in the language the user writes in.
- Use the tools to look at the data before you answer: never invent a table, a column or a number.
- Write your answers in Markdown: short paragraphs, tables where they help. Numbers with sensible precision.
- When you run an analysis, say what it found in plain words, then the key numbers.
- {permission}
- When a tool fails, say so and what you would try; do not pretend it worked."""

_PERMISSIONS = {
    READ_ONLY: "You may only read the project: answer with what you find. If the user asks for an "
                        "analysis or a change, explain how to do it in the application instead.",
    ANALYSES: "You may read the project, run analyses and draw charts; you may not change the data. If "
                       "the user asks for a change to the data, explain how to do it in the application.",
    EVERYTHING: "You may read the project, run analyses, draw charts and change the data. Every change "
                         "is confirmed by the user before it runs and can be undone; describe each one exactly.",
}


def system_prompt(provider: AIProvider, tools: AssistantTools, level: str) -> str:
    """The instructions; a small model also gets the project's tables, and is told to use their exact names."""
    prompt = SYSTEM.format(permission=_PERMISSIONS[level])
    if provider.SMALL_MODEL:
        prompt += ("\n- Use these exact table and column names. Call the tool for the request at once; if it fails, "
                   "correct the arguments and call it again.\n\nTables:\n" + tools.run("list_tables", {}, level)[0])
    return prompt


class Assistant(QObject):
    """The conversation; its signals are the panel's."""

    #: Text of the answer being written, as it arrives.
    text_arrived = Signal(str)
    #: A tool was run: its name and what it gave back (shortened).
    tool_used = Signal(str, str)
    #: The answer is complete: the model that wrote it, the tokens of the question so far (in, out).
    answered = Signal(str, int, int)
    #: Why the question could not be answered.
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, provider: AIProvider, tools: AssistantTools, *, api_key: str, level: str, mode: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._tools = tools
        self._api_key = api_key
        level = READ_ONLY if provider.READ_ONLY else level
        if provider.MAX_RESULT:
            tools.max_result = provider.MAX_RESULT
        self._level = level
        self._mode = mode
        self._models = dict(provider.models())
        self._session = provider.start(api_key=api_key, system=system_prompt(provider, tools, level),
                                       tools=tools.specs(level))
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(80)
        self._flush_timer.timeout.connect(self._flush)
        self._task: BackgroundTask | None = None
        self._tier = ACCURATE
        self._tool_turns = 0
        self._tokens = [0, 0]

    @property
    def busy(self) -> bool:
        return self._task is not None and self._task.running

    def ask(self, text: str) -> None:
        """A question: routed (Automatic), then answered."""
        if self.busy:
            return
        self._tool_turns, self._tokens = 0, [0, 0]
        self.busy_changed.emit(True)
        if self._provider.SMALL_MODEL and hasattr(self._session, "fill"):
            self._ask_with_form(text)
            return
        if self._mode == AUTO:
            self._start(lambda _cancel: self._provider.classify(text, api_key=self._api_key),
                        lambda tier: self._send(tier=str(tier), user_text=text))
        else:
            self._send(tier=FAST if self._mode == FAST else ACCURATE, user_text=text)

    def _ask_with_form(self, text: str) -> None:
        """A small model: it fills the form, the application runs it, the model says what came of it (form.py)."""
        from app.utils import assistant_form as form

        model = self._models[ACCURATE]
        instructions, schema = form.instructions(self._tools, self._level), form.schema(self._tools, self._level)

        def run(filled: Any) -> None:  # GUI thread: the tools read and change the project
            action, content, failed = form.execute(self._tools, dict(filled or {}), self._level)
            if action != "answer":
                self.tool_used.emit(action, content.splitlines()[0][:200] if content else "")
            self._flush_timer.start()
            prompt = form.answer_prompt(text, action, content, failed)
            self._start(lambda cancel: self._session.say(model=model, text=prompt, on_text=self._buffered,
                                                         cancel=cancel),
                        self._on_turn)

        self._start(lambda cancel: self._session.fill(model=model, instructions=instructions, schema=schema,
                                                      text=text, cancel=cancel),
                    run)

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    # ------------------------------------------------------------------

    def _start(self, work: Any, then: Any) -> None:
        self._task = run_in_background(work, then, self._failed)

    def _send(self, *, tier: str, user_text: str | None = None, tool_results: tuple[ToolResult, ...] = ()) -> None:
        self._tier = tier if tier in self._models else ACCURATE
        model = self._models[self._tier]
        self._flush_timer.start()
        self._start(lambda cancel: self._session.send(model=model, user_text=user_text, tool_results=tool_results,
                                                       on_text=self._buffered, cancel=cancel),
                    self._on_turn)

    def _buffered(self, text: str) -> None:  # worker thread: no Qt here
        with self._lock:
            self._buffer.append(text)

    def _flush(self) -> None:
        with self._lock:
            text, self._buffer = "".join(self._buffer), []
        if text:
            self.text_arrived.emit(text)

    def _on_turn(self, turn: Turn) -> None:
        self._flush()
        self._tokens[0] += turn.input_tokens
        self._tokens[1] += turn.output_tokens
        if turn.stop == "tools":
            self._tool_turns += 1
            if self._tool_turns > MAX_TOOL_TURNS:
                self._end(failure="The assistant was stopped: too many steps for one question.")
                return
            results = []
            for call in turn.tool_calls:
                content, is_error = self._tools.run(call.name, call.input, self._level)
                results.append(ToolResult(call.id, content, is_error))
                self.tool_used.emit(call.name, content.splitlines()[0][:200] if content else "")
            self._send(tier=self._tier, tool_results=tuple(results))
            return
        messages = {"stopped": "Stopped.", "refused": "The model declined to answer this request.",
                    "too_long": "The answer was too long and was cut before a step could run."}
        if turn.stop in messages:
            self._end(failure=messages[turn.stop])
            return
        self._end(model=turn.model)

    def _failed(self, error: BaseException) -> None:
        self._flush()
        self._end(failure=str(error) or type(error).__name__)

    def _end(self, *, model: str = "", failure: str = "") -> None:
        self._flush_timer.stop()
        self._task = None
        if failure:
            self.failed.emit(failure)
        else:
            self.answered.emit(model, *self._tokens)
        self.busy_changed.emit(False)
