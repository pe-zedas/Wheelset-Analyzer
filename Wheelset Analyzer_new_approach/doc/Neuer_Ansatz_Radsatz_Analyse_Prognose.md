# Neuer Ansatz: Analyse und Prognose von Radsatzdaten (VGF / ZEDAS)

Stand: überarbeitetes Konzeptpapier; Anbindung an ZEDAS-Tabellen entsprechend der Feldbelegung im Produktivcode bzw. CSV-Export.

---

## 1. Zweck und Geltungsbereich

**Ziel:** Den **Verschleißverlauf** an Radsätzen (hier insbesondere **Laufkreisdurchmesser LKD1/LKD2**) **analysieren** und die **Reststrecke** bis zu **Warn- und Grenzwerten** in **Laufleistung (km)** und **Datum** abschätzen. Vorrang sind **Erklärbarkeit**, **Robustheit bei Lücken und Ausreißern** sowie die saubere Abbildung von **Instandhaltungsereignissen** (z. B. Reprofilierung).

**Geltung:** Eingangsdaten aus `BO_RADSATZDATEN` (oder gleichwertiger CSV-Export); Ausgang weiterhin kompatibel zu `BO_RADSATZDATEN_PROGNOSE` (siehe Abschnitt 7), optional erweiterbar um Unsicherheitsgrößen.

**Nicht-Ziel:** Black-Box-Machine-Learning als alleinige Quelle für Grenztermine ohne fachliche und technische Nachvollziehbarkeit und ohne definierte Daten- und Abnahmepflichten.

---

## 2. Leitprinzipien

1. **Zyklusbasiert:** Prognose und Trend beziehen sich auf den **aktuellen Verschleißzyklus** (seit Reprofilierung bzw. seit letztem definierenden Eingriff).
2. **Ereignisse vor Heuristik:** **Reprofilierung / Achstausch** als erfasstes Ereignis in der Datenhaltung (ZEDAS), wenn vorhandig; **Sprungableitung** aus `STAND`/`LAUFLEISTUNG` nur als **Fallback** mit dokumentierter Plausibilitätsprüfung.
3. **Analyse getrennt von Prognose:** Zuerst **Ist-Trend** und Qualität der Datenlage im Zyklus; danach **Restweg** zu den Schwellen – keine Vermischung mit langfristiger „Schönrechnerei“ ohne Datenbasis.
4. **Prognose als Restweg:** Die Kernaussage ist „**noch wie viele km** bis Gelb bzw. bis untere Grenze“ und „**voraussichtliches Datum**“ (über Nutzungsintensität), nicht die Behauptung einer einzigen **Wahrheitskurve** weit über den gesicherten Datenbereich hinaus.
5. **Unsicherheit sichtbar machen:** Kurze oder streuende Messreihen führen zu **breiteren Intervallen** oder **Qualitätsflags**; Punkttermine ohne Band sind fachlich leicht überinterpretiert.
6. **Konsistente Schwellen:** Für Schnittpunkte gelten die **zuletzt gültigen** `GELB_MIN` und `MIN` der jeweiligen Messreihe (bzw. des zugehörigen Zählers), damit Anzeige, Report und Prognose zusammenpassen.

---

## 3. Datenbasis und Filter

Aus `BO_RADSATZDATEN` (bzw. Export mit gleicher Semantik):

- **Identifikation:** `TOPEINHEITBEZEICHNUNG`, `DGEINBAUPOS`, `RSEINBAUPOS`; Messart `ZARTBEZ` / `ZAEHLERARTID`.
- **Zeitreihe:** `DATUM`, `LAUFLEISTUNG`, `STAND`.
- **Schwellen:** `GELB_MIN`, `MIN`, `MAX` (für Darstellung und Zieldefinition; Prognoseschnittpunkte primär mit `GELB_MIN` und `MIN`).
- **Lebenszyklus:** `EINBAU`, `AUSBAU`, `AKTUELL` – nur **aktuell eingebaute** Achsen bzw. gefilterte Historie, konsistent zur Quelle.
- **Zeitlicher Ausschnitt:** konfigurierbares Startdatum (z. B. `dt_start_data`), um Altlasten zu begrenzen und Laufzeiten zu stabilisieren.

---

## 4. Zyklus und Instandhaltung

**Zyklusbeginn (bevorzugt):** Zeitpunkt des letzten dokumentierten Ereignisses **Reprofilierung** oder vergleichbarer Eingriff aus ZEDAS, der den LKD-Zyklus zurücksetzt.

**Zyklusbeginn (Fallback):** Letzter **signifikanter Sprung** im `STAND` entlang der `LAUFLEISTUNG` (parametrierbarer Schwellwert, vergleichbar heutigem `diff_lkd`), ergänzt um Plausibilität:

- innerhalb eines Zyklus sollte die **Laufleistung** nicht unkontrolliert fallen (Kontinuität);
- Ausreißer und Messlücken sollten die Zyklusgrenze nicht willkürlich verschieben (siehe robuste Trendstufe).

**Dokumentation:** In Logs oder Metadaten soll erkennbar sein, ob der Zyklusstart aus **Ereignis** oder **Sprungheuristik** stammt (Auditierbarkeit).

---

## 5. Stufe A – Analyse (Trend im aktuellen Zyklus)

### 5.1 Modellierung

- **Achse:** `LAUFLEISTUNG` (km) als unabhängige Größe, `STAND` (mm) als abhängige Größe; **nur Punkte ab Zyklusstart**.
- **Empfohlener Trend:** **robuster, glatter Trend** mit wenigen Freiheitsgraden, z. B.:
  - **Penalisierter Spline** oder **GAM** mit niedriger Komplexität, oder
  - **Theil–Sen** / **robuste Regression** als einfachere Alternative mit geringerem Implementationsaufwand.
