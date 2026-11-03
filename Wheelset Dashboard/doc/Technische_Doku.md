# Wheelset Dashboard — Technische Dokumentation

Stand: 2026-10-28 · Version 1.1 (RC)

## 1. Architekturübersicht

Strikte 3-Schichten-Trennung:

```
UI (PySide6, Matplotlib)
  └── wheelset_dashboard/ui/
Logic (reine Python-Funktionen, GUI-frei)
  └── wheelset_dashboard/logic/
Data (Repository-Fassade über CSV und Oracle)
  └── wheelset_dashboard/data/
Config (Profile, Logging)
  └── wheelset_dashboard/config/
```

Logic und Data haben keine Qt-Abhängigkeit und sind unit-testbar.

## 2. Verzeichnisstruktur

```
Wheelset Dashboard/
├── wheelset_dashboard/
│   ├── main.py                 # Einstiegspunkt
│   ├── smoketest.py            # Konsolen-Smoke-Test der Datenschicht
│   ├── config/
│   │   ├── logging_setup.py    # Rotierendes File-Logging + Exception-Hook
│   │   └── profiles/*.yaml     # Kundenprofile (vgf, abellio, mob)
│   ├── data/
│   │   ├── models.py           # Dataclasses Flotte/Einheit/DG/Achse/Rad/Messreihe
│   │   ├── profile.py          # YAML-Profil-Loader + ZARTBEZ-Klassifikation
│   │   ├── csv_source.py       # CSV-Loader (Profil-gesteuert)
│   │   ├── oracle_source.py    # Oracle-Loader + Testverbindung
│   │   └── repository.py       # Fassade (einheitlicher Zugriff)
│   ├── logic/
│   │   ├── status.py           # Ampel aus Ist + Prognose (schlechter gewinnt)
│   │   ├── lager_state.py      # STORED_READY vs. STORED_TO_OVERHAUL
│   │   └── export.py           # Werkstattliste.xlsx + Rohdaten.csv
│   └── ui/
│       ├── main_window.py      # QMainWindow + Side-Nav + Breadcrumb + Menü
│       ├── settings_dialog.py  # Settings-Dialog + Testverbindung
│       ├── widgets.py          # AmpelDot, StatusPill, KpiCard
│       ├── views.py            # L1-L3-Views + L4 AchseView mit Reitern
│       ├── overview_widgets.py # DonutCanvas + GanttCanvas
│       ├── plot_widget.py      # PlotCanvas für Detail-Plots
│       └── style.qss           # Light-Theme-Stylesheet
├── tests/                       # pytest Unit-Tests (status, lager_state)
├── doc/                         # PRD, Benutzerhandbuch, diese Datei, Freigabe-Checkliste
├── requirements.txt
└── README.md
```

## 3. Datenmodell (Kern)

Siehe `wheelset_dashboard/data/models.py`:

- **Flotte** → Einheiten + Lager-Komponenten
- **Einheit** → Drehgestelle (Dict nach Einbauposition)
- **Drehgestell** → Achsen **und/oder** `direkt_messreihen` (für Kundenprofile ohne Radsatz-Ebene)
- **Achse** → Räder (`left`/`right`/`unspecified`)
- **Rad** → `Dict[messgroesse → Messreihe]`
- **Messreihe** → Historie (Messpunkt-Liste), optionale Prognose, berechneter Status, **`direction`** aus dem Profilkatalog (`decreasing` | `increasing` | `both`)
- **LagerKomponente** → eigener Zustand (`STORED_READY`/`STORED_TO_OVERHAUL`), `kind` (`drehgestell` | `achse`), bei Drehgestellen zusätzlich das Dict der eingebauten `achsen`, bei Einzelachsen die Räder direkt an der Komponente

