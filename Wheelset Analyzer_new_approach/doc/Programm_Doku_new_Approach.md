# Programmdokumentation: Radsatz_Bahn_DB_new_Approach.py

Stand: 2026-06-01, Rev. 5 (Datums-Speicherung umgestellt auf `numpy.datetime64`; Matlab-Datezahl entfällt im neuen Ansatz)  
Autor: Peter Engel  
Basis: `doc/Neuer_Ansatz_Radsatz_Analyse_Prognose_CL.md`

---

## Inhaltsverzeichnis

1. [Zweck und Abgrenzung](#1-zweck-und-abgrenzung)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Konfiguration](#3-konfiguration)
4. [Architektur und Modulstruktur](#4-architektur-und-modulstruktur)
5. [Datenfluss](#5-datenfluss)
6. [Funktionsreferenz](#6-funktionsreferenz)
7. [Algorithmen im Detail](#7-algorithmen-im-detail)
8. [Ausgaben](#8-ausgaben)
9. [Logging und Qualitätsflags](#9-logging-und-qualitätsflags)
10. [Fehlerbehandlung](#10-fehlerbehandlung)
11. [Unterschiede zum Vorgängerprogramm](#11-unterschiede-zum-vorgängerprogramm)
12. [Erweiterungsmöglichkeiten](#12-erweiterungsmöglichkeiten)
13. [Änderungen seit Rev. 1](#13-änderungen-seit-rev-1)

---

## 1. Zweck und Abgrenzung

### 1.1 Aufgabe und Zielsetzung

Das Programm unterstützt die **vorausschauende Instandhaltungsplanung** für eingebaute Radsätze
in der VGF-/ZEDAS-Datenwelt. Es verbindet drei eng zusammenhängende Aufgaben:

1. **Verschleißprognose** — Wie entwickelt sich der Laufkreisdurchmesser (LKD) weiter, und wann
   werden betriebliche Warn- und Grenzwerte voraussichtlich erreicht?
2. **Reprofilierung aus der Historie schätzen** — Wann und wie stark wurde in der Vergangenheit
   reprofiliert (Sprünge in der Messreihe), und welche typischen Intervalle und Abtragstiefen
   gelten für eine Achse oder die Flotte?
3. **Reprofilierung in die Zukunft einplanen** — Wie sieht die Prognose aus, wenn periodisch
   nachgebearbeitet wird (Zickzack-Kurve), und wie verschiebt das die km- und Datumsschwellen?

**Eingabe:** Historische Messreihen je Achse und Rad (LKD1/LKD2) aus `BO_RADSATZDATEN` (Oracle)
oder CSV-Export — Laufleistung, LKD, Datum sowie die je Messpunkt hinterlegten Schwellen
`GELB_MIN` und `MIN`.

**Ausgabe:** Prognosekurven und Schwellentermine für die Datenbanktabelle
`BO_RADSATZDATEN_PROGNOSE` oder eine kompatible CSV; optional Diagramme zur Sichtprüfung.

Damit lassen sich Wartungsfenster, Reprofilierungstermine und kritische Laufleistungen früher
abschätzen als aus der bloßen Betrachtung der letzten Messwerte.

---

### 1.2 Berechnung der Prognosedaten (Verschleiß)

#### Was prognostiziert wird

Für jede **aktuell eingebaute Achse** (Fahrzeug + Drehgestell-Position + Radsatz-Position) und
für **beide Räder** (`Rad-Laufkreisdurchmesser-1` / `-2`) wird aus der Messhistorie abgeleitet:

| Ergebnis | Bedeutung |
|----------|-----------|
| **Prognosekurve** | Folge von Punkten `(LAUFLEISTUNG, STAND, DATUM)` bis zum Prognosehorizont `n_km` |
| **KM_WARNWERT / DATUM_WARNWERT** | Erreichen der gelben Warnschwelle (`GELB_MIN`) |
| **KM_GRENZWERT / DATUM_GRENZWERT** | Erreichen des unteren Grenzwerts (`MIN`) |
| **Konservative Schätzung** (Theil-Sen) | Zusätzlich pessimistische km/Datum über das 90%-KI der Steigung (`slope_low`) |

Die **Datumsschätzung** entsteht nicht aus einem Kalendermodell, sondern aus der gemessenen
Beziehung „Tage pro Kilometer“: aus den letzten Zykluspunkten wird ein robuster Median der
km-/Datums-Differenzen gebildet (`days_per_km`) und auf die km-Schwellen hochgerechnet.

#### Verarbeitungsschritte (fachlich)

1. **Achsenbildung** — Alle Messpunkte mit leerem `AUSBAU` werden den eingebauten Achsen
   zugeordnet; pro Achse existieren zwei parallele Zählerreihen (LKD1, LKD2).
2. **Verschleißzyklus** — Zunächst wird der **letzte Verschleißzyklus** bestimmt: große positive
   Sprünge im LKD (Reprofilierung / Radtausch) schneiden ältere Zyklen ab (`diff_lkd`, Standard
   20 mm). Optional wird innerhalb des Zyklus die **letzte dokumentierte Reprofilierung** erkannt
   und nur der **Sub-Zyklus danach** für den Fit verwendet (siehe Abschnitt 1.3).
3. **Datenbereinigung** — IQR-Filter entfernt Ausreißer in LKD und Laufleistung.
4. **Trendmodell** — Je nach `prognosis_method`:
   - **Theil-Sen:** robuste lineare Verschleißrate (mm/km) mit Konfidenzintervall; optional
     Power-Law, wenn der lineare Fit zu ungenau ist.
   - **Gauss-Newton:** exponentielle Kurve in der km-Domäne (Legacy-Logik über
     `VehicleAxis.CalcPrognostic`).
5. **Schwellenschnitt** — Aus dem Trend werden die km errechnet, an denen `GELB_MIN` bzw. `MIN`
   unterschritten werden; daraus die Datumsprognose.
6. **Persistenz** — Bei `write_prog_data=true` Schreiben in `BO_RADSATZDATEN_PROGNOSE` bzw. CSV.

#### Zwei Planungsperspektiven

| Perspektive | Annahme | Nutzen |
|------------|---------|--------|
| **Ohne weitere Reprofilierung** | Kontinuierlicher Verschleiß bis zur Schwelle | „Was passiert, wenn nichts nachgearbeitet wird?“ |
| **Mit geplanter Reprofilierung** | Periodische Wiederherstellung des LKD (Sprünge nach oben) | Realistischere Betriebsplanung bei regelmäßiger Nachbearbeitung |

Im Theil-Sen-Zweig werden **Export und Prognosekurve** bevorzugt aus dem **Reprof-Szenario**
gespeist, sobald es berechenbar ist; sonst gelten die linearen Schwellen. Im Plot können beide
Sichtweisen (inkl. KI-Band nur ohne Reprof-Kurve) verglichen werden.

---

### 1.3 Reprofilierung: Erkennung, Schätzung und Einplanung

Reprofilierung (Nachbearbeitung des Laufrads) zeigt sich in den Messdaten als **kurzfristiger
Anstieg des LKD** bei geringer Zunahme der Laufleistung — im Gegensatz zum Verschleiß, bei dem
der LKD mit steigender km **fällt**.

#### 1.3.1 Erkennung in der Historie

Modul `reprof_learning.py` wertet für jede Achse **LKD1 und LKD2 gemeinsam** alle Messpaare aus:

- `Δkm` = Differenz der Laufleistung zwischen zwei aufeinanderfolgenden Messungen
- `ΔLKD` = Differenz des LKD

Ein Ereignis gilt als **Reprofilierung**, wenn gleichzeitig:

- `ΔLKD < 0` (LKD steigt — „negativer Verschleißschritt“),
- `Δkm ≤ dkm_threshold` (Sprung erfolgt in kurzer Laufstrecke),
- `|ΔLKD| ≥ dlkd_abs_min` (Mindestabtrag in mm).

Die Schwellen `dkm_threshold` und `dlkd_abs_min` werden **datengetrieben** aus vielen solcher
Sprünge geschätzt (Perzentile über „Seed“-Ereignisse mit kleinem km-Abstand und ausreichendem
LKD-Anstieg). Aus den erkannten Ereignissen werden zwei **Betriebsparameter** abgeleitet:

| Parameter | Bedeutung | Verwendung |
|-----------|-----------|------------|
| **typical_interval_km** | Median der Abstände [km] zwischen aufeinanderfolgenden Reprofilierungen | Periodenlänge in der Zukunfts-Simulation |
| **typical_magnitude_mm** | Median des LKD-Anstiegs [mm] je Reprofilierung | Abtragstiefe / Sprunghöhe in der Prognosekurve |

Zusätzlich wird gezählt, wie viele Ereignisse (`n_detected`) zur Schätzung beigetragen haben.

**Lernreihenfolge pro Achse** (`learn_reprofiling_params_per_axis`):

1. Individuell aus der Historie dieser Achse (mindestens drei erkannte Seeds),
2. sonst **Median** aller erfolgreich gelernten Achsen der Flotte,
3. sonst **INI-Fallback** aus `[prognose]`: `n_km_repro`, `n_value_repro`, `reprof_dkm_threshold`,
   `reprof_dlkd_abs_min`.

Ein separater **Flottenlauf** (`learn_reprofiling_params`) dient vor allem dem Logging und
Vergleich; maßgeblich für die Prognose sind die **pro-Achse-Parameter**.

#### 1.3.2 Zeitpunkt der letzten Reprofilierung (Rückblick)

Vor dem eigentlichen Fit sucht der Theil-Sen-Zweig im aktuellen Zyklus den **letzten**
Reprofilierungssprung (`_find_last_reprofiling_in_cycle`). Liegt dieser nahe am Ende der
Historie und liefert der Abschnitt **danach** genügend Messpunkte, wird nur dieser **Sub-Zyklus**
gefittet — der Trend beschreibt dann den Verschleiß **seit der letzten Nachbearbeitung**, nicht
seit einem älteren Radtausch.

Das verbessert die Schätzung der aktuellen Verschleißrate, wenn im selben „großen“ Zyklus
(mehrere tausend km) noch eine Reprofilierung stattfand.

#### 1.3.3 Zeitpunkte künftiger Reprofilierungen (Vorausschau)

Für die **Zukunftsplanung** wird ein **Szenario mit periodischer Reprofilierung** simuliert
(`_simulate_with_reprofilings` in `prognosis_new_core.py`):

- Ausgangspunkt: letzter Messpunkt `(last_km, last_lkd)` und geschätzte Verschleißrate `slope`.
- Alle **`typical_interval_km`** km wird der LKD um **`typical_magnitude_mm`** angehoben
  (Sprung nach oben, im Plot ein nahezu vertikaler Absatz).
- Dazwischen fällt der LKD linear mit `slope` (Verschleiß).
- Die Simulation endet, wenn
  - **GELB_MIN** vor der nächsten Reprofilierung erreicht wird → `km_warn_reprof`,
  - der LKD nach einer Reprofilierung **unter MIN** läge → keine sichere Nachbearbeitung mehr →
    `km_limit_reprof`,
  - oder der Horizont `n_km` ausgeschöpft ist.

Die so erzeugte **Zickzack-Prognosekurve** (`km_prog_reprof`, `lkd_prog_reprof`) ist die
betriebsnahe Darstellung: wiederholte Reprofilierungen verlängern die nutzbare Laufleistung,
bis der Grenzwert auch nach einem Eingriff nicht mehr sicher eingehalten werden kann.

**Gauss-Zweig:** Dieselben gelernten Werte `typical_interval_km` / `typical_magnitude_mm`
(über `reprof_km_value_for_axis`) ersetzen die INI-Standardwerte `n_km_repro` / `n_value_repro`
in `VehicleAxis.CalcPrognostic` / `insertReprofiling` — die Reprofilierungssprünge werden dort
in die exponentielle Prognosekurve eingebettet.

#### 1.3.4 Abtragstiefe bei der Reprofilierung

Die **Abtragstiefe** im Sinne des Programms ist der **LKD-Anstieg pro Eingriff** in Millimeter:

- **Historisch:** Median der betragsmäßigen Sprünge `|ΔLKD|` aller als Reprofilierung
  klassifizierten Schritte → `typical_magnitude_mm`.
- **Prognose:** Bei jedem simulierten Reprofilierungstermin wird der prognostizierte LKD um
  genau diesen Betrag erhöht (Material wird wieder „aufgebaut“, der messbare Durchmesser steigt).

Das ist **kein** separates Werkstattmaß aus einer anderen Datenquelle, sondern eine **statistische
Schätzung aus der Messhistorie** der jeweiligen Achse (bzw. Flotten-Median / INI-Fallback).

Typische INI-Startwerte: alle **30 000 km** reprofilieren, je **6 mm** Anstieg — werden durch
das Lernen ersetzt, sobald genügend dokumentierte Ereignisse vorliegen.

#### 1.3.5 Was nicht geschätzt wird

- **Kein exakter Werkstatttermin** einzelner zukünftiger Reprofilierungen im Kalender — nur
  km-basierte Periodizität plus Umrechnung in Datum über `days_per_km`.
- **Keine Unterscheidung** zwischen Reprofilierung, Radtausch und Messartefakt — alles, was die
  Sprungkriterien erfüllt, fließt in dieselbe Kategorie ein.
- **Keine Reprofilierung** in der konservativen KI-Schätzung des Theil-Sen-Zweigs (KI bezieht
  sich auf den linearen Trend ohne Sprünge).

---

### 1.4 Abgrenzung zum Vorgängerprogramm

`Radsatz_Bahn_DB_new_Approach.py` ersetzt die Prognoseberechnung aus
`Radsatz_Bahn_DB_KM_Default_Class_All.py`. Die DB-Schnittstelle und alle Hilfsklassen
(`VehicleAxis`, `MeterList`, `radsatz_settings`) bleiben unverändert.  
Die methodischen Unterschiede sind in Abschnitt 11 tabellarisch zusammengefasst.

---

## 2. Voraussetzungen

### 2.1 Python-Version

Python 3.8 oder höher.

### 2.2 Abhängigkeiten

| Paket | Min. Version | Zweck | Neu ggü. Vorgänger |
|-------|-------------|-------|--------------------|
| `numpy` | 1.21 | Array-Operationen | nein |
| `scipy` | 1.7 | `theilslopes`, `curve_fit` | **ja** |
| `matplotlib` | 3.4 | Diagramme | nein |
| `oracledb` | 1.0 | Oracle-Datenbankzugriff | nein |

Installation:
```
python -m pip install numpy scipy matplotlib oracledb
```

### 2.3 Benötigte Dateien und Python-Module im Projektverzeichnis

| Datei / Modul | Pflicht | Beschreibung |
|---------------|---------|-------------|
| `radsatz_config.ini` | ja | Konfigurationsparameter (siehe Abschnitt 3) |
| `bo_radsatzdaten_export.csv` | bei `use_database=false` | Messdaten-Export (siehe 2.5) |
| `oracle_connect_string.txt` | bei `use_database=true` | Oracle-Verbindungsstring (siehe 2.4) |
| `Radsatz_Bahn_DB_new_Approach.py` | ja | Hauptprogramm |
| `radsatz_settings.py`, `radsatz_csv_io.py` | ja | Config und CSV-Laden |
| `prognosis_new_core.py`, `prognosis_gauss.py` | ja | Prognoseverfahren |
| `reprof_learning.py` | ja | Reprofilierungsparameter |
| `VehicleAxis.py`, `MeterList.py` | ja | Datenhaltung und DB/CSV-Ausgabe |
| `GaussNewtonLinearReg_Exp.py` | ja | Exponentialfit (Gauss-Zweig) |
| `dates_np.py`, `toolsWheelset.py` | ja | Datum-Konvertierung (`numpy.datetime64`-Helfer), Zykluserkennung |
| `datetime2matlabdn.py` | nein | nur noch von Legacy-Skripten (`Radsatz_Bahn_DB_KM_Gauss_Class_All*.py`) verwendet |
| `radsatz_axis_labels.py`, `radsatz_matplotlib.py` | ja | Achsbezeichnungen, Plot-Backend |

Optional zum Erzeugen der Eingabedaten:

| Skript | Zweck |
|--------|--------|
| `export_bo_radsatzdaten_csv.py` | Vollständiger Export `BO_RADSATZDATEN` → CSV |
| `export_bo_radsatzdaten_prognose_csv.py` | Export bestehender Prognosezeilen (Vergleich) |

---

### 2.4 Datentechnische Voraussetzungen (Überblick)

Das Programm erwartet **historische Radsatz-Messwerte** im ZEDAS-/VGF-Schema der Tabelle `BO_RADSATZDATEN`. Pro **eingebauter Achse** (Fahrzeug + Drehgestell-Position + Radsatz-Position) werden zwei parallele Messreihen verarbeitet:

| Zähler (`ZARTBEZ`) | Inhalt |
|--------------------|--------|
| `Rad-Laufkreisdurchmesser-1` | LKD Rad 1 |
| `Rad-Laufkreisdurchmesser-2` | LKD Rad 2 |

**Fachliche Mindestanforderungen pro Achse und Zähler:**

| Anforderung | Details |
|-------------|---------|
| Einbau aktiv | `AUSBAU` muss leer/`NULL` sein (nur aktuell eingebaute Radsätze) |
| Zeitraum | `DATUM` > `dt_start_data` (INI, Standard `2014-01-01`) |
| Pflichtfelder je Messpunkt | `DATUM`, `STAND` (LKD [mm]), `LAUFLEISTUNG` [km], `MIN`, `MAX`, `GELB_MIN` — fehlt eines davon, wird der Punkt verworfen |
| Punkte für Fit | Nach Zyklus- und IQR-Filter mindestens `min_points_fit` Punkte (INI `[prognose_new]`, Standard `3`) |
| Qualität „OK“ | Optional höher: `min_points_quality` (Standard `8`) — sonst Flag `LOW` |
| Zyklus | Letzter Verschleißzyklus wird über Sprünge in `STAND` erkannt (`diff_lkd`, Standard `20` mm); ohne erkennbaren Sprung wird die gesamte gefilterte Reihe genutzt |
| Laufleistung | Sollte innerhalb einer Achse/Zählerreihe **monoton wachsen**; für Datumsprognose werden aus km-Differenzen Tage/km abgeleitet |
| Power-Law (optional) | Nur bei **positiven** `LAUFLEISTUNG` und `STAND`; mindestens 6 Punkte nach Filter |

**Oracle vs. CSV:** Dieselben fachlichen Filter und Spaltensemantik; Unterschied nur in der Datenquelle (`use_database` in `[pipeline]`).

---

### 2.5 Oracle-Datenbankzugriff

#### Verbindung

| Voraussetzung | Beschreibung |
|---------------|-------------|
| `use_database = true` | in `[pipeline]` |
| Connect-String | Eine Zeile in `oracle_connect_string.txt` (relativ zum Skript) **oder** Umgebungsvariable `ORACLE_CONNECT_STRING` (überschreibt Datei) |
| Oracle Client | `oracledb.init_oracle_client()` — **Oracle Instant Client** muss auf dem Rechner installiert und auffindbar sein (Thick-Mode) |
| Berechtigungen | `SELECT` auf `BO_RADSATZDATEN`; bei `write_prog_data=true` zusätzlich `INSERT`/`DELETE` auf `BO_RADSATZDATEN_PROGNOSE` |

Beispiel Connect-String (Format wie von `oracledb` erwartet):

```text
benutzer/kennwort@host:1521/service_name
```

#### Eingabetabelle `BO_RADSATZDATEN`

Das Hauptprogramm liest zwei Abfragen (Oracle-Spaltennamen in Kleinschreibung in SQL):

**Abfrage 1 — Achsenliste (`res1`):**

```sql
SELECT topeinheitbezeichnung, dgeinbaupos, rseinbaupos
FROM bo_radsatzdaten
WHERE ausbau IS NULL
GROUP BY topeinheitbezeichnung, dgeinbaupos, rseinbaupos
```

**Abfrage 2 — Messwerte (`res2`):**

```sql
SELECT topeinheitbezeichnung, dgeinbaupos, rseinbaupos, zartbez, datum, stand,
       laufleistung, min, max, gelb_min, topeinheitid, dgeinheitid, dgbezeichnung,
       rseinheitid, rsbezeichnung, einbau, ausbau, aktuell, zaehlerartid
FROM bo_radsatzdaten
WHERE zartbez IN ('Rad-Laufkreisdurchmesser-1', 'Rad-Laufkreisdurchmesser-2')
  AND datum > TO_DATE(:StartDatum, 'YYYY-MM-DD')
  AND ausbau IS NULL
ORDER BY datum
```

| Spalte (DB) | Pflicht für Verarbeitung | Rolle |
|-------------|-------------------------|--------|
| `TOPEINHEITBEZEICHNUNG`, `DGEINBAUPOS`, `RSEINBAUPOS` | ja | Achsidentifikation |
| `ZARTBEZ` | ja | Nur die beiden LKD-Zähler (siehe oben) |
| `DATUM` | ja | Messzeitpunkt |
| `STAND` | ja | Laufkreisdurchmesser [mm] |
| `LAUFLEISTUNG` | ja | Laufleistung [km] |
| `MIN`, `MAX`, `GELB_MIN` | ja | Grenz- und Warnschwellen je Messpunkt |
| `TOPEINHEITID`, `DGEINHEITID`, `RSEINHEITID` | empfohlen | Metadaten für Export/Prognose |
| `DGBEZEICHNUNG`, `RSBEZEICHNUNG` | optional | Anzeige in Plots und CSV-Ausgabe |
| `EINBAU`, `AKTUELL`, `ZAEHLERARTID` | optional | Metadaten; werden an `VehicleAxis` übernommen |
| `AUSBAU` | Filter | Muss `NULL` sein, sonst wird die Zeile ignoriert |

Weitere Spalten der Tabelle werden beim Lesen **nicht** ausgewertet.

#### Ausgabetabelle `BO_RADSATZDATEN_PROGNOSE` (optional)

Nur wenn `write_prog_data = true`:

- Vor dem Insert: Löschen alter Zeilen mit `LETZTEAENDZEIT` älter als `n_days_2_delete` Tage.
- Insert-Spalten: `TOPEINHEITID`, `TOPEINHEITBEZEICHNUNG`, `DGEINHEITID`, `DGBEZEICHNUNG`, `DGEINBAUPOS`, `RSEINHEITID`, `RSBEZEICHNUNG`, `RSEINBAUPOS`, `EINBAU`, `AUSBAU`, `AKTUELL`, `ZAEHLERARTID`, `ZARTBEZ`, `STAND`, `DATUM`, `LAUFLEISTUNG`, `LETZTEAENDZEIT`, `KM_GRENZWERT`, `DATUM_GRENZWERT`, `KM_WARNWERT`, `DATUM_WARNWERT` (siehe Abschnitt 8.1).

Bei mehreren aktiven Prognosemethoden (`theil_sen, gauss`) wird nur die **erste** Methode in der INI-Reihenfolge exportiert.

---

### 2.6 CSV-Eingabe (`bo_radsatzdaten_export.csv`)

#### Wann

`use_database = false` — Pfad über `[paths] csv_bo_radsatzdaten` (Standard: `bo_radsatzdaten_export.csv` im Skriptverzeichnis).

#### Dateiformat

| Eigenschaft | Wert |
|-------------|------|
| Encoding | UTF-8 mit BOM (`utf-8-sig`) |
| Trennzeichen | Semikolon (`;`) |
| Kopfzeile | Spaltennamen wie Oracle-Export (Großbuchstaben) |
| Datumsformat | `YYYY-MM-DD` oder `YYYY-MM-DD HH:MM:SS` (optional Millisekunden) |
| Dezimalzahlen | Punkt oder Komma (wird intern normalisiert) |

Empfohlen: Export mit `python export_bo_radsatzdaten_csv.py` — liefert `SELECT * FROM bo_radsatzdaten` mit konsistenten Spaltennamen.

#### Pflicht-Spalten (werden ausgewertet)

Die Loader-Logik (`radsatz_csv_io.load_bo_radsatz_from_csv`) nutzt dieselben Felder wie die Oracle-Abfrage:

| Spalte | Pflicht | Hinweis |
|--------|---------|---------|
| `TOPEINHEITBEZEICHNUNG` | ja | Fahrzeugbezeichnung |
| `DGEINBAUPOS` | ja | Drehgestell-Einbauposition |
| `RSEINBAUPOS` | ja | Radsatz-Einbauposition |
| `ZARTBEZ` | ja | Nur `Rad-Laufkreisdurchmesser-1` / `-2` |
| `DATUM` | ja | > `dt_start_data` |
| `STAND` | ja | LKD [mm] |
| `LAUFLEISTUNG` | ja | [km] |
| `MIN`, `MAX`, `GELB_MIN` | ja | Schwellen |
| `AUSBAU` | Filter | **Leer** = eingebaut; gefülltes Datum = ausgebaut → Zeile wird übersprungen |
| `TOPEINHEITID`, `DGEINHEITID`, `RSEINHEITID` | empfohlen | Für Prognose-Export |
| `DGBEZEICHNUNG`, `RSBEZEICHNUNG` | optional | Beschriftung |
| `EINBAU`, `AKTUELL`, `ZAEHLERARTID` | optional | Metadaten |

**Nicht ausgewertet** (können im Export vorhanden sein): z. B. `GELB_MAX`, `LETZTEAENDZEIT` und alle weiteren Spalten des Vollexports.

#### Beispiel-Kopfzeile (Auszug)

```text
TOPEINHEITID;TOPEINHEITBEZEICHNUNG;DGEINHEITID;DGBEZEICHNUNG;DGEINBAUPOS;RSEINHEITID;RSBEZEICHNUNG;RSEINBAUPOS;EINBAU;AUSBAU;AKTUELL;ZAEHLERARTID;ZARTBEZ;STAND;DATUM;MIN;MAX;GELB_MIN;LAUFLEISTUNG;...
```

#### Typische Fehlerquellen

| Problem | Symptom |
|---------|---------|
| Alle Zeilen haben `AUSBAU` gesetzt | `res1`/`res2` leer → „Keine Messdaten gefunden“ |
| Falsche `ZARTBEZ` | Keine LKD-Reihen |
| `DATUM` vor `dt_start_data` | Zeilen werden still gefiltert |
| Fehlende `STAND`/`LAUFLEISTUNG`/Schwellen | Warnung „Zählerdaten nicht vollständig“, Punkt übersprungen |
| Zu wenige Punkte im letzten Zyklus | Qualität `INSUFFICIENT`, kein Plot/Export für diese Achse |

---

### 2.7 CSV-Ausgabe der Prognose (optional)

Wenn `use_database = false` und `write_prog_data = true`:

| Eigenschaft | Wert |
|-------------|------|
| Datei | `[paths] csv_bo_prognose_out` (Standard `bo_radsatzdaten_prognose_recalc.csv`) |
| Format | `;`, UTF-8-BOM, Kopfzeile wie `BO_RADSATZDATEN_PROGNOSE` |
| Spalten | siehe Abschnitt 8.1 / `_PROGNOSE_CSV_HEADER` im Hauptskript |

Voraussetzung: Für die Achse wurde eine Prognose mit ausreichender Datenlage berechnet (`OK` oder `LOW`); bei `INSUFFICIENT` entstehen keine Prognosezeilen.

---

## 3. Konfiguration

Alle Laufzeitparameter werden aus `radsatz_config.ini` geladen (Datei im Skriptverzeichnis).
Ist die Datei nicht vorhanden, gelten die in `radsatz_settings.py` definierten Standardwerte.

### 3.1 Sektion `[pipeline]`

| Schlüssel | Typ | Standard | Beschreibung |
|-----------|-----|---------|-------------|
| `use_database` | bool | `false` | `true` = Oracle-DB, `false` = CSV-Modus |
| `write_prog_data` | bool | `false` | Prognosedaten schreiben (DB oder CSV) |

### 3.2 Sektion `[paths]`

| Schlüssel | Standard | Beschreibung |
|-----------|---------|-------------|
| `csv_bo_radsatzdaten` | `bo_radsatzdaten_export.csv` | Eingabe-CSV (relativ zum Skript) |
| `csv_bo_prognose_out` | `bo_radsatzdaten_prognose_recalc.csv` | Ausgabe-CSV |
| `oracle_connect_filename` | `oracle_connect_string.txt` | Datei mit Oracle-Verbindungsstring |

### 3.3 Sektion `[prognose]`

| Schlüssel | Typ | Standard | Beschreibung |
|-----------|-----|---------|-------------|
| `prognosis_method` | str / Liste | `theil_sen` | `theil_sen`, `gauss` oder kommagetrennt beides (`theil_sen, gauss`) |
| `dt_start_data` | Datum | `2014-01-01` | Startdatum der historischen Daten |
| `n_km` | int | `300000` | Prognosehorizont [km] |
| `diff_lkd` | float | `20` | Sprungschwelle für Zykluserkennung [mm] |
| `n_km_repro` | float | `30000` | Reprofilierungsintervall [km]; wird für Gauss und Reprof-Szenarien genutzt |
| `n_value_repro` | float | `6` | Reprofilierungsabtrag [mm]; wird für Gauss und Reprof-Szenarien genutzt |
| `n_days_2_delete` | int | `14` | Alter [Tage] ab dem alte Prognoseeinträge gelöscht werden |

> **Hinweis:** `def_jump_repro` und `def_param_exp_*` werden im Gauss-Zweig verwendet.

### 3.4 Sektion `[plot]`

| Schlüssel | Typ | Standard | Beschreibung |
|-----------|-----|---------|-------------|
| `show_plot` | bool | `true` | Diagrammausgabe aktivieren |
| `plot_output_dir` | Pfad | *(leer)* | Zielverzeichnis für PNG-Export (leer = kein Export) |
| `plot_top_einheit_filter` | str | *(leer)* | Optionaler Filter auf `TOPEINHEITBEZEICHNUNG \| DG \| Achse` (z. B. `FLIRT 101`) |
| `plot_show_window` | bool | `true` | Fenster anzeigen (`false` = nur PNG-Export) |
| `figure_width` | float | `20` | Diagrammbreite [Zoll] |
| `figure_height` | float | `8` | Diagrammhöhe [Zoll] |
| `figure_dpi` | int | `80` | Auflösung |
| `debug_print_axis_keys` | str | *(leer)* | Kommaseparierte Teilstrings; passende Achsen-Keys werden auf Konsole ausgegeben |

### 3.5 Sektion `[prognose_new]`

| Schlüssel | Typ | Standard | Beschreibung |
|-----------|-----|---------|-------------|
| `min_points_fit` | int | `3` | Mindestanzahl Punkte für Theil-Sen-Fit |
| `min_points_quality` | int | `8` | Schwelle für Qualitätsflag `OK` |
| `iqr_factor` | float | `2.0` | IQR-Ausreißerfaktor |
| `ci_alpha` | float | `0.90` | Theil-Sen-Konfidenzniveau |
| `rmse_threshold_mm` | float | `0.5` | Umschaltkriterium linear → Power-Law |
| `n_prog_points` | int | `20` | Anzahl Punkte der gespeicherten Prognosekurve |
| `cv_tune` | bool | `true/false` | Optionales CV-Tuning (nur Theil-Sen) |
| `baureihe_fallback` | bool | `false` | Optionaler Fallback bei `INSUFFICIENT`: mittleren Baureihen-Anstieg nutzen |

### 3.6 Typische INI-Setups

#### A) Nur Theil-Sen (empfohlener Standard)

```ini
[prognose]
prognosis_method = theil_sen

[prognose_new]
baureihe_fallback = false
```

#### B) Nur Gauss-Newton

```ini
[prognose]
prognosis_method = gauss
```

#### C) Kombiniert (Theil-Sen + Gauss im selben Plot)

```ini
[prognose]
prognosis_method = theil_sen, gauss
```

Optional im Kombimodus:
- `write_prog_data=true`: Export nutzt die erste verfügbare Methode in der Reihenfolge.
- `plot_top_einheit_filter=FLIRT 101`: nur bestimmte Einheit(en) plotten.

### 3.7 Setup nach Einsatzzweck (Kurzempfehlung)

| Einsatzzweck | Empfohlenes Setup |
|---|---|
| Regelbetrieb (robust, nachvollziehbar) | `prognosis_method = theil_sen` |
| Vergleich / Validierung alter vs. neuer Methodik | `prognosis_method = theil_sen, gauss` |
| Rückwärtskompatibler Lauf mit Gauss-Logik | `prognosis_method = gauss` |
| Schwache Datenlage im Theil-Sen-Zweig absichern | zusätzlich `baureihe_fallback = true` (bewusst aktivieren) |
| Gezielte Sichtprüfung einzelner Fahrzeuge | zusätzlich `plot_top_einheit_filter = <Teilstring>` |

---

## 4. Architektur und Modulstruktur

```
Radsatz_Bahn_DB_new_Approach.py          ← Hauptprogramm (Methoden-Orchestrierung)
│
├── radsatz_settings.py                  ← Config-Loader (inkl. Methodenliste)
├── radsatz_axis_labels.py               ← Achsschlüssel, Titel, Plot-Manifest
├── radsatz_csv_io.py                    ← CSV-Laden (Oracle-kompatibles Tupelformat)
├── radsatz_matplotlib.py                ← Backend-Handling / Fenstersteuerung
├── prognosis_new_core.py                ← Theil-Sen + IQR + optional Power-Law
├── prognosis_gauss.py                   ← Gauss-Newton + IQR-Filter
├── reprof_learning.py                   ← Reprofilierungsparameter pro Achse
├── dates_np.py                          ← Datums-Helfer (numpy.datetime64[s])
├── datetime2matlabdn.py                 ← (Legacy) Datum ↔ Matlab-Datezahl, nur noch alte Skripte
├── toolsWheelset.py                     ← getStartIndexLastCycle()
├── MeterList.py                         ← Datenhaltung Messwerte + Prognosewerte
└── VehicleAxis.py                       ← Datenhaltung + DB/CSV-Ausgabe
```

`Radsatz_Bahn_DB_new_Approach.py` ruft je nach Konfiguration einen oder mehrere
Methodenzweige auf. Im Kombimodus (`theil_sen, gauss`) werden beide Ergebnisse pro
Achse berechnet und in einem gemeinsamen Diagramm überlagert dargestellt
(Historie nur einmal).

---

## 5. Datenfluss

```
                    ┌─────────────────────┐
                    │  radsatz_config.ini  │
                    └──────────┬──────────┘
                               │ load_radsatz_config()
                               ▼
          ┌──────────────────────────────────────┐
          │  Oracle BO_RADSATZDATEN              │
          │  oder CSV bo_radsatzdaten_export.csv │
          └──────────────────┬───────────────────┘
                             │ res1 (Achsenliste), res2 (Messwerte)
                             ▼
                  ┌─────────────────────┐
                  │  dict_VehicleAxis    │
                  │  (VehicleAxis +      │
                  │   MeterList LKD1/2) │
                  └──────────┬──────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │ learn_reprofiling_params_*   │
              │ (Intervall + Abtrag je Achse)│
              └──────────────┬───────────────┘
                             │
              ┌──────────────┼──────────────┐
              │ für jede Achse              │
              ▼                             ▼
   getStartIndexLastCycle()    getStartIndexLastCycle()
         LKD1                        LKD2
              │                             │
              ▼                             ▼
   _calc_prognosis_axis()       _calc_prognosis_axis()
   ┌─────────────────────┐
   │ 1. Monotonie-Check   │
   │ 2. Min-Punkte-Check  │
   │ 3. IQR-Filter        │
   │ 4. Theil-Sen-Fit     │
   │ 5. Power-Law (opt.)  │
   │ 6. Reprof-Szenario   │
   │ 7. Schnittpunkte     │
   │ 8. daysPerKm (Median)│
   │ 9. Datum-Prognose    │
   │10. MeterList setzen  │
   └─────────────────────┘
              │
              ▼
   _plot_axis()  (wenn show_plot=true)
              │
              ▼
   iter_prognose_insert_tuples()
              │
              ▼
   ┌────────────────────────────────────────────┐
   │  Oracle BO_RADSATZDATEN_PROGNOSE           │
   │  oder CSV bo_radsatzdaten_prognose_*.csv   │
   └────────────────────────────────────────────┘
```

### 5.1 Methoden-Orchestrierung (Rev. 2)

- `prognosis_method = theil_sen`: nur `prognosis_new_core._calc_prognosis_axis`
- `prognosis_method = gauss`: nur `prognosis_gauss.run_gauss_prognosis_for_vehicle`
- `prognosis_method = theil_sen, gauss`: beide Pfade pro Achse

Regeln im Kombimodus:
- Historische Messdaten werden nur einmal gezeichnet.
- Prognoseverläufe beider Methoden werden im selben Plot überlagert.
- Fällt eine Methode aus (zu wenig Daten/Exception), wird die andere weiterhin
  verwendet; ein Plot wird erstellt, sobald mindestens eine Methode erfolgreich ist.
- Für DB/CSV-Export wird die erste verfügbare Methode in der konfigurierten Reihenfolge genutzt.

---

## 6. Funktionsreferenz

### 6.1 Datenladen

#### `load_connect_string(script_dir, connect_filename) → str`

Liest den Oracle-Verbindungsstring aus Umgebungsvariable `ORACLE_CONNECT_STRING`
(Priorität) oder aus der angegebenen Datei. Wirft `SystemExit` bei fehlendem Zugriff.

#### `load_bo_radsatz_from_csv(csv_path, dt_start_str) → (res1, res2)`

Liest die Messdaten-CSV und gibt zwei Listen zurück:
- `res1`: Liste von `(TOPEINHEITBEZEICHNUNG, DGEINBAUPOS, RSEINBAUPOS)` – nur aktuell eingebaute Achsen
- `res2`: Liste von Messwert-Tupeln für LKD1/LKD2, gefiltert nach `dt_start_str` und `AUSBAU IS NULL`

---

### 6.2 Prognoseberechnung (Kernfunktionen)

#### `_outlier_filter_iqr(km, lkd, iqr_factor, axis_key) → (km_clean, lkd_clean, n_removed)`

**Eingabe:**
- `km`: numpy-Array mit Laufleistungswerten [km]
- `lkd`: numpy-Array mit LKD-Messwerten [mm]
- `iqr_factor`: Faktor für den Schwellwert (Standard: 2.0)
- `axis_key`: Identifikationsstring für das Logging

**Verfahren:**
1. Vorläufige lineare Regression (`numpy.polyfit`) zur Residuenberechnung
2. IQR der Residuen berechnen
3. Maske: Punkte mit `|Residuum| > iqr_factor × IQR` werden ausgeschlossen

**Ausgabe:** Gefilterte Arrays + Anzahl entfernter Punkte. Bei `IQR = 0` (alle
Punkte auf einer Linie) kein Filter.

---

#### `_fit_theilsen(km, lkd, ci_alpha) → (slope, intercept, slope_low, slope_high, rmse)`

**Eingabe:**
- `km`, `lkd`: gefilterte Arrays nach `_outlier_filter_iqr`
- `ci_alpha`: Konfidenzintervall (Standard: 0.90 → 90 %)

**Verfahren:**  
Aufruf von `scipy.stats.theilslopes(y=lkd, x=km, alpha=ci_alpha)`.  
Der Theil-Sen-Schätzer berechnet den **Median aller paarweisen Steigungen** zwischen
je zwei Messpunkten. Er ist robust gegen Ausreißer (Breakdown-Point ≈ 29 %).

**Ausgabe:**

| Rückgabewert | Bedeutung |
|---|---|
| `slope` | Medianschätzer der Verschleißrate [mm/km] |
| `intercept` | Zugehöriger Achsenabschnitt |
| `slope_low` | Untere Konfidenzgrenze (pessimistisch = schnellerer Verschleiß) |
| `slope_high` | Obere Konfidenzgrenze (optimistisch = langsamerer Verschleiß) |
| `rmse` | RMSE des Medianfits über die bereinigten Messdaten [mm] |

---

#### `_fit_powerlaw(km, lkd, last_km, last_lkd) → (b, c, rmse) | None`

Optionaler Fit des Modells `lkd = last_lkd - b × (km − last_km)^c`
via `scipy.optimize.curve_fit`. Wird nur aufgerufen wenn:
- linearer RMSE > `RMSE_THRESHOLD_MM`
- mindestens 6 Punkte nach Filter vorhanden

Schranken: `b ∈ [0, 1]`, `c ∈ [0.1, 3.0]`; Startwerte `b=1e-5`, `c=1.0` (linear).  
Gibt `None` zurück wenn `curve_fit` nicht konvergiert.

---

#### `_km_threshold_linear(last_km, last_lkd, slope, y_thresh) → float | None`

Analytischer Schnittpunkt der am letzten Messpunkt verankerten Trendgeraden
`lkd(km) = last_lkd + slope × (km − last_km)` mit dem Schwellwert `y_thresh`.

```
km_thresh = last_km + (last_lkd − y_thresh) / (−slope)
```

Gibt `None` zurück wenn `slope ≥ 0` (kein Verschleiß) oder die Schwelle bereits
unterschritten ist.

---

#### `_km_threshold_powerlaw(last_km, last_lkd, b, c, y_thresh) → float | None`

Analytischer Schnittpunkt des Power-Law-Modells mit `y_thresh`:

```
km_thresh = last_km + ((last_lkd − y_thresh) / b)^(1/c)
```

Gibt `None` zurück wenn Vorbedingungen nicht erfüllt (`b ≤ 0`, `c ≤ 0`,
`last_lkd ≤ y_thresh`).

---

#### `_calc_days_per_km_robust(km_cycle, date_num_cycle, axis_key) → float`

Berechnet die mittlere Nutzungsintensität als **Median paarweiser Tage/km-Raten**
über alle benachbarten Messpunkte im aktuellen Zyklus.

```
rates[i] = (date_num[i+1] − date_num[i]) / (km[i+1] − km[i])   für km[i+1] > km[i]
daysPerKm = Median(rates)
```

Vorteil gegenüber dem Vorgänger (Erster-zu-letzter-Punkt): Betriebsunterbrechungen
und saisonale Pausen verzerren das Ergebnis nicht systematisch.  
Fallback: `0.01` Tage/km wenn keine gültigen Paare vorhanden.

---

#### `_calc_prognosis_axis(met, axis_key, n_km_horizon) → _PrognResult`

**Hauptfunktion** der Prognoseberechnung. Orchestriert alle Teilschritte und
schreibt die Ergebnisse direkt in das übergebene `MeterList`-Objekt.

**Eingabe:**
- `met`: `MeterList`-Objekt mit befüllten Messdaten und gesetztem `indexStartLastCycle`
- `axis_key`: Identifikationsstring für Logging
- `n_km_horizon`: Prognosehorizont [km] aus Config

**Verarbeitungsschritte:**

| Schritt | Beschreibung |
|---------|-------------|
| 1 | Sortierung nach km (stellt Monotonie sicher) |
| 2 | Mindestpunkteprüfung (`MIN_POINTS_FIT`); bei Unterschreitung: `QUALITY_INSUFFICIENT` |
| 3 | IQR-Ausreißerfilter (`_outlier_filter_iqr`) |
| 4 | Theil-Sen-Fit (`_fit_theilsen`); liefert Steigung + 90%-KI |
| 5 | Optional Power-Law-Fit wenn RMSE > Schwelle (`_fit_powerlaw`) |
| 6 | Qualitätsflag setzen (OK / LOW anhand `MIN_POINTS_QUALITY`) |
| 7 | Schnittpunkte mit GELB_MIN und MIN (median + konservativ) |
| 8 | Prognosekurve generieren (`N_PROG_POINTS` Punkte) |
| 9 | Robuste `daysPerKm`-Schätzung (`_calc_days_per_km_robust`) |
| 10 | Datum-Prognose (km → `numpy.datetime64[s]` via `last_date + days_to_timedelta64(km_delta · days_per_km)`) |
| 11 | Alle Ergebnisse in `MeterList` schreiben |

**Felder, die in `MeterList` geschrieben werden:**

| Setter | Inhalt |
|--------|--------|
| `setkmProg` | km-Werte der Prognosekurve |
| `setvaluesProg` | LKD-Werte der Prognosekurve [mm] |
| `setnDatesProg` | `numpy.ndarray[datetime64[s]]` der Prognosekurve |
| `setgelb_min_Prog_km` | km bei GELB_MIN-Schnittpunkt (Median); **`0.0` wenn kein Schnittpunkt** |
| `setmin_Prog_km` | km bei MIN-Schnittpunkt (Median); **`0.0` wenn kein Schnittpunkt** |
| `setgelb_min_Prog_dt` | `numpy.datetime64[s]` bei GELB_MIN-Schnittpunkt; `NaT` wenn nicht berechenbar |
| `setmin_Prog_dt` | `numpy.datetime64[s]` bei MIN-Schnittpunkt; `NaT` wenn nicht berechenbar |

> **Hinweis zu „kein Wert":** Für km-Felder wird weiterhin `0.0` als
> Sentinelwert verwendet (`MeterList` initialisiert numerisch). Für Datums-Felder
> wird `numpy.datetime64('NaT')` als „kein Wert"-Marker genutzt.
> `VehicleAxis._prognose_insert_tuples_for_meter` konvertiert beim DB-Insert
> über `dates_np.to_python_datetime()` zu einem Python-`datetime` (bzw. `None`
> bei `NaT`/`0`); km-Felder werden via `if value > 0` als `None` geschrieben.
> Damit entstehen am DB-Boundary nur native Python-Typen, die `oracledb`
> akzeptiert (geprüft via `test_db_insert_types.py`).

**Ausgabe:** Gibt immer eine `_PrognResult`-Dataclass zurück – auch bei
unzureichender Datenlage (dann `quality = QUALITY_INSUFFICIENT`, keine
MeterList-Felder gesetzt). Eine Exception propagiert zum aufrufenden
`try/except`-Block in der Hauptschleife; `None` wird nie zurückgegeben.

---

### 6.3 Visualisierung

#### `_plot_axis(tmpVehicle, res1_m, res2_m, method_label)`

Erzeugt ein Diagramm für **eine** Methode mit:

| Element | Farbe | Stil |
|---------|-------|------|
| LKD1 Messdaten | Blau | Punkte (scatter) |
| LKD2 Messdaten | Grün | Punkte (scatter) |
| LKD1 Prognosekurve | Blau | methodenspezifisch |
| LKD2 Prognosekurve | Grün | methodenspezifisch |
| KI-Band LKD1 (90 %, slope_low bis slope_median) | Blau | 10 % Transparenz |
| KI-Band LKD2 (90 %, slope_low bis slope_median) | Grün | 10 % Transparenz |
| MIN-Grenzwert | Rot | durchgezogen |
| MAX-Grenzwert | Rot | durchgezogen |
| GELB_MIN-Warnwert | Goldgelb | durchgezogen |
| Annotationen (D1/D2 Gelb, D1/D2 Grenze) | — | Pfeil |

**Hinweis Rev. 2:** Im Gauss-Modus werden keine KI-Bänder gezeichnet.

#### `_plot_axis_compare_methods(base_vehicle, method_series, method_order)`

Erzeugt ein gemeinsames Vergleichsdiagramm, wenn mehrere Methoden aktiv sind
(`theil_sen, gauss`):
- Historie (LKD1/LKD2) nur einmal
- Prognosekurven pro Methode überlagert
- Legende mit Methodenlabel

---

## 7. Algorithmen im Detail

### 7.0 Kurzüberblick der drei Methoden

| Methode | Typ | Einsatz im Programm |
|---------|-----|---------------------|
| Theil-Sen | robust linear | Standard im Zweig `theil_sen`; wird immer zuerst für linearen Trend + KI verwendet |
| Power-Law | nichtlinear | Im Theil-Sen-Zweig optional, wenn linearer Fit zu ungenau ist (`RMSE > rmse_threshold_mm`) und genug Daten vorliegen |
| Gauss-Newton (Exp) | nichtlinear, iterativ | Im Zweig `gauss` über `VehicleAxis.CalcPrognostic`; optional auch parallel zu Theil-Sen im Kombimodus |

Kurzlogik:
- `prognosis_method = theil_sen`: Theil-Sen (optional Power-Law-Ersatz)
- `prognosis_method = gauss`: Gauss-Newton
- `prognosis_method = theil_sen, gauss`: beide Verfahren pro Achse; gemeinsamer Plot

---

### 7.0b Power-Law-Modell (Potenzgesetz)

#### Grundform

Das Power-Law-Modell beschreibt einen **nichtlinearen** Zusammenhang zwischen einer unabhängigen und einer abhängigen Größe:

```text
y = a · x^b
```

| Symbol | Bedeutung (im Verschleißkontext) |
|--------|------------------------------|
| **y** | Abhängige Variable (z. B. prognostizierter LKD [mm]) |
| **x** | Unabhängige Variable (z. B. Laufleistung [km] seit Zyklusstart) |
| **a** | Skalierungsparameter (Niveau / Startwert) |
| **b** | Exponent (Form der Kurve) |

#### Was das Modell macht

Es nimmt an, dass die Beziehung zwischen Laufleistung und Verschleiß **keiner Geraden**, sondern einer **Potenzfunktion** folgt:

- **b > 1:** überproportionales Wachstum (konvex) — typisch für „je mehr km, desto stärker der Abfall“
- **0 < b < 1:** unterproportionales Wachstum (konkav)
- **b < 0:** Abnahme mit steigendem x (selten im Verschleißkontext)

#### Einsatz im Programm

Im Theil-Sen-Zweig wird Power-Law **nur optional** aktiviert: Wenn der lineare Theil-Sen-Fit nach IQR-Filter einen RMSE oberhalb `rmse_threshold_mm` liefert (Standard oft 0,5 mm), wird stattdessen ein Power-Law-Fit auf den Zyklusdaten versucht. Nur wenn der Power-Law-RMSE **kleiner** ist als der lineare RMSE, wird das Power-Law-Modell für die Prognosekurve verwendet.

#### Parameterschätzung (linearisiert)

Häufig wird geschätzt über:

```text
log(y) = log(a) + b · log(x)
```

Damit wird aus dem nichtlinearen Problem ein lineares Regressionsproblem in den Log-Parametern.

#### Stärken

- Gut, wenn die wahre Beziehung tatsächlich potenzförmig ist
- Einfach zu interpretieren
- Nur für **positive** x und y geeignet

#### Schwächen

- Ausreißer können die Schätzung verzerren
- Schlecht, wenn die wahre Kurve S-förmig oder stark geknickt ist

---

### 7.0c Theil-Sen-Methode (robuste lineare Regression)

#### Grundidee

Theil-Sen ist ein **robuster linearer Schätzer** für die Verschleißrate (LKD pro km). Statt eines einzelnen Least-Squares-Fits werden viele paarweise Steigungen zwischen allen Messpunkten gebildet; der **Median** dieser Steigungen ist robust gegen Ausreißer.

#### Mathematische Grundlage

Für n Messpunkte `(km_i, lkd_i)` werden alle Paar-Steigungen berechnet:

```text
s_ij = (lkd_j − lkd_i) / (km_j − km_i)   für alle i < j
```

Die geschätzte Steigung ist der Median aller `s_ij`. Zusätzlich liefert `scipy.stats.theilslopes` ein **90%-Konfidenzintervall** für die Steigung (`slope_low`, `slope_high`).

#### Was das im Verschleißprogramm bedeutet

- Verschleiß wird als **negativer** Trend modelliert: `slope < 0` (LKD sinkt mit steigender Laufleistung).
- Prognose wird am **letzten Messpunkt** verankert: `lkd_prog(km) = last_lkd + slope × (km − last_km)`.
- Zusätzlich: **90%-KI** für konservative Planung (`slope_low` → frühere Schwellen).
- Optional: **Reprofilierungs-Szenario** mit periodischen Sprüngen in der Prognosekurve (wenn Reprof-Parameter gelernt wurden).

#### Stärken

- Sehr robust gegen einzelne Ausreißer (Breakdown-Point ≈ 29 %)
- Transparente Unsicherheit über KI
- Schnell und stabil für typische Zyklusdaten

#### Schwächen / Grenzen

- Linearer Kern — bei stark gekrümmten Verläufen ungenau
- Dann optional Power-Law (siehe 7.0b)

#### Wann einsetzen

- Standard für `prognosis_method = theil_sen`
- Im Kombimodus `theil_sen, gauss` als Referenzmethode
- Wenn viele Ausreißer oder instabile Trends: zuerst IQR, dann Theil-Sen

---

### 7.0d Gauss-Newton-Methode (Exponentialfit, iterativ)

#### Grundform

Die Gauss-Methode im Programm fitet eine **Exponentialkurve** (nicht Potenzgesetz) in der Laufleistung:

```text
y = a₁ − e^(a₂ · x)
```

| Symbol | Bedeutung (im Verschleißkontext) |
|--------|------------------------------|
| **y** | Abhängige Variable (LKD [mm]) |
| **x** | Unabhängige Variable (Laufleistung [km], normiert im Fit) |
| **a₁** | Skalierung / Niveau der Kurve |
| **a₂** | Exponentialrate (Steilheit des Verlaufs) |

Vor dem Fit werden x und y auf den Zyklusanfang normiert; die Prognose wird auf den km-Horizont `n_km` extrapoliert (`GaussNewtonLinearReg_ExpNorm`).

#### Grundidee

Die Gauss-Methode im neuen Programm nutzt den **klassischen Gauss-Newton-Ansatz** aus dem Legacy-Code (`VehicleAxis.CalcPrognostic` → `GaussNewtonLinearReg_ExpNorm`): iterativ werden die Parameter `a₁`, `a₂` so angepasst, dass die Summe der quadrierten Residuen `r_i = y_i − (a₁ − e^(a₂·x_i))` minimiert wird (max. 30 Schritte, Toleranz `1e-8`).

#### Was das Modell macht

1. Bereinigt die Messreihe (Sprungentfernung bei Reprofilierung, optional IQR wie im Theil-Sen-Zweig).
2. Passt die Exponentialkurve `y = a₁ − e^(a₂·x)` an die Zykluspunkte `(km, LKD)` an (Gauss-Newton, max. 30 Iterationen).
3. Extrapoliert die Kurve bis zum Horizont `n_km` und modelliert Reprofilierungssprünge (`nKmRepro`, `nValueRepro`).
4. Berechnet Schwellen (GELB_MIN / MIN) und schreibt `kmProg`, `valuesProg`, `nDatesProg` in `MeterList`.

#### Typische Anwendungen

- Stark gekrümmte Verschleißverläufe (exponentieller Abfall des LKD)
- Historischer Referenzansatz im Legacy-Programm (`Radsatz_Bahn_DB_KM_Default_Class_All.py`)
- Methodenvergleich im Kombimodus `theil_sen, gauss`

#### Parameterschätzung

Nicht linearisierbar wie beim Power-Law: Die Parameter `a₁`, `a₂` werden per **Gauss-Newton-Iteration** aus dem Jacobian der Residuen bestimmt. Startwerte kommen aus dem Code bzw. der INI (`def_param_exp_a0`, `def_param_exp_a1`); Konvergenz bei Änderung von `a₁` unter `1e-8`.

#### Parameter (INI)

| Parameter | Typische Rolle |
|-----------|----------------|
| `def_param_exp_a0`, `def_param_exp_a1` | Startwerte / Form der Exponentialkurve |
| `n_km_repro`, `n_value_repro` | Reprofilierungs-Szenario in der Kurve |
| `def_jump_repro` | Sprungdetektion im Zyklus (Legacy-Logik) |

#### Stärken

- Bewährte Darstellung von **stark gekrümmten** oder **exponentiellen** Verschleißverläufen
- Enthält bereits Reprofilierung in der Prognosekurve (Zickzack)

#### Schwächen

- Iterativ — kann bei schwierigen Datenkonvergenz scheitern (`ContinuityError`)
- Kein analytisches 90%-KI wie beim Theil-Sen-Zweig (konservative Planung nur indirekt über Reprof-Szenario)
- Default-Kurven-Mischung aus synthetischen Punkten im Legacy-Code entfällt im neuen Pfad

#### Wann einsetzen

- `prognosis_method = gauss`
- Vergleich mit Theil-Sen: `prognosis_method = theil_sen, gauss`
- Wenn historisch der Gauss-Ansatz der Referenz war und Theil-Sen zu instabil ist

---

### 7.1 Theil-Sen-Schätzer

Für `n` Messpunkte `(km₁, lkd₁), ..., (kmₙ, lkdₙ)` werden alle `n(n−1)/2`
paarweisen Steigungen berechnet:

```
s_ij = (lkd_j − lkd_i) / (km_j − km_i)   für alle i < j
```

Die Steigungsschätzung ist der **Median** aller `s_ij`.  
Der Achsenabschnitt ist `median(lkd_i − slope × km_i)`.

Das 90%-Konfidenzintervall auf `slope` wird über die Verteilung der `s_ij`-Werte
berechnet (asymptotische Normalverteilung, Algorithmus nach Sen 1968, implementiert
in `scipy.stats.theilslopes`).

**Robustheit:** Bis zu `⌊(n−1)/3⌋` Ausreißer können entfernt werden ohne die
Schätzung zu beeinflussen (Breakdown-Point ≈ 29 % bei großem n).

### 7.2 Modellverankerung am letzten Messpunkt

Die Prognose wird am **letzten gemessenen Datenpunkt** `(last_km, last_lkd)` verankert:

```
lkd_prog(km) = last_lkd + slope × (km − last_km)
```

Damit ist die Prognose unabhängig vom globalen Achsenabschnitt des Fits und startet
immer am tatsächlich zuletzt gemessenen Wert.

Für die Schnittpunktberechnung folgt daraus ein **effektiver Achsenabschnitt**:

```
intercept_eff = last_lkd − slope × last_km
km_thresh = (y_thresh − intercept_eff) / slope
```

Dasselbe gilt für das konservative Szenario mit `slope_low`.

### 7.3 Konservatives Szenario

Das konservative Szenario verwendet `slope_low` (untere Konfidenzgrenze, 90%-KI).
Da der Verschleiß negativ ist (`slope < 0`), gilt `slope_low < slope < 0`:
`slope_low` entspricht dem schnelleren Verschleiß → früherer Schwellenwert.

Für die Instandhaltungsplanung ist `km_warn_conservative` / `km_limit_conservative`
der maßgebliche Planungstermin; der Medianwert ist der Erwartungswert.

### 7.4 Optionaler Power-Law-Fit

Wenn `RMSE_linear > RMSE_THRESHOLD_MM` (Standard: 0.5 mm) und mindestens 6 Punkte
nach Filter vorhanden sind, wird versucht, das Modell

```
lkd(km) = last_lkd − b × (km − last_km)^c
```

mit `scipy.optimize.curve_fit` zu fitten. Nur wenn der resultierende RMSE
**kleiner** als `RMSE_linear` ist, wird das Power-Law-Modell übernommen.

Das konservative Szenario wird auch beim Power-Law-Modell immer aus dem
Theil-Sen-KI abgeleitet (Power-Law-Fit hat kein analytisches KI).

---

## 8. Ausgaben

### 8.1 Datenbankausgabe (wenn `use_database=true` und `write_prog_data=true`)

Tabelle `BO_RADSATZDATEN_PROGNOSE` — Schema identisch zum Vorgängerprogramm:

| Spalte | Typ | Inhalt |
|--------|-----|--------|
| `TOPEINHEITID` … `AKTUELL` | — | Fahrzeug-Metadaten (aus Messdaten) |
| `ZAEHLERARTID`, `ZARTBEZ` | — | Zählertyp |
| `STAND` | NUMBER | LKD-Prognosewert [mm] |
| `DATUM` | DATE | Prognosedatum |
| `LAUFLEISTUNG` | NUMBER | Prognose-Laufleistung [km] |
| `LETZTEAENDZEIT` | DATE | Zeitstempel der Berechnung |
| `KM_WARNWERT` | NUMBER | Laufleistung bei GELB_MIN [km] |
| `DATUM_WARNWERT` | DATE | Geschätztes Datum bei GELB_MIN |
| `KM_GRENZWERT` | NUMBER | Laufleistung bei MIN [km] |
| `DATUM_GRENZWERT` | DATE | Geschätztes Datum bei MIN |

Vor dem Schreiben werden Einträge gelöscht, deren `LETZTEAENDZEIT` älter als
`n_days_2_delete` Tage ist.

### 8.2 CSV-Ausgabe (wenn `use_database=false` und `write_prog_data=true`)

Datei: `bo_radsatzdaten_prognose_recalc.csv` (konfigurierbar via `csv_bo_prognose_out`).  
Trennzeichen: `;`, Encoding: UTF-8 mit BOM.  
Spaltenreihenfolge: identisch zu Abschnitt 8.1.

Datumsformat: `YYYY-MM-DD HH:MM:SS`  
Zahlenformat: Dezimalpunkt (`.`), 2 Nachkommastellen für LKD und km-Werte.

### 8.3 Diagramme (wenn `show_plot=true`)

Pro Fahrzeugachse ein Matplotlib-Diagramm mit Messdaten, Prognoselinien,
Konfidenzband und Schwellenwert-Annotationen.

- Fensteranzeige: wenn `plot_show_window=true`
- PNG-Export: wenn `plot_output_dir` gesetzt; Dateiname: `prognose_new_<key>.png`

Zusätzliche Dateien:
- `plot_manifest_<methoden>.csv` mit Plot-Reihenfolge (`TOPEINHEITBEZEICHNUNG`, DG, Achse)
  zur Vergleichbarkeit zwischen Läufen/Methoden.

---

## 9. Logging und Qualitätsflags

### 9.1 Log-Datei

Konfigurierbar via `log_file` (Standard: `Prog_Radsatzdaten.log` im Skriptverzeichnis).  
Format: `YYYY-MM-DD HH:MM:SS LEVEL Meldung`

### 9.2 Qualitätsflags

Jede Achse erhält ein Qualitätsflag, das ins Log geschrieben wird:

| Flag | Bedingung | Auswirkung |
|------|-----------|-----------|
| `OK` | ≥ `MIN_POINTS_QUALITY` Punkte nach Filter | Prognose wird normal ausgegeben |
| `LOW` | ≥ `MIN_POINTS_FIT`, aber < `MIN_POINTS_QUALITY` | Prognose wird ausgegeben, Warnung im Log |
| `INSUFFICIENT` | < `MIN_POINTS_FIT` Punkte | Keine Prognose; kein Eintrag in DB/CSV |

### 9.3 Log-Einträge pro Achse

Für jede Achse mit valider Prognose wird geloggt:

```
INFO  Fit: LINEAR | slope=-0.0412 [mm/km] | slope_low=-0.0589 | RMSE=0.312 mm |
      n_fit=14 | n_outliers=1 | quality=OK | cycle=HEURISTIC | <key>_LKD1
INFO  Prognose: km_warn=185400 km_limit=223700 km_warn_konservativ=174200
      km_limit_konservativ=208600 | <key>_LKD1
```

### 9.4 Weitere Log-Ereignisse

| Ereignis | Level | Meldung |
|----------|-------|---------|
| Start / Ende | INFO | `=== ... gestartet ===` / `=== ... beendet ===` |
| Ausreißer entfernt | INFO | `IQR-Filter: N Ausreißer entfernt ...` |
| Power-Law gewählt | INFO | `Power-Law gewählt (RMSE_lin=X > RMSE_pow=Y) ...` |
| Zu wenig Punkte | WARNING | `QUALITY=INSUFFICIENT: nur N Punkte ...` |
| Unvollständige DB-Zeile | WARNING | `Zählerdaten unvollständig: ...` |
| Fehlender Achsschlüssel | WARNING | `Achsschlüssel fehlt im Dictionary: ...` |
| Ausnahmefehler Prognose | ERROR | `Prognose fehlgeschlagen für: ...` (mit Traceback) |

---

## 10. Fehlerbehandlung

| Situation | Behandlung |
|-----------|-----------|
| `scipy` nicht installiert | `ImportError` mit Installationshinweis beim Start |
| `oracledb` nicht installiert | `ImportError` mit Installationshinweis beim Start |
| CSV nicht lesbar | `SystemExit` mit Pfadangabe |
| Oracle-Verbindungsstring fehlt | `SystemExit` mit Pfadangabe |
| km nicht monoton steigend | Warnung; automatische Sortierung nach km |
| < `MIN_POINTS_FIT` Punkte im Zyklus | `QUALITY_INSUFFICIENT`, kein Eintrag |
| < `MIN_POINTS_FIT` nach IQR-Filter | `QUALITY_INSUFFICIENT`, kein Eintrag |
| Power-Law-Fit konvergiert nicht | Fallback auf lineares Modell, kein Fehler |
| `slope ≥ 0` (kein Verschleiß) | Schnittpunkt = `None`, kein Eintrag für Schwelle |
| Beliebige Exception in `_calc_prognosis_axis` | propagiert zum `try/except` der Hauptschleife → `logging.exception`, Achse überspringen |

---

## 11. Unterschiede zum Vorgängerprogramm

| Aspekt | `Radsatz_Bahn_DB_KM_Default_Class_All.py` | `Radsatz_Bahn_DB_new_Approach.py` (Rev. 2) |
|--------|------------------------------------------|-----------------------------------|
| **Fitverfahren** | Gauss-Newton, Exponentialform `a₁ − e^(a₂·x)` | Theil-Sen (robust linear); Power-Law optional |
| **Methodenwahl** | fest auf Gauss | `theil_sen`, `gauss` oder kombiniertes `theil_sen, gauss` |
| **Default-Kurven-Mix** | Synthetische Datenpunkte vor Fit eingemischt | Entfällt vollständig |
| **Startparameter** | `a = [10, 0.03]`, maxstep=30, kein Konvergenzcheck | Kein iterativer Algorithmus |
| **Ausreißerbehandlung** | Keine | IQR-Filter (Faktor konfigurierbar) |
| **Unsicherheit** | Nur Punktwert | 90%-KI → konservative Rest-km |
| **daysPerKm** | Erster-zu-letzter Punkt; Verwurf bei > Standard | Median paarweiser Raten, kein Verwurf |
| **Zyklusstart** | Sprungdetektion (heuristisch) | Sprungdetektion (heuristisch) + EVENT-Pfad vorbereitet |
| **Qualitätskennzeichnung** | Nicht vorhanden | OK / LOW / INSUFFICIENT im Log |
| **Plot** | Messlinie + Prognoselinie + Schwellen | Harmonisiert: gleiche Basisdarstellung für alle Methoden; KI-Band nur bei Theil-Sen |
| **Ausfallverhalten** | Achse fällt bei Fehler aus | Mehrmethoden-Fallback: Plot mit verbleibend erfolgreicher Methode |
| **DB-Schnittstelle** | BO_RADSATZDATEN_PROGNOSE | Identisch; kompatibel |
| **Neue Abhängigkeit** | — | `scipy` (theilslopes, curve_fit) |
| **Gauss-Parameter in INI** | zentral | In Rev. 2 bei `prognosis_method=gauss` aktiv genutzt |
| **Neue Fallback-Option** | — | optional `baureihe_fallback=true` für Theil-Sen bei `INSUFFICIENT` |
| **Fehlende Schnittpunkte** | nicht explizit behandelt | `0.0` in MeterList; VehicleAxis filtert korrekt per `> 0`-Prüfung vor DB-Insert |

---

## 12. Erweiterungsmöglichkeiten

### 12.1 Konfiguration der neuen Parameter in `radsatz_config.ini`

Ist bereits umgesetzt: relevante Parameter liegen in `[prognose_new]`.
Erweiterungspotenzial besteht in:
- methodenspezifischen Schaltern (z. B. separates Plot-/Exportverhalten je Methode),
- eigener Sektion für Mehrmethodenbetrieb (Prioritäten, Mindestanforderungen).

### 12.2 Reprofilierungsereignisse als Zyklusstart

`_calc_prognosis_axis` enthält den Platzhalter `cycle_source = "HEURISTIC"`.
Wenn ZEDAS Instandhaltungsereignisse bereitstellt, kann hier ein EVENT-Pfad ergänzt
werden, der das letzte dokumentierte Reprofilierungsereignis als Zyklusstart nutzt
(Logging: `CYCLE_SOURCE = EVENT`).

### 12.3 Konservative Werte in Datenbank schreiben

Aktuell werden nur Medianwerte in `BO_RADSATZDATEN_PROGNOSE` geschrieben.
`_PrognResult` enthält `km_warn_conservative` und `km_limit_conservative`;
nach Erweiterung des DB-Schemas könnten diese als zusätzliche Spalten
(`KM_WARNWERT_KONSERVATIV`, `KM_GRENZWERT_KONSERVATIV`) gespeichert werden.

### 12.4 Backtesting

Für abgeschlossene Zyklen (dokumentierte Reprofilierung) kann der prognostizierte
Rest-km zum Zeitpunkt eines vergangenen Datums mit dem tatsächlich gefahrenen
Rest-km verglichen werden. Empfohlene Metrik: Mittlerer absoluter Fehler (MAE)
in km und Prozent des tatsächlichen Restwegs.

---

## 13. Änderungen seit Rev. 1

### 13.1 Methodenumschaltung per INI

- `prognosis_method` unterstützt jetzt:
  - `theil_sen`
  - `gauss`
  - `theil_sen, gauss` (Kombimodus)

### 13.2 Kombimodus (beide Methoden im selben Plot)

- Beide Methoden werden pro Achse berechnet.
- Historische Daten werden nur einmal gezeichnet.
- Beide Prognoseverläufe werden überlagert dargestellt.

### 13.3 Robustes Verhalten bei Teilfehlern

- Wenn eine Methode für eine Achse ausfällt, wird die andere weiterhin genutzt.
- Plot wird erzeugt, sobald mindestens eine Methode erfolgreich ist.

### 13.4 Plot-Harmonisierung

- Einheitliche Titel-/Legendenstruktur über Methoden hinweg.
- Für Gauss werden keine Theil-Sen-KI-Bänder gezeichnet.
- Stabile Achsenreihenfolge + Plot-Manifest (`plot_manifest_*.csv`).

### 13.5 Optionaler Theil-Sen-Baureihen-Fallback

- Neuer Schalter `[prognose_new] baureihe_fallback = true|false`.
- Bei `INSUFFICIENT` kann optional ein mittlerer Baureihen-Anstieg zur
  Ersatzprognose verwendet werden.
- Standard ist `false`.

### 13.6 Konfigurations-/Modulstand

- Neue/erweiterte Module: `prognosis_gauss.py`, `radsatz_axis_labels.py`,
  `radsatz_csv_io.py`, `radsatz_matplotlib.py`, `reprof_learning.py`.
- `radsatz_settings.py` unterstützt Methodenliste (`prognosis_methods`)
  und zusätzliche Plot-/Fallback-Schalter.

### 13.7 Datums-Speicherung auf `numpy.datetime64` umgestellt (Rev. 5)

- `MeterList.nDates` und `MeterList.nDatesProg` sind im neuen Ansatz jetzt
  `numpy.ndarray[datetime64[s]]` (statt Liste von Matlab-Datezahl-Floats).
- `MeterList.gelb_min_Prog_dt` / `min_Prog_dt` sind `numpy.datetime64`-Skalare
  (oder `NaT` für „kein Wert"); der bisherige `0.0`-Sentinel für Datums-Felder
  entfällt im neuen Pfad.
- Neues Helper-Modul `dates_np.py`:
  - `to_datetime64_array(dates)` — Liste von Python-`datetime` → `np.datetime64[s]`-Array
  - `to_python_datetime(dt)` — `np.datetime64` / `NaT` / `0` → Python-`datetime` (oder `None`)
  - `add_days(dt64, days)`, `days_to_timedelta64(days)`, `timedelta64_to_days(td)`,
    `is_nat(x)`, `NAT`
- Berechnungen:
  - `_calc_days_per_km_robust` und `_calc_days_per_km_from_meter` arbeiten auf
    `timedelta64`-Differenzen statt Float-Differenzen.
  - Datum-Prognose: `last_date + days_to_timedelta64((km − last_km) · days_per_km)`.
  - `VehicleAxis.calcnDatesProg` rechnet intern in Float-Sekunden-seit-Epoche
    (für `findXforY`-Interpolation) und konvertiert das Ergebnis zurück zu
    `np.datetime64[s]`. `calcDaysPerKm` nutzt `timedelta64_to_days` für die
    Tage/km-Schätzung.
  - `VehicleAxis.eliminateJump` (Legacy-Gauss-Reprofilierungs-Erkennung) erkennt
    `datetime64` automatisch und rechnet weiter in Float-Tagen (mathematisch
    identisch zur alten matlabdn-Logik).
- DB-Boundary: `VehicleAxis._prognose_insert_tuples_for_meter` nutzt
  `to_python_datetime()` statt `matlabdn2datetime()`; alle DATUM-Spalten im
  Insert-Tupel sind native `datetime.datetime` (oracledb-kompatibel).
- `datetime2matlabdn.py` bleibt unverändert erhalten — wird nur noch von den
  Legacy-Skripten `Radsatz_Bahn_DB_KM_Gauss_Class_All*.py` verwendet.
- Test: `test_db_insert_types.py` simuliert den DB-Insert-Pfad mit einem
  Mock-Cursor und prüft Typ-Korrektheit aller Insert-Tupel beider Methoden.

**Motivation:** Saubere Trennung von „kein Wert" (NaT) und „echter 0-Wert",
Wegfall des Schaltjahr-0-Offsets (`+366 days`) der Matlab-Datezahl, bessere
Lesbarkeit der Zwischenwerte (datetime64 lässt sich in numpy direkt anzeigen).

---

*Ende der Dokumentation.*
