@echo off
rem Windows: rebuild every launcher - ChartLibre.exe/.bat/.app/.sh in the project folder, the Developer launchers in dev\
rem (double-click, or run in a terminal). The .exe needs zig (ZIG=path or on the PATH); the .app is built for real only on a Mac.
cd /d "%~dp0\..\.."
set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe
if exist .python\python.exe set PY=.python\python.exe
"%PY%" dev\tools\make_launcher.py %*
pause
