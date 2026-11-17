"""The Animation page's two sections are always open: no chevron, no fold."""
from __future__ import annotations

from dev.tests.test_animation import _figure, _spin, repo  # noqa: F401 - the fixture


def test_both_sections_stay_open(qapp, repo) -> None:
    from app.main_window.main_window import MainWindow

    _figure(repo)
    window = MainWindow(repo, repo.db_path)
    try:
        window.resize(1200, 760)
        window.show()
        window._left_panel.select("chart_properties")
        _spin(qapp, 0.6)
        page = window._animation_widget
        page._enabled.setChecked(True)
        _spin(qapp, 0.3)
        for section in page._cards:
            assert section.is_open() and not section.body.isHidden()
            assert section._header.isHidden()
    finally:
        window.close()
