"""Import the scientific libraries ahead of time, a module at a time, while the window is idle.

The first data operation of a session used to take two to three seconds
to open: SciPy's signal and optimisation modules, scikit-learn, statsmodels
and PyWavelets are imported when an operation's module first
loads, and that is a second or more of a frozen window each. Imported here
instead, a few seconds after the window appears, so by the time an operation
is opened they are already in memory.

On the main thread, one module per turn of the event loop - never in a
thread of its own. PySide6 puts its own hook on every import (Shiboken's
lazy_import), and it is not safe against the main thread creating a Qt type
meanwhile: with the libraries no longer imported at the start, the warm-up
thread was in the middle of an import when the window was shown, and the
window's first QWindow crashed the process (SIGSEGV in
Shiboken::ObjectType::introduceWrapperType, three times on 2026-11-11). A
module at a time costs a few short pauses in the first seconds, each shorter
than the freeze it saves later.

A failure is logged and otherwise ignored - the operation that needs the
library imports it again, and reports the error where it belongs.
"""
from __future__ import annotations

import importlib
import sys

from app.utils.logger import applogger

#: The modules the data operations import, slowest first.
MODULES: tuple[str, ...] = (
    "sklearn.ensemble",
    "sklearn.cluster",
    "sklearn.decomposition",
    "sklearn.manifold",
    "sklearn.gaussian_process",
    "sklearn.preprocessing",
    "sklearn.linear_model",
    "sklearn.isotonic",
    "sklearn.neighbors",
    "sklearn.svm",
    "sklearn.covariance",
    "statsmodels.api",
    "statsmodels.formula.api",
    "scipy.signal",
    "scipy.optimize",
    "scipy.interpolate",
    "scipy.stats",
    "scipy.cluster.hierarchy",
    "pywt",
)

#: Milliseconds between two imports: the event loop's turn - a click, a repaint - in between.
PAUSE_MS: int = 150

_started = False
_pending: list[str] = []


def _import_next() -> None:
    """Import one module, then ask for the next after a pause."""
    # The process may be ending (a short test run, a quick quit): nothing more to import then.
    if not _pending or sys.is_finalizing():
        _pending.clear()
        return
    name = _pending.pop(0)
    try:
        importlib.import_module(name)
    except Exception as exc:
        applogger.debug("Warm-up: %s could not be imported: %s", name, exc)
    if _pending:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(PAUSE_MS, _import_next)


def warm_up_gradually() -> None:
    """Start importing MODULES on the main thread, one per turn of the event loop; once per process."""
    global _started
    if _started:
        return
    _started = True
    _pending.extend(MODULES)
    _import_next()


def finish_now() -> None:
    """Import what is still pending, at once - before a calculation goes to a worker thread.

    A worker that met a library not yet imported would import it there, which is the very thing the main
    thread must do (see the module's note). Costs a pause only when an operation is run in the first
    seconds of a session.
    """
    global _started
    if not _started:
        _started = True
        _pending.extend(MODULES)
    while _pending and not sys.is_finalizing():
        name = _pending.pop(0)
        try:
            importlib.import_module(name)
        except Exception as exc:
            applogger.debug("Warm-up: %s could not be imported: %s", name, exc)
