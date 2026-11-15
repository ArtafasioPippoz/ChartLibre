"""ChartLibre Developer's window: a sidebar page per section, as Preferences."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "ChartLibreDeveloper.py"


def test_developer_window_has_a_sidebar_page_per_section(qapp):
    spec = importlib.util.spec_from_file_location("developer_window", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    window = module.DeveloperWindow()
    names = [window._sidebar.item(i).text() for i in range(window._sidebar.count())]
    assert names == [section[0] for section in module.SECTIONS]
    window.close()
