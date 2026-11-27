"""The workpad's equation helper: the kind of equations is recognised, the commands run, the dialog serves both helpers."""
from __future__ import annotations

import pytest

from app.utils import equation_helper as helper
from app.utils.function_helper import BadFormula


@pytest.mark.parametrize(("text", "kind"), [
    ("x^3 - 2x = 1", "algebraic"), ("x^2 - 4", "algebraic"), ("x + y = 3; x - y = 1", "system"),
    ("x^2 - 4 > 0", "inequality"), ("y' + 2y = sin(x)", "ode"), ("y'' + y = 0; y(0) = 1; y'(0) = 0", "ode"),
])
def test_the_kind_is_recognised(text: str, kind: str) -> None:
    assert helper.parse(text).kind == kind


def test_an_ode_keeps_its_initial_conditions_and_independent_variable() -> None:
    eq = helper.parse("y'' + y = 0; y(0) = 1; y'(0) = 0")
    assert eq.function == "y" and len(eq.conditions) == 2 and helper.default_variable(eq) == "x"
    assert [s.key for s in helper.suggestions(eq, "x")][:3] == ["classify", "general", "particular"]


def test_linear_systems_get_their_matrix_form() -> None:
    keys = {s.key for s in helper.suggestions(helper.parse("x + y = 3; x - y = 1"), "x")}
    assert {"matrix", "linsolve"} <= keys
    assert "matrix" not in {s.key for s in helper.suggestions(helper.parse("x*y = 3; x - y = 1"), "x")}


def test_bad_text_is_refused() -> None:
    for text in ("", "__import__('os')", "y(0) = 1", "x ="):
        with pytest.raises(BadFormula):
            helper.parse(text)


def test_the_commands_run(qapp, tmp_path) -> None:
    from app.data.sqlite_repo import SqliteRepo
    from app.utils.workpad import Workpad

    repo = SqliteRepo(db_path=tmp_path / "e.dhub")
    for text in ("x^3 - 2x = 1", "x + y = 3; x - y = 1", "y' + 2y = sin(x); y(0) = 1"):
        eq = helper.parse(text)
        found = helper.suggestions(eq, helper.default_variable(eq), -3, 3, 1)
        Workpad(lambda: repo).run(helper.script(eq, helper.default_variable(eq), found, -3, 3, 1))
    repo.close()


def test_the_dialog_serves_equations(qapp) -> None:
    from app.widgets.function_helper_dialog import FunctionHelperDialog

    dialog = FunctionHelperDialog(None, text="x^2 = 4", equations=True)
    assert "solve" in {key for key, _item in dialog._items()}
    assert dialog.windowTitle() == "Equation helper"
