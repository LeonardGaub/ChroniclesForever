@echo off
rem Journey Forever: syncs once with the friends' cloud folder (upload my data, fetch friends' data). Same as "Jetzt abgleichen" (F5) in the desktop app.
title Journey Forever abgleichen
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ForeverSync.ps1" -Once
powershell.exe -NoProfile -Command "Get-Content -Tail 8 -Encoding UTF8 (Join-Path $env:LOCALAPPDATA 'ForeverChronicle\sync\sync.log')"
echo.
echo Fertig. Neue Freunde-Daten siehst du im Spiel nach /reload.
pause
