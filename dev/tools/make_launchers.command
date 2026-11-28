#!/bin/bash
# macOS: rebuild every launcher - ChartLibre.app/.exe/.bat/.sh in the project folder, ChartLibre Developer's in dev/
# (double-click in Finder, or run in a terminal). The .app needs clang (xcode-select --install), the .exe zig.
cd "$(dirname "$0")/../.." || exit 1
PY=python3
[ -x .venv/bin/python3 ] && PY=.venv/bin/python3
[ -x .python/bin/python3 ] && PY=.python/bin/python3
"$PY" dev/tools/make_launcher.py "$@"
status=$?
[ -t 0 ] && read -r -p "Done (exit $status). Press Return to close. "
exit $status
