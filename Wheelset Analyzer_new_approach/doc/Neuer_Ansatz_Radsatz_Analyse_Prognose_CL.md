# Verbesserter Ansatz: Analyse und Prognose von Radsatzdaten (VGF / ZEDAS)

Stand: 2026-05-12 — erstellt auf Basis Codeanalyse (`Radsatz_Bahn_DB_KM_Default_Class_All.py`,
`VehicleAxis.py`, `GaussNewtonLinearReg_Exp.py`, `toolsWheelset.py`) und bestehender Konzeptdokumentation.

---

## 1. Zweck und Geltungsbereich

**Ziel:** Den **Verschleißverlauf** an Radsätzen (Laufkreisdurchmesser LKD1/LKD2) **analysieren** und
die **Reststrecke** bis zu **Warn- und Grenzwerten** in Laufleistung (km) und Datum abschätzen.
Vorrang haben **Erklärbarkeit**, **Robustheit bei Ausreißern und Datenlücken** sowie die saubere
Abbildung von Instandhaltungsereignissen (Reprofilierung, Achstausch).

**Geltung:** Eingangsdaten aus `BO_RADSATZDATEN` (oder gleichwertiger CSV-Export); Ausgabe weiterhin
kompatibel zu `BO_RADSATZDATEN_PROGNOSE`. Bestehende DB-Schnittstelle bleibt unverändert; optionale
Erweiterungsfelder für Konfidenzgrenzen sind vorgesehen, aber nicht zwingend.

**Nicht-Ziel:** Black-Box-Machine-Learning ohne fachliche Nachvollziehbarkeit. Bei typisch 10–50
Messpunkten pro Achse und Zyklus ist kein ML-Verfahren ohne separaten, validierten Trainingsdatensatz
anderer Achsen methodisch vertretbar.

---

## 2. Schwachstellenanalyse des bisherigen Ansatzes

### 2.1 Default-Kurven-Mischung (größtes Problem)

In `VehicleAxis.CalcPrognostic()` wird vor dem Gauss-Newton-Fit eine synthetische Default-Kurve
(aus `defParamExp`) mit den realen Messdaten **konkateniert**:

```python
pqNew = np.concatenate((pqArray, pq), axis=1)   # Default-Kurve + Messdaten gemischt
```

Dies ist kein statistisch fundiertes Regularisierungsverfahren. Bei wenigen Messpunkten im aktuellen
Zyklus (3–6 Punkte nach Reprofilierung) dominieren die synthetischen Default-Punkte den Fit
vollständig. Das Ergebnis ist keine Schätzung aus den Daten, sondern eine erzwungene Kurvenform.
Die Qualität der Prognose hängt dann primär von der Güte der manuell gewählten Default-Parameter ab.

### 2.2 Fixe Exponentialform

`GaussNewtonLinearReg_ExpNorm` fittet immer `y = a₁ - e^(a₂·x)` mit fixen Startwerten `a = [10, 0.03]`.
Realer Radreifenverschleiß ist im mittleren und späten Zyklusbereich **oft annähernd linear**
(konstante mm/km). Eine erzwungene Exponentialform erzeugt bei schwacher Krümmung instabile
Parameterschätzungen und physikalisch unsinnige Extrapolationen.

### 2.3 Keine Ausreißerbehandlung

Zwischen Datenladen und Fit gibt es keinen Filterungsschritt. Ein einzelner Messfehler oder
Datenbankfehler verändert den Fit erheblich – besonders kritisch bei wenigen Punkten pro Zyklus.

### 2.4 Gauss-Newton ohne Konvergenzprüfung

`maxstep = 30` – bricht der Algorithmus vor Erreichen der Toleranz `tol = 1e-8` ab, wird der
letzte Iterationsstand **stillschweigend** als Ergebnis verwendet. Ein nicht konvergierter Fit
ist nicht von einem konvergierten unterscheidbar.

### 2.5 daysPerKm-Logik systematisch verzerrt

```python
if nDays / tmpKm < self.getdaysPerKm():   # nur akzeptiert wenn kleiner als Standardwert
    self.setdaysPerKm(nDays / tmpKm)
```

Ein berechneter Wert wird nur übernommen, wenn er kleiner als der Standardwert 0.01 Tage/km ist.
Höhere Werte (langsamer Betrieb, seltene Nutzung) werden verworfen und durch den Standardwert
ersetzt. Das verzerrt die Datumsprognose systematisch in Richtung intensiverer Nutzung.

