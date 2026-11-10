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
wheelset_dashboard/
  config/   Pfade, Logging, Kundenprofile (YAML)
  data/     models, profile, parsing, structure (Aufbau der Hierarchie), prognose_source,
            csv_source, oracle_source, repository
  logic/    status, lager_state, aggregation (Kennzahlen für die Ansichten), export, backend_runner, prognose
  ui/       main_window, jobs (Hintergrund-Aufgaben), views/ (Flotte, Einheit, Drehgestell, Achse, Lager),
            plot_widget, overview_widgets, settings_dialog
  perf.py   Zeitmesser für die DEBUG-Logs
tests/      pytest        tools/   Entwickler-Hilfsprogramme        doc/   Dokumentation
```

`logic` und `data` kennen kein Qt. Neue Kunden: YAML in `config/profiles/` anlegen (siehe Technische Dokumentation).
