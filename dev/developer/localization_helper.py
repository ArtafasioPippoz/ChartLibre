"""Edit Localization: a table editor for one language's .po catalogue
(todo.txt P3-5).

Every row is a source string ``_()``/``tr()`` wraps somewhere in the app
(``i18n.source_translator_calls()``, an AST sweep of the source) unioned
with whatever the selected language's catalogue already has, so a string
that is translated but no longer used anywhere still shows up to edit or
remove by hand, and a string used but never added to the catalogue shows
up with an empty translation. "Missing only" filters to exactly that
empty-translation case - the catalogues are kept here, by hand; no test
checks what they cover.

Saving writes through :func:`app.utils.i18n._write_po` (round-trips
losslessly with :func:`app.utils.i18n._parse_po`, see that function's own
docstring) and recompiles the .mo immediately via
:func:`app.utils.i18n.compile_catalog`, so a translation shows up the next
time that language is selected without restarting the app.

"Translate missing (auto)" is a soft dependency on ``deep_translator``
(Google Translate or MyMemory, no key needed), on a DeepL API key in
Settings, or on ``ctranslate2`` and ``sentencepiece`` for Argos Translate,
offline (see app.utils.machine_translation) - offered only when one of
them is there, run
on a worker thread so the dialog stays usable and can be stopped, and
always a starting point to review, never treated as a finished translation.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from app.dialogs.settings_dialog import LANGUAGE_NAMES
from app.dialogs.two_panels_dialog_base import SettingsTableDialog
from app.logs.logger import applogger
from app.styles.style import (
    create_action_button,
    load_icon,
    mark_editor_panel,
    stdSizeAndlayout,
)
from app.utils import i18n, machine_translation
from app.utils.background import BackgroundTask, run_in_background
from app.utils.config import get_value
from app.utils.i18n import _
from app.utils.messages import show_message

#: A catalogue this new is seeded with every known source string and
#: nothing else - see _default_header.
_NEW_CATALOG_HEADER_TEMPLATE = (
    "Project-Id-Version: ChartLibre\n"
    "Language: {code}\n"
    "MIME-Version: 1.0\n"
    "Content-Type: text/plain; charset=UTF-8\n"
    "Content-Transfer-Encoding: 8bit\n"
)


#: The packs' source folders (dev/packs/<id>/): each can hold locales/<language>/pack.po, read by the application
#: as it is once the pack is installed (app.utils.packs.catalogues).
PACKS_DIR: Path = Path(__file__).resolve().parents[1] / "packs"


def pack_sources() -> list[tuple[str, str]]:
    """(id, name) of every pack folder in dev/packs, by id."""
    found = []
    for manifest in sorted(PACKS_DIR.glob("*/pack.json")):
        try:
            name = str(json.loads(manifest.read_text(encoding="utf-8")).get("name") or manifest.parent.name)
        except (OSError, ValueError):
            name = manifest.parent.name
        found.append((manifest.parent.name, name))
    return found


def _po_path(language: str, pack_id: str = "") -> Path:
    """The catalogue of *language*: the application's, or that of the pack *pack_id*."""
    if pack_id:
        return PACKS_DIR / pack_id / "locales" / language / "pack.po"
    return i18n.LOCALES_DIR / language / "LC_MESSAGES" / f"{i18n.DOMAIN}.po"


def source_strings(pack_id: str = "") -> set[str]:
    """Every string the catalogue should hold: the application's, or the pack's (its plugins' and its
    manifest's name and description, which Preferences shows through tr())."""
    if not pack_id:
        return i18n.source_translator_calls()
    folder = PACKS_DIR / pack_id
    found = i18n.source_translator_calls(folder)
    try:
        manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    found.update(str(manifest[key]) for key in ("name", "description") if manifest.get(key))
    return found


def _leading_comment(path: Path) -> str:
    """Return a .po file's leading ``#`` comment lines, verbatim.

    _write_po does not reconstruct these on its own (see its own
    docstring) - reading them here before a save is what keeps them from
    being silently dropped on an existing catalogue's first re-save
    through this dialog.
    """
    if not path.is_file():
        return ""
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("#"):
            lines.append(raw_line)
            continue
        break
    return "\n".join(lines)