### 2.6 Keine Unsicherheitsquantifizierung

Die Prognose liefert einen Punktwert für KM_WARNWERT und KM_GRENZWERT. Im instandhaltungsrelevanten
Kontext (Sicherheitsrelevanz, Ressourcenplanung) fehlt ein konservatives Szenario (pessimistische
Rest-km). Kurze Messreihen und streuende Daten führen ohne Qualitätskennzeichnung zu scheinbar
gleich zuverlässigen Prognosewerten wie lange, stabile Reihen.

### 2.7 Zykluserkennung rein heuristisch

`getStartIndexLastCycle()` sucht positive Sprünge im STAND-Verlauf über der Laufleistung.
Fragil bei: Messrauschen nahe dem Schwellwert `diffLKD`, mehreren kleinen Reprofilierungsschritten,
oder fehlenden Messungen um den Reprofilierungszeitpunkt herum. Es gibt keine Unterscheidung,
ob der Zyklusstart aus einem dokumentierten Ereignis oder aus der Heuristik stammt.

---

## 3. Leitprinzipien des verbesserten Ansatzes

1. **Kein Default-Mix:** Der Trend wird ausschließlich aus den realen Messdaten des aktuellen
   Zyklus geschätzt. Externe Formvorgaben entfallen.
2. **Modell folgt Daten:** Linearer Verschleiß als Primärmodell; nicht-linearer Fit nur, wenn
   die Daten das rechtfertigen (Modellvergleich via RMSE).
3. **Robustheit vor Genauigkeit:** Ein robustr Schätzer mit nachgewiesener Ausreißertoleranz
   ist zuverlässiger als ein präziser Schätzer ohne Ausreißerschutz.
4. **Unsicherheit sichtbar:** Kurze oder streuende Messreihen führen zu breiteren Intervallen
   und expliziten Qualitätsflags im Log; Punkttermine ohne Band werden nur bei ausreichend langer
   Datenbasis ausgegeben.
5. **Ereignis vor Heuristik:** Reprofilierungsereignisse aus ZEDAS (sofern verfügbar) als primäre
   Zyklusgrenze; Sprungdetektion nur als Fallback.
6. **Auditierbarkeit:** In Logs und optionalen Metadaten ist erkennbar, welches Modell verwendet
   wurde, wie viele Punkte nach Ausreißerfilter verblieben und ob der Zyklusstart aus Ereignis
   oder Heuristik stammt.

---

## 4. Datenbasis und Filter

Unverändert gegenüber bisherigem System:

- **Identifikation:** `TOPEINHEITBEZEICHNUNG`, `DGEINBAUPOS`, `RSEINBAUPOS`; Messart `ZARTBEZ` / `ZAEHLERARTID`
- **Zeitreihe:** `DATUM`, `LAUFLEISTUNG`, `STAND`
- **Schwellen:** `GELB_MIN`, `MIN`, `MAX`
- **Lebenszyklus:** `EINBAU`, `AUSBAU`, `AKTUELL`
- **Zeitlicher Ausschnitt:** konfigurierbares `dt_start_data`

Neu: Mindestanzahl Messpunkte **im aktuellen Zyklus** vor dem Fit (Konfigurationsparameter
`min_points_fit`, Empfehlung: 4). Achsen mit weniger Punkten werden mit Qualitätsflag
`QUALITY = LOW` geloggt; keine Prognose, oder nur Prognose mit explizitem Warnhinweis.

---

## 5. Zykluserkennung

### 5.1 Primär: Reprofilierungsereignis aus ZEDAS

Sofern ZEDAS Instandhaltungsereignisse mit Ereignistyp „Reprofilierung" oder „Achstausch"
bereitstellt und diese über `RSEINHEITID` verknüpfbar sind, gilt das letzte solche Ereignis
als Zyklusstart. Dieser Pfad ist im Log als `CYCLE_SOURCE = EVENT` zu kennzeichnen.

### 5.2 Fallback: Sprungdetektion

Bleibt methodisch identisch zu `getStartIndexLastCycle()` (positiver Sprung im STAND über `diffLKD`).
Erweiterungen:

- Prüfung, ob der detektierte Sprung plausibel ist (Betrag zwischen `diffLKD` und `max_reprof_jump`,
  konfigurierbar), um Messrauschen von echten Reprofilierungen zu trennen.
