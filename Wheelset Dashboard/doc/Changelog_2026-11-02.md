# Änderungen vom 2026-11-02

Dokumentiert die Dashboard-Anpassungen dieses Arbeitstages. Aufgeführt sind
nur **bleibende** Änderungen (frühere Zwischenstände, die wieder revidiert
wurden, sind weggelassen).

Alle Pfade sind relativ zu
`C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard\wheelset_dashboard\`.


## 1. Fälligkeiten-Gantt — pro Achse das kritische Rad

Datei: `ui/views.py` (`_collect_gantt_entries`), `ui/overview_widgets.py`
(`set_entries`).

### Was sich geändert hat

- **Pro Achse wird nur das kritische Rad in das Diagramm eingetragen.**
  Das andere Rad erscheint nicht mehr. Kritisch = Rad mit der frühesten
  Grenzwert-Unterschreitung. Erreicht kein Rad das MIN, zählt das Rad mit
  der frühesten Warnung; erreicht keines die Warnschwelle, wird das erste
  Rad mit auswertbarer Prognose genommen.
- **Reprofilierungen des kritischen Rades werden nur bis zur ersten
  Grenzwert-Unterschreitung angezeigt.** Nach dem MIN sind weitere
  Reprofilierungen fachlich nicht mehr sinnvoll.
- **Rückgabeformat des Helpers** jetzt
  `(label, reprofs, warns, grenze)` mit Listen aus
  `(datum, achsen_label)`-Tupeln. Die Labels enthalten den Rad-Pfad
  (`dg · achse · Rad links/rechts`) und erscheinen im Hover-Tooltip.
- **`set_entries` akzeptiert weiterhin die alten 3er- und 4er-Formate**
  (Rückwärtskompatibilität).
- Neuer Helper `_as_date_list` in `ui/overview_widgets.py`; `_extract_latest_grenz`
  liest nun die ganze Liste.

### Warum

Beide Räder einer Achse zu zeigen wurde unübersichtlich (16 Marker für
eine Einheit), und die Information „zweites Rad ist etwas später kritisch"
hilft bei der Fälligkeitsplanung nicht. Entscheidend ist das zuerst
auffällige Rad.


## 2. Fälligkeiten-Gantt — Umschalten erst beim Doppelklick

Datei: `ui/views.py` (`FlotteView._on_selection_changed`,
`EinheitView._on_selection_changed`, `DrehgestellView._on_selection_changed`).

### Was sich geändert hat

- Die Selektion einer Tabellenzeile aktualisiert nur noch den **Donut**.
- Das **Fälligkeiten-Panel wechselt nicht mehr auf die untergeordnete
  Ebene**, wenn der Nutzer eine Zeile einfach anklickt.
- Erst der **Doppelklick** emittiert `drilldown`, das Hauptfenster
  wechselt in die nächsttiefere View, und erst dort zeigt der Gantt die
  Ebene darunter (Einheit → DGs, DG → Achsen).

### Warum

Vorher sprang der Gantt bei jeder Zeilenauswahl auf eine andere Ebene;
das war verwirrend, weil die Tabelle unverändert blieb. Der Doppelklick
ist der etablierte Drilldown-Trigger — der Gantt folgt ihm jetzt.


## 3. Fälligkeiten-Gantt — Panel-Titel und Jahr auf der X-Achse

Datei: `ui/views.py`, `ui/overview_widgets.py`.

### Was sich geändert hat

- **Panel-Titel überall `Prognose Fälligkeiten LKD : <Kontext>`:**
  - FlotteView: `Prognose Fälligkeiten LKD : Flotte`
  - EinheitView: `Prognose Fälligkeiten LKD : Einheit <topeinheit_bez>`
  - DrehgestellView:
    `Prognose Fälligkeiten LKD : <topeinheit_bez> · <dg_einbaupos>`
- **X-Achse zeigt die Jahreszahl.** Ein `FuncFormatter` schreibt den
  Monatsnamen in eine Zeile und bei Januar sowie am linken Rand das Jahr
  darunter (`Dec\n2026`, `Jan\n2027`, `Feb`, `Mar`, …).

### Warum

Der Panel-Titel macht die Messgröße (LKD) und die Ebene explizit; die
Jahreszahl verhindert, dass Marker im Januar eines späteren Jahres mit
denen des aktuellen Januars verwechselt werden.


## 4. KPI-Kacheln über den Tabellen entfernt

Datei: `ui/views.py` (`FlotteView.set_flotte`, `LagerView.set_flotte`).

### Was sich geändert hat

- Entfernt in der **Flotten-Übersicht:** `Einheiten`, `Achsen überwacht`,
  `Warn`, `Grenz`.
- Entfernt in der **Lager-Übersicht:** `Lager gesamt`, `Drehgestelle`,
  `Einsatzbereit`, `Zu überholen`.
- Die KPI-Zeile selbst (`_kpi_row`) wird in diesen beiden Views beim
  Aufbau geleert und nicht neu befüllt.

### Warum

Die Zahlen stehen ebenso in Donut + Tabelle; die Kachelreihe war
redundant und nahm vertikalen Platz weg. Die KPI-Kacheln in `EinheitView`,
`DrehgestellView` und `AchseView` bleiben erhalten — sie dienen dort
der Navigation (Breadcrumb-Ersatz).


## 5. Settings-Dialog als Baumnavigation (QGIS-Stil)

Datei: `ui/settings_dialog.py` (vollständig neu geschrieben).

### Was sich geändert hat

Statt einer langen Formularliste jetzt links ein `QTreeWidget` mit
hierarchisch gruppierten Abschnitten, rechts ein `QStackedWidget` mit
jeweils einer kompakten Formular-Seite:

```
Allgemein                          # Kundenprofil, Auto-Refresh
Datenquelle                        # Umschalter csv / oracle
  ├── CSV                          # csv_raw, csv_prognose
  └── Oracle                       # DSN, User, Passwort, DB-Testverbindung