class EditLocalizationDialog(SettingsTableDialog):
    """Browse, edit and extend one language's translation catalogue."""

    def __init__(self, parent: QWidget | None = None) -> None:
        # The language and what to show on the left; its strings on the right.
        super().__init__(
            parent,
            title=_("Edit Localization"),
            icon=load_icon("edit_localization"),
            size="large",
            settings_width=280,
            sections=True,
        )
        # A titled frame per section, titles above the boxes.
        panel = self.add_settings_card(_("Language"))
        side = panel.layout()
        card = self.add_content_card(_("Strings"), stretch=1)
        self.content_frame, self.content_layout = card, card.layout()

        # Which catalogue: the application's, or one of the packs' (dev/packs/<id>/locales/<language>/pack.po).
        self._catalogue_combo = QComboBox(panel)
        self._catalogue_combo.addItem("ChartLibre", "")
        for pack_id, name in pack_sources():
            self._catalogue_combo.addItem(_("Pack: {name}").format(name=name), pack_id)
        self._catalogue_combo.setToolTip(_("The catalogue to edit: the application's, or the one a pack carries"))
        self._catalogue_combo.setVisible(self._catalogue_combo.count() > 1)
        self._catalogue_combo.currentIndexChanged.connect(self._on_language_changed)
        side.addWidget(self._catalogue_combo)

        self._language_combo = self._build_language_combo(panel)
        self._language_combo.currentIndexChanged.connect(self._on_language_changed)
        side.addWidget(self._language_combo)
        new_row = QHBoxLayout()
        stdSizeAndlayout(new_row)
        create_action_button(
            parent=self,
            action_id="new",
            action=self._on_new_language,
            layout=new_row,
            presentation=(load_icon("new"), _("New language…"), _("Create a new, empty catalogue")),
        )
        create_action_button(
            parent=self,
            action_id="delete",
            action=self._on_remove_language,
            layout=new_row,
            presentation=(load_icon("delete"), _("Remove…"),
                          _("Remove this language: its catalogue goes to the Trash")),
        )
        new_row.addStretch(1)
        side.addLayout(new_row)

        panel = self.add_settings_card(_("Show"))
        side = panel.layout()
        self._search_edit = QLineEdit(panel)
        self._search_edit.setPlaceholderText(_("Search source or translation…"))
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._apply_filter)
        side.addWidget(self._search_edit)
        self._missing_only_check = QCheckBox(_("Missing only"), panel)
        self._missing_only_check.toggled.connect(self._apply_filter)
        side.addWidget(self._missing_only_check)

        self._translate_button: QPushButton | None = None
        self._translate_all_button: QPushButton | None = None
        self._provider_combo: QComboBox | None = None
        self._deepl_key = str(get_value(machine_translation.DEEPL_KEY_SETTING, "") or "")
        self._providers = machine_translation.available_providers(self._deepl_key)
        if self._providers:
            panel = self.add_settings_card(_("Machine translation"))
            side = panel.layout()
            self._provider_combo = QComboBox(panel)
            self._provider_combo.setToolTip(_("Translation service"))
            for key, name in self._providers:
                self._provider_combo.addItem(name, key)
            side.addWidget(self._provider_combo)
            translate_row = QHBoxLayout()
            stdSizeAndlayout(translate_row)
            self._translate_button = create_action_button(
                parent=self,
                action_id="run",
                action=self._on_auto_translate_missing,
                layout=translate_row,
                presentation=(
                    load_icon("run"),
                    _("Translate missing (auto)"),
                    _("Fill every empty translation with a machine translation to review"),
                ),
            )
            translate_row.addStretch(1)
            side.addLayout(translate_row)
            all_row = QHBoxLayout()
            stdSizeAndlayout(all_row)
            self._translate_all_button = create_action_button(
                parent=self,
                action_id="run",
                action=self._on_translate_all_languages,
                layout=all_row,
                presentation=(
                    load_icon("run"),
                    _("Translate all languages (auto)"),
                    _("Fill the empty translations of every language of this catalogue, one after the other, "
                      "and save each"),
                ),
            )
            all_row.addStretch(1)
            side.addLayout(all_row)

        panel = self.add_settings_card(_("Manual"))
        side = panel.layout()
        manual_row = QHBoxLayout()
        stdSizeAndlayout(manual_row)
        create_action_button(
            parent=self,
            action_id="info",
            action=self._show_manual_instructions,
            layout=manual_row,
            presentation=(
                load_icon("info"),
                _("Localized manual…"),
                _("How to produce a translated copy of the user manual"),
            ),
        )
        manual_row.addStretch(1)
        side.addLayout(manual_row)
        self._settings_column.layout().addStretch(1)

        self._table = QTableWidget(0, 2, card)
        self._table.setHorizontalHeaderLabels([_("Source"), _("Translation")])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        mark_editor_panel(self._table)
        self.content_layout.addWidget(self._table, 1)

        copy_row = QHBoxLayout()
        stdSizeAndlayout(copy_row)
        create_action_button(
            parent=self,
            action_id="copy",
            action=self._on_copy_source,
            layout=copy_row,
            presentation=(
                load_icon("copy"),
                _("Copy source"),
                _("Put the English source, untranslated, into the translation of the selected rows"),
            ),
        )
        copy_row.addStretch(1)
        self.content_layout.addLayout(copy_row)

        self._status_label = QLabel(card)
        self._status_label.setWordWrap(True)
        self.content_layout.addWidget(self._status_label)

        # One button, Close, and no Cancel (ID100): what is typed is kept - when the language is changed
        # and when the dialog closes, however it closes. Not the default button: Return ends a cell's edit.
        self.add_action("dismiss", self.accept)

        self._entries: dict[str, str] = {}
        #: The language the table shows, and whether it holds something its file does not.
        self._loaded_language: str | None = None
        #: The pack whose catalogue the table shows ("" for the application's).
        self._loaded_pack = ""
        self._dirty = False
        self._filling = False
        self._table.itemChanged.connect(self._on_item_changed)
        self._translation_task: BackgroundTask | None = None
        #: [done, total], written by the worker thread, read by the timer.
        self._translation_progress: list[int] = [0, 0]
        #: (source, translation) pairs the worker has finished and the
        #: timer has not yet put in the table. list.append is atomic, so
        #: the worker appends and the GUI thread drains without a lock.
        self._arrived: list[tuple[str, str]] = []
        self._translation_filled = 0
        #: "Translate all languages": the language combo's indices still to do (None when not running),
        #: what was filled so far and what went wrong, language by language.
        self._all_queue: list[int] | None = None
        self._all_filled = 0
        self._all_reasons: list[str] = []
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(250)
        self._progress_timer.timeout.connect(self._show_translation_progress)
        self._reload_table()

    # ------------------------------------------------------------------
    # Language combo
    # ------------------------------------------------------------------
    def _build_language_combo(self, parent: QWidget) -> QComboBox:
        combo = QComboBox(parent)
        # "en" is the source language, not a translation target - the
        # msgid *is* the English text, so there is nothing to edit into it.
        for code in i18n.available_languages():
            if code == i18n.DEFAULT_LANGUAGE:
                continue
            combo.addItem(LANGUAGE_NAMES.get(code, code), code)
        if combo.count() == 0:
            combo.addItem(LANGUAGE_NAMES.get("it", "it"), "it")
        return combo

    def _current_pack(self) -> str:
        return str(self._catalogue_combo.currentData() or "")

    def _current_language(self) -> str:
        return str(self._language_combo.currentData() or "it")

    def _on_new_language(self) -> None:
        if self._current_pack():
            show_message(self, "dev.validation_error",
                         detail=_("A pack's catalogue takes the languages ChartLibre has: pick one in the list."))
            return
        choices = language_choices(exclude=set(i18n.available_languages()))
        label, ok = QInputDialog.getItem(self, _("New language"), _("Country: language"), list(choices), 0, False)
        code = choices.get(label, "") if ok else ""
        if not code:
            return
        if not (code.isalpha() and 2 <= len(code) <= 3):
            show_message(self, "dev.validation_error", detail=_("Not a valid language code."))
            return
        if code in i18n.available_languages():
            show_message(
                self, "dev.validation_error",
                detail=_("\"{code}\" already has a catalogue.").format(code=code),
            )
            return

        entries = {string: "" for string in sorted(i18n.source_translator_calls())}
        entries[""] = _NEW_CATALOG_HEADER_TEMPLATE.format(code=code)
        path = _po_path(code)
        i18n._write_po(
            entries, path,
            header_comment=f"# {code} translation for ChartLibre.\n# Message ids are the English source strings.",
        )
        i18n.compile_catalog(code, force=True)

        self._language_combo.addItem(LANGUAGE_NAMES.get(code, code), code)
        self._language_combo.setCurrentIndex(self._language_combo.count() - 1)

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------
    def _on_item_changed(self, _item: QTableWidgetItem) -> None:
        if not self._filling:
            self._dirty = True

    def _on_language_changed(self, *_args: object) -> None:
        """Another language chosen: what was typed for the one shown is saved first, then the table changes."""
        self._save_if_changed()
        self._reload_table()

    def _save_if_changed(self) -> bool:
        """Save the language shown if the table holds a change; False only when the save failed."""
        if not self._dirty or self._loaded_language is None:
            return True
        return self._save(self._loaded_language, self._loaded_pack)

    def _on_remove_language(self) -> None:
        """Remove the language shown, after a question: its folder goes to the Trash, where it can be found."""
        from PySide6.QtCore import QFile

        from app.utils.messages import ask

        language = self._current_language()
        pack_id = self._current_pack()
        # The application's language is a folder with LC_MESSAGES in it; a pack's, locales/<language>.
        folder = _po_path(language, pack_id).parent if pack_id else _po_path(language).parent.parent
        if not folder.is_dir():
            return
        if language == i18n.language() and not pack_id:
            show_message(self, "dev.validation_error",
                         detail=_("This is the language the application is shown in: choose another in Settings first."))
            return
        if not ask(self, "dev.confirm_remove_language", language=LANGUAGE_NAMES.get(language, language)):
            return
        if not QFile.moveToTrash(str(folder)):
            show_message(self, "dev.validation_error", detail=_("The language could not be moved to the Trash."))
            return
        applogger.info("Edit Localization: removed %s (moved to the Trash).", folder)
        i18n._translation.cache_clear()
        # Nothing of the removed language is saved back: the table is another one's from here.
        self._dirty, self._loaded_language = False, None
        if pack_id:  # only the pack's file goes: the language is still the application's
            self._reload_table()
            return
        self._language_combo.blockSignals(True)
        self._language_combo.removeItem(self._language_combo.currentIndex())
        if self._language_combo.count() == 0:
            self._language_combo.addItem(LANGUAGE_NAMES.get("it", "it"), "it")
        self._language_combo.blockSignals(False)
        self._reload_table()

    def _reload_table(self) -> None:
        language = self._current_language()
        pack_id = self._current_pack()
        self._loaded_language, self._loaded_pack = language, pack_id
        path = _po_path(language, pack_id)
        catalog = i18n._parse_po(path) if path.is_file() else {}
        catalog.pop("", None)

        merged: dict[str, str] = dict.fromkeys(sorted(source_strings(pack_id)), "")
        merged.update(catalog)  # existing translations, and any orphaned extra entries
        self._entries = merged
        self._populate_table()
        self._status_label.setText(
            _("{count} string(s), {missing} missing translation.").format(
                count=len(merged),
                missing=sum(1 for value in merged.values() if not value.strip()),
            )
        )

    def _populate_table(self) -> None:
        self._filling = True
        try:
            self._table.setRowCount(0)
            self._table.setRowCount(len(self._entries))
            for row, (msgid, msgstr) in enumerate(self._entries.items()):
                source_item = QTableWidgetItem(msgid)
                source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                source_item.setData(Qt.ItemDataRole.UserRole, msgid)
                self._table.setItem(row, 0, source_item)
                self._table.setItem(row, 1, QTableWidgetItem(msgstr))
        finally:
            self._filling = False
        self._dirty = False
        self._apply_filter()

    def _on_copy_source(self) -> None:
        """The selected rows' English source, as it is, into their translation (shown rows only)."""
        self._commit_open_edit()
        rows = sorted({index.row() for index in self._table.selectionModel().selectedIndexes()})
        for row in rows:
            source_item = self._table.item(row, 0)
            translation_item = self._table.item(row, 1)
            if source_item is None or translation_item is None or self._table.isRowHidden(row):
                continue
            translation_item.setText(str(source_item.data(Qt.ItemDataRole.UserRole)))

    def _apply_filter(self) -> None:
        missing_only = self._missing_only_check.isChecked()
        search = self._search_edit.text().strip().lower()
        for row in range(self._table.rowCount()):
            source_item = self._table.item(row, 0)
            translation_item = self._table.item(row, 1)
            source_text = source_item.text() if source_item else ""
            translation_text = translation_item.text() if translation_item else ""
            is_missing = not translation_text.strip()
            matches_search = (
                not search
                or search in source_text.lower()
                or search in translation_text.lower()
            )
            hide = (missing_only and not is_missing) or not matches_search
            self._table.setRowHidden(row, hide)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _commit_open_edit(self) -> None:
        """The cell being typed into, written to its item: OK clicked mid-edit saved the text before it."""
        editor = QApplication.focusWidget()
        if self._table.state() == QAbstractItemView.State.EditingState and editor is not None:
            self._table.commitData(editor)
            self._table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _on_save(self) -> None:
        """Save the language shown and close (kept for the callers that asked for OK)."""
        self.accept()

    def _save(self, language: str, pack_id: str = "") -> bool:
        """Write the table to *language*'s catalogue (the pack *pack_id*'s, if given); False, with a message,
        when it could not be written."""
        self._commit_open_edit()
        path = _po_path(language, pack_id)
        header_comment = _leading_comment(path)
        if not header_comment:
            header_comment = (
                f"# {LANGUAGE_NAMES.get(language, language)} translation for "
                f"{'the pack ' + pack_id if pack_id else 'ChartLibre'}.\n"
                "# Message ids are the English source strings."
            )

        entries = dict(self._entries)
        for row in range(self._table.rowCount()):
            source_item = self._table.item(row, 0)
            translation_item = self._table.item(row, 1)
            if source_item is None or translation_item is None:
                continue
            msgid = str(source_item.data(Qt.ItemDataRole.UserRole))
            entries[msgid] = translation_item.text()

        existing = i18n._parse_po(path) if path.is_file() else {}
        entries[""] = existing.get("", _NEW_CATALOG_HEADER_TEMPLATE.format(code=language))

        try:
            i18n._write_po(entries, path, header_comment=header_comment)
            if not pack_id:  # a pack's file is read as it is: no .mo
                i18n.compile_catalog(language, force=True)
        except OSError as exc:
            applogger.exception("Could not save the localization catalogue.")
            show_message(self, "dev.validation_error", detail=str(exc))
            return False

        applogger.info("Edit Localization: saved %s (%d entries).", path, len(entries) - 1)
        self._entries = {key: value for key, value in entries.items() if key}
        self._dirty = False
        return True

    # ------------------------------------------------------------------
    # Auto-translate
    # ------------------------------------------------------------------
    def _on_auto_translate_missing(self) -> None:
        """Start filling the empty translations - or, while running, stop."""
        if self._translation_task is not None:
            self._all_queue = None
            self._translation_task.cancel()
            return
        self._start_translation(ask=True)

    def _on_translate_all_languages(self) -> None:
        """Fill the empty translations of every language, one after the other - or, while running, stop."""
        if self._translation_task is not None:
            self._all_queue = None
            self._translation_task.cancel()
            return
        if not ask_before_auto_translate(self):
            return
        self._all_queue = list(range(self._language_combo.count()))
        self._all_filled, self._all_reasons = 0, []
        self._translate_next_language()

    def _translate_next_language(self) -> None:
        """Show the next language of the queue (the one shown is saved) and translate it; at the end, say how
        it went."""
        while self._all_queue:
            self._language_combo.setCurrentIndex(self._all_queue.pop(0))  # saves the one shown, loads this
            if self._start_translation(ask=False):
                return
        self._all_queue = None
        self._save_if_changed()
        if self._all_reasons:
            show_message(self, "dev.localization_auto_translate_partial",
                         count=self._all_filled, reasons="; ".join(self._all_reasons))
        else:
            show_message(self, "dev.localization_auto_translated", count=self._all_filled)

    def _start_translation(self, *, ask: bool) -> bool:
        """Start the service on the empty translations of the table; False when there are none (said if *ask*)
        or the question was declined."""
        missing = [
            str(source_item.data(Qt.ItemDataRole.UserRole))
            for row in range(self._table.rowCount())
            if (source_item := self._table.item(row, 0)) is not None
            and (translation_item := self._table.item(row, 1)) is not None
            and not translation_item.text().strip()
        ]
        if not missing:
            if ask:
                show_message(self, "dev.localization_auto_translated", count=0)
            return False
        if ask and not ask_before_auto_translate(self):
            return False

        language = self._current_language()
        provider = str(self._provider_combo.currentData()) if self._provider_combo else "google"
        progress = self._translation_progress
        progress[:] = [0, len(missing)]
        arrived = self._arrived
        arrived.clear()
        self._translation_filled = 0

        def work(cancel_event: object) -> machine_translation.TranslationRun:
            def report(done: int, total: int) -> None:
                progress[:] = [done, total]

            return machine_translation.translate_all(
                missing,
                language=language,
                provider=provider,
                # Google refuses addresses that ask too often: what it does
                # not translate goes to the other service.
                fallbacks=[key for key, _name in self._providers if key != provider],
                deepl_key=self._deepl_key,
                cancel_event=cancel_event,  # pyright: ignore[reportArgumentType]
                progress=report,
                on_result=lambda source, text: arrived.append((source, text)),
            )

        self._translation_task = run_in_background(
            work, self._on_translation_finished, self._on_translation_failed
        )
        self._set_translating(True)
        return True

    def _set_translating(self, running: bool) -> None:
        all_languages = self._all_queue is not None
        if self._translate_button is not None:
            self._translate_button.setText(
                _("Stop") if running and not all_languages else _("Translate missing (auto)"))
            self._translate_button.setEnabled(not (running and all_languages))
        if self._translate_all_button is not None:
            self._translate_all_button.setText(
                _("Stop") if running and all_languages else _("Translate all languages (auto)"))
            self._translate_all_button.setEnabled(not running or all_languages)
        if self._provider_combo is not None:
            self._provider_combo.setEnabled(not running)
        self._language_combo.setEnabled(not running)
        if running:
            self._progress_timer.start()
            self._show_translation_progress()
        else:
            self._progress_timer.stop()

    def _show_translation_progress(self) -> None:
        self._fill_arrived()
        done, total = self._translation_progress
        self._status_label.setText(
            _("Translating {done} of {total}…").format(done=done, total=total)
        )

    def _fill_arrived(self) -> int:
        """Put the translations that have arrived into their empty cells.

        Run by the progress timer while the service works, so the table
        fills block by block and Stop keeps everything already there.
        Only into a cell still empty: the table stays editable meanwhile,
        and a hand-typed translation wins.
        """
        if not self._arrived:
            return 0
        count = len(self._arrived)  # the worker may append meanwhile
        batch = dict(self._arrived[:count])
        del self._arrived[:count]
        filled = 0
        for row in range(self._table.rowCount()):
            source_item = self._table.item(row, 0)
            translation_item = self._table.item(row, 1)
            if source_item is None or translation_item is None:
                continue
            guess = batch.get(str(source_item.data(Qt.ItemDataRole.UserRole)))
            if guess and not translation_item.text().strip():
                translation_item.setText(guess)
                filled += 1
        self._translation_filled += filled
        return filled

    def _on_translation_finished(self, run: machine_translation.TranslationRun) -> None:
        self._translation_task = None
        self._set_translating(False)
        self._fill_arrived()
        filled = self._translation_filled
        self._apply_filter()
        self._status_label.setText(
            _("{count} string(s), {missing} missing translation.").format(
                count=self._table.rowCount(),
                missing=sum(
                    1 for row in range(self._table.rowCount())
                    if (item := self._table.item(row, 1)) is not None and not item.text().strip()
                ),
            )
        )
        reasons = self._run_reasons(run)
        if self._all_queue is not None:  # one language of "Translate all languages": save it, on to the next
            self._all_filled += filled
            if reasons:
                self._all_reasons.append(f"{self._language_combo.currentText()}: {'; '.join(reasons)}")
            self._save_if_changed()
            self._translate_next_language()
            return
        if reasons:
            show_message(
                self, "dev.localization_auto_translate_partial",
                count=filled, reasons="; ".join(reasons),
            )
        else:
            show_message(self, "dev.localization_auto_translated", count=filled)

    @staticmethod
    def _run_reasons(run: machine_translation.TranslationRun) -> list[str]:
        """What a translation run did not do, and why; empty when it translated everything."""
        switched = "; ".join(
            _("{first} refused the requests, continued with {second}").format(first=first, second=second)
            for first, second in run.switched
        )
        reasons: list[str] = [switched] if switched else []
        if run.stopped:
            reasons.append(_("stopped"))
        if run.failed:
            why = (
                _("{services} refused for their request limit - Google for a while, MyMemory until tomorrow").format(
                    services=", ".join(run.limited)
                )
                if run.limited
                else run.error or _("no answer")
            )
            reasons.append(
                _("{count} not translated by the service ({error})").format(count=run.failed, error=why)
            )
        if run.rejected:
            reasons.append(
                _("{count} discarded because a placeholder such as {{name}} or %s was lost").format(
                    count=run.rejected
                )
            )
        return reasons

    def _on_translation_failed(self, error: BaseException) -> None:
        self._translation_task = None
        self._all_queue = None
        self._set_translating(False)
        self._reload_status_only()
        applogger.warning(
            "Automatic translation could not start: %s", error,
        )
        show_message(self, "dev.validation_error", detail=str(error))

    def _reload_status_only(self) -> None:
        self._status_label.setText(
            _("{count} string(s), {missing} missing translation.").format(
                count=len(self._entries),
                missing=sum(1 for value in self._entries.values() if not value.strip()),
            )
        )

    def done(self, result: int) -> None:
        """Stop a running translation and keep what was typed when the dialog closes, however it closes.

        A save that fails says why and leaves the dialog open once; closing again gives the change up.
        """
        self._all_queue = None
        if self._translation_task is not None:
            self._translation_task.cancel()
            self._fill_arrived()
        if not self._save_if_changed():
            self._dirty = False  # said; the next Close closes
            return
        super().done(result)

    # ------------------------------------------------------------------
    # Manual
    # ------------------------------------------------------------------
    def _show_manual_instructions(self) -> None:
        QMessageBox.information(
            self,
            _("Localized manual"),
            _(
                "docs/manual/user_manual.typ is not translated by this tool - "
                "it is prose inside Typst markup, not a string catalogue. To "
                "produce a translated copy:\n\n"
                "1. Copy user_manual.typ to user_manual_<lang>.typ (e.g. "
                "user_manual_it.typ).\n"
                "2. Translate the prose, leaving every #-command, code block "
                "and image reference untouched.\n"
                "3. Compile it: typst compile user_manual_<lang>.typ.\n\n"
                "The application text itself does not need this step - it "
                "comes from the catalogue this dialog edits."
            ),
        )


