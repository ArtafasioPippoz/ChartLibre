"""Time the application's start, step by step: imports, style, main window, first events.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=. .python/bin/python3 dev/tools/startup_timing.py <copy of a .dhub>

Always offscreen, on a copy of a project. The last field lists the heavy libraries the start
imported: it should stay empty (they are imported when first needed, or by app/utils/warm_up.py).
"""
import sys, time
from pathlib import Path
T=[time.perf_counter()]; L=[]
def mark(n): T.append(time.perf_counter()); L.append(f"{n} {T[-1]-T[-2]:.2f}")
from app.utils.qt_plugins import ensure_visible_plugins
ensure_visible_plugins()
from PySide6.QtWidgets import QApplication
from app.data.sqlite_repo import SqliteRepo
from app.main_window.main_window import MainWindow
from app.styles.style import apply_platform_style, ensure_icon_theme
from app.utils.i18n import set_language, install_qt_translations
from app.utils.config import get_language
mark("imports")
app=QApplication(sys.argv); mark("qapp")
set_language(get_language()); install_qt_translations(app); mark("lang")
apply_platform_style(app); mark("style")
ensure_icon_theme(); mark("icons")
p=Path(sys.argv[1]); repo=SqliteRepo(db_path=p); mark("repo")
w=MainWindow(repo=repo, db_path=p); mark("window")
w.show(); mark("show")
for _ in range(30): app.processEvents(); time.sleep(0.01)
mark("events")
print(" | ".join(L), "| heavy:", [m for m in ("anthropic","sympy","sklearn","scipy","statsmodels","PySide6.QtWebEngineWidgets","AppKit") if m in sys.modules])
