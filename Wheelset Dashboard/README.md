# Wheelset Dashboard

Desktop-Dashboard zur Visualisierung der Radsatzdaten (parallel zum Prognose-Backend `Wheelset Analyzer_new_approach`).
Es zeigt die Hierarchie Flotte › Einheit › Drehgestell › Achse mit Ampel-Status, Messverläufen und Prognose-Fälligkeiten sowie das Lager (ausgebaute Komponenten).

- Oberfläche: PySide6 (Qt 6), Diagramme mit Matplotlib
- Datenquellen: Oracle (`BO_RADSATZDATEN`, `BO_RADSATZDATEN_PROGNOSE`) oder CSV-Export
- Kundenprofile (VGF, Abellio, MOB): `wheelset_dashboard/config/profiles/*.yaml`

Dokumentation in [doc/](doc/): [Benutzerhandbuch](doc/Benutzerhandbuch.md), [Technische Dokumentation](doc/Technische_Doku.md),
[Anwenderhandbuch](doc/Anwenderhandbuch.md), [PRD](doc/PRD_Wheelset_Dashboard.md) und die [Changelogs](doc/).

## Setup

Am sichersten in einem eigenen virtuellen Environment (PyQt5 und PySide6 nicht mischen):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt          # oder requirements-dev.txt (mit Tests)
```

`requirements-lock.txt` nennt die zuletzt gemeinsam getesteten Versionen. `pip install -e .` installiert das Paket als Entwicklungsinstallation (die Konfiguration bleibt im Projektordner).

## Starten

```powershell
# Oracle (Zugangsdaten siehe unten)
python -m wheelset_dashboard.main --profile vgf --source oracle
python -m wheelset_dashboard.main --profile abellio --source oracle
python -m wheelset_dashboard.main --profile mob --source oracle

# CSV-Export statt Datenbank
python -m wheelset_dashboard.main --profile vgf --source csv --csv-raw "..\Wheelset Analyzer_new_approach\bo_radsatzdaten_export.csv"
```

`start_vgf_oracle.bat` startet das VGF-Profil mit Oracle. Mit `-v` loggt das Programm auf DEBUG-Stufe (inkl. Zeitangaben für Start und Laden) nach `wheelset_dashboard.log`. Das Laden läuft im Hintergrund; das Fenster erscheint sofort.

### Oracle-Zugangsdaten

`config/oracle_connect_string.txt` (nicht im Repository) enthält je Kunde eine Zeile:

```
vgf    = benutzer/passwort@host/dienst
abellio = benutzer/passwort@dsn
mob    = benutzer/passwort@dsn
```

Alternativ die Umgebungsvariable `ORACLE_CONNECT_STRING` oder der Einstellungsdialog (Extras › Einstellungen › Datenquelle › Oracle; er füllt Benutzer und DSN je Profil vor). Passwörter werden nicht geloggt.

## Als EXE packen (PyInstaller)

Zum Weitergeben an Tester ohne Python-Installation. Wichtig: **nicht** `wheelset_dashboard/main.py` direkt angeben — die Datei nutzt relative Imports (`from .config import ...`) und bricht dann mit `ImportError: attempted relative import with no known parent package` ab. PyInstaller braucht einen Startpunkt außerhalb des Pakets, dafür gibt es `run_dashboard.py` im Projektordner.

```powershell
pip install pyinstaller
pyinstaller --name Wheelset-Dashboard --onefile --windowed ^
  --add-data "wheelset_dashboard\config\profiles;wheelset_dashboard\config\profiles" ^
  --add-data "wheelset_dashboard\ui\style.qss;wheelset_dashboard\ui" ^
  --add-data "wheelset_dashboard\ui\assets;wheelset_dashboard\ui\assets" ^
  run_dashboard.py
