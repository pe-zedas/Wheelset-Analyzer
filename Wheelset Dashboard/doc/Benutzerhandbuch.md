# Wheelset Dashboard — Benutzerhandbuch

Stand: 2026-10-28 · Version 1.1 (RC)

## 1. Was ist das?

Das Wheelset Dashboard zeigt den Zustand aller Radsätze einer Fahrzeugflotte auf einen Blick:

- **Flottenübersicht** mit Donut (Status-Verteilung), Gantt-Zeitachse (Fälligkeiten der nächsten 12 Monate) und Tabelle mit Status pro Messgröße.
- **Drill-Down** von Flotte → Einheit → Drehgestell → Achse → Rad.
- **Detail-Plot** mit historischen Messwerten, LKD-Prognose, Warn- und Grenzwertlinien.
- **Lager-Zweig** mit allen ausgebauten Komponenten inklusive Messwert-Historie und Drill-Down bis zum einzelnen Rad.
- **Werkstattliste-Export** als `.xlsx`.
- **Sortierbare Tabellen mit Freitext-Filter** in jeder Ebene.
- **Umschaltbare Zellanzeige**: Ampelpunkt oder Ampelpunkt + letzter Messwert.

Das Dashboard **liest nur** (Oracle oder CSV) — es rechnet selbst keine Prognose. Die Prognosewerte stammen aus dem bestehenden Backend `Wheelset Analyzer_new_approach`.

## 2. Installation

