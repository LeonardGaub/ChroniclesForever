@echo off
rem Journey Forever: installs/updates the addon in WoW Forever and starts the desktop app.
rem First start: sets up Python and the app (a few minutes). Later starts take a few seconds.
setlocal EnableExtensions
cd /d "%~dp0"
title Journey Forever
rem Python environment in a short, fixed place: independent of where this folder was unzipped and well
rem below the Windows path length limit; a newer version of this folder reuses it.
set "VENV=%LOCALAPPDATA%\ForeverChronicle\venv"
set "VPY=%VENV%\Scripts\python.exe"

if exist "%VPY%" goto :deps

echo Ersteinrichtung: Python-Umgebung fuer Journey Forever wird angelegt ...
call :findpython
if not defined PY call :installpython
if not defined PY goto :nopython
"%PY%" -m venv "%VENV%"
if errorlevel 1 goto :fail

:deps
if exist "%VENV%\.ready2" goto :sound
if exist "%VENV%\.ready" goto :extras
echo Programmteile werden installiert (Qt fuer Python, einmalig, ca. 100 MB) ...
"%VPY%" -m pip install --disable-pip-version-check --quiet "PySide6-Essentials>=6.6"
if errorlevel 1 goto :fail
echo ok> "%VENV%\.ready"

:extras
rem numpy and Pillow read the event icons from the game (desktop/pyproject.toml). Optional: if the download
rem fails, the app starts anyway with symbols instead, and the next start tries again.
echo Programmteile fuer die Spiel-Icons werden installiert (einmalig, ca. 30 MB) ...
"%VPY%" -m pip install --disable-pip-version-check --quiet "numpy>=1.26" "pillow>=10"
if not errorlevel 1 echo ok> "%VENV%\.ready2"

:sound
rem Qt Multimedia (PySide6-Addons, of exactly the installed PySide6 version) plays the sounds and the music.
rem Optional like the icons: without it the app runs silent and offers the same download (ui/audio_setup.py).
if exist "%VENV%\.ready_sound" goto :addon
echo Programmteil fuer Ton und Musik wird installiert (einmalig, ca. 40 MB) ...
"%VPY%" -c "import importlib.util as u, subprocess, sys, PySide6; sys.exit(0 if u.find_spec('PySide6.QtMultimedia') else subprocess.call([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', 'PySide6-Addons==' + PySide6.__version__]))"
if not errorlevel 1 echo ok> "%VENV%\.ready_sound"

:addon
echo.
pushd "%~dp0desktop"
"%VPY%" -m forever_chronicle.setup_addon "%~dp0addons\ForeverChronicle"
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" goto :fail

rem FC_SETUP_ONLY=1: set up and install the addon, but do not start the app (used for testing).
if defined FC_SETUP_ONLY exit /b 0
echo Desktop-App wird gestartet ...
pushd "%~dp0desktop"
start "" "%VENV%\Scripts\pythonw.exe" -m forever_chronicle
popd
timeout /t 3 >nul
exit /b 0

rem ---------------------------------------------------------------------------------------------
:findpython
rem Python 3.11 or newer: py launcher, python on PATH, or the default per-user install folder.
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)"') do set "PY=%%P"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "PY=%%P"
)
for %%V in (313 312 311) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)
exit /b 0

:installpython
where winget >nul 2>&1
if errorlevel 1 exit /b 0
echo.
echo Python 3.12 wird benoetigt und ist nicht installiert.
choice /c JN /m "Jetzt fuer diesen Benutzer installieren (winget, ohne Adminrechte)?"
if errorlevel 2 exit /b 0
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :findpython
exit /b 0

:nopython
echo.
echo Python 3.11 oder neuer wurde nicht gefunden.
echo Bitte von https://www.python.org/downloads/ installieren (Haken bei "Add python.exe to PATH")
echo und diese Datei danach erneut starten.
pause
exit /b 1

:fail
echo.
echo Etwas ist schiefgegangen (siehe oben). Bitte ein Foto/Screenshot dieses Fensters an Leon schicken.
pause
exit /b 1