- Log-Eintrag `CYCLE_SOURCE = HEURISTIC` mit Angabe des gefundenen Sprungwerts.

### 5.3 Validierung

Nach Zyklusstart-Bestimmung: Prüfe `len(km[nIndex:]) >= min_points_fit`. Falls nicht erfüllt:
Prognose verwerfen, Warning loggen.

---

## 6. Ausreißerfilter

Vor dem Fit wird ein IQR-basierter Ausreißerfilter angewendet:

```python
# 1. Vorläufige lineare Regression für Residuenberechnung
coeffs = np.polyfit(km_cycle, lkd_cycle, deg=1)
residuals = lkd_cycle - np.polyval(coeffs, km_cycle)

# 2. IQR-Filter
q25, q75 = np.percentile(residuals, [25, 75])
iqr = q75 - q25
mask = np.abs(residuals) <= 2.0 * iqr

km_clean   = km_cycle[mask]
lkd_clean  = lkd_cycle[mask]
n_removed  = np.sum(~mask)

if n_removed > 0:
    logging.info("Ausreißerfilter: %d Punkte entfernt für %s", n_removed, axis_key)
```

Der Faktor 2.0 ist konfigurierbar (`iqr_factor`). Entfernte Punkte werden **geloggt, nicht gelöscht**;
die Originaldaten bleiben in der MeterList erhalten.

---

## 7. Stufe A – Trendschätzung (Verschleißrate)

### 7.1 Primärmodell: Theil-Sen-Schätzer (robust linear)

```python
from scipy.stats import theilslopes

result = theilslopes(
    y   = lkd_clean,
    x   = km_clean,
    alpha = 0.90          # 90%-Konfidenzintervall auf die Steigung
)

slope_median = result.slope        # Verschleiß [mm/km], Punktwert
slope_low    = result.low_slope    # pessimistisch (schnellerer Verschleiß)
slope_high   = result.high_slope   # optimistisch
intercept    = result.intercept
```

**Warum Theil-Sen:**
- Median aller paarweisen Steigungen → robust gegen bis zu ~29 % Ausreißer
- Keine Konvergenzprobleme, keine Startparameter, kein Default-Mix
- Liefert analytisches Konfidenzintervall auf die Steigung
- In `scipy.stats` standardmäßig vorhanden, keine zusätzliche Abhängigkeit

### 7.2 Optionales Sekundärmodell: Power-Law-Fit

Falls der Verschleiß klare Krümmung zeigt (RMSE des linearen Fits > Schwellwert `rmse_threshold`):

```python
from scipy.optimize import curve_fit

def power_wear(km, a, b, c):
    return a - b * (km ** c)

popt, pcov = curve_fit(
    power_wear, km_clean, lkd_clean,
    p0=[lkd_clean[0], 1e-5, 1.0],   # c=1 → linear als Startwert
    maxfev=2000
)
```

Modellwahl: lineares Modell gewinnt, wenn sein RMSE ≤ RMSE des Power-Law-Fits. Das vermeidet
unnötige Komplexität. Der Modellname wird geloggt (`MODEL = LINEAR` oder `MODEL = POWER`).

---

## 8. Stufe B – Prognose (Warn- und Grenzwert)

### 8.1 Schnittpunktberechnung

Für das lineare Modell ergibt sich der Schnittpunkt mit einer Schwelle `y_thresh` direkt:

```python
def km_to_threshold(last_km, last_lkd, slope, y_thresh):
    if slope >= 0:
        return None          # kein Verschleiß → kein Schnittpunkt
    rest_km = (last_lkd - y_thresh) / (-slope)
    return last_km + rest_km
```

Ausgaben:

| Größe | Berechnung | DB-Feld |
|-------|-----------|---------|
| KM_WARNWERT (Punkt) | Steigung `slope_median` → GELB_MIN | `KM_WARNWERT` |
| KM_WARNWERT (konservativ) | Steigung `slope_low` → GELB_MIN | optional: Erweiterungsfeld |
| KM_GRENZWERT (Punkt) | Steigung `slope_median` → MIN | `KM_GRENZWERT` |
| KM_GRENZWERT (konservativ) | Steigung `slope_low` → MIN | optional: Erweiterungsfeld |

Für die Instandhaltungsplanung empfiehlt sich, den **konservativen Wert** (`slope_low`) als
primären Planungstermin zu verwenden und den Punktwert als Erwartungswert auszuweisen.

### 8.2 Datum-Prognose (km → Datum)

