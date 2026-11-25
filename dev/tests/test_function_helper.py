"""The workpad's function helper: suggestions that suit the formula, commands that run, the dialog that writes them."""
from __future__ import annotations

import pytest

from app.workpad import function_helper as helper


def _keys(text: str, **kwargs) -> set[str]:
    formula = helper.parse(text)
    return {s.key for s in helper.suggestions(formula, helper.default_variable(formula), **kwargs)}


def test_suggestions_follow_the_kind_of_function() -> None:
    assert {"factor", "degree", "roots_poly"} <= _keys("x^3 - 2x + 1")
    assert "roots_numeric" not in _keys("x^3 - 2x + 1")
    assert "period" in _keys("sin(x)*exp(-x/5)")
    assert "asymptotes" in _keys("1/(x-1)")
    assert "partials" in _keys("a*x^2 + b")
    assert "factor" not in _keys("a*x^2 + b")  # symbolic coefficients: no numerical roots


def test_unsafe_or_empty_text_is_refused() -> None:
    for text in ("", "__import__('os')", "lambda x: x", "x +"):
        with pytest.raises(helper.BadFormula):
            helper.parse(text)


def test_the_commands_run_in_the_workpad(qapp, tmp_path) -> None:
    from app.data.sqlite_repo import SqliteRepo
    from app.workpad.engine import Workpad

    repo = SqliteRepo(db_path=tmp_path / "f.dhub")
    formula = helper.parse("x^3 - 2x + 1")
    found = {s.key: s for s in helper.suggestions(formula, "x", -3, 3, 1)}
    pad = Workpad(lambda: repo)
    pad.run(helper.script(formula, "x", [found[k] for k in ("derivative", "critical", "plot", "plot_d")], -3, 3, 1))
    assert len(repo.list_user_tables()) == 2  # the two charts' tables
    repo.close()


def test_the_dialog_writes_what_was_ticked(qapp) -> None:
    from PySide6.QtCore import Qt

    from app.widgets.function_helper_dialog import FunctionHelperDialog

    dialog = FunctionHelperDialog(None, text="x^2")
    assert not dialog.write_button.isEnabled()
    assert dialog.variable_combo.currentText() == "x"
    for key, item in dialog._items():
        if key == "derivative":
            item.setCheckState(Qt.CheckState.Checked)
    assert "diff(f, x)" in dialog.script()
    written: list[str] = []
    dialog.commands.connect(written.append)
    dialog.write_button.click()
    assert written and written[0].startswith("x = Symbol('x')")
    dialog.formula_edit.setText("")
    assert dialog.script() == "" and dialog.message.text()
