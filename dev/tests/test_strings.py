"""Tests of strings, one section per former file:

* po_escapes: A .po string is read back as it was written: a typed backslash-n is not a line break.
* localization: The translation function itself.
* label_strings: One string for a word and its colon: a label is written _("Name") and field_label() puts the colon on
* section_titles_case: Frame titles keep the case they are written in ("Select Columns", not "SELECT COLUMNS"), as macOS's own.
* field_labels: Form labels as the style in use writes them: a colon on macOS, none on Windows 11 and Linux.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget
import pytest

from app.styles import widgets as style_widgets
from app.styles.style import field_label, normalize_form_labels
from app.utils import i18n


# --- po_escapes: A .po string is read back as it was written: a typed backslash-n is not a line break.
def test_escapes_round_trip() -> None:
    for text in ("type \\n where a line ends", "two\nlines", 'a "quote"', "a tab\there", "back\\slash"):
        assert i18n._po_string(i18n._po_escape(text)) == text


# --- localization: The translation function itself.
def test_an_empty_string_stays_empty() -> None:
    """gettext translates "" as the catalogue's header: a report's blank column title read "Content-Type: ..."."""
    previous = i18n.language()
    try:
        i18n.set_language("it")
        assert i18n.tr("") == ""
    finally:
        i18n.set_language(previous)


# --- label_strings: One string for a word and its colon: a label is written _("Name") and field_label() puts the colon on
ROOT = Path(__file__).resolve().parents[2]
LITERAL = re.compile(r"""\b(?:_|tr)\((["'])([^"'\\\n]{1,60}:)\1\)""")
#: Sentences that introduce something (not a label), and strings joined to another text.
ALLOWED = {
    "JMP documentation:", "Name of the new column:", "Hide rows where {column} {operator}:",
    "Select rows where {column} {operator}:", "Column names, separated by commas:",
    "The assistant wants to change the project:", "Password for {username}@{host}:",
    "Template name (an existing name is replaced):", "Against the correlation asked for ({requested:g}):",
}


def test_no_label_string_ends_with_a_colon() -> None:
    found = []
    for path in sorted((ROOT / "app").rglob("*.py")) + sorted((ROOT / "dev").rglob("*.py")):
        if "tests" in path.parts or "ai_providers" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in LITERAL.finditer(line):
                if match.group(2) not in ALLOWED:
                    found.append(f"{path.relative_to(ROOT)}:{number}: {match.group(2)}")
    assert not found, "write the label without its colon and wrap it in field_label():\n" + "\n".join(found)


def test_the_catalogues_have_no_label_with_and_without_its_colon() -> None:
    import re as _re

    for catalogue in sorted((ROOT / "app" / "locales").glob("*/LC_MESSAGES/ChartLibre.po")):
        ids = set(_re.findall(r'^msgid "((?:[^"\\]|\\.)*)"$', catalogue.read_text(encoding="utf-8"), flags=_re.M))
        twins = sorted(text for text in ids if text.endswith(":") and text[:-1] in ids and len(text) < 60
                       and text not in ALLOWED)
        assert not twins, f"{catalogue.parent.parent.name}: {twins[:5]}"


# --- section_titles_case: Frame titles keep the case they are written in ("Select Columns", not "SELECT COLUMNS"), as macOS's own.
STYLES = Path(__file__).resolve().parents[2] / "app" / "styles"


@pytest.mark.parametrize("sheet", ["fluent_win11.qss", "macos_native.qss", "ubuntu_native.qss"])
def test_a_section_title_is_not_forced_to_capitals(sheet: str) -> None:
    text = (STYLES / sheet).read_text(encoding="utf-8")
    for body in re.findall(r'QLabel\[sectionTitle="true"\]\s*\{([^}]*)\}', text):
        assert "text-transform" not in body, f"{sheet}: a section title is still transformed"


# --- field_labels: Form labels as the style in use writes them: a colon on macOS, none on Windows 11 and Linux.
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
