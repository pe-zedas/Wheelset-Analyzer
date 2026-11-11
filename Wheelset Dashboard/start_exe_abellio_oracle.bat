@echo off
cd /d "%~dp0"
Wheelset-Dashboard.exe --profile abellio --source oracle %*
if errorlevel 1 (
    echo.
    echo Programm wurde mit Fehler beendet. Siehe wheelset_dashboard.log.
    pause
)