```python
# Paarweise Raten: alle benachbarten Messpunkte im aktuellen Zyklus
dk = km_cycle[1:] - km_cycle[:-1]
dd = date_num_cycle[1:] - date_num_cycle[:-1]
valid = dk > 0
rates = dd[valid] / dk[valid]          # Tage/km, paarweise
days_per_km = float(np.median(rates))  # Median: robust gegen Betriebsunterbrechungen
```

Der Median der paarweisen Raten ersetzt den bisherigen Vergleich erster-zu-letzter Punkt mit
asymmetrischem Verwurf. Damit werden Betriebsunterbrechungen (Revisionen, saisonale Pausen)
korrekt und ohne systematische Verzerrung abgebildet.

Datum-Schätzung:

```python
datum_warnwert  = last_date + timedelta(days = rest_km_warn  * days_per_km)
datum_grenzwert = last_date + timedelta(days = rest_km_limit * days_per_km)
```

### 8.3 Prognosepunkte für DB/CSV

Die Prognosekurve wird wie bisher als Punktfolge gespeichert. Sie folgt der Trendgerade:

```python
km_prog   = np.linspace(last_km, km_grenzwert + n_km_buffer, num=20)
lkd_prog  = intercept + slope_median * km_prog
```

Reprofilierungsschritte können optional wie bisher über `insertReprofiling` eingebaut werden,
sofern `nKmRepro` und `nValueRepro` konfiguriert sind. Dabei ist darauf zu achten, dass
periodische Reprofilierungen als **Annahme** (nicht als Prognose) kenntlich gemacht werden.

---

## 9. Qualitätsflags und Logging

Für jede Achse / jeden Zähler wird folgendes geloggt:

| Feld | Wert | Bedeutung |
|------|------|-----------|
| `CYCLE_SOURCE` | `EVENT` / `HEURISTIC` | Zyklusstart-Quelle |
| `MODEL` | `LINEAR` / `POWER` | verwendetes Verschleißmodell |
| `N_POINTS_FIT` | Integer | Anzahl Punkte nach Ausreißerfilter |
| `N_OUTLIERS` | Integer | entfernte Ausreißer |
| `QUALITY` | `OK` / `LOW` / `INSUFFICIENT` | Datenqualität |
| `SLOPE_UNIT` | `mm/km` | Einheit der Verschleißrate |

`QUALITY = INSUFFICIENT` → Prognose wird nicht in DB/CSV geschrieben.
`QUALITY = LOW` → Prognose wird geschrieben, aber mit explizitem Log-Hinweis.

Schwellen (konfigurierbar):
- `INSUFFICIENT`: weniger als `min_points_fit` Punkte nach Filter
- `LOW`: weniger als `min_points_quality` Punkte (Empfehlung: 8) oder RMSE > `rmse_quality_threshold`

---

## 10. Schnittstelle zur Datenbank (unverändert kompatibel)

Das Zielschema `BO_RADSATZDATEN_PROGNOSE` bleibt unverändert:

```
TOPEINHEITID, TOPEINHEITBEZEICHNUNG, DGEINHEITID, DGBEZEICHNUNG, DGEINBAUPOS,
RSEINHEITID, RSBEZEICHNUNG, RSEINBAUPOS, EINBAU, AUSBAU, AKTUELL,
ZAEHLERARTID, ZARTBEZ,
STAND, DATUM, LAUFLEISTUNG, LETZTEAENDZEIT,
KM_GRENZWERT, DATUM_GRENZWERT, KM_WARNWERT, DATUM_WARNWERT
```

**Empfohlene optionale Erweiterung** (ohne bestehende Auswertungen zu brechen):
Zusätzliche Spalten oder Nebentabelle für:
- `KM_WARNWERT_KONSERVATIV`, `DATUM_WARNWERT_KONSERVATIV`
- `KM_GRENZWERT_KONSERVATIV`, `DATUM_GRENZWERT_KONSERVATIV`
- `PROGNOSE_QUALITAET` (VARCHAR: OK / LOW / INSUFFICIENT)
- `PROGNOSE_MODELL` (VARCHAR: LINEAR / POWER)

---

## 11. Vergleich bisheriger vs. verbesserter Ansatz

