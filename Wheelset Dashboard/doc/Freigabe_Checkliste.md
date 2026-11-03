# Freigabe-Checkliste · Wheelset Dashboard 1.1 (RC)

Stand: 2026-10-28

Abgleich der aktuellen Build mit den funktionalen und nicht-funktionalen Anforderungen aus [PRD_Wheelset_Dashboard.md](PRD_Wheelset_Dashboard.md).

## Legende

- ✅ erfüllt und getestet (CSV-Modus)
- 🟡 implementiert, aber **End-to-End-Test gegen Oracle-DB steht aus**
- ⚠️ bekannte Einschränkung / vereinfacht
- ⏳ für spätere Release geplant

## Navigation (F-NAV-1 … 6)

| | Anforderung | Status |
|---|---|---|
| F-NAV-1 | Baum-/Kachel-Navigation durch beide Zweige | ✅ (Side-Nav + Doppelklick) |
| F-NAV-2 | Breadcrumb mit Rücksprung | ✅ |
| F-NAV-3 | Suche/Filter über beide Zweige | ✅ (Freitextfilter pro Tabelle in Flotte/Einheit/DG/Lager) |
| F-NAV-4 | Filter-Chip Lager-Zustand | ⚠️ ersetzt: Filter läuft jetzt über die Zustand-Spalte + Freitext; Side-Nav zeigt nur noch „Komponenten" |
| F-NAV-5 | Einbau-/Ausbau-Historie im Rad-Detail | ⏳ |
| F-NAV-6 | Drei Drill-Down-Wege + Tastatur | ✅ Klick+Nav+Breadcrumb; ⏳ alle Tastaturkürzel |

## Status (F-STATUS-1 … 5)

| | | |
|---|---|---|
| F-STATUS-1 | Zwei-Quellen-Ampel | ✅ |
| F-STATUS-2 | Rollup schlechtester gewinnt | ✅ (Status zuerst, bei Gleichstand numerisch schlechterer Wert) |
| F-STATUS-3 | Schwellen (Tage) konfigurierbar | ✅ (Settings) |
| F-STATUS-4 | Prognose nur für LKD | ✅ |
| F-STATUS-5 | Ampel aus Ist + Prognose je Messgröße | ✅ |
| F-STATUS-6 | Richtungssensitive Schwellenauswertung (`decreasing`/`increasing`) | ✅ (`direction`-Feld in Messreihe, aus Profilkatalog; robust gegen inkonsistente CSV-Werte wie `GELB_MAX = MIN`) |
| F-STATUS-7 | Stale-Prognose: Prognose mit vergangenem Zieldatum + grünem Ist wird GRAU | ✅ |

## Ansichten (F-VIEW-*, F-UI-*)

