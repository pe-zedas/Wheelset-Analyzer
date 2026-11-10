@echo off
REM Wheelset Dashboard — Start mit VGF-Profil und Oracle-Datenquelle.
REM Connect-String: config\oracle_connect_string.txt (Zeile 'vgf = user/pw@dsn')
REM oder Umgebungsvariable ORACLE_CONNECT_STRING.

cd /d "%~dp0"
python -m wheelset_dashboard.main --profile vgf --source oracle %*

if errorlevel 1 (
    echo.
    echo Programm wurde mit Fehler beendet. Siehe wheelset_dashboard.log.
    pause
)
