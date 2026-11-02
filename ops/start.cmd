@echo off
rem Double-clickable launcher: runs start.ps1 even when the PowerShell execution policy blocks scripts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
