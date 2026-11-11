@echo off
REM Wheelset-Dashboard.exe -- Start mit VGF-Profil und Oracle-Datenquelle.
REM Erwartet die EXE im selben Ordner wie dieses Skript (z.B. dist\).
REM Connect-String: config\oracle_connect_string.txt (Zeile 'vgf = user/pw@dsn'),
REM dieser Ordner "config" muss neben der .exe liegen.

cd /d "%~dp0"
Wheelset-Dashboard.exe --profile vgf --source oracle %*

if errorlevel 1 (
    echo.
    echo Programm wurde mit Fehler beendet. Siehe wheelset_dashboard.log.
    pause
)
