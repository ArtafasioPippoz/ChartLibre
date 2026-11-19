"""macOS: buttons, check boxes and option buttons drawn by Cocoa; the axis' letters above their boxes."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from app.styles.style.themes import _without_native_mac_rules
from app.widgets.chart_properties.axis_properties import AxisPropertiesWidget


def test_the_sheets_rules_for_native_controls_go_and_the_others_stay() -> None:
    qss = """
    /* a comment */
    QPushButton { background: red; border-radius: 6px; icon-size: 0px 0px; }
    QPushButton:hover, QDialogButtonBox QPushButton:pressed { background: blue; }
    QCheckBox::indicator:checked { image: url(tick.png); }
    QRadioButton::indicator { width: 14px; }
    QPushButton[primary="true"] { background: palette(highlight); }
    QCheckBox { spacing: 8px; }
    """
    out = _without_native_mac_rules(qss)
    assert "red" not in out and "blue" not in out and "tick.png" not in out and "width" not in out
    assert "icon-size: 0px 0px" in out  # words only on a button: it does not take the drawing from Cocoa
    assert 'QPushButton[primary="true"] { background: palette(highlight); }' in out
    assert "spacing: 8px" in out


def test_each_letter_is_a_label_above_its_own_box(qapp) -> None:
    widget = AxisPropertiesWidget()
    for check in [*widget._spine_checks().values(), *widget._share_checks.values()]:
        assert check.text() == ""
        letters = [label.text() for label in check.parentWidget().findChildren(QLabel)]
        assert letters in (["T", "R", "B", "L"], ["X", "Y", "Z"])
