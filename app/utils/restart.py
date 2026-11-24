"""Start the application again: what Preferences asks for when a change shows only at the next start."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def restart() -> None:
    """Quit, and start the same command again once this process has let go of its files (the database)."""
    app = QApplication.instance()
    if app is None:
        return
    # The script by its full path: a relative one means nothing once the application has changed folder.
    main = getattr(sys.modules.get("__main__"), "__file__", None) or sys.argv[0]
    command = [sys.executable, str(Path(main).resolve()), *sys.argv[1:]]

    def relaunch() -> None:
        try:
            subprocess.Popen(command, close_fds=True, start_new_session=True)
        except OSError:
            pass

    # aboutToQuit only fires when the application really quits: a window that cancels its close cancels this too.
    app.aboutToQuit.connect(relaunch)
    app.closeAllWindows()
    app.quit()