| | | |
|---|---|---|
| F-VIEW-AGG-1 | Gantt-Zeitachse | ✅ (reaktiv zur Zeilenauswahl) |
| F-VIEW-AGG-2 | Marker für Warn+Grenz | ✅ |
| F-VIEW-AGG-3 | Sortierbare Tabelle | ✅ (alle Spalten inkl. Status-/Messwert-Spalten) |
| F-VIEW-AGG-4 | Klick → Drilldown | ✅ (einfacher Klick = Donut/Gantt aktualisieren; Doppelklick = Drilldown) |
| F-VIEW-AGG-5 | Freitextfilter oberhalb der Tabelle | ✅ |
| F-VIEW-AGG-6 | Umschaltbare Zellanzeige (Ampelpunkt ↔ Punkt+letzter Messwert) | ✅ (Checkbox in der Statusleiste; europäisches Zahlenformat mit Komma) |
| F-VIEW-AGG-7 | Aggregierter Zellwert = numerisch schlechtester der enthaltenen Räder | ✅ |
| F-VIEW-LAGER-1 | Komplette Drehgestelle als eine Komponente erkennbar, mit Achsenanzahl | ✅ |
| F-VIEW-LAGER-2 | Zweistufiger Drilldown DG → Achsenliste → Rad-Detail | ✅ |
| F-VIEW-AXIS-1 | Detail-Plot | ✅ (Legende oben rechts) |
| F-VIEW-AXIS-2 | Numerische Prognose-Tabelle | ✅ (Kennzahlen-Zeile; „letzter Wert" aus chronologisch jüngstem Messpunkt) |
| F-VIEW-AXIS-3 | X-Achse Datum/km umschalten | ✅ |
| F-UI-1 | Dashboard-Layout mit KPIs/Donut/Gantt/Tabelle | ✅ (Tabelle hat Vorrang vor Overview, ≥ 6 Zeilen reserviert; Donut/Gantt gedeckelt) |
| F-UI-2 | QSS, Farbcodes aus PRD | ✅ |
| F-UI-3 | Matplotlib + Qt-Widgets | ✅ |
| F-UI-4 | Status-Matrix pro Messgröße | ✅ |

## Daten (F-DATA-1 … 7)

| | | |
|---|---|---|
| F-DATA-1 | Oracle-Modus mit AUSBAU/AKTUELL-Logik | ✅ (E2E 2026-10-28 gegen VGF-DB, 2 000 Zeilen, 2 Einheiten + 42 Lager-Komp., Status red/yellow) |
| F-DATA-2 | CSV-Modus als vollwertige Alternative | ✅ |
| F-DATA-3 | CSV-Export Rohtabellen | ✅ (Menü) |
| F-DATA-4 | CSV-Import als Datenquelle | ✅ (Settings) |
| F-DATA-5 | Werkstattlisten-Export .xlsx | ✅ (Strg+E) |
| F-DATA-6 | Kundenprofil mit Spalten-Mapping | ✅ (YAML für vgf/abellio/mob) |
| F-DATA-7 | ZARTBEZ-Vokabular je Profil | ✅ (DE + FR) |

## Modell (F-MODEL-1 … 2)

| | | |
|---|---|---|
| F-MODEL-1 | Flexible Hierarchie (L4 optional) | ✅ (MOB läuft) |
| F-MODEL-2 | Mehrere Messgrößen pro Rad | ✅ |

## Settings / Logging / Perf

| | | |
|---|---|---|
| F-SET-1…7 | Settings-Dialog | ✅ |
| F-LOG-1/2 | Rotierendes Logging | ✅ |
| F-ERR-1 | DB-Verbindungsfehler ohne Datenverlust | ✅ |
| F-ERR-2/3 | Robuste Isolation pro Achse | ✅ |
| F-PERF-1 | Startansicht < 3 s bei 10k Achsen | 🟡 (Benchmark steht aus) |
| F-PERF-2 | Drill-down < 500 ms | ✅ (gemessen VGF/Abellio) |
| F-PERF-3 | Caching + Auto-Refresh 15 min + Reload | ✅ |

## Nicht-funktional

| | | |
|---|---|---|
| Plattform | Windows 10/11 + Python 3.11+ | ✅ (Windows 11, Py 3.13) |
| Sprache | Deutsche UI | ✅ |
| Sicherheit | DB-Credentials verschlüsselt via keyring | ⏳ (aktuell im Settings-Dialog im Klartext) |
| Barrierefreiheit | Tastatur-Navigation grundlegend | 🟡 (teilweise, Vollausbau ⏳) |

## End-to-End-Tests (durchgeführt im CSV-Modus)

| Profil | Einheiten | Lager | Flottenstatus | Werkstattliste 180 T |
|--------|-----------|-------|----------------|-----------------------|
| VGF    | 5         | 108   | 🔴 | 48 Zeilen |
| Abellio| 128       | 290   | 🔴 | 0 (Prognose fehlt, ZAR-3219) |
| MOB    | 2         | 1     | ⚪ grau | 0 (keine Prognose) |

Für alle drei Profile wurden Flotte → Einheit → DG → Achse → Lager erfolgreich navigiert; keine ungefangenen Exceptions.

## Noch offen vor Produktiv-Freigabe

1. **Oracle-Volllauf** ohne `--limit` zur Bestätigung der Vollständigkeit (bisher 2 000-Zeilen-Fenster getestet).
2. **Keyring-Integration** für DB-Passwort (ersetzt Klartext im Settings-Dialog).
3. **Lücken in Abellio/MOB-Prognosedaten** klären (verlinkt mit ZAR-3219 — Zuständigkeit DB-Export).
4. **Performance-Benchmark** mit vollständigem VGF-Datensatz (10 k Achsen).
5. **Einbau-/Ausbau-Historie** als Querverweis in Rad-Detail (F-NAV-5).

## Änderungslog Version 1.1 (2026-10-28)

**UI/Bedienung**
- Lager-Side-Nav vereinfacht (nur noch „Komponenten"); Filter läuft über Zustand-Spalte + Freitext.
- Sortierbare Spalten in allen Tabellen (Status-Spalten via `_AmpelSortItem`).
- Freitextfilter oberhalb jeder Tabelle.
- Zeilenauswahl aktualisiert Donut/Gantt für die selektierte Entität.
- Donut-Center-Label bricht bei langen Bezeichnungen auf zwei Zeilen um.
- Statusleisten-Checkbox „Messwerte anzeigen" (Ampelpunkt ↔ Punkt + letzter Wert, europäisches Zahlenformat mit Komma).
- Layout: Tabelle hat Vorrang (Stretch 5, ≥ 6 Zeilen), Donut/Gantt gedeckelt (Max 220 px).
- Legende im Detail-Plot nach oben rechts verschoben.
- Lager-Komponenten tragen Messwert-Spalten je Messgröße.
- Zweistufiger Lager-Drilldown: DG → Achsenliste → Einzelrad-Detail.

**Daten/Modell**
- `LagerKomponente` erweitert um `kind` (`achse` | `drehgestell`), `dg_bez`, `raeder`, `achsen`.
- CSV-Loader gruppiert Lager-Zeilen mit DG-Zuordnung zu einer gemeinsamen DG-Komponente (Fachregel: Ausbau einer Achse = Ausbau des gesamten DGs).
- `Messreihe.direction` aus dem Profilkatalog (`decreasing`/`increasing`/`both`).
- `Messreihe.letzter_wert()` nutzt `max(datum)` statt `[-1]`.

**Status-Logik**
- `classify_messpunkt_ist(mp, direction)` wertet nur die relevante Schwellenseite aus; zusätzlich Validitätsprüfung (`gelb_min` muss im gültigen Bereich liegen).
- Prognose fließt nicht in die Ampel ein; Status ausschließlich aus letztem Ist-Messwert (`classify_messreihe`). `classify_prognose` wurde am 2026-10-29 entfernt.
- Aggregation (`_worst_messreihe`): schlechter Status zuerst, bei Gleichstand numerisch schlechterer letzter Wert.

## E2E-Oracle-Protokoll (2026-10-28)

```
1) Testverbindung...
   OK — DB erreichbar, BO_RADSATZDATEN hat 12701 Zeilen
2) Lade Daten (Profil: vgf, Limit 2000)...
   Oracle: 2000 Zeilen aus BO_RADSATZDATEN geladen
   2 Einheiten, 42 Lager-Komponenten
3) Berechne Status und Lager-Zustand...
   Lager: ready=0, to_overhaul=42
   Flotten-Status: red
4) Top-5 Einheiten:
   [yellow] 3180 080 6101-8                 DGs=4  Achsen=8
   [red   ] FLIRT 102                       DGs=4  Achsen=8
```
Zeilenzahl deckt sich exakt mit dem Backend-CSV-Export → Datenstand identisch.
