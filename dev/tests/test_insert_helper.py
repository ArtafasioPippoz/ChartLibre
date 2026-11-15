"""Tables, Columns, Functions over the workpad's command and the assistant's question; Send with a local server."""
from __future__ import annotations

import time

import pandas as pd
import pytest

from app.data.sqlite_repo import SqliteRepo


@pytest.fixture
def repo(tmp_path):
    project = SqliteRepo(db_path=tmp_path / "h.dhub")
    project.import_dataframe(pd.DataFrame({"mass": [1.0, 2.0], "species": ["a", "b"]}), table_name="Birds",
                             normalize_columns=False)
    yield project
    project.close()


def _labels(menu) -> list[str]:
    menu.aboutToShow.emit()
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def test_the_workpad_writes_quoted_names_and_lists_its_functions(qapp, repo) -> None:
    from app.widgets.workpad_panel import WorkpadPanel

    panel = WorkpadPanel(None, repo=lambda: repo)
    helper = panel._helper
    tables = helper.tables_button.menu()
    assert _labels(tables) == ["Birds"]
    tables.actions()[0].trigger()
    assert panel._command.toPlainText() == "'Birds'"
    columns = helper.columns_button.menu()
    assert _labels(columns) == ["mass", "species"]  # one table: its columns at once, none of the hidden ones
    columns.actions()[0].trigger()
    assert panel._command.toPlainText() == "'Birds''mass'"
    functions = _labels(helper.functions_button.menu())
    assert {"get(table, column)", "tables()", "mean(data)", "Model(name).predict(table)"} <= set(functions)
    panel._command.clear()
    next(a for a in helper.functions_button.menu().actions() if a.text() == "tables()").trigger()
    panel.run()
    assert "Birds" in panel._transcript.toPlainText()  # what the menu wrote runs as it is
    panel.deleteLater()


def test_the_assistant_writes_plain_names_and_requests(qapp, repo) -> None:
    from app.widgets.assistant_panel import AssistantPanel

    panel = AssistantPanel(None, repo=lambda: repo, current_figure=lambda: None)
    helper = panel._helper
    requests = helper.functions_button.menu()
    assert "Compare groups" in _labels(requests)
    next(a for a in requests.actions() if a.text() == "Describe a table").trigger()
    helper.tables_button.menu().aboutToShow.emit()
    helper.tables_button.menu().actions()[0].trigger()
    assert panel._question.toPlainText() == "Describe the table Birds"
    panel.deleteLater()


def test_send_reaches_a_provider_whose_check_is_asynchronous(qapp, repo, monkeypatch) -> None:
    """Ollama: Send asked the server again in the background and dropped the question while it waited."""
    from app.plugin_api.ai.provider import AIProvider
    from app.widgets import assistant_panel

    class Local(AIProvider):
        Name = "Local"
        KEY_NAME = ""
        SENDS_DATA = False
        CHECKS_NETWORK = True

        def unavailable(self) -> str:
            return ""

    monkeypatch.setattr(assistant_panel, "_load_provider", lambda name: Local())
    panel = assistant_panel.AssistantPanel(None, repo=lambda: repo, current_figure=lambda: None)
    deadline = time.monotonic() + 5
    while not panel._ready and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    asked: list[str] = []
    monkeypatch.setattr(panel, "_conversation", lambda: type("C", (), {"ask": lambda self, text: asked.append(text)})())
    panel._question.setPlainText("How many birds?")
    panel._send()
    assert asked == ["How many birds?"] and panel._ready
    panel.deleteLater()


def test_columns_lists_only_the_selected_table(qapp, repo) -> None:
    import pandas as pd

    from app.widgets.insert_helper import InsertHelper

    repo.import_dataframe(pd.DataFrame({"length": [1.0], "wing": [2.0]}), table_name="Fish", normalize_columns=False)
    selected = {"table": "Fish"}
    helper = InsertHelper(None, repo=lambda: repo, functions=lambda: [], current_table=lambda: selected["table"])
    assert _labels(helper.columns_button.menu()) == ["length", "wing"]  # no sub-menu per table
    selected["table"] = None
    menu = helper.columns_button.menu()
    menu.aboutToShow.emit()
    assert [a.text() for a in menu.actions()] == ["Birds", "Fish"]  # none selected: a sub-menu per table
    helper.deleteLater()
