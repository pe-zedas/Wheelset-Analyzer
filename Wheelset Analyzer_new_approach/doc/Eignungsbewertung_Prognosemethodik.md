# Eignungsbewertung der Prognosemethodik

Stand: 2026-10-27 (Merge aus September-Fassung 2026-09-08 + Oktober-Ergänzungen)
Geltung: `Radsatz_Bahn_DB_new_Approach.py` mit umschaltbaren Verfahren (`theil_sen`, `gauss`, optional kombiniert).
Detaillierte Algorithmen: [Programm_Doku_new_Approach.md](Programm_Doku_new_Approach.md), Abschnitte 1 und 7.
Empirische Vergleichsplots: Ordner `prognose_vergleich_plots/`.

---

## 1. Gegenstand der Bewertung

Bewertet wird nicht mehr ein einzelnes Gauss-Newton-Verfahren, sondern die **aktuelle Methodenkette**:

| Verfahren | Rolle | Modellform |
|-----------|--------|------------|
| **Theil-Sen** | Standard (`prognosis_method = theil_sen`) | robust linear: `LKD = last_lkd + slope · (km − last_km)` |
| **Power-Law** | optional im Theil-Sen-Zweig | `LKD = last_lkd − b · \|km − last_km\|^c`, nur wenn RMSE besser als linear |
| **Gauss-Newton (Exp)** | Alternative / Vergleich (`gauss`) | `y = a₁ − e^(a₂·x)` plus Default-Kurven-Mischung in `CalcPrognostic` |
| **Reprofilierung** | vorgelagertes Lernen + Szenario in der Prognose | Intervall [km] und Abtragstiefe [mm] aus Historie |

Gemeinsame Vorstufen für alle Verfahren: Zyklusgrenzen (`diff_lkd`), IQR-Ausreißerfilter, datengetriebenes Reprofilierungslernen.

Dieses Dokument trennt klar zwischen:

- **methodischer Bewertung** (was die Verfahren strukturell unterscheidet),
- **empirischen Befunden** (was der Vergleichslauf auf Realdaten zeigt) und
- **echter Genauigkeitsaussage** (was noch nicht belegt ist und wie sich das nachweisen ließe).

---

## 2. Robustheit bei Datenlücken und Ausreißern

### Stärken (aktueller Stand)

