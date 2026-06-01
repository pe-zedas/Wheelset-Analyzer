# Programmdokumentation: Radsatz_Bahn_DB_new_Approach.py

Stand: 2026-05-28, Rev. 2 (Methodenumschaltung, Kombimodus, Fallbacks, Plot-Harmonisierung)  
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

### 1.1 Aufgabe

Das Programm liest Radsatz-Messdaten (Laufkreisdurchmesser LKD1 und LKD2) aus einer Oracle-Datenbank
(`BO_RADSATZDATEN`) oder einem CSV-Export und berechnet für jede aktuell eingebaute Achse eine
Verschleißprognose. Ausgegeben werden:

- voraussichtliche **Laufleistung** (km) bis zur **Warnschwelle** (GELB_MIN) und zum **Grenzwert** (MIN)
- zugehörige **Datumsschätzungen**
- ein optionaler **konservativer Schätzwert** (pessimistisches Konfidenzintervall)

Das Ergebnis wird in `BO_RADSATZDATEN_PROGNOSE` (Datenbank) oder in eine CSV-Datei geschrieben.

### 1.2 Abgrenzung zum Vorgängerprogramm

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

### 2.3 Benötigte Dateien im Projektverzeichnis

| Datei | Pflicht | Beschreibung |
|-------|---------|-------------|
| `radsatz_config.ini` | ja | Konfigurationsparameter (siehe Abschnitt 3) |
| `bo_radsatzdaten_export.csv` | wenn `use_database=false` | Messdaten-Export |
| `oracle_connect_string.txt` | wenn `use_database=true` | Oracle-Verbindungsstring |
| `VehicleAxis.py` | ja | Datenhaltungsklasse |
| `MeterList.py` | ja | Datenhaltungsklasse |
| `radsatz_settings.py` | ja | Config-Loader |
| `datetime2matlabdn.py` | ja | Datum-Konvertierung |
| `toolsWheelset.py` | ja | Zykluserkennung |

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
├── datetime2matlabdn.py                 ← Datum ↔ Matlab-Datezahl
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
   │ 6. Schnittpunkte     │
   │ 7. daysPerKm (Median)│
   │ 8. Datum-Prognose    │
   │ 9. MeterList setzen  │
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
| 10 | Datum-Prognose (km → Matlab-Datezahl) |
| 11 | Alle Ergebnisse in `MeterList` schreiben |

**Felder, die in `MeterList` geschrieben werden:**

| Setter | Inhalt |
|--------|--------|
| `setkmProg` | km-Werte der Prognosekurve |
| `setvaluesProg` | LKD-Werte der Prognosekurve [mm] |
| `setnDatesProg` | Matlab-Datezahlen der Prognosekurve |
| `setgelb_min_Prog_km` | km bei GELB_MIN-Schnittpunkt (Median); **`0.0` wenn kein Schnittpunkt** |
| `setmin_Prog_km` | km bei MIN-Schnittpunkt (Median); **`0.0` wenn kein Schnittpunkt** |
| `setgelb_min_Prog_dt` | Matlab-Datezahl bei GELB_MIN-Schnittpunkt; `0.0` wenn nicht berechenbar |
| `setmin_Prog_dt` | Matlab-Datezahl bei MIN-Schnittpunkt; `0.0` wenn nicht berechenbar |

> **Hinweis zu `0.0` als Fehlerwert:** `MeterList` kennt keinen `None`-Typ für
> numerische Felder. Fehlende Schnittpunkte werden daher als `0.0` gespeichert.
> `VehicleAxis._prognose_insert_tuples_for_meter` prüft vor jedem DB-Insert
> `if value > 0`, sodass `0.0` korrekt als „kein Wert" behandelt wird und kein
> `NULL`-Fehler im Insert entsteht.

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

---

*Ende der Dokumentation.*