| Aspekt | Bisheriger Ansatz | Verbesserter Ansatz |
|--------|-------------------|---------------------|
| **Fitverfahren** | Gauss-Newton, Exponentialform fix | Theil-Sen (robust linear); Power-Law optional bei Bedarf |
| **Default-Kurven-Mix** | Ja – synthetische Punkte eingemischt | Entfällt vollständig |
| **Startwerte / Konvergenz** | `a = [10, 0.03]`, max 30 Iterationen, kein Konvergenzcheck | Kein iteratives Verfahren (Theil-Sen: exakt) |
| **Ausreißer** | Keine Behandlung | IQR-Filter (Faktor konfigurierbar), geloggt |
| **Unsicherheit** | Kein Band, nur Punktwert | 90%-KI auf Steigung → konservative Rest-km |
| **daysPerKm** | Erster-zu-letzter Punkt, asymmetrischer Verwurf | Median paarweiser Raten, kein Verwurf |
| **Konvergenzrisiko** | Stiller Abbruch nach maxstep | Entfällt |
| **Zyklusstart** | Sprungdetektion (heuristisch) | Ereignis bevorzugt; Sprung als Fallback; beides geloggt |
| **Qualitätskennzeichnung** | Nicht vorhanden | Qualitätsflag und N_POINTS_FIT im Log |
| **DB-Schnittstelle** | Bestehend | Unverändert; konservative Werte optional als Erweiterung |
| **Abhängigkeiten** | numpy, matplotlib, oracledb | + `scipy.stats.theilslopes` (bereits in scipy vorhanden) |

---

## 12. Einführung und Qualitätssicherung

1. **Unit-Tests:** `theilslopes`-Wrapper und Ausreißerfilter mit synthetischen Daten (bekannter
   Steigung, eingestreuten Ausreißern) testen; Schnittpunktberechnung gegen analytische Werte.
2. **Backtest:** Für abgeschlossene Zyklen (Reprofilierung dokumentiert): prognostizierter
   Rest-km zum Zeitpunkt X gegen tatsächlich gefahrenen Rest-km vergleichen.
3. **Pilotlauf:** Beide Verfahren (alt / neu) parallel auf denselben Daten ausführen; Differenz
   der KM_WARNWERT-Ausgaben auswerten; Fachbereich über systematische Abweichungen informieren.
4. **Parameter-Kalibrierung:** `min_points_fit`, `iqr_factor`, `rmse_threshold` auf Basis des
   Backtests einstellen; nicht auf Default-Werte verlassen.
5. **Betrieb:** Zentrales Logging aller Qualitätsflags; Alert bei hohem Anteil `INSUFFICIENT`-Achsen
   (deutet auf Datenproblem hin).

---

## 13. Abhängigkeiten und Anforderungen

| Paket | Version | Zweck |
|-------|---------|-------|
| `numpy` | ≥ 1.21 | Array-Operationen (unverändert) |
| `scipy` | ≥ 1.7 | `scipy.stats.theilslopes`, `scipy.optimize.curve_fit` |
| `matplotlib` | ≥ 3.4 | Darstellung (unverändert) |
| `oracledb` | ≥ 1.0 | Oracle-Anbindung (unverändert) |

`scipy` ist die einzige neue Abhängigkeit. Theil-Sen ist seit scipy 0.15 verfügbar.

---

## 14. Glossar

- **Theil-Sen-Schätzer:** Robuste Regressionsschätzung als Median aller paarweisen Steigungen
  zwischen Messpunkten. Robust gegen Ausreißer, keine Konvergenzvoraussetzung.
- **IQR (Interquartilsabstand):** Differenz zwischen 75. und 25. Perzentil der Residuen;
  dient als robustes Streuungsmaß für Ausreißerdetektion.
- **Konfidenzintervall (KI):** Bereich, der den wahren Parameter mit vorgegebener Wahrscheinlichkeit
  (hier 90 %) enthält; `slope_low` entspricht der pessimistischsten (schnellsten) Verschleißrate.
- **Verschleißzyklus:** Zeitraum zwischen zwei die LKD-Kurve zurücksetzenden Eingriffen.
- **Rest-km:** Differenz zwischen letzter beobachteter Laufleistung und der Laufleistung am
  Schnittpunkt des Trends mit einer Schwelle (GELB_MIN oder MIN).
- **daysPerKm:** Mittlere Tage pro km im aktuellen Zyklus; Umrechnung Rest-km → Datum.
- **RMSE:** Mittlerer quadratischer Fehler (Root Mean Squared Error); Maß für Fit-Güte.

---

*Ende des Dokuments.*