- **Nicht als Standard:** eine **fixe Exponentialform** für alle Achsen, ggf. mit starkem Default-Einfluss – das ist für viele reale Verläufe zu starr und bei wenigen Punkten zu empfindlich.

### 5.2 Ausreißer und Lücken

- Vor dem Fit: **konservative** Ausreißerbehandlung (z. B. IQR/Median-Downweight oder M-Schätzer im Rahmen des gewählten Modells).
- **Lücken:** unregelmäßige Messabstände sind zulässig; sehr große Lücken oder zu wenige Punkte führen zu **keiner** oder nur **qualitätsgekennzeichneter** Prognose (siehe Abschnitt 9).

### 5.3 Ergebnis der Analyse

- Geschätzter Verlauf **ŷ(km)** im aktuellen Zyklus.
- **Unsicherheit:** z. B. **Bootstrap** der Residuen oder ein analytisches Näherungsband – abhängig von gewähltem Verfahren und verfügbarer Bibliothek.

---

## 6. Stufe B – Prognose (Warn- und Grenzwert)

### 6.1 Zielgrößen

- **Warnung:** Schnittpunkt des Trends mit der **aktuellen** `GELB_MIN` der Messreihe.
- **Grenzwert:** Schnittpunkt mit **`MIN`** (untere Grenze).

Ausgabe als **Rest-km** (Differenz von letzter Mess-Laufleistung zum Schwellen-km) und, über Nutzungsintensität, als **Datum**.

### 6.2 Unsicherheit

- Neben einem **Punktwert** (z. B. Median aus Bootstrap) **Intervalle** für Rest-km und Datum (untere/obere Grenze), sobald dies in Produktion gewünscht und technisch abbildbar ist.
- Bis dahin: mindestens **Qualitätskennzahl** oder **Begründung** bei Veröffentlichung im Log (z. B. „nur 3 Messpunkte im Zyklus“).

### 6.3 Umrechnung km → Datum

- **Robuste** Schätzung der Nutzungsintensität (z. B. **Tage pro km** aus dem **aktuellen Zyklus** oder einem gleitenden Fenster), nicht als unkritischer Globalwert.
- Datum der Fälligkeit: letztes Messdatum plus Rest-km multipliziert mit Tage/km; bei Unsicherheit des Trends entsprechend **Intervall**.

### 6.4 Szenarien (optional)

- **Basis:** Trend ohne weiteren Eingriff bis zur ersten relevanten Schwelle.
- **Erweiterung:** separates Szenario „typische Reprofilierung nach X km / Kalender“ nur mit **explizit** genannten Annahmen und klarer Kennzeichnung als hypothetisch.

---

## 7. Ausgabe und Schnittstelle zur Datenbank

Zielschema bleibt kompatibel zu `BO_RADSATZDATEN_PROGNOSE`:

- Prognosepunkte: `STAND`, `LAUFLEISTUNG`, optional `DATUM`
- Kernkennzahlen: `KM_WARNWERT`, `DATUM_WARNWERT`, `KM_GRENZWERT`, `DATUM_GRENZWERT`
- Metadaten: `LETZTEAENDZEIT` etc. wie im bestehenden System

**Empfohlene Erweiterung (optional):** Zusätzliche Felder oder Nebentabelle für **untere/obere Grenze** (km und/oder Datum) sowie **Prognosequalität**, sobald Datenbank oder API das zulässt – ohne die bestehende Auswertung für Punktwerte zu brechen.

---

## 8. Abgrenzung zum bisherigen Referenzansatz (Code-Pipeline)

| Aspekt | Bisheriger Referenzfokus | Neuer Ansatz |
|--------|---------------------------|--------------|
| Trendform | Exponentialkurve (Gauss-Newton), Default-Kurve eingemischt | Robust / glatt auf km im Zyklus; Exponential nur optional, wo fachlich begründet |
| Zyklus | Sprungheuristik | Ereignis bevorzugt; Sprung als Fallback |
| Aussage | lange extrapolierte Kurve | Schwerpunkt Rest-km und Datum; optional Band |
| Ausreißer | keine dedizierte Behandlung | gezielt und konservativ |
| ML | nicht zentral | höchstens ergänzend für Plausibilität, nicht für undokumentierte Grenzprognose |

---

## 9. Einführung und Qualitätssicherung

1. **Mindestanforderungen** an Datenlage pro Achse/Zähler (z. B. Mindestanzahl Messungen im aktuellen Zyklus) festlegen und im Programm durchsetzen.
2. **Pilot:** Backtest auf Historiendaten (prognostizierter Rest-km bis Gelb vs. spätere Ist-Entwicklung).
3. **Abstimmung mit Fachbereich:** Zielmetrik (z. B. mm/km vs. Kurvenform) und akzeptable Abweichung definieren.
4. **Betrieb:** zentrale Konfiguration (Parameter, Pfade), aussagekräftiges Logging bei verworfenen oder eingeschränkten Prognosen.

---

## 10. Glossar

- **Verschleißzyklus:** Zeitraum zwischen einem die LKD-Kurve zurücksetzenden Eingriff und dem nächsten solchen Eingriff.
- **Rest-km:** Differenz zwischen der letzten beobachteten Laufleistung und der Laufleistung am Schnittpunkt des Trends mit einer Schwelle.
- **Robustheit:** Trend und abgeleitete Restwege bleiben unter Ausreißern und moderaten Lücken stabil im Rahmen der vorhandenen Information.

---

*Ende des Dokuments.*
