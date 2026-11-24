"""Form labels as the style in use writes them: a colon on macOS, none on Windows 11 and Linux."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from app.styles.style import field_label, normalize_form_labels
from app.styles.style import widgets as style_widgets


@pytest.mark.parametrize("platform, expected", [("darwin", "Name:"), ("win32", "Name"), ("linux", "Name")])
def test_a_word_and_its_colon_are_one_string(monkeypatch, platform: str, expected: str) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(style_widgets, "_label_colon", None)  # no style applied: the platform decides
    assert field_label("Name") == expected and field_label("Name:") == expected and field_label("Name :") == expected


def test_questions_ellipses_and_empty_text_are_left_alone() -> None:
    assert field_label("") == "" and field_label("Sure?") == "Sure?" and field_label("More…") == "More…"


def test_a_form_is_normalised_whatever_its_labels_were(qapp, monkeypatch) -> None:
    monkeypatch.setattr(style_widgets, "_label_colon", True)
    page = QWidget()
    form = QFormLayout(page)
    form.addRow("Name", QLineEdit())
    form.addRow("Size:", QLineEdit())
    normalize_form_labels(page)
    labels = [form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget() for row in range(2)]
    assert [label.text() for label in labels if isinstance(label, QLabel)] == ["Name:", "Size:"]


def test_the_style_in_use_decides_not_the_machine(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(style_widgets, "_label_colon", False)  # the Windows 11 look on a Mac
    assert field_label("Name:") == "Name"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(style_widgets, "_label_colon", True)  # the macOS look on Windows
    assert field_label("Name") == "Name:"
