"""One string for a word and its colon (todo ID101): a label is written _("Name") and field_label() puts the colon on
or leaves it off as the platform does; a catalogue string never ends in a colon for a label."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LITERAL = re.compile(r"""\b(?:_|tr)\((["'])([^"'\\\n]{1,60}:)\1\)""")
#: Sentences that introduce something (not a label), and strings joined to another text.
ALLOWED = {
    "JMP documentation:", "Name of the new column:", "Hide rows where {column} {operator}:",
    "Select rows where {column} {operator}:", "Column names, separated by commas:",
    "The assistant wants to change the project:", "Password for {username}@{host}:",
    "Template name (an existing name is replaced):",
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