def flag(country: str) -> str:
    """The flag emoji of a two-letter country code (IT -> the Italian flag); "" for anything else."""
    country = country.upper()
    if len(country) != 2 or not country.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country)


def language_choices(*, exclude: set[str] = frozenset()) -> dict[str, str]:
    """Every language Qt knows with a two-letter code, as "<flag> Country: language (code)" -> code.

    The country is the language's main one (Portugal for Portuguese, Germany for German); the catalogue is
    the language's, whatever the country. Sorted by country; the languages in *exclude* left out.
    """
    from PySide6.QtCore import QLocale

    choices: dict[str, tuple[str, str]] = {}
    for language in QLocale.Language:
        if language in (QLocale.Language.AnyLanguage, QLocale.Language.C):
            continue
        locale = QLocale(language)
        code, _sep, country = locale.name().partition("_")
        if len(code) != 2 or code in exclude or code == i18n.DEFAULT_LANGUAGE or locale.language() != language:
            continue
        # The language's own country where it has one - Portugal for Portuguese, not Qt's Brazil.
        home = QLocale(f"{code}_{code.upper()}")
        if home.language() == language and home.name() == f"{code}_{code.upper()}":
            locale, country = home, code.upper()
        name = locale.nativeLanguageName() or QLocale.languageToString(language)
        place = QLocale.territoryToString(locale.territory())
        label = f"{flag(country)} {place}: {name} ({code})".strip()
        choices.setdefault(code, (label, place))
    return dict(sorted(((label, code) for code, (label, _place) in choices.items()), key=lambda item: item[0][2:]))


def ask_before_auto_translate(parent: QWidget) -> bool:
    """Confirm before filling the table with machine translations.

    A separate function so a test can call it without going through the
    real QMessageBox.
    """
    return (
        QMessageBox.question(
            parent,
            _("Translate missing (auto)"),
            _(
                "This fills every empty translation with a machine "
                "translation from an online service - a starting point to "
                "review, not a finished translation. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )
