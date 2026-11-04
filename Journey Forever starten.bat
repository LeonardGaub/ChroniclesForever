@echo off
rem Journey Forever: one double-click from the unzipped folder to the running app.
rem   1. Python 3.11 or newer: found, or installed for this user (winget, else the python.org installer).
rem   2. Python environment with Qt in %LOCALAPPDATA%\ForeverChronicle\venv (first start only, a few minutes).
rem   3. Copies the app and the addon to %LOCALAPPDATA%\ForeverChronicle\app, so the unzipped folder can be
rem      deleted afterwards. A newer zip: unzip it and double-click this file again.
rem   4. Installs the addon in WoW Forever, asks once whether to put a "Journey Forever" shortcut on the desktop
rem      and in the start menu, starts the app. The app updates the addon itself.
rem Built into the friends' zip by tools\package_for_friends.py.
setlocal EnableExtensions
cd /d "%~dp0"
title Journey Forever
rem Short, fixed places: independent of where the zip was unpacked and well below the Windows path length limit.
set "BASE=%LOCALAPPDATA%\ForeverChronicle"
set "VENV=%BASE%\venv"
set "VPY=%VENV%\Scripts\python.exe"
set "APP=%BASE%\app"

rem Started from inside the zip (Explorer unpacks only this file into a temporary folder).
if not exist "%~dp0addons\ForeverChronicle\ForeverChronicle.toc" goto :notunzipped
if not exist "%~dp0desktop\forever_chronicle\__main__.py" goto :notunzipped

echo.
echo  ==================================================
echo    Journey Forever wird eingerichtet ...
echo  ==================================================
echo.

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
if exist "%VENV%\.ready_sound" goto :copyapp
echo Programmteil fuer Ton und Musik wird installiert (einmalig, ca. 40 MB) ...
"%VPY%" -c "import importlib.util as u, subprocess, sys, PySide6; sys.exit(0 if u.find_spec('PySide6.QtMultimedia') else subprocess.call([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', 'PySide6-Addons==' + PySide6.__version__]))"
if not errorlevel 1 echo ok> "%VENV%\.ready_sound"

:copyapp
echo Programm wird installiert: %APP%
rem /MIR: stale files of an older version go; robocopy exit codes below 8 mean success.
robocopy "%~dp0addons\ForeverChronicle" "%APP%\addons\ForeverChronicle" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copyfail
robocopy "%~dp0desktop\forever_chronicle" "%APP%\desktop\forever_chronicle" /MIR /XD __pycache__ /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :copyfail

rem FC_SETUP_ONLY=1: Python, packages and the app copy only; leaves the game, the desktop and the app alone (tests).
if defined FC_SETUP_ONLY exit /b 0

:addon
echo.
pushd "%APP%\desktop"
"%VPY%" -m forever_chronicle.setup_addon "%APP%\addons\ForeverChronicle"
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" goto :fail

:shortcut
rem Desktop and start menu ("Journey Forever" in the Windows search), only if the player agrees. Asked once: the
rem answer is remembered in %BASE% (.shortcut / .no_shortcut). The paths never change, so a shortcut made once
rem stays right for later versions. Paths come in through the environment: no quoting trouble with the user name.
if exist "%BASE%\.shortcut" goto :start
if exist "%BASE%\.no_shortcut" goto :start
echo.
choice /c JN /m "Verknuepfung Journey Forever auf dem Desktop und im Startmenue anlegen?"
if errorlevel 2 (
  echo no> "%BASE%\.no_shortcut"
  goto :start
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$sh = New-Object -ComObject WScript.Shell; foreach ($dir in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) { $s = $sh.CreateShortcut((Join-Path $dir 'Journey Forever.lnk')); $s.TargetPath = Join-Path $env:VENV 'Scripts\pythonw.exe'; $s.Arguments = '-m forever_chronicle'; $s.WorkingDirectory = Join-Path $env:APP 'desktop'; $s.IconLocation = Join-Path $env:APP 'desktop\forever_chronicle\app.ico'; $s.Description = 'Journey Forever'; $s.Save() }" >nul 2>&1
if errorlevel 1 goto :shortcutfail
echo ok> "%BASE%\.shortcut"
echo Verknuepfung "Journey Forever" liegt auf dem Desktop und im Startmenue.
goto :start
:shortcutfail
echo Hinweis: Die Verknuepfung konnte nicht angelegt werden. Starten geht auch ueber diese Datei.

:start
echo.
echo Desktop-App wird gestartet ...
pushd "%APP%\desktop"
start "" "%VENV%\Scripts\pythonw.exe" -m forever_chronicle
popd
echo.
if exist "%BASE%\.shortcut" (
  echo  Fertig! Ab jetzt die App ueber die Verknuepfung "Journey Forever" starten.
  echo  Den entpackten Ordner brauchst du nicht mehr.
) else (
  echo  Fertig! Starten kannst du die App jederzeit wieder ueber diese Datei.
  echo  Den entpackten Ordner deshalb bitte behalten.
)
timeout /t 10 >nul
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
echo.
echo Python 3.12 wird benoetigt und ist nicht installiert.
choice /c JN /m "Jetzt fuer diesen Benutzer installieren (ohne Adminrechte)?"
if errorlevel 2 exit /b 0
where winget >nul 2>&1
if not errorlevel 1 (
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  call :findpython
)
if defined PY exit /b 0
rem No winget (older Windows 10) or it failed: the official installer, per user, without questions.
set "PYSETUP=%TEMP%\python-3.12.10-amd64.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
echo Python wird von python.org heruntergeladen (ca. 25 MB) ...
curl -L --fail --silent --show-error -o "%PYSETUP%" "%PYURL%"
if errorlevel 1 powershell -NoProfile -Command "Invoke-WebRequest -UseBasicParsing -Uri $env:PYURL -OutFile $env:PYSETUP"
if not exist "%PYSETUP%" exit /b 0
echo Python wird installiert (ca. 1 Minute) ...
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del "%PYSETUP%" >nul 2>&1
call :findpython
exit /b 0

:nopython
echo.
echo Python 3.11 oder neuer wurde nicht gefunden.
echo Bitte von https://www.python.org/downloads/ installieren (Haken bei "Add python.exe to PATH")
echo und diese Datei danach erneut starten.
pause
exit /b 1

:notunzipped
echo.
echo Bitte die ZIP-Datei zuerst entpacken:
echo   Rechtsklick auf die ZIP-Datei, "Alle extrahieren...", dann im entpackten Ordner
echo   "Journey Forever starten.bat" doppelklicken.
echo.
pause
exit /b 1

:copyfail
echo.
echo Das Programm konnte nicht nach %APP% kopiert werden.
echo Laeuft die Desktop-App noch? Bitte schliessen und diese Datei erneut starten.
goto :fail

:fail
echo.
echo Etwas ist schiefgegangen (siehe oben). Bitte ein Foto/Screenshot dieses Fensters an Leon schicken.
pause
exit /b 1
