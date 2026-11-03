# Änderungen vom 2026-10-29

Dokumentiert alle Anpassungen eines Tages Arbeit an Dashboard und Backend.
Eine Änderung ist hier nur aufgeführt, wenn sie Bestand hat (nicht in einer
späteren Runde wieder revidiert wurde).

Alle Ersetzungen betreffen entweder das **Dashboard**
(`C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard\wheelset_dashboard\`)
oder das **Backend-Prognoseprogramm**
(`E:\Projekte\Konzepte\Radsatzdaten\Python\Radsatz_VGF_DB - CSV - neuer Ansatz\`
und spiegelgleich `C:\User\GitHub\Wheelset-Analyzer\Wheelset Analyzer_new_approach\`).


## 1. Prognose-Algorithmus (Dashboard, `logic/prognose.py`)

Komplett überarbeitet, so dass er mit dem Backend-Verfahren
(`prognosis_new_core._calc_prognosis_axis`) deckungsgleich ist.

### 1.1 Zyklus-Fit (`cycle_fit`)

- **Zyklus-Start = Index nach dem letzten positiven LKD-Sprung > 10 mm**
  (Rad-Tausch), nicht nach der letzten Reprofilierung. Entspricht dem
  Backend-Helper `getStartIndexLastCycle`.
- **Sub-Zyklus-Erkennung**: ab der letzten Reprofilierung innerhalb des
  Zyklus wird abgeschnitten, aber nur wenn danach ≥ `min_points_fit = 4`
  Punkte übrig bleiben. Fällt dieser Test, bleibt der volle Zyklus
  erhalten — kein Fallback mehr auf _alle_ Historienpunkte.
- **IQR-Vorfit** (`iqr_factor = 2.0`) filtert die Reprof-Sprünge als
  Ausreißer, damit Theil-Sen die reine Verschleißsteigung fittet.
- **Theil-Sen** über die bereinigten Punkte: `slope`, `slope_low`,
  `slope_high` (`scipy.stats.theilslopes(alpha=0.90)`, Fallback: eigene
  Pairwise-Implementierung).

### 1.2 Reprof-Parameter-Kaskade (`effective_params`)

Reihenfolge:
1. **Achsen-Scope** (`_axle_merged_params`): km-Marken aller Reprofs
   beider Räder werden vereinigt (Dedup mit Toleranz 500 km). Das Reprof-
   Intervall ist der Median der vereinigten Marken-Abstände → **beide
   Räder einer Achse haben zwangsläufig dasselbe Intervall**, die
   Magnitude bleibt pro Rad individuell. Löst das Problem, dass
   leicht unterschiedliche `dlkd_min`-Schwellen pro Rad vorher
   verschiedene Reprof-Zählungen und damit unterschiedliche
   Mediane ergeben haben.
2. Rad-Scope (`learn_reprof_params`).
3. Flotten-Fallback (`_fleet_median_params`): Median über alle Achsen
   der Flotte, falls einzelne Achse zu wenig Daten hat.
4. Hartcodierte Defaults aus `PrognoseConfig`.

Robustheit beim Lernen: Bei weniger als vier Seeds wird `dlkd_abs_min`
nicht per P25, sondern als `min(seed_drop) - 0.01` gesetzt, damit auch
kleine Seed-Mengen (2–3 Reprofs) sauber durchlaufen.

### 1.3 Treppen-Prognose (`project_with_reprofs`)

- Prognose startet am letzten Messwert.
- Alle `typical_interval_km` eine Reprofilierung mit `typical_magnitude_mm`
  Abtrag.
- **Verlängerung bis MIN**: Wenn der letzte Zyklus unter MIN führen würde,
  wird die fallende Linie bis genau zum MIN-Punkt extrapoliert, statt
  vorzeitig abzubrechen. Dadurch endet jede Prognose geometrisch sauber
  auf der MIN-Linie.

### 1.4 Konfidenzintervall (`ci_band`)

- **Pooled Achsen-CI** (`_axle_pooled_ci`): Residuen beider Räder einer
  Achse werden gegen ihre jeweilige Trendlinie berechnet und gepoolt.
  Theil-Sen auf diese gepoolten (km, residuum)-Paare liefert eine
  gemeinsame Band-Breite für beide Räder.
- **RMSE-Heuristik** (`_use_pooled_ci`, Schwelle `POOL_RMSE_RATIO = 2.0`):
  Pooling wird nur verwendet, wenn das Verhältnis der Rad-Residuen-RMSE
  ≤ 2 ist. Streut ein Rad merklich stärker als das andere, behält jedes
  Rad sein eigenes CI → asymmetrische Streuung (z. B. defektes Rad)
  bleibt sichtbar.
- **CI-Clamp** (`_clamp_ci`, Faktor `CI_CLAMP_FACTOR = 3.0`): Band-
  Halbbreite auf max. 3 × |slope| begrenzt. Verhindert, dass einzelne
  `dkm = 0`-Paare (Reprof-Doppelmessungen am selben km-Stand) die
  pairweise Theil-Sen-Statistik in absurde Werte wie −22 mm/1000 km
  kippen. Im Pooled-Fall wird der Clamp mit dem Mittelwert beider
  Rad-|slope| berechnet, damit die Band-Breite symmetrisch bleibt.

### 1.5 Schnittpunkt-Berechnung (`crossings`)

Neue Funktion: liefert die km-Positionen, an denen die Treppen-Prognose
eine horizontale Schwelle (z. B. GELB_MIN oder MIN) kreuzt. Interpoliert
linear auf stetigen Segmenten; vertikale Reprof-Sprünge am gleichen km
werden direkt übernommen, wenn der Y-Level dazwischen liegt. Nutzung:
Marker im Plot und Fallback-Grenzwert-Datum/km für die KPI-Kacheln.

### 1.6 Prognose nur für LKD

`effective_params` + `project_with_reprofs` + `ci_band` werden nur noch
für `messgroesse == "LKD"` angewendet. Für andere Messgrößen (Sh, Sd,
Spurmaß, Stichmaß) wird im Plot keine Prognosekurve mehr gezeichnet
und die View zeigt eine Hinweis-Kachel „Keine Prognose vorhanden"
rechts unter dem Diagramm.


## 2. Plot (`ui/plot_widget.py`)

### 2.1 Prognose-Darstellung

- **Gestrichelte Linie** `linestyle="--"` für die Treppen-Prognose.
- **Marker an den Schnittpunkten**: Kreis in Warnfarbe an der GELB_MIN-
  Kreuzung, Raute in Grenzfarbe an der MIN-Kreuzung. Markerfüllung in
  der Radfarbe → links/rechts gleich erkennbar.
- **Senkrechte vertikale Linien aus `prog.km_warnwert`/`km_grenzwert`
  entfernt**: Die Schnittpunkte stehen jetzt direkt als Marker auf der
  Prognosekurve.

### 2.2 Darstellung im Datum-Modus

- Treppen-Prognose, Marker und KI-Band werden auch im Datum-Modus
  gezeichnet. km → Datum über `_estimate_km_per_day(mr)` (Median der
  km/Tag-Rate aus den jüngsten 6 Historie-Punkten).
- Der frühere Guard `use_ci = (... and x_mode == "km")` ist aufgehoben.

### 2.3 KI-Band folgt den Treppen

Statt einer linearen Fläche vom letzten Messwert aus wird das Band jetzt
Punkt für Punkt auf die Treppen-Prognose aufgesattelt:

- `band_lower[i] = treppe_y[i] + (slope_hi_band − slope) · (km_i − km_start)`
- `band_upper[i] = treppe_y[i] + (slope_lo_band − slope) · (km_i − km_start)`

Dadurch verschiebt sich das Band bei jedem Reprof-Sprung gemeinsam mit
der Prognose nach unten, bleibt in der Breite aber proportional zu dkm.

### 2.4 KI-Band bis zur MIN-Linie

Zusätzlicher Tail-Punkt rechts, bei dem der obere Band-Rand genau MIN
erreicht (`km_tail = km_last + (MIN − upper_last) / slope_upper_band`).
Der untere Rand wird ab dort auf MIN gecappt. Das Band hat damit einen
sauberen rechten Abschluss auf der Grenzwert-Linie.

### 2.5 Achsenbeschriftung

- X-Achse im km-Modus: `FuncFormatter` → z. B. `1 400 Tkm` statt
  `1.4 1e6`. Beispiele: `50 Tkm`, `1 000 Tkm`.
- Y-Achsen-Label-Farbe und Grid-Styling unverändert.

### 2.6 Alle vier Grenzwerte

Horizontale Schwellen MIN, MAX, GELB_MIN, GELB_MAX werden unabhängig
von `mr.direction` gezeichnet, sofern vorhanden und im gültigen
Zwischenbereich. (Vorher wurden z. B. bei `direction="decreasing"`
MAX und GELB_MAX weggelassen, auch wenn die CSV sie lieferte.)

### 2.7 Info-/Hinweistext ausgelagert

- `ax.text(...)`-Boxen für Prognose-Parameter und „Keine Prognose
  vorhanden" wurden aus dem Plot entfernt. Der Plot setzt stattdessen
  die Flags `_prognose_info` und `_prognose_available` auf der Canvas.
- Die View zeigt diese Information als Kacheln unter dem Diagramm.


## 3. Views (`ui/views.py`, AchseView)

### 3.1 KPI-Kacheln unter dem Diagramm

- **Letzter Messwert** je Rad, Rahmen in Ampelfarbe.
- **Grenz-** und **Warn-**Kachel: Haupt-Wert (groß oben) wechselt mit
  dem X-Achsen-Modus:
  - km-Modus → `810 Tkm` oben, Datum unten klein.
  - Datum-Modus → Datum oben, km unten klein.
- Fallback: Fehlt der Grenz-/Warn-km aus der Backend-Prognose-Tabelle,
  wird er aus den Treppen-`crossings` berechnet und das Datum via
  `_estimate_km_per_day` ergänzt.

### 3.2 Hinweis-/Info-Kachel ganz rechts

- **Prognose vorhanden**: weiße Box mit einer Zeile pro Rad:
  `Rad links: Reprofilierungsintervall 34 Tkm · Abtrag 7,19 mm`.
- **Keine Prognose**: graue, kursive Box `Keine Prognose vorhanden`.

Beide auf gleicher Höhe wie die Letzter-Wert-/Grenz-/Warn-Kacheln.

### 3.3 Durchreichen der Achse

`AchseView.set_flotte()` + Übergabe von `achse=self._achse` an
`plot_messreihen()` → Prognose-Pfad bekommt sowohl Flotten- als auch
Achsen-Kontext für seine Kaskade.


## 4. Widgets (`ui/widgets.py`, `ui/style.qss`)

### 4.1 KpiCard kleiner

- `KpiLabel`: 11 → 10 px
- `KpiValue`: 20 → 15 px
- Innenabstand: 10/8 → 8/5 px
- Rahmen-Padding bei `set_status_border`: 10/14 → 4/8 px
- Border-Radius: 8 → 6 px

### 4.2 Zweite Zeile

Neue Methode `KpiCard.setSubValue(text)` fügt eine kleine Zusatz-Zeile
unter dem Hauptwert ein (`KpiSub`-Style). Nutzung z. B. in den Grenz-/
Warn-Kacheln, wenn Datum oben und km unten (oder umgekehrt) steht.


## 5. Settings-Dialog (`ui/settings_dialog.py`)

### 5.1 Prognose-Abschnitt zweistufig

- Große Überschrift **Prognose** (allgemein).
- Zwischenüberschrift **LKD** (grau, eingerückt), darunter alle sieben
  LKD-spezifischen Felder (Auto-Erkennung, Sprung, Intervall,
  Erkennungs-Schwelle, Treppen-Prognose, KI-Band, Niveau).

### 5.2 KI-Band standardmäßig aus

- `PrognoseConfig.show_ci_band = False` (vorher `True`).
- Zuschaltbar im Dialog unter **Prognose → LKD → KI-Band**.

### 5.3 Entfernt

- Die Felder **„Rot-Schwelle"** und **„Gelb-Schwelle"** (Tage) wurden
  entfernt. Sie waren nicht mehr wirksam, weil der Status seit einer
  früheren Entscheidung ausschließlich aus den aktuellen Ist-Messwerten
  gegen die CSV-/DB-Schwellen bestimmt wird und die Prognose nicht in
  die Ampel einfließt.
- Das Feld **„Mindest-Standzeit"** wurde entfernt, da es nach dem
  Backend-Angleich keinen Platz mehr in `PrognoseConfig` hatte.


## 6. Status-Logik (`logic/status.py`)

- `StatusThresholds`, `classify_prognose` und der `thr`-Parameter in
  `classify_messreihe`/`recompute_all` wurden entfernt.
- Jetzt eine klare Signatur: `recompute_all(flotte, now=None)`,
  `classify_messreihe(mr, now=None)`.
- `tests/test_status.py` entsprechend reduziert — es gibt nur noch
  Tests für Ist-Status und Rollup.


## 7. `PrognoseConfig` (`data/models.py`)

Angleich an das Backend-Vokabular:
- `reprof_dkm_threshold`, `reprof_dlkd_abs_min` — Erkennungs-Parameter.
- `reprof_typical_interval_km`, `reprof_typical_magnitude_mm` — Projektions-
  Fallbacks, wenn die Historie zu dünn ist.
- `min_points_fit = 4`, `min_points_quality = 8`, `iqr_factor = 2.0`,
  `ci_level = 0.90`.
- `auto_from_history`, `show_reprof_steps`, `show_ci_band` (letzterer
  jetzt `False`).


## 8. Backend-Programm (`prognosis_new_core.py`,
`Radsatz_Bahn_DB_new_Approach.py`, `prognosis_gauss.py`)

Dasselbe CI-Pattern wie im Dashboard eingebaut.

### 8.1 `prognosis_new_core.py`

- Neue Modul-Konstanten `POOL_RMSE_RATIO = 2.0`, `CI_CLAMP_FACTOR = 3.0`.
- Neue Helper `_clamp_slope_bounds(slope, lo, hi, max_half=None)`.
- `_calc_prognosis_axis` erweitert um optionale Parameter
  `ci_override=(lo, hi)` und `ci_clamp_max_half`. Clamp wird direkt
  nach dem Theil-Sen-Fit angewendet, dadurch profitieren sowohl die
  konservativen Schwellen (`km_warn_conservative`, `km_limit_conservative`)
  als auch die Plot-Darstellung.
- Neuer Helper `_fit_residuals_rmse(met, axis_key)` — Pre-Fit für die
  Pool-Entscheidung.
- Neue Funktion `_calc_prognosis_axis_pair(met1, met2, k1, k2, nKm)` —
  orchestriert beide Räder einer Achse: Pre-Fit, RMSE-Vergleich, pooled
  Theil-Sen auf gepoolten Residuen, Clamp mit `3 × Mittel-|slope|`.
  Rückgabe: `(res1, res2)` wie zuvor.

### 8.2 `Radsatz_Bahn_DB_new_Approach.py`

- Import von `_calc_prognosis_axis_pair` ergänzt.
- Zeile 1023–1024: Statt zweier getrennter `_calc_prognosis_axis`-
  Aufrufe wird nun einmal `_calc_prognosis_axis_pair(wm1, wm2, …)`
  aufgerufen. Baureihen-Fallback und restliche Logik unverändert.

### 8.3 `prognosis_gauss.py`

- Import von `_clamp_slope_bounds`.
- `_slopes_for_plot_ki()` klemmt die Theil-Sen-Grenzen direkt nach dem
  Fit. (Pooling im Gauss-Zweig würde eine strukturelle Umarbeitung
  erfordern — der Clamp allein verhindert aber bereits die absurden
  Werte und ist der wichtigste Fix.)

### 8.4 Backups

Alte Fassungen gesichert als
- `prognosis_new_core_v1.py`
- `Radsatz_Bahn_DB_new_Approach_v1.py`
- `prognosis_gauss_v1.py`

in beiden Repo-Ständen (`E:\…` + `C:\User\GitHub\…\Wheelset Analyzer_new_approach\`).
`E:\…` und `\\cpcpe\D\…` zeigen laut `cmp` auf dasselbe Dateisystem
(kein separater Sync nötig).


## 9. Dateistruktur-Hinweis

| Pfad | Rolle |
|---|---|
| `E:\…\Radsatz_VGF_DB - CSV - neuer Ansatz\` | Produktiv-Stand Backend (identisch zu `\\cpcpe\D\…`) |
| `C:\User\GitHub\Wheelset-Analyzer\Wheelset Analyzer_new_approach\` | Repo-Kopie Backend. Heute von `E:\` übernommen; CRLF-Zeilenenden werden dabei auf LF umgestellt |
| `C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard\` | Dashboard-Projekt |