**Lager-Gruppierung (CSV-Loader)**: Fachregel „Hat eine ausgebaute Achse ein DG, wurde das komplette DG ausgebaut" wird im `_add_lager` abgebildet: alle Zeilen mit identischer `(dg_id, dg_bez, ausbau_date)` werden zu einer LagerKomponente(`kind="drehgestell"`) mit ihrer Achsenliste zusammengeführt. Nur Zeilen ohne DG-Zuordnung werden zu einer `kind="achse"`-Komponente.

**Letzter Messwert**: `Messreihe.letzter_wert()` liefert den Messpunkt mit **max(datum)** — robust auch bei unsortierter CSV-Reihenfolge.

**Aggregations-Helfer** `_worst_messreihe(prev, cand)` liefert die „schlechtere" zweier Messreihen: schlechter Status schlägt besseren Status; bei Gleichstand entscheidet der numerisch schlechtere letzte Wert (Richtung aus den Schwellen bzw. aus `direction`).

Alle Status-Werte werden über `logic/status.recompute_all(flotte)` berechnet und in die Messreihen geschrieben; Entitätsstatus = `_worst_status` der untergeordneten Reihen.

### 3.1 Status-Logik (`logic/status.py`)

- `classify_messpunkt_ist(mp, direction)` wertet nur die semantisch relevante Seite der Schwellen aus:
  - `decreasing` → nur `min_val` und `gelb_min`,
  - `increasing` → nur `max_val` und `gelb_max`,
  - `both` → beide Seiten.
  Zusätzliche Validitätsprüfung: eine Warn-/Grenz-Schwelle gilt nur, wenn sie innerhalb des gültigen Bereichs liegt (`gelb_min < max_val`, `gelb_min > min_val` usw.) — schützt vor inkonsistenten CSV-Werten wie `GELB_MAX = MIN`.
- Die Prognose fließt NICHT in die Ampel ein (`classify_messreihe` nutzt ausschließlich den letzten Ist-Messwert gegen die Schwellen). Die frühere `classify_prognose`-Funktion und die zugehörigen `red_days`/`yellow_days`-Settings wurden am 2026-10-29 entfernt.
- `classify_messreihe` ruft beide und verrechnet via `_worst_status`.

## 4. Kundenprofil (YAML)

Jedes Profil beschreibt:

1. **CSV-Dialekt** (`csv.delimiter`, `encoding`, `date_format`, `decimal`).
2. **Spalten-Mapping** (`columns_raw`, `columns_prognose`) — CSV-/DB-Spalte → interner kanonischer Name.
3. **Pflichtfelder** (`required_measurement_fields.base` + `prognosis_eligible`).
4. **Hierarchie-Tiefe** (`hierarchy_depth`) — `4` = bis Radsatz, `3` = nur bis Drehgestell.
5. **Messgrößen-Katalog** (`measurement_catalog`) mit Regex-Patterns pro Seite (`left`/`right`/`unspecified`) für jede kanonische Messgröße.

Neues Profil anlegen:

```yaml
name: mykunde
csv:
  delimiter: ";"
  encoding: utf-8-sig
columns_raw:
  TOPEINHEITID: topeinheit_id
  …
measurement_catalog:
  LKD:
    patterns:
      - regex: "^Dein-LKD-Name$"
        side: unspecified
    unit: mm
    direction: decreasing
    prognosis: true
```

Datei in `wheelset_dashboard/config/profiles/mykunde.yaml` ablegen und per `--profile mykunde` bzw. Settings-Dialog wählen.

## 4a. UI-Mechanik (`ui/views.py`)

