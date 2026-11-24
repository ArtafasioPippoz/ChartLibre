"""ChartLibre Developer's launchers: the .app, the .bat, and the macros of the C sources."""
from __future__ import annotations

from pathlib import Path

from dev.tools import make_launcher as ml

SOURCE = Path(ml.__file__).parent / "launcher"


def test_windows_bat_is_crlf_and_runs_the_developer_script(tmp_path):
    data = ml.make_developer_windows_launcher(tmp_path).read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    assert b"dev\\ChartLibreDeveloper.py" in data


def test_macos_app_has_executable_icon_and_plist(tmp_path):
    app = ml.make_developer_macos_app(tmp_path)
    executable = app / "Contents" / "MacOS" / ml.DEVELOPER_NAME
    assert executable.is_file() and executable.stat().st_mode & 0o111
    assert "org.chartlibre.developer" in (app / "Contents" / "Info.plist").read_text()


def test_c_launchers_take_the_script_from_a_macro():
    assert "LAUNCH_SCRIPT" in (SOURCE / "chartlibre_mac_launcher.c").read_text()
    windows = (SOURCE / "chartlibre_launcher.c").read_text()
    assert "DEVELOPER_LAUNCHER" in windows and "ChartLibreDeveloper.py" in windows

