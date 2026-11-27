@echo off
rem ChartLibre Developer launcher (dev/tools/make_launcher.py), in dev\launchers.
cd /d "%~dp0..\.."
if exist ".python\pythonw.exe" (
  start "" ".python\pythonw.exe" "dev\ChartLibreDeveloper.py" %*
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "dev\ChartLibreDeveloper.py" %*
  exit /b 0
)
echo ChartLibre Developer uses the Python that ChartLibre installs in its folder.
echo Open ChartLibre once (ChartLibre.bat), then open ChartLibre Developer again.
pause
