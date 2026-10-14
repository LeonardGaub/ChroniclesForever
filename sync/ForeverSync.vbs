Option Explicit
' Journey Forever Sync: starts ForeverSync.ps1 in the background without a window (Startup folder).
Dim shell, folder
Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & folder & "\ForeverSync.ps1"" -Loop", 0, False
