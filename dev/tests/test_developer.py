"""Tests of developer, one section per former file:

* developer_window: ChartLibre Developer's window: a sidebar page per section, as Preferences.
* developer_app: dev/ChartLibreDeveloper.py: the launcher builds, and its quick jobs answer without running anything long.
* developer_launchers: ChartLibre Developer's launchers: the .app, the .bat, and the macros of the C sources.
* sql_workpad_developer: The SQL workpad is a ChartLibre Developer tool: a project file is opened, a statement runs on it.
"""
from __future__ import annotations

from pathlib import Path
import importlib.util
import runpy

import pandas as pd

from app.data.sqlite_repo import SqliteRepo
from dev.developer.sql_workpad_dialog import SqlWorkpadDialog
from dev.tools import make_launcher as ml


# --- developer_window: ChartLibre Developer's window: a sidebar page per section, as Preferences.
SCRIPT = Path(__file__).resolve().parents[1] / "ChartLibreDeveloper.py"


def test_developer_window_has_a_sidebar_page_per_section(qapp):
    spec = importlib.util.spec_from_file_location("developer_window", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    window = module.DeveloperWindow()
    names = [window._sidebar.item(i).text() for i in range(window._sidebar.count())]
    assert names == [section[0] for section in module.SECTIONS]
    window.close()


# --- developer_app: dev/ChartLibreDeveloper.py: the launcher builds, and its quick jobs answer without running anything long.
LAUNCHER = Path(__file__).resolve().parents[1] / "ChartLibreDeveloper.py"


def test_the_launcher_shows_every_tool_and_counts_the_project(qapp) -> None:
    from PySide6.QtWidgets import QPushButton

    module = runpy.run_path(str(LAUNCHER), run_name="developer_app_test")
    window = module["DeveloperWindow"]()
    try:
        texts = {button.text() for button in window.findChildren(QPushButton)}
        for wanted in ("Run the tests", "NIST report", "Build the bundle", "Compile the user manual",
                       "Developer manual", "Make chart previews", "Update Python libraries"):
            assert wanted in texts
        window._project_size()
        assert window._log.toPlainText().startswith("Now: app/")
    finally:
        window.close()


def test_the_qss_editor_fills_the_tokens_and_saves_with_a_backup(qapp, tmp_path, monkeypatch) -> None:
    import dev.developer.qss_editor as editor

    sheet = tmp_path / "try.qss"
    sheet.write_text("QWidget { color: @ACCENT_RGB@; }\n", encoding="utf-8")
    monkeypatch.setattr(editor, "STYLES_DIR", tmp_path)
    dialog = editor.QssEditorDialog()
    try:
        assert "@" not in dialog.themed() or "@ICON:" in dialog.themed()
        dialog._text.setPlainText("QWidget { color: red; }\n")
        dialog._save()
        assert sheet.read_text(encoding="utf-8") == "QWidget { color: red; }\n"
        assert (tmp_path / "try.qss.bak").read_text(encoding="utf-8").startswith("QWidget { color: @")
    finally:
        dialog.reject()


# --- developer_launchers: ChartLibre Developer's launchers: the .app, the .bat, and the macros of the C sources.
SOURCE = Path(ml.__file__).parent / "launcher"


def test_windows_bat_is_crlf_and_runs_the_developer_script(tmp_path):
    data = ml.make_developer_windows_launcher(tmp_path).read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert b"dev\\ChartLibreDeveloper.py" in data
    assert b'cd /d "%~dp0.."' in data  # it sits in dev


def test_macos_app_has_executable_icon_and_plist(tmp_path):
    app = ml.make_developer_macos_app(tmp_path)
    executable = app / "Contents" / "MacOS" / ml.DEVELOPER_NAME
    assert executable.is_file() and executable.stat().st_mode & 0o111
    assert "org.chartlibre.developer" in (app / "Contents" / "Info.plist").read_text()


def test_c_launchers_take_the_script_from_a_macro():
    assert "LAUNCH_SCRIPT" in (SOURCE / "chartlibre_mac_launcher.c").read_text()
    windows = (SOURCE / "chartlibre_launcher.c").read_text()
    assert "DEVELOPER_LAUNCHER" in windows and "ChartLibreDeveloper.py" in windows
    assert "ROOT_LEVELS" in windows and "ROOT_LEVELS" in (SOURCE / "chartlibre_mac_launcher.c").read_text()


def test_developer_launchers_live_in_dev_and_stay_out_of_every_package():
    from dev.tools.build_bundle import wanted_file

    root = Path(ml.PROJECT_DIR)
    assert not any(root.glob(f"{ml.DEVELOPER_NAME}.*"))
    for name in (".app/Contents/Info.plist", ".bat", ".exe"):
        path = f"{ml.DEVELOPER_LAUNCHERS.as_posix()}/{ml.DEVELOPER_NAME}{name}"
        assert (root / path).is_file()
        assert not any(wanted_file(path, system) for system in ("macos", "windows", "linux"))


# --- sql_workpad_developer: The SQL workpad is a ChartLibre Developer tool: a project file is opened, a statement runs on it.
def test_the_dialog_runs_a_select_on_the_picked_project(qapp, tmp_path) -> None:
    path = tmp_path / "w.dhub"
    repo = SqliteRepo(db_path=path)
    repo.import_dataframe(pd.DataFrame({"a": [1, 2, 3]}), table_name="t", normalize_columns=False)
    repo.close()
    dialog = SqlWorkpadDialog(None, path)
    dialog.panel.run('SELECT a FROM "t" ORDER BY a')
    assert dialog.panel._result.rowCount() == 3
    dialog.done(0)