- Fit auf der **km-Achse** toleriert unregelmäßige Messabstände; die Datumsschätzung erfolgt nachträglich über `days_per_km` (Median der km-/Datums-Differenzen).
- **IQR-Filter** vor dem Fit entfernt Ausreißer relativ zu einem linearen Rest (Theil-Sen- und Gauss-Zweig).
- **Theil-Sen** ist gegenüber einzelnen Ausreißern robust (Median aller Paar-Steigungen, Breakdown-Point ≈ 29 %).
- **Mindestpunktzahl** (`min_points_fit`) und Qualitätsflags `OK` / `LOW` / `INSUFFICIENT` verhindern stille Extrapolation aus zu wenigen Punkten.
- **Reprofilierungssprünge** werden erkannt (nicht nur „entfernt und wieder eingefügt"): Zyklusstart per Sprungheuristik, optional Sub-Zyklus nach letzter Reprofilierung, Zukunftsszenario mit gelerntem Intervall und Abtrag.
- Optional **Baureihen-Fallback** bei `INSUFFICIENT` (INI, bewusst aktivieren).

### Risiken

- Große Lücken im letzten Zyklus bleiben im Trend enthalten; IQR filtert vor allem **vertikale** Ausreißer, nicht „lange Zeit ohne Messung".
- Theil-Sen und Power-Law brauchen **positive, monoton wachsende** Laufleistung; nicht-monotone km erzeugen Warnungen und können den Fit verzerren (Gauss bricht bei fallender km mit `ContinuityError` ab).
- Power-Law ist nur für **positive** x/y geeignet und empfindlich gegenüber Ausreißern trotz vorherigem IQR.
- Gauss-Newton bleibt **iterativ** (max. 30 Schritte) und kann bei schwierigen Daten nicht konvergieren.
- Flotten-Median für Reprofilierung kann bei Achsen ohne eigene Historie ein **unpassendes** Intervall/Abtrag übernehmen.

---

## 3. Verfahren im Einzelnen

### 3.1 Theil-Sen (empfohlener Standard)

**Eignung:** Hoch, wenn der Verschleiß im aktuellen Zyklus **annähernd linear** in der Laufleistung ist (typisch: gleichmäßiger Abtrag über viele tausend km).

| Kriterium | Bewertung |
|-----------|-----------|
| Robustheit | sehr gut (Median-Steigung, Breakdown ≈ 29 %) |
| Erklärbarkeit | sehr gut (mm/km, transparentes 90%-KI) |
| Unsicherheit | ja (`slope_low` / `slope_high`, konservative km/Datum) |
| Gekrümmte Verläufe | eingeschränkt → optional Power-Law |
| Konvergenz | keine Iteration, stabil |

**Wann eingeschränkt:** stark beschleunigter oder S-förmiger Verschleiß; dann RMSE hoch, Umschaltung auf Power-Law oder Vergleich mit Gauss.

### 3.2 Power-Law (optionaler Ersatz im Theil-Sen-Zweig)

**Eignung:** Mittel — nur wenn der lineare RMSE über `rmse_threshold_mm` (typisch 0,5 mm) liegt **und** der Power-Law-RMSE kleiner ist.

- Gut bei **über- oder unterproportionalem** Abfall (`c ≠ 1`).
- **Kein eigenes KI**; konservative Schwellen bleiben beim Theil-Sen-`slope_low`.
- Schlecht bei S-Kurven, Sprüngen, die der IQR nicht entfernt hat, oder zu wenigen Punkten (mindestens 6 nach Filter).

### 3.3 Gauss-Newton (Exponentialfit)

**Eignung:** Mittel bis gut bei **deutlich gekrümmten** Verläufen; historisch der Legacy-Ansatz.

| Kriterium | Bewertung |
|-----------|-----------|
| Robustheit | mittel (Least-Squares + Default-Kurve) |
| Erklärbarkeit | mittel (zwei Exponentialparameter, schwerer zu kommunizieren als mm/km) |
| Unsicherheit | **kein** analytisches 90%-KI im Plot/Export |
| Gekrümmte Verläufe | gut, wenn die Form `a₁ − e^(a₂·x)` passt |
| Konvergenz | Risiko `ContinuityError` / Nichtkonvergenz |

**Sensitivität von `def_param_exp` (a0, a1):** Unverändert relevant. In `CalcPrognostic` wird eine **Default-Exponentialkurve** erzeugt und mit den Messpunkten **vermischt**. Bei **kurzen** Zyklusreihen hat dieser Default-Anteil starkes Gewicht; die Prognose folgt dann eher der INI-Form als den Messungen. Bei **langen** Reihen sinkt der Einfluss, bleibt aber vorhanden. IQR und gelernte Reprof-Parameter mildern das, ersetzen die Default-Mischung aber nicht.

---

## 4. Reprofilierung: Intervall und Abtragstiefe

Die Methodik unterscheidet **Erkennung** (Historie) und **Einplanung** (Zukunft). Das ist für die Eignung zentral: ohne Reprof-Szenario unterschätzt eine reine Verschleißgerade die nutzbare Laufleistung, wenn regelmäßig nachgearbeitet wird.

| Größe | Herkunft | Eignung |
|-------|----------|---------|
| Erkennungs-Schwellen `dkm_threshold`, `dlkd_abs_min` | Perzentile aus Sprüngen, sonst INI | Gut, solange Reprofilierung als kurzer LKD-Anstieg sichtbar ist |
| **typical_interval_km** | Median der Abstände zwischen erkannten Ereignissen | Gut bei mehreren historischen Reprofilierungen; unsicher bei 0–1 Ereignis (Median anderer Achsen / INI) |
| **typical_magnitude_mm** (Abtragstiefe) | Median der Sprunghöhen | Statistische Schätzung aus Messdaten, **kein** Werkstatt-Sollwert |

**Risiken:** Verwechslung mit Radtausch oder Messartefakt; periodische Simulation nimmt **konstantes** Intervall und Abtrag an; Export-Schwellen `KM_WARNWERT` / `KM_GRENZWERT` folgen dem Reprof-Szenario, sobald es berechenbar ist — das ist fachlich gewollt, aber von der linearen „ohne Nachbearbeitung"-Zahl verschieden.

---

## 5. Methodische Eignung (Gesamt)

| Datenlage / Verlauf | Empfohlen | Begründung |
|---------------------|-----------|------------|
| Typischer linearer Zyklus, Ausreißer, Lücken | **Theil-Sen** | robust, KI, nachvollziehbar |
| Linearer Fit ungenau, Potenzform plausibel | Theil-Sen + **Power-Law** (automatisch) | RMSE-Schalter |
| Stark gekrümmt / Legacy-Vergleich | **Gauss** oder Kombimodus | Form passt besser, aber ohne KI |
| Validierung alt vs. neu | `theil_sen, gauss` | gleicher Plot, getrennte Kurven |
| Zu wenige Punkte | keine harte Prognose / optional Baureihen-Fallback | Qualitätsflag `INSUFFICIENT` |

- **Geeignet als Regelbetrieb:** Theil-Sen inkl. IQR, Qualitätsflags, gelerntes Reprof-Szenario.
- **Eingeschränkt:** Gauss allein (Default-Kurven-Gewicht, keine Unsicherheit); Power-Law allein (kein KI, enge Annahmen).
- **Ungeeignet ohne Zusatzmaßnahmen:** sehr kurze Zyklen, nicht-monotone km, Reprofilierung nicht als Sprung erkennbar.

---

## 6. Empirische Befunde aus dem Vergleichslauf

Basis: 10 ausgewertete Achsen aus den Baureihen FLIRT 101, FLIRT 102 und FS 101. Plots: `prognose_vergleich_plots/prognose_vergleich_*.png` (Einzelachsen), `prognose_vergleich_delta_schwellen.png` (Balkendiagramm), `prognose_vergleich_delta_scatter.png` (Streudiagramm).

### 6.1 Spannweite der Schwellen-Verschiebung (neu minus alt)

| Kennzahl | Δ km Warn (GELB_MIN) | Δ km Grenze (MIN) |
|---|---|---|
| Minimum | −25.000 km | −5.000 km |
| Maximum | +26.000 km | +45.000 km |
| Anteil Achsen mit \|Δ\| > 10.000 km | ~70 % | ~70 % |
| Systematischer Bias | gemischt — kein klarer Trend | überwiegend positiv |

### 6.2 Interpretation

- **Δ Grenze überwiegend positiv:** Der neue Ansatz schätzt bei der MIN-Grenze tendenziell mehr Restweg. Bei Achsen mit großem positiven Δ deutet das darauf hin, dass die Default-Kurve im alten Verfahren den Verschleiß systematisch zu früh „durch die Wand fallen" ließ.
- **Δ Warn streut um Null:** Bei der GELB_MIN-Warnschwelle gleicht sich ein systematischer Bias über die Achsen aus — einige Achsen verschieben sich nach vorn, andere nach hinten.
- **Vorzeichenkonsistenz Warn ↔ Grenze:** Die Punkte im Streudiagramm folgen grob einer Diagonale → wenn der neue Ansatz bei einer Achse mehr Restweg bei Warn schätzt, dann meist auch bei Grenze. Das spricht für die innere Konsistenz der neuen Methode.
- **Quadranten-Verteilung im Streudiagramm:**
  - 1. Quadrant (beide positiv, ~4 Punkte): klare Verbesserung — neuer Ansatz schätzt mehr Restweg in beiden Schwellen
  - 2. Quadrant (Δ Warn negativ, Δ Grenze positiv, ~3 Punkte): Warn früher, Grenze später als alt
  - 3. Quadrant (beide negativ, ~4 Punkte): neuer Ansatz pessimistischer — typisch für Achsen, deren alte Fits durch Default-Punkte künstlich „länger gut" aussahen
  - 4. Quadrant (Δ Warn positiv, Δ Grenze negativ): leer

### 6.3 Operative Beobachtung aus dem Smoke-Test (CSV-Modus, dieselben Eingangsdaten)

| Methode | erzeugte Insert-Tupel | Achsen mit `INSUFFICIENT` |
|---|---|---|
| Theil-Sen | 1.634 | 16 (zu wenige Punkte im Zyklus → keine Prognose) |
| Gauss-Newton | 12.250 | keine (Gauss liefert ohne Mindestanforderung weiter) |

Der große Tupel-Unterschied resultiert aus mehr Punkten pro Achse beim Gauss (Sägezahn) und daraus, dass Gauss alle Achsen verarbeitet — auch solche, bei denen Theil-Sen das ablehnt. Das ist kein Argument für die Vollständigkeit von Gauss, sondern zeigt: **der alte Ansatz liefert auch dort eine Zahl, wo die Datenlage eigentlich keine zulässt.**

---

## 7. Was über die echte Genauigkeit (noch) *nicht* bekannt ist

Aktuell vergleichen wir **Methode gegen Methode**, nicht **Methode gegen Realität**. Folgende Fragen sind ohne Backtest unbeantwortet:

1. Welche der beiden Methoden ist bei einer Achse mit großem Δ tatsächlich näher an der späteren Realentwicklung?
2. Werden die 90 %-Konfidenzbänder der Theil-Sen-Methode in der Praxis zu 90 % eingehalten (Kalibrierung)?
3. Trifft das datengetrieben gelernte Reprofilierungs-Szenario (`typical_interval_km`, `typical_magnitude_mm`) die tatsächliche Wartungspraxis der Baureihe?
4. Bei den ~30 % der Achsen mit kleinem Δ — geben beide Methoden den richtigen Wert oder beide den falschen?
5. Lohnt die Komplexität des optionalen Power-Law-Modells im praktischen Datenrauschen oder dominiert der lineare Fit ohnehin?

---

## 8. Backtest-Plan zur Quantifizierung echter Genauigkeit

Ein 4-Schritte-Vorgehen, das ohne neue Datenerhebung machbar ist:

1. **Abgeschlossene Zyklen identifizieren**
   Achsen, bei denen in der Historie zwischen zwei dokumentierten Reprofilierungen genügend Messpunkte liegen. Die zweite Reprofilierung definiert den „wahren Endpunkt" des Zyklus (LKD beim Sprung).
2. **Cutoff-Vorhersage**
   Auf den Datenpräfix der ersten `n = 4, 6, 8, 10` Punkte beider Methoden anwenden und die Schwellen-km (GELB_MIN, MIN) voraussagen.
3. **Vergleich mit Ground Truth**
   Den tatsächlichen Schnittpunkt der gemessenen Kurve mit GELB_MIN bzw. MIN aus der vollständigen Historie als Wahrheit nehmen.
4. **Metriken**
   - MAE und RMSE der km-Termin-Schätzung pro Methode und pro `n`
   - Coverage der Theil-Sen-90 %-KI: wie oft liegt die Realität tatsächlich im Band?
   - Lernkurve: wie verringert sich der Fehler mit zunehmender Datenmenge?

Eine Cross-Validation-Implementierung in dieser Richtung existiert bereits als Bausteine in `radsatz_crossval.py` (expanding-window-CV für Theil-Sen-Hyperparameter); ein dedizierter Methodenvergleich wäre eine eigene, kurze Erweiterung.

---

## 9. Empfehlung

1. **Regelbetrieb:** `prognosis_method = theil_sen`; `baureihe_fallback` nur bewusst aktivieren.
2. **Mindestpunkte** (`min_points_fit` / `min_points_quality`) beibehalten und nicht unter 3/8 ohne Begründung senken.
3. **IQR** belassen; bei systematisch „zackigen" aber echten Verläufen `iqr_factor` nicht zu klein wählen (sonst echte Krümmung als Ausreißer).
4. **Gauss** für Methodenvergleich und Achsen, bei denen Theil-Sen den Verlauf sichtbar verfehlt; `def_param_exp` fahrzeugtyp-spezifisch kalibrieren, nicht als universellen Default belassen.
5. **Reprofilierung:** gelernte Intervalle/Abträge im Log prüfen; INI-Werte (`n_km_repro`, `n_value_repro`) nur als Fallback verstehen.
6. **Plots:** Gelb-Marker am Schnitt Prognosekurve × `GELB_MIN` (seit September 2026 implementiert über `_gelb_marker_on_threshold`); Reprof- und Linear-Szenario nicht verwechseln.
7. **Konservative Planung:** `slope_low` aus dem 90 %-KI nutzen — pessimistische km/Datum-Variante nur im Theil-Sen-Zweig verfügbar.
8. **Validierung vor breiter Produktivnahme:** Backtest nach Abschnitt 8 fahren, bevor die neue Methodik Legacy-Prognosen vollständig ersetzt.
9. Offene Verbesserung: dokumentierte ZEDAS-Ereignisse statt reiner Sprungheuristik (siehe Konzeptpapier).

---

## 10. Kurzfazit

Die früher allein bewertete Gauss-Newton-Methodik bleibt für **gekrümmte** Verläufe und Legacy-Vergleich nützlich, ist aber **nicht** mehr der robusteste Standard. Für die Instandhaltungsplanung (Warn-/Grenztermine, Unsicherheit, Ausreißer, Reprofilierung) ist **Theil-Sen mit IQR und gelerntem Reprof-Szenario** methodisch besser geeignet.

Im direkten Vergleich auf 10 ausgewerteten Achsen aus FLIRT- und FS-Baureihen weichen die Methoden bei rund 70 % der Achsen um mehr als 10.000 km voneinander ab — bei der MIN-Grenze überwiegend zugunsten eines größeren Restwegs. Ob diese Verschiebung die „genauere" ist, lässt sich nicht aus dem Methodenvergleich allein beantworten, sondern erfordert einen Backtest gegen abgeschlossene Zyklen.

**Für den Regelbetrieb spricht alles für Theil-Sen** — wegen Robustheit, Auditierbarkeit, expliziter Unsicherheit und sichtbarer Datenqualitätsflags. Power-Law und Gauss sind Ergänzungen, kein Ersatz der robusten linearen Basis. Die punktuelle Genauigkeit gegenüber Realdaten sollte zur Absicherung in einem Backtest quantifiziert werden, idealerweise vor breiter Produktivnahme. Bis dahin ist der Kombimodus (`theil_sen, gauss`) ein guter Übergangs-Modus, der beide Ergebnisse zur Sichtprüfung im selben Diagramm zeigt.

---

*Ende des Dokuments.*
