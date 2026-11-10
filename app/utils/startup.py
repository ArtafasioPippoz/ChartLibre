"""What has to be decided before the main window can be built.

One question: which database is this run about?  Three answers, in order -
the one named on the command line, the one the last run left behind if it is
still there, or a new empty one in the home directory.

No question is asked for any of them.  A first run used to offer to build the
demo projects and, when that was declined, fall back to an open dialog: two
boxes in front of someone who has not seen the application yet, the second of
which can only open a file they do not have.  Starting on an empty project is
the answer that needs no explaining, and the demo set is still one menu item
away once the window is up (File, Load demo).

It lives here rather than in ``ChartLibre.py`` because the remaining fallback shows
a box, and every box in this application comes from the catalogue in
config.json (see ``app/utils/messages.py``).  A message id used only from the
root script would sit outside the sweep that proves every id is defined and
every defined id is used.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

from app import APP_NAME
from app.data.sqlite_repo import DatabaseError, SqliteRepo
from app.logs.logger import applogger
from app.utils.config import get_last_database, remember_untitled_database
from app.utils.i18n import _
from app.utils.messages import show_message

#: What a run with nothing remembered opens: a new, empty project, as macOS
#: and Windows applications start on a new untitled document.  In the home
#: directory, the one place every desktop platform agrees the user can write
#: to; "Untitled.dhub", then "Untitled 2.dhub" and on, never an existing file -
#: Save as names it later.  The name is translated (a literal in
#: _new_database_path, so the catalogue sweep finds it).

#: The project file's own filter line, for the New/Open/Save-as dialogs in
#: the main window.  One definition rather than four: it was written out by
#: hand in three more places, all of them still saying "Data Hub DB" after
#: the rename, which is exactly the drift a shared constant prevents.
PROJECT_FILE_FILTER: str = f"{APP_NAME} DB (*.dhub)"

#: The open dialog's filter.  ``.dhub`` first so the file the user is looking
#: for is the one they see.
DATABASE_FILTER: str = f"{PROJECT_FILE_FILTER};;All files (*.*)"


def select_database(
    argument: str | None = None,
    *,
    parent: QWidget | None = None,
) -> Path | None:
    """Return the database this run should open, or None to exit.

    The order is deliberate: an explicit argument beats a remembered path,
    and a remembered path beats both - because the common case is opening the
    app on yesterday's work, and a dialog in front of that every morning is a
    dialog nobody reads.

    None is returned only when there is nowhere to write and the user then
    cancels the open dialog, which is the one case where the application
    genuinely has no database to be about.
    """
    if argument and argument.strip():
        return Path(argument).expanduser().resolve()

    remembered = _remembered_database()
    if remembered is not None:
        return remembered

    # Nothing remembered: a first run, user.json was reset, or the last project is gone.
    return _default_database(parent)


def _remembered_database() -> Path | None:
    """Return the database the last run left behind, or None when there is none or it is gone.

    A project that was moved, renamed or deleted counts as nothing remembered: the run starts as a first
    run does, on a new database, as macOS and Windows applications start on a new document. No empty
    file is made under the lost project's name.
    """
    last_database = get_last_database()  # None for a file that no longer exists
    if not last_database:
        return None
    return Path(last_database).expanduser().resolve()


def _default_database(parent: QWidget | None) -> Path | None:
    """Return a new, empty database in the home directory.

    Nothing is asked, which is the whole point: the alternative was offering
    to build the demo set and then, on "no", an open dialog with nothing in it
    to open.  An empty project is a legitimate way to start, and the demo is
    still reachable from File, Load demo once the window is up.

    Always a file of its own, never one already there: a run that finds
    nothing to reopen starts on a blank project, not on whatever an earlier
    first run left in the home directory - that is in Open recent.

    The open dialog survives as the fallback for the one case that cannot be
    solved by writing a file: a home directory that is not writable.
    """
    path = _new_database_path()
    applogger.info("No database remembered; starting on a new one, %s", path)
    try:
        created = SqliteRepo.create_empty(path)
    except (OSError, DatabaseError, ValueError) as exc:
        # Read-only home, a full disk, or that name taken by a folder.
        applogger.exception("Could not create a database at %s: %s", path, exc)
        show_message(parent, "startup.default_database_failed", error=exc)
        return _ask_for_a_database(parent)
    # Untitled until it is named: the window asks for a name when it closes (or throws it away if empty).
    remember_untitled_database(created)
    return created


def _new_database_path(folder: Path | None = None) -> Path:
    """The first free "Untitled" name in *folder* (the home directory): Untitled.dhub, Untitled 2.dhub..."""
    folder = folder or Path.home()
    stem = _("Untitled")
    candidate = folder / f"{stem}.dhub"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem} {number}.dhub"
        number += 1
    return candidate


def _ask_for_a_database(parent: QWidget | None) -> Path | None:
    """Return a database chosen in the open dialog, or None if cancelled."""
    file_path, _unused = QFileDialog.getOpenFileName(
        parent,
        _("Open database"),
        str(Path.home()),
        DATABASE_FILTER,
    )
    if not file_path:
        return None
    return Path(file_path).expanduser().resolve()
