# Änderungen vom 2026-11-05

Nur bleibende Änderungen. Pfade im Dashboard sind relativ zum Package
`C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard\wheelset_dashboard\`,
Backend-Pfade relativ zu
`C:\User\GitHub\Wheelset-Analyzer\Wheelset Analyzer_new_approach\`.


## 1. Lager-Komponenten: Prognose auch ohne `dt_start`-Cutoff

Dateien (Backend):
- `radsatz_csv_io.py`
- `Radsatz_Bahn_DB_new_Approach.py`

### Was sich geändert hat

Der `dt_start_data`-Filter (INI: `[prognose] dt_start_data`) wird nur
noch auf **eingebaute** Zeilen angewendet. Für Zeilen mit gesetztem
`AUSBAU` (Lagerkomponenten) laufen jetzt **alle** historischen
Messwerte in die Prognose ein, auch wenn sie vor dem Stichdatum liegen.

- CSV-Loader (`radsatz_csv_io.py`): Das `continue` beim
  `dt_mess <= dt_start`-Check gilt nur, wenn `AUSBAU` leer ist.
- Oracle-Query (`Radsatz_Bahn_DB_new_Approach.py`,
  `_fetch_oracle_measurements`): WHERE-Klausel erweitert um
  `ausbau is not null or datum > TO_DATE(:StartDatum,:FormatString)`.

### Warum

Lagerkomponenten haben häufig nur wenige Messungen, die
Reprof-Doppelmessungen können mehrere Jahre vor dem Cutoff liegen. Mit
dem alten Filter verlor die Prognose entscheidende Punkte und
produzierte für ganze Lager-Drehgestelle **keine** Prognose
(Fallbeispiel: `s SLGx / 176295 Losradachse 1` — 7 Rohzeilen, davon 4
vor 2014-01-01). Die alte VGF-Live-App hat ebenfalls alle verfügbaren
Lager-Messungen verwendet.


## 2. Lager-DGs mit mehreren Ausbau-Zyklen nicht mehr dupliziert

Datei: `data/csv_source.py` (Funktion `_add_lager`). Betrifft auch den
Oracle-Loader (`data/oracle_source.py` nutzt dieselbe Funktion).

### Was sich geändert hat

Das Gruppierungs-Key für Lager-Komponenten enthält **nicht mehr** das
Ausbau-Datum:

- vorher: `("dg", dg_id, dg_bez, ausbau_bucket)`
- jetzt:  `("dg", dg_id, dg_bez)` (analog für
  `("rs", rs_id, rs_bez)`)

Das `ausbau`-Feld der Komponente wird auf das **jüngste**
Ausbau-Datum über alle gelesenen Zeilen gesetzt; `letzte_einheit`
entsprechend aktualisiert.

### Warum

Eine physische Achse / ein physisches DG kann in der Historie mehrere
Ein-/Ausbau-Zyklen haben (z. B. `s SLGx / 176303`: 2008 ausgebaut,
wieder eingebaut, 2017 erneut ausgebaut). Mit dem Ausbau-Datum im Key
entstanden zwei separate `LagerKomponente`-Einträge mit identischer
DG-ID. Der Prognose-Loader hängt die berechnete Prognose per `rs_id`
an genau einen davon an — das Duplikat ohne Prognose war aber
diejenige, die in der App sichtbar war. Nach dem Fix: eine
Komponente pro physischer Einheit, die Prognose landet dort, wo sie
hingehört.


## 3. Button „Prognose neu berechnen" aus der Statusleiste in den
   Einstellungen-Dialog verschoben

Dateien:
- `ui/main_window.py`
- `ui/settings_dialog.py`

### Was sich geändert hat

- **Statusleiste**: Der Button `Prognose neu berechnen` ist entfernt.
  Es bleibt nur noch der `Neu laden`-Button sowie die Checkbox
  `Messwerte anzeigen`.
- **Einstellungen**: Neue Baum-Seite `Prognose · Neuberechnung` mit
  Button `Prognose jetzt neu berechnen`. Ein Klick setzt
  `recalc_requested = True` und akzeptiert den Dialog.
- `MainWindow.open_settings()` prüft nach `QDialog.Accepted`, ob
  `dlg.recalc_requested` gesetzt ist, übernimmt zuerst die
  Einstellungen (inkl. Repository-Wechsel) und ruft dann
  `recalc_prognose()` auf.
- Der Bestätigungsdialog (Dauer-Warnung) in `recalc_prognose()` bleibt
  — die lange Hintergrundaktion wird weiterhin explizit bestätigt.

### Warum

Die Statusleiste soll nur noch das zeigen, was zum laufenden Betrieb
gehört (Stand, Profil, Kennzahlen, Neu laden). Die Neuberechnung ist
eine gelegentliche Administrationsaktion und gehört inhaltlich zur
Prognose-Konfiguration; dort ist sie leichter zu finden und lässt
sich zusammen mit einer Parameter-Änderung in einem Schritt anstoßen.


## 4. Panel-Überschriften: Anzahl + Status-Herkunft

Datei: `ui/views.py`.

### Was sich geändert hat

- **Flotten-Übersicht** (`FlotteView`, `set_flotte`):
  vorher „Einheiten · Status je Messgröße (5)",
  jetzt „Einheiten: Anzahl 5 - Status (anhand schlechtesten,
  letzten Messwert)".
- **Lager-Übersicht** (`LagerView`, `set_lager`):
  vorher „Lager-Komponenten[ · Filter] (N)",
  jetzt „Lager-Komponenten[ · Filter]: Anzahl N - Status
  (anhand schlechtesten, letzten Messwert)".

Die Zahl `N` entspricht wie bisher der sichtbaren Zeilenzahl
(bei Lager inkl. aktivem Status-Filter / Drilldown).

### Warum

Der bisherige Titel verriet nicht, wie die Ampeln der
Messgrößen-Spalten entstehen. Die neue Formulierung macht den
Status-Algorithmus explizit: Pro Messgröße zählt der schlechteste
Status über alle Räder der Einheit / Komponente, auf Basis der
jeweils letzten Messung.
