@echo off
rem Developer start (desktop\.venv). Without that venv (a friend's copy) hand over to the friend launcher,
rem which sets up %LOCALAPPDATA%\ForeverChronicle\venv and starts the app.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m forever_chronicle
  exit /b 0
)
if exist "%LOCALAPPDATA%\ForeverChronicle\venv\Scripts\pythonw.exe" (
  start "" "%LOCALAPPDATA%\ForeverChronicle\venv\Scripts\pythonw.exe" -m forever_chronicle
  exit /b 0
)
if exist "..\Journey Forever starten.bat" (
  call "..\Journey Forever starten.bat"
  exit /b
)
echo Python-Umgebung nicht gefunden. Bitte "Journey Forever starten.bat" im Hauptordner starten.
pause
exit /b 1