```

Ergebnis liegt in `dist\Wheelset-Dashboard.exe`. `--onefile` baut eine einzelne Datei (entpackt sich bei jedem Start in einen Temp-Ordner — Programmstart dadurch etwas langsamer); `--onedir` (weglassen von `--onefile`) startet schneller und ist einfacher zu debuggen, liefert dafür einen ganzen Ordner statt einer Datei.

Das Betriebs-Konfigurationsverzeichnis (`config/oracle_connect_string.txt`, Logdatei) liegt dann **neben der .exe**, nicht im Temp-Ordner — es bleibt also über Neustarts hinweg erhalten (`config/app_paths.py` erkennt den PyInstaller-Betrieb und rechnet `APP_ROOT` ab `sys.executable` statt ab `__file__`). Dafür muss der Ordner `config/` (mit `oracle_connect_string.txt`) einmalig neben die `.exe` kopiert werden — er wird nicht mitgebaut, weil er Zugangsdaten enthält:

```powershell
xcopy /E /I config dist\config
```

Zwei Dinge, die beim reinen Doppelklick auf die `.exe` überraschen können:
- **Datenquelle:** Ohne Parameter startet die EXE wie die Entwicklungsversion mit `--source csv` (sucht dann CSV-Dateien relativ zum Arbeitsverzeichnis, die beim Tester nicht existieren — „Fehler beim Laden: No such file or directory"). Für Oracle muss `--profile <vgf|abellio|mob> --source oracle` mitgegeben werden. Die vorhandenen Start-Batches `start_exe_vgf_oracle.bat` / `start_exe_abellio_oracle.bat` / `start_exe_mob_oracle.bat` übernehmen das — mit in `dist/` kopieren (sie rufen `Wheelset-Dashboard.exe` im selben Ordner auf) und darüber starten statt über die `.exe` direkt.
- Die Datenquelle lässt sich alternativ auch nachträglich im Einstellungsdialog (Extras › Einstellungen › Datenquelle) auf Oracle umstellen; „OK" lädt dann sofort neu.

Eine komplett unlesbare/unveränderbare `.exe` liefert PyInstaller nicht (der Python-Bytecode lässt sich mit Aufwand zurückgewinnen) — für Tester, die den Code nicht versehentlich einsehen oder anpassen sollen, reicht es aber.

## Tests

```powershell
python -m pytest            # Konfiguration in pytest.ini; Qt läuft ohne Bildschirm
```

Die Tests brauchen keine Datenbank: Ein Smoke-Test lädt je Profil synthetische Daten, öffnet das Fenster und jede Ebene bis zum Diagramm (siehe `tests/synth.py`).

Entwickler-Hilfsprogramme (Projektordner als Arbeitsverzeichnis):

```powershell
python -m tools.smoketest --profile vgf --csv-raw "..\Wheelset Analyzer_new_approach\bo_radsatzdaten_export.csv"   # Datenschicht auf der Konsole
python -m tools.oracle_e2e --profile mob                                                                         # Ende-zu-Ende gegen die Oracle-DB
python -m pyflakes wheelset_dashboard tests tools                                                                 # statische Prüfung
```

## Aufbau

```
run_dashboard.py   Startpunkt fuer PyInstaller/EXE (siehe "Als EXE packen"); normaler Betrieb startet
                    weiter ueber `python -m wheelset_dashboard.main`
wheelset_dashboard/
  config/   Pfade, Logging, Kundenprofile (YAML)
  data/     models, profile, parsing, structure (Aufbau der Hierarchie), prognose_source,
            csv_source, oracle_source, repository
  logic/    status, lager_state, aggregation (Kennzahlen für die Ansichten), export, backend_runner, prognose
  ui/       main_window, jobs (Hintergrund-Aufgaben), views/ (Flotte, Einheit, Drehgestell, Achse, Lager),
            plot_widget, time_axis (Zeitachse mit Sprung), overview_widgets, settings_dialog
  perf.py   Zeitmesser für die DEBUG-Logs
tests/      pytest        tools/   Entwickler-Hilfsprogramme        doc/   Dokumentation
```

`logic` und `data` kennen kein Qt. Neue Kunden: YAML in `config/profiles/` anlegen (siehe Technische Dokumentation).
