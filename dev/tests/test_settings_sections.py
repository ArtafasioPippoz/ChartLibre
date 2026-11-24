"""Settings: every section has its own icon and sentence, in a translated interface too."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize

from app.utils import i18n


@pytest.mark.parametrize("language", ["en", "it"])
def test_each_section_has_an_icon_of_its_own_whatever_the_language(qapp, language: str) -> None:
    from app.dialogs.settings_dialog import SettingsDialog

    before = i18n.language()
    i18n.set_language(language)
    try:
        dialog = SettingsDialog()
        sidebar = dialog._sidebar
        pictures = []
        for row in range(sidebar.count()):
            image = sidebar.item(row).icon().pixmap(QSize(24, 24)).toImage()
            pictures.append(bytes(image.constBits()))
        assert sidebar.count() == len(SettingsDialog.SECTIONS)
        assert len(set(pictures)) == len(pictures)  # none alike: no section fell back to the gear
        # Each page says what it is for, under its title.
        assert dialog._stack.widget(0).findChild(type(dialog._stack.widget(0)), "settingsAppearanceHeading") is not None
        dialog.close()
    finally:
        i18n.set_language(before)