Prognose
  └── LKD
      ├── Reprofilierungs-Erkennung    # p_auto, p_min_jump
      ├── Standard-Werte               # p_delta, p_interval
      └── Darstellung                  # p_show_steps, p_show_ci, p_ci_level
```

- Jede Seite hat eine kurze einführende Erklärung (`color: #6B6F78`),
  die den Zweck der Felder beschreibt.
- Der Dialog-Header zeigt den **aktiven Pfad** (`Datenquelle · CSV`,
  `Prognose · LKD · Standard-Werte`), damit die Orientierung auch bei
  tiefen Pfaden klar bleibt.
- **`get_config()` liefert dasselbe Dictionary wie vorher** (15 Keys,
  identische Namen) — das Hauptfenster brauchte keine Anpassung.
- Die DB-Testverbindung sitzt direkt auf der Oracle-Seite.

### Warum

Der alte Dialog war linear und für neue Nutzer unübersichtlich (CSV-
und Oracle-Felder nebeneinander, Prognose unten dran). Die Baumstruktur
nach QGIS-Vorbild macht thematisch Verwandtes zusammengehörig und
versteckt Felder, die gerade nicht relevant sind.


## 6. Nebenpunkt — EinheitView/DrehgestellView nutzen den Gantt-Helper

Datei: `ui/views.py`.

Beide Views bekommen jetzt `set_prognose_config` und `set_flotte`
analog zu `AchseView`; `main_window.py` ruft diese vor `set_einheit` /
`set_dg` auf. Die Gantt-Berechnung läuft damit überall über
`_collect_gantt_entries` statt über den älteren Fallback mit
`mr.prognose.datum_warnwert` / `datum_grenzwert`. Die Darstellung ist
dadurch über alle Ebenen konsistent.


---

Die zugehörigen Code-Änderungen liegen in:

- `ui/views.py`
- `ui/overview_widgets.py`
- `ui/settings_dialog.py`
- `ui/main_window.py`