- **BaseView** stellt Tabellen-Fassade + Donut/Gantt-Overview für L1–L3 und Lager bereit. Enthält:
  - **Sortierung** aktiv (`setSortingEnabled(True)`), Status-Spalten mit Ampelpunkt-Widgets sortieren über `_AmpelSortItem` (eigene `__lt__` auf `Qt.UserRole`).
  - **Freitextfilter** `_apply_filter(text)` oberhalb der Tabelle, filtert zeilenweise über alle Textspalten; rechts wird `n/total` angezeigt.
  - **Layout-Reservierung**: Panel mit Tabelle hat Stretch 5, Donut/Gantt-Canvas haben Max-Höhen (220 px) und die Tabelle hat Mindesthöhe für ≥ 6 Zeilen.
  - **Selektions-Reaktion** `_on_selection_changed`: einfacher Zeilenklick aktualisiert Donut und Gantt auf das selektierte Objekt (Flotte→Einheit, Einheit→DG, DG→Rad); Donut-Center-Label bricht bei langen Bezeichnungen auf zwei Zeilen um.
  - **Zellenbau** `_set_ampel_cell(table, row, col, status, value)` schaltet zwischen Ampelpunkt und Ampelpunkt+Zahl um — gesteuert über den globalen Modus `SHOW_VALUES`, der von `set_show_values(flag)` aus der Statusleisten-Checkbox gesetzt wird. Zahlenformat durch `_fmt_num(v)` europäisch mit Komma.
- **LagerView** nutzt BaseView, erweitert um Typ-Spalte, Messwert-Spalten je Messgröße (via `LagerKomponente.messgroessen_data()`), und sendet beim Doppelklick das Signal `lager_drilldown(komp, achse|None)`.
- **MainWindow** verdrahtet das Lager-Drilldown zweistufig: DG-Komponente → `DrehgestellView` mit synthetischem Einheit/DG (temporäres Umschalten des DG-Drilldown-Signals über `_set_dg_drilldown_mode`); Achsen-Komponente → direkt `AchseView`. Die Flotten-Standard-Verdrahtung wird vor jedem normalen Flotte-DG-Pfad wiederhergestellt.

## 5. Erweiterung: neue Messgröße

1. Katalog-Eintrag im Profil ergänzen (`measurement_catalog`).
2. `ui/views.MGROESSEN_SPALTEN` + `MGROESSEN_LABEL` erweitern (für die Status-Matrix in L1–L3).
3. Keine weitere Code-Änderung nötig — Detailansicht erzeugt den Reiter automatisch.

## 6. Oracle-Anbindung

- Treiber: `python-oracledb` ≥ 2.0 (Thick-Mode für Verbindungen gegen ältere Oracle-Server).
- `oracle_source.load_flotte_from_oracle(dsn, user, password, profile, thick_mode_lib_dir)` liest `BO_RADSATZDATEN` und erzeugt dieselbe Flotten-Struktur wie der CSV-Loader.
- `oracle_source.test_connection()` prüft Verbindung + Zugriff auf `BO_RADSATZDATEN`.
- Credentials werden lokal via `keyring` abgelegt (geplant für finale Release — aktuell im Klartext im Settings-Dialog).

## 7. Logging

`config/logging_setup.setup_logging()` konfiguriert:

- **RotatingFileHandler** `wheelset_dashboard.log`, 10 MB, 5 Backups, UTF-8.
- **StreamHandler** auf stderr für Dev-Betrieb.
- **install_global_exception_handler** zeigt ungefangene Exceptions als QMessageBox + loggt mit Traceback.

## 8. Tests

```powershell
python -m pytest tests/ -q
```

Smoke-Test der Datenschicht (nur Konsole):

```powershell
python -m wheelset_dashboard.smoketest --profile vgf \
    --csv-raw "..\Wheelset Analyzer_new_approach\bo_radsatzdaten_export.csv"
```

## 9. Build und Release

- Keine kompilierte Distribution geplant — Paket läuft aus dem Repo.
- Für Einzelplatz-Rollout optional PyInstaller/briefcase (nicht Teil dieser Release).

## 10. Abhängigkeiten

Siehe `requirements.txt`:

| Paket | Zweck |
|-------|-------|
| PySide6 | Qt 6 GUI |
| matplotlib | Charts (Donut, Gantt, Detail-Plot) |
| oracledb | Oracle-Treiber |
| openpyxl | Werkstattlisten-Export |
| PyYAML | Kundenprofile |
| keyring | Passwort-Speicherung (geplant) |
| qtawesome | Icon-Font (Material/Tabler) |
