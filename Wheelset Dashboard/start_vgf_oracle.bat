@echo off
REM Wheelset Dashboard — Start mit VGF-Profil und Oracle-Datenquelle.
REM Connect-String wird aus ..\Wheelset Analyzer_new_approach\oracle_connect_string.txt gelesen
REM (oder aus der Umgebungsvariable ORACLE_CONNECT_STRING).

cd /d "%~dp0"
python -m wheelset_dashboard.main --profile vgf --source oracle %*

if errorlevel 1 (
    echo.
    echo Programm wurde mit Fehler beendet. Siehe wheelset_dashboard.log.
    pause
)