```powershell
cd "C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Benötigt: Windows 10/11, Python 3.11+.

## 3. Start

```powershell
python -m wheelset_dashboard.main --profile vgf
```

Optionen:

| Option | Bedeutung | Default |
|--------|-----------|---------|
| `--profile` | `vgf`, `abellio`, `mob` | `vgf` |
| `--csv-raw` | Pfad zu `bo_radsatzdaten_export.csv` | Backend-CSV |
| `--csv-prognose` | Pfad zur Prognose-CSV | Backend-CSV |
| `-v` | Verbose-Logging | aus |

Alle Pfade und das Profil können nachträglich in **Einstellungen** geändert werden.

## 4. Bedienung

### 4.1 Side-Navigation (linke Spalte)

- **Flotte · Übersicht** — L1-Ansicht aller Einheiten.
- **Lager · Komponenten** — alle ausgebauten Komponenten (Achsen und komplette Drehgestelle) in einer gemeinsamen Sicht; Filterung über die Zustand-Spalte oder das Freitextfeld.
- **Einstellungen** — Datenquelle, Schwellen, Auto-Refresh.

### 4.2 Drill-Down

Drei gleichwertige Wege (siehe PRD F-NAV-6):

1. **Doppelklick** auf eine Zeile öffnet die nächsttiefere Ebene.
2. **Breadcrumb** oben zeigt den Pfad; jedes Segment ist anklickbar.
3. **Side-Nav** — direkter Sprung in einen Bereich.

Im **Lager** ist der Drill-Down zweistufig: Doppelklick auf ein **Drehgestell** zeigt die Liste seiner eingebauten Achsen (gleiche Darstellung wie aus der Flotte); Doppelklick auf eine Achse führt in den Detail-Plot. Lager-Achsen ohne DG-Zuordnung springen direkt in die Detail-Ansicht.

### 4.3 Tabellen-Interaktion

- **Zeilenauswahl** (einfacher Klick) in Flotte-/Einheit-/DG-Tabelle: Donut-Chart und Gantt-Zeitachse unterhalb aktualisieren sich sofort und zeigen die Verteilung bzw. Fälligkeiten der ausgewählten Entität statt der Gesamtaggregation.
- **Diagramm-Symbol (letzte Spalte)**: Ein kleines Diagramm-Symbol ganz rechts zeigt, dass es für diese Zeile Messdaten gibt. Es erscheint, sobald die Zeile selbst oder eine darunterliegende Komponente Messdaten hat (Einheit → Drehgestell → Achse). Ohne Messdaten bleibt die Zelle leer. Gilt in der Flotten-, Einheiten-, Drehgestell- und Lager-Tabelle; die Spalte lässt sich sortieren.
- **Spaltensortierung**: Klick auf einen Spaltenkopf. Für die Status-Spalten (LKD, Sd, Sh, qR, Hohll., Überw., Breite) wird nach Ampelstufe sortiert (grau < grün < gelb < rot).
- **Freitextfilter** oberhalb jeder Tabelle: filtert zeilenweise über alle Textspalten; rechts wird `n/total` eingeblendet.

### 4.4 Statusleiste

Unten links Datenstand, in der Mitte Statusmeldungen. Rechts:

- **Checkbox „Messwerte anzeigen"** — schaltet die Status-Spalten um:
  - **aus** (Standard): nur farbiger Ampelpunkt.
  - **an**: Ampelpunkt + letzter Messwert in Ampelfarbe (`28,3` mm o. Ä.). Ohne Messwert bleibt die Zelle leer.
  Bei aggregierten Zeilen (Einheit, Drehgestell) wird der **schlechteste tatsächliche Zahlenwert** aus den enthaltenen Rädern angezeigt — Richtung aus dem Profil (für LKD, Sd kleiner = schlechter; für Hohllauf, Überwalzung größer = schlechter).
- **Button „Neu laden"** — manueller Reload (F5).

### 4.5 Status-Ampel

| Farbe | Bedeutung |
|-------|-----------|
| 🟢 OK | Letzter Messwert außerhalb aller Warnbänder, Prognose unauffällig |
| 🟡 Warn | Ist-Wert im Warnband oder Prognose-Warntermin ≤ 90 Tage |
| 🔴 Grenz | Ist-Wert außerhalb Grenzwert oder Prognose-Grenztermin ≤ 30 Tage |
| ⚪ Unbekannt | Keine verwertbaren Schwellen und keine Prognose |

**Ausgewertet werden nur semantisch sinnvolle Schwellen**: Für monoton fallende Messgrößen (LKD, Sd) werden `MIN`/`GELB_MIN` geprüft; für monoton steigende (Hohllauf, Überwalzung) nur `MAX`/`GELB_MAX`. Unsinnige Werte in der CSV (z. B. `GELB_MAX = MIN`) werden ignoriert.

**Prognose-Stale-Regel**: Liegt der Warn-/Grenz-Termin der Prognose bereits in der Vergangenheit und ist der aktuelle Ist-Wert noch grün, wird die Prognose als veraltet (grau) behandelt — sie zieht den Status dann nicht mehr auf gelb/rot, weil die Realität die alte Vorhersage widerlegt hat.

**Dezimalstellen** werden europäisch mit Komma dargestellt (`28,3 mm`).

### 4.6 Lager-Tabelle im Detail

Jede Zeile ist entweder eine ausgebaute Einzelachse oder — häufiger — ein **komplettes Drehgestell**. Ein DG wird erkannt, wenn in der CSV eine `dg_id`/`dg_bez` vorhanden ist; alle Achsen desselben DGs mit demselben Ausbaudatum werden zu einer gemeinsamen Lager-Komponente zusammengefasst (eine Achse mit Ausbaudatum impliziert laut Fachregel immer den Ausbau des gesamten DGs). In der Typ-Spalte steht `Drehgestell (n)` mit der Anzahl der eingebauten Achsen; `Achse` für Einzelachsen.

Spalten (links nach rechts): Status · Typ · Bezeichnung · letzte Einheit · Ausbau · Zustand · Messwert-Status je Messgröße (LKD, Sd, Sh, qR, Hohll., Überw., Breite). Mit Checkbox „Messwerte anzeigen" werden die letzten tatsächlichen Zahlen eingeblendet.

### 4.7 Detailansicht (L4 / L5)

- **Reiter** oben: eine Registerkarte pro verfügbarer Messgröße (LKD, Sd, Sh, qR, Hohllauf …).
- **Rad-Umschalter**: Beide / Nur links / Nur rechts.
- **X-Achse**: Datum ↔ Laufleistung [km].
- **Blaue Punkte** = LKD1 (links), **Grüne Punkte** = LKD2 (rechts).
- **Gelbe Linie** = GELB_MIN, **Rote Linie** = MIN.
- **Gestrichelte Fortsetzung** = LKD-Prognose bis zum Grenzwert.
- **Vertikale Linien** = heute (blau), Warn-Termin (gelb), Grenz-Termin (rot).
- **Legende** oben rechts.
- Die KPI „LKD left/right (letzter)" nutzt den chronologisch jüngsten Messpunkt — unabhängig von der CSV-Zeilenreihenfolge. Unter dem Wert steht das Datum dieser Messung („Messung JJJJ-MM-TT“).

### 4.8 Werkstattliste exportieren

**Datei → Werkstattliste exportieren (xlsx)** oder `Strg + E`.

Enthält alle Räder, deren Warn- oder Grenz-Termin im aktiven Horizont liegt (Default 90 Tage), sortiert nach frühestem Grenz-Termin. Spalten: Einheit, DG-Pos, Achse-Pos, Rad, aktueller LKD, aktuelle Laufleistung, Warn-/Grenz-Termine, Rest-km, Status, Qualität, Methode.

### 4.9 Rohdaten als CSV exportieren

**Datei → Rohdaten als CSV exportieren**. Schreibt den aktuellen Datenstand im Backend-CSV-Format (profilspezifisch) raus — nützlich für Weitergabe oder Archivierung.

### 4.10 Einstellungen

| Feld | Zweck |
|------|-------|
| Kundenprofil | `vgf` / `abellio` / `mob` — bestimmt Spalten-Mapping und Zählervokabular |
| Datenquelle | `csv` (Pfade angeben) oder `oracle` (DSN/User/Passwort) |
| Rot-Schwelle | Tage bis zum Grenz-Termin, ab denen Status rot wird (Default 30) |
| Gelb-Schwelle | Tage bis zum Warn-Termin, ab denen Status gelb wird (Default 90) |
| Auto-Refresh | `off`, `5`, `15`, `30`, `60` min — konfigurierbarer Takt |
| DB-Testverbindung | Prüft Oracle-DSN inline, zeigt grüne/rote Statuszeile |

### 4.11 Fehler und Logs

- Fehler erscheinen als Toast in der Statusleiste oder als Dialog.
- Die alten Daten bleiben sichtbar und werden als „Stand … (veraltet)" markiert.
- Rotierendes Logfile `wheelset_dashboard.log` (max. 10 MB, 5 Backups) im Arbeitsverzeichnis.

## 5. Kundenprofile

Die drei mitgelieferten Profile unterscheiden sich in:

| | VGF | Abellio | MOB |
|---|---|---|---|
| Spalten | 21 (Legacy) | 23 (neu) | 23 (neu) |
| Schwellen | `MIN/MAX` + Warnband `GELB_MIN/MAX` | `MIN`/`MAX` und Toleranzbereich `MIN_BEREICH/MAX_BEREICH` (gilt als Grenzwert, kein Gelb) | keine (Spalten leer) |
| Letzte Änderung | `LETZTEAENDZEIT` | `LASTUPDATE` (Rohdaten), `LETZTEAENDZEIT` (Prognose-Tabelle) | `LASTUPDATE` (Rohdaten), `LETZTEAENDZEIT` (Prognose-Tabelle) |
| Mess-Vokabular | Deutsch, nur LKD1/LKD2 | Deutsch, Seite in vier Schreibweisen (`links`, `[Radscheibe Laufradsatz (L)]`, …) | **Französisch**, ohne Seitenangabe (`Diamètre de roue`, `Epaisseur du boudin`, …) |
| Hierarchie | bis Radsatz | gemischt: mit DG+Radsatz, nur DG, nur Einheit | nur Drehgestell, Räder als „Messposition 1–4“ |
| Nullwerte | – | `STAND = 0` = Platzhalter, wird verworfen | Durchmesser 0 wird verworfen; `Creux` (Hohllauf) ist durchgehend 0 und gültig |
| Prognose | Backend-Lauf | nicht berechnet (LKD ohne Grenzwerte) | nicht möglich (weder Laufleistung noch Grenzwerte) |

**MOB — was zu beachten ist:**

- **Umfang:** derzeit nur 104 Zeilen (Aug. 2024 – Jan. 2025), 3 Einheiten, 2 Drehgestelle; sieben Messgrößen (Durchmesser, Spurkranzdicke/-höhe, Flankenmaß qR, Hohllauf, Überwalzung, Radbreite).
- **Keine Radsatz-Ebene:** Die Daten kennen nur das Drehgestell. Die Einheiten-Übersicht zeigt deshalb `1` Drehgestell und `0` Achsen.
- **Vier Räder, ein Zähler → Messposition 1–4:** Je Drehgestell und Termin liefert die Messanlage vier Werte je Messgröße nacheinander im Abstand von etwa einer Minute, ohne Seiten- oder Achsangabe. Das Dashboard ordnet den k-ten Wert eines Termins der **Messposition k** zu. Jede Messposition ist eine eigene Zeitreihe mit Linie und eigener Ampel; die Drehgestell-Ansicht heißt dann „Messpositionen“, der Donut zählt vier Räder.
- **Messposition ≠ Radnummer:** Die Nummer folgt der Messreihenfolge. Welches Rad am Fahrzeug dahintersteckt (Achse 1 links/rechts …), steht nicht in den Daten. Die Zuordnung ist nur richtig, wenn die Anlage jedes Mal in derselben Reihenfolge misst. Über mehrere Termine ist das nicht prüfbar, solange keine Radnummer vorliegt.
- **Unvollständige Termine:** Hat ein Termin nicht genau vier Werte einer Messgröße, wird nichts geraten: Die Werte bleiben in der Sammel-Achse `(Radsatz-Zuordnung fehlt)` (nur Punkte, keine Linie).
- **Ampel grau:** Es gibt keine Grenzwerte und keine Laufleistung. Eine Prognose ist damit nicht möglich.
- **Drehgestell wechselt die Einheit:** `Bogie EV 1 / 137.21.0026_A` war in Einheit 271 ausgebaut und ist seit 22.08.2024 in Einheit 273 eingebaut. Es erscheint nur in Einheit 273 (zuletzt benutzter Platz); die Messwerte vom August 2024 aus Einheit 271 sind dadurch nicht mehr sichtbar (siehe Hinweis zur Lager-Liste unten). Das Lager ist bei MOB damit leer.
- **Prognose neu berechnen** ist nur für VGF freigegeben.

**Abellio — was zu beachten ist:**

- **Anzeige:** historische Messwerte von Durchmesser, Spurkranzdicke/-höhe, Flankenmaß qR, Hohllauf, Überwalzung, Radbreite, Spurmaß und Radinnenabstand. Bremsscheiben, Rund-/Planlaufabweichung und Durchmesserdifferenz werden nicht angezeigt.
- **LKD-Ampel grau:** In der Datenbank hat der Durchmesser weder `MIN` noch `MAX` noch `MIN_BEREICH`; ohne Grenzwert gibt es keine Ampel. Die Verläufe sind trotzdem sichtbar.
- **Einheiten ohne Radsatz-Zuordnung:** Bei etwa der Hälfte der Einheiten stehen die Messwerte nur auf Einheitenebene. Sie erscheinen unter `(ohne Drehgestell)` › `(Radsatz-Zuordnung fehlt)`. An einem Zähler hängen dort mehrere Achsen (bis zu 9 Werte je Tag); sie lassen sich ohne Achs-ID nicht trennen, das Diagramm zeigt daher mehrere Punkte je Tag.
- **Prognose neu berechnen** ist nur für VGF freigegeben (das Backend rechnet das VGF-Schema).
- **Zugangsdaten:** `config/oracle_connect_string.txt` enthält eine Zeile je Kunde (`vgf = user/passwort@dsn`, `abellio = …`, `mob = …`). Der Einstellungsdialog füllt Nutzer, DSN und Passwort beim Profilwechsel.

Neue Profile können im Ordner `wheelset_dashboard/config/profiles/` als YAML angelegt werden (siehe Technische Doku).

## 6. Bekannte Einschränkungen (Stand 1.0 RC)

- Oracle-Loader ist angebunden, aber in dieser Build ohne Live-DB getestet. **End-to-End-Test gegen Produktions-DB steht aus.**
- Für Abellio/MOB sind die Prognosedaten derzeit lückenhaft (vgl. ZAR-3219) — Dashboard zeigt die Historie, markiert Räder ohne Prognose als ⚪.
- Die Lager-Liste zeigt nur Komponenten, deren **zuletzt benutzter Platz das Lager** ist. Ein Drehgestell oder Radsatz mit eingebauten Zeilen (Ausbau leer, `AKTUELL = 1`) gilt als eingebaut und steht nicht im Lager (ausgeblendet: VGF 8 von 55, Abellio 95 von 162, MOB 1 von 1). Die **Messhistorie des früheren Einbaus** wird dabei nicht an die eingebaute Reihe angehängt, sie ist dann nirgends mehr sichtbar. Der Grund: Laufleistung und Prognose gelten je Einbau.
- Lager-"überholt"/"zu überholen"-Erkennung basiert auf LKD-Sprung ≥ 2 mm nach letztem Ausbau — Schwelle in `wheelset_dashboard/logic/lager_state.py` anpassbar.
