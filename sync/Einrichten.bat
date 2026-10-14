@echo off
rem Journey Forever: one-time setup of the cloud sync (addon updates and friends' data). Lives in the cloud folder's tools folder.
title Journey Forever Sync einrichten
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ForeverSync.ps1" -Setup
if errorlevel 1 (
  echo.
  echo Einrichtung fehlgeschlagen. Bitte ein Foto dieses Fensters an Leon schicken.
)
pause
