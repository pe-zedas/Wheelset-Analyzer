# Änderungen vom 2026-11-10

Nur bleibende Änderungen. Pfade relativ zum Dashboard-Package
`C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard\wheelset_dashboard\`.


## 1. Oracle-Zugangsdaten je Kundenprofil

Dateien: `config/app_paths.py`, `ui/settings_dialog.py`, `ui/main_window.py`,
`main.py`, `oracle_e2e.py`.

- `config/oracle_connect_string.txt` enthält jetzt **eine Zeile je Kunde**:
  `vgf = user/passwort@dsn`, `abellio = …`, `mob = …`. Eine alte
  unbeschriftete Zeile gilt weiterhin nur für `vgf`.
- Der **Einstellungsdialog** füllt beim Profilwechsel DSN, Nutzer und Passwort.
  Gibt es für das Profil keinen Eintrag, werden die Felder geleert (keine
  VGF-Zugangsdaten bei anderen Kunden) und der erwartete Dateieintrag genannt.
- Nach OK wird die Verbindung als Connect-String aufgebaut; damit läuft auch
  nach einem Profilwechsel der schnelle Parallel-Ladepfad.
- `main.py --profile` und `oracle_e2e.py --profile` lesen den Eintrag des
  angegebenen Profils (das E2E-Skript ignorierte `--profile` bisher).
- Entfernt: `write_oracle_connect_string` (ungenutzt; hätte die Datei mit allen
  Kunden überschrieben).


## 2. Abellio: historische Radsatzdaten einlesen und anzeigen

Dateien: `config/profiles/abellio.yaml` (neu geschrieben), `data/profile.py`,
`data/csv_source.py`, `data/oracle_source.py`.

Grundlage ist eine Analyse der echten Abellio-Daten (120 326 Zeilen, 2018–2022):

| Befund | Umsetzung |
|---|---|
| Seite steckt in vier Schreibweisen im Namen (`links`, `[Radscheibe Laufradsatz (L)]`, `[Radscheibe Treibradsatz (L)]`, `[Radscheibe links]`) | Neue Regex je Messgröße. Das alte Muster `(L\|links)` hielt **rechte** Räder für links, weil `Laufradsatz` ein großes L enthält. |
| `DGEINBAUPOS` nicht eindeutig (39 Einheiten, z. B. mehrere `Drehgestell`) | `structure.dg_key: id`: Drehgestelle über die ID führen; Beschriftung nur bei Kollision um die Bezeichnung ergänzt. Vorher wären die Messreihen verschiedener Räder zu einer vermischt worden. |
| Zeilen nur auf Einheitenebene (95 von 171 Einheiten) oder nur mit DG | `structure.fallback_axle: true`: Sammel-Achse `(Radsatz-Zuordnung fehlt)`. |
| `STAND = 0` als Platzhalter (4 624 von 14 374 Durchmesser-Zeilen) | `valid_range` je Messgröße; verworfen wurden exakt die 21 740 Nullwerte, kein echter Messwert. |
| `MIN_BEREICH`/`MAX_BEREICH` = konstante Toleranzbereiche (Sh 26–36, Sd 27,5–33, Spurmaß 1415–1426, Radinnenabstand 1359–1363) | `thresholds.bereich_as_limits: true`: gelten als Grenzwerte (rot). Annahme, siehe Hinweis unten. |
| LKD hat keine Grenzwerte | Ampel grau, Verlauf sichtbar. |
| Prognose-Tabelle hat `LETZTEAENDZEIT`, das Profil verlangte `LASTUPDATE` | Profil korrigiert; die Abfrage wäre mit „ungültiger Bezeichner" gescheitert. |
| `ZAEHLERHISTORIEID`, `LASTRUNID`, `LASTUPDATE` im Dashboard ungenutzt | Nicht mehr geladen (weniger Datenvolumen). |

Weitere Änderungen im Loader (gelten für alle Profile, VGF-Ergebnis ist
nachweislich identisch):

- Gemeinsamer Messpunkt-Builder `_make_messpunkt` für CSV und Oracle
  (Wertebereich, Bereich-als-Grenzwert); der ältere Oracle-Pfad nutzt jetzt
  dieselbe Zeilenverarbeitung statt einer Kopie.
- Unbekannte Messgrößen werden vor der Textkonvertierung verworfen;
  `classify_zartbez` merkt sich das Ergebnis je Bezeichnung.
- Lager-Zeilen ohne DG **und** Radsatz verschmelzen nicht mehr zu einer
  Phantom-Komponente, sondern werden übersprungen und gezählt.

Ergebnis: 171 Einheiten, 415 Drehgestelle, 697 Achsen, 43 125 Messpunkte,
162 Lager-Komponenten; Laden 3,3 s.

**Grenzen:** Bei den Einheiten ohne Radsatz-Zuordnung hängen mehrere Achsen an
einem Zähler (bis zu 9 Werte je Tag) und lassen sich ohne Achs-ID nicht
trennen. Bremsscheiben, Rund-/Planlauf und Durchmesserdifferenz werden nicht
angezeigt (keine Spalte im Dashboard).


## 3. Fälligkeiten-/Flotten-Ansicht: schneller bei vielen Einheiten

Datei: `ui/views.py` (`FlotteView.set_flotte`).

Die Fälligkeiten-Kachel wurde beim Füllen dreimal neu aufgebaut (Sortier-Hook,
Filter, abschließend), je ~0,7 s bei 171 Einheiten. Jetzt nur noch einmal am
Ende; der Aufbau der Flotten-Ansicht sank von 2,4 s auf 1,1 s.


## 4. Diagramm: „heute"-Linie staucht historische Verläufe nicht mehr

Datei: `ui/plot_widget.py`.

`axvline(heute)` zog die Zeitachse bis heute auf, sodass ein Verlauf, der Jahre
zurückliegt (Abellio: Messungen enden 2020–2022), in einer Ecke klebte. Die
Linie wird nur noch gezeichnet, wenn sie den Datenbereich um höchstens die
Hälfte verlängert; bei aktuellen Daten (VGF) ändert sich nichts.


## 5. „Prognose neu berechnen" nur für VGF

Datei: `ui/main_window.py`.

Das Backend liest immer die VGF-Datenbank (eigener Connect-String,
VGF-Spaltennamen). Bei anderen Profilen erscheint ein Hinweis statt eines
Laufs, der die falsche Prognose rechnen würde.


## 6. Qt-Binding festgelegt

Datei: `__init__.py`.

`QT_API=pyside6` wird im Paket gesetzt. Ist PyQt5 installiert, wählt `qtpy`
(über `qtawesome`) sonst PyQt5; zwei Qt-Bindings in einem Prozess stürzen mit
einer Access Violation ab. Betroffen war ein direkter Import von
`ui.main_window` ohne vorherigen PySide6-Import (z. B. in Skripten);
der normale App-Start war nicht betroffen.


## 7. Schema (Kundenprofil) in der Oberfläche sichtbar

Dateien: `ui/main_window.py`.

Im Kopf neben dem Logo steht eine Marke `Schema: Abellio` (bzw. `VGF`, `MOB`);
der Tooltip nennt die Profilbeschreibung. Der Fenstertitel lautet
`Wheelset Analyzer Dashboard — Abellio`. Die Anzeige wird bei jedem Laden
aktualisiert, also auch nach einem Profilwechsel im Einstellungsdialog.


## 8. Donut: Achsen mit nur seitenlosen Messwerten werden gezählt

Dateien: `ui/views.py` (`_iter_achse_rad`, Lager-Donut `_count_axle`),
`ui/overview_widgets.py` (`DonutCanvas.set_counts`).

- **Fehler:** Einheit 121101 (Abellio) hat ein Triebdrehgestell, dessen
  Messwerte am Drehgestell ohne Seitenangabe stehen (`Rad unspecified`). Der
  Donut zählte nur linke/rechte Räder und zeigte deshalb „keine Daten", obwohl
  Daten vorlagen. Jetzt zählt eine Achse, die **nur** seitenlose Messwerte hat,
  als eine Messstelle. Bei Achsen mit linkem/rechtem Rad bleibt alles wie
  bisher (das seitenlose Pseudo-Rad trägt dort nur Spur-/Stichmaß und wird auf
  beide Räder übertragen).
- **Leerzustand:** Bei „keine Daten" blieben die Achsenzahlen 0,0–1,0 des
  leeren Diagramms stehen. Die Achse wird jetzt ausgeblendet.
- VGF-Donuts sind unverändert (alle 27 Donut-Aufrufe über Flotte, Einheiten,
  Drehgestelle und Lager vor/nach der Änderung identisch).


## 9. MOB: Import und Darstellung angepasst

Dateien: `config/profiles/mob.yaml` (neu geschrieben), `ui/views.py`,
`ui/plot_widget.py`.

Grundlage ist eine Analyse der echten MOB-Daten (104 Zeilen, 08/2024 – 01/2025):

| Befund | Umsetzung |
|---|---|
| Nur Drehgestell-Ebene (kein Radsatz) – Messwerte lagen in `direkt_messreihen`, die UI hat dafür weder Diagramm noch Drilldown | `hierarchy_depth: 4` + `structure.fallback_axle`: Sammel-Achse `(Radsatz-Zuordnung fehlt)`, Diagramm erreichbar (später auf Messpositionen aufgeteilt, siehe 11) |
| Je Drehgestell und Termin 4 Werte im Minutenabstand unter einem Zähler, ohne Seite/Achse | Sammel-Achse zeichnet **nur Punkte** (keine Linie zwischen verschiedenen Rädern); Radnummern werden nicht erfunden |
| Keine Laufleistung, keine Grenzwerte | Ampel grau, keine Prognose |
| Prognose-Tabelle: `LETZTEAENDZEIT`, das Profil verlangte `LASTUPDATE` | Profil korrigiert (die Abfrage warf `ORA-00904`) |
| Bezeichnungen mit Leerzeichen am Ende (`Creux `, `Cote qR `) | Muster tolerieren das; alle sieben Namen werden erkannt |
| `Creux` (Hohllauf) durchgehend 0 | gültig, kein `valid_range` |
| DG-Position `Bogie EV 1 (IO)` bei allen Drehgestellen gleich, Drehgestell wechselt die Einheit | `dg_key: id` |

Ergebnis: 2 eingebaute Einheiten, 104 von 104 Zeilen verarbeitet. Einheit
271 hat nur ausgebaute Zeilen (`AKTUELL = 0`); ihr Drehgestell ist inzwischen
in Einheit 273 eingebaut und steht deshalb nicht im Lager (siehe 10).

**Ansichts-Änderungen (gelten für alle Profile):**

- **Zahlen in den Tabellen:** `Drehgestelle`/`Achsen` zählen nur echte
  Strukturen; Sammel-Drehgestell und Sammel-Achse zählen nicht mit (MOB: `1` und
  `0`). VGF unverändert (dort gibt es keine Sammelobjekte).
- **Diagramm, Sammel-Achse:** nur Punkte, keine Verbindungslinie (gilt auch für
  die Abellio-Einheiten ohne Radsatz-Zuordnung).
- **Diagramm, Datumsbeschriftung:** Bei Zeiträumen unter 150 Tagen statt
  `%Y-%m` (an jeder Marke gleich) jetzt `TT.MM.JJJJ`, unter 3 Tagen mit Uhrzeit.
  Betrifft auch kurze VGF-Reihen (64 von 320), die bisher wiederholte,
  identische Beschriftungen zeigten.


## 10. Lager-Liste: wieder eingebaute Komponenten ausgeblendet

Dateien: `data/csv_source.py` (`drop_reinstalled_lager`, aufgerufen aus
`finalize_structure`), `data/models.py` (`LagerKomponente.dg_id`).

Es zählt der zuletzt benutzte Platz: Gibt es zu einer Lager-Komponente
eingebaute Zeilen (Ausbau leer, `AKTUELL = 1`) mit derselben DG-ID bzw.
Radsatz-ID, steht sie nicht im Lager.

| Profil | Lager vorher | nachher |
|---|---|---|
| VGF | 55 | 47 |
| Abellio | 162 | 67 |
| MOB | 1 | 0 |

Eingebaute Struktur und Prognose sind unverändert (VGF: gleicher
Fingerabdruck, Flotten-Donuts identisch; der Lager-Donut zählt 184 statt 216 Räder).

**Folge:** Die Messhistorie des früheren Einbaus (z. B. VGF `STGx / 176505`:
342 Punkte) ist nirgends mehr sichtbar. Sie wird bewusst nicht an die
eingebaute Reihe angehängt, weil die Laufleistung je Einheit gilt und die
Dashboard-Prognose sonst andere Werte rechnen würde.

Außerdem: Die leere Lager-Liste zeigt im Fälligkeiten-Feld „keine Einträge“
statt eines leeren Standard-Diagramms und behält keine Einträge des vorigen
Profils (`LagerView._rebuild_gantt_from_table`).


## 11. MOB: Räder auf Messpositionen verteilt

Dateien: `config/profiles/mob.yaml` (`structure.wheel_positions: 4`),
`data/csv_source.py` (`split_wheel_positions`, `is_synthetic_axle`),
`data/profile.py`, `ui/views.py`.

Befund aus den echten Daten: Je Termin liefert die Messanlage je Messgröße
4 Werte im Abstand von ca. einer Minute; je Rad stehen alle Messgrößen
(6 oder 7) direkt hintereinander. Der k-te Wert eines Termins wird daher der
**Messposition k** zugeordnet (Messreihenfolge).

| Vorher | Jetzt |
|---|---|
| eine Sammel-Achse, nur Punkte | vier Achsen „Messposition 1–4“, je eine Zeitreihe mit Linie |
| Donut: Drehgestell = 1 Messstelle | Donut: 4 Räder |
| Titel „Achsen · … (0 Achsen)“ | Titel „Messpositionen · … (4 Messpositionen)“ |

Grenzen: Die Nummer ist die Messreihenfolge, nicht die Radnummer am
Fahrzeug (nicht in den Daten, über Termine nicht prüfbar). Termine mit
anderer Anzahl Werte bleiben ungeteilt in der Sammel-Achse. Die
Reihenfolge der `ZAEHLERHISTORIEID` wird nicht verwendet: In einem Termin
(Einheit 383, 09.08.2024) weicht sie von der Zeitreihenfolge ab.

Die Messpositionen zählen in den Tabellen nicht als Achsen. Eine künftige
MOB-Prognose würde sie nicht trennen können, weil ihnen die Radsatz-ID
fehlt (ohne Laufleistung ist sie ohnehin nicht möglich).


## 12. Aggregation aus den Ansichten nach `logic/aggregation.py`

Dateien: `logic/aggregation.py` (neu), `ui/views.py` (1.500 → 1.170 Zeilen).

Donut-Zählung, Messgrößen-Spalten, Gantt-Daten und Strukturzahlen standen in `ui/views.py`,
die Lager-Ansicht zählte die Donut-Räder zusätzlich in einem eigenen Inline-Block. Die
Regel „Achse ohne Seitenangabe zählt als eine Messstelle“ musste deshalb an zwei Stellen
gepflegt werden. Jetzt gibt es eine Zählung (`status_counts`) für Flotte, Einheit,
Drehgestell, Achse und Lager (Komponente oder Liste). Die Funktionen sind öffentlich
benannt (`status_counts`, `collect_messgroessen_values`, `collect_gantt_entries`,
`n_real_dg`, `n_real_achsen`, `n_messpositionen`) und ohne Qt testbar.

Nicht verwendeter Code entfernt: `_iter_messreihen` in der Form der Ansicht,
`_collect_messgroessen_statuses`.

**Prüfung:** Vor dem Umbau wurde das Verhalten für alle drei Profile festgehalten (VGF per CSV,
Abellio und MOB live aus Oracle): Donut-Zahlen je Flotte/Einheit/Drehgestell/Achse, Lager-Donut
in allen drei Filtern, Messgrößen-Werte, Gantt-Einträge, Strukturzahlen und die Donut-Aufrufe der
echten Ansichten. Nach dem Umbau sind sie **identisch**; einzige Abweichung ist ein
Gantt-Termin, der um Mitternacht den Tag wechselt (die Verschiebung hängt von der Uhrzeit ab).

## 13. Laden und Backend-Lauf im Hintergrund

Dateien: `ui/jobs.py` (neu), `ui/main_window.py`.

Vorher liefen `reload_data` und `recalc_prognose` im GUI-Thread: Oracle-Laden 3–10 s,
Backend-Lauf Minuten, in denen Windows das Fenster als „reagiert nicht“ markieren kann.
Jetzt läuft beides in einem Hintergrund-Thread (Details: Technische Doku 4b).

Gemessen gegen die echten Schemas (Fenster bedienbar nach / Daten nach): MOB 0,10 s / 0,85 s,
Abellio 0,02 s / 4,0 s, VGF 0,03 s / 2,4 s. Während des Ladens läuft die Ereignisschleife
weiter (z. B. Abellio: 54 Timer-Ticks à 50 ms). Die Hinweis-Meldung der Neuberechnung
sagt nicht mehr „das Dashboard reagiert nicht“.

Nebenwirkung: Das Schema-Etikett und der Fenstertitel wechseln erst, wenn die Daten des neuen
Profils angezeigt werden (vorher sofort, mit den alten Daten darunter).

## 14. Rohdaten-Export: Lager-Drehgestelle fehlten

Datei: `logic/export.py`.

`export_raw_csv` schrieb von Lager-Komponenten nur `messreihen` und `raeder`. Die Messwerte
eines Lager-**Drehgestells** hängen an dessen Achsen und wurden nicht exportiert (VGF-Szenario
im Test: 36 statt 44 Zeilen). Jetzt kommen sie mit Drehgestell- und Achsangaben dazu; die
bisherigen Zeilen bleiben unverändert. Gefunden durch den neuen Smoke-Test.


## 15. Achsen-Diagramm: leere Anzeige bei Abellio/MOB behoben

Dateien: `ui/views.py` (`AchseView._sync_controls`), `ui/plot_widget.py`.

**Fehler:** Die Achsen-Ansicht wird für alle Achsen wiederverwendet, die Auswahl
`X-Achse` und `Rad` blieb beim Wechsel stehen. Wer zuvor „Laufleistung [km]“ oder „Nur links“
gewählt hatte, sah danach bei Abellio/MOB (keine Laufleistung, keine Radseite) ein leeres
Diagramm; die Konsole meldete „No artists with labels found to put in legend“.

**Behebung:**
- Beim Öffnen einer Achse wird die Auswahl angepasst: Ohne Laufleistung wird „Laufleistung [km]“
  deaktiviert und auf „Datum“ gesetzt, ohne Radseite wird „Rad“ deaktiviert und auf „Beide“ gesetzt
  (mit Hinweis im Tooltip). Bei normalen Achsen bleibt die Auswahl erhalten.
- Ist ein Diagramm trotzdem ohne Punkte, steht ein Hinweis darin („Keine Messwerte für diese
  Auswahl“ bzw. „Keine Laufleistung in den Daten“) statt einer Legenden-Warnung.


## 16. Spalte „Messdaten vorhanden“ (Diagramm-Symbol)

Dateien: `ui/views.py` (`_MessdatenItem`, `_set_messdaten_cell`, `_setup_messdaten_column`),
`logic/aggregation.py` (`has_messdaten`, `iter_messreihen` kennt jetzt Lager-Komponenten).

Ganz rechts in den Tabellen Flotte (Einheiten), Einheit (Drehgestelle), Drehgestell (Achsen) und
Lager steht in einer schmalen Spalte (30 px) ein Diagramm-Symbol, wenn die Zeile selbst oder eine
darunterliegende Komponente mindestens einen Messpunkt hat (Messdaten direkt am Drehgestell
zählen mit). Ohne Messdaten bleibt die Zelle leer. Die Spalte sortiert nach Vorhandensein und wird
vom Freitextfilter nicht als Text gelesen.


## 17. Entscheidung: Dashboard-eigener Prognose-Code bleibt erhalten

Datei: `logic/prognose.py` (nur Kopfkommentar geändert).

Der Code zur Prognose direkt in der App (Theil-Sen, Reprofilierungs-Lernen, Zyklus-Fit,
Konfidenzband) wird **aktuell nicht genutzt**: Die Anzeige liest die Prognose aus
`BO_RADSATZDATEN_PROGNOSE`; aus dem Modul wird nur `faelligkeit_shift` verwendet
(22 von 23 Funktionen ohne Aufrufer). Er bleibt **zunächst erhalten** und wird nicht gelöscht;
der Kopfkommentar der Datei hält das fest. Offen: ob er für Abellio/MOB reaktiviert wird (das
Backend rechnet nur das VGF-Schema) und ob er weiter mit dem Backend abgeglichen wird.


## 18. Umbau der Struktur (Schritte 5 und 6 der Verbesserungsliste)

Ziel: weniger doppelter Code, klarere Schichten, kürzere Funktionen — **ohne Verhaltensänderung**.

**Datenschicht**
- `data/csv_source.py` zerlegt: `parsing.py` (Text → Wert), `structure.py` (Aufbau Flotte/Lager aus
  Rohzeilen, `build_flotte`), `prognose_source.py` (Prognose-Anreicherung), `csv_source.py` liest nur noch Dateien.
- **CSV und Oracle teilen jetzt denselben Aufbau und dieselbe Prognose-Anreicherung.** Vorher gab es zwei
  zu rund 60 % deckungsgleiche Prognose-Parser (je 130–160 Zeilen) und zwei Rohdaten-Parser. Die Oracle-Werte
  werden nur zuvor in Text umgewandelt. Dabei vereinheitlicht: Die Bezeichnung wird in beiden Wegen gestrippt
  (die CSV tat es schon, Oracle nicht).
- **Ein Oracle-Ladeweg:** Connect-String, zwei parallele Sessions. Entfernt: `load_flotte_from_oracle`,
  `load_flotte_from_connect_string`, `load_prognose_from_connect_string`. DSN/Nutzer/Passwort aus dem Dialog
  werden zum Connect-String zusammengesetzt; unvollständige Angaben melden einen klaren Fehler.
- `init_oracle_client` (Thick-Mode) steht nur noch an einer Stelle (vorher dreimal).
- **Synthetische Strukturen sind im Modell markiert** (`Achse.kind` = `radsatz`/`sammel`/`messposition`,
  `Drehgestell.synthetic`) statt über Beschriftungen erkannt zu werden. Ansichten und Auswertung importieren
  keine Konstanten mehr aus dem CSV-Loader; `_worst_status`/`_worst_messreihe` heißen öffentlich
  `worst_status`/`worst_messreihe`.
- Profil-Schalter `backend_prognosis` statt `profile.name != "vgf"` im Hauptfenster.

**Oberfläche**
- `ui/views.py` (1.170 Zeilen) → Paket `ui/views/` (common, flotte, einheit, drehgestell, achse, lager).
  Der Anzeigemodus „Messwerte anzeigen“ wird über `show_values()` gelesen.
- Lange Funktionen zerlegt: `PlotCanvas.plot_messreihen` (322 → ca. 35 Zeilen Ablauf + Teilschritte),
  `MainWindow.__init__` (163), `GanttCanvas.set_entries` (145), `AchseView._redraw_current` (123),
  `SettingsDialog.__init__` (120, Baum jetzt datengesteuert), `collect_gantt_entries` (120) und der
  parallele Oracle-Lader.

**Hygiene**
- `perf.py`: gemeinsamer Zeitmesser (`timed`, `Timer`) ersetzt rund 45 verstreute `time.monotonic()`-Paare;
  alle bisherigen DEBUG-Zeitangaben bleiben erhalten.
- `smoketest.py` und `oracle_e2e.py` nach `tools/` (`python -m tools.smoketest`).
- `keyring` aus `requirements.txt` entfernt (wurde nirgends benutzt); neu `pyproject.toml`,
  `requirements-dev.txt`, `requirements-lock.txt` (zuletzt getestete Versionen). README neu geschrieben,
  Kommentar in `start_vgf_oracle.bat` korrigiert.
- Ungenutzte Importe entfernt (außer in `logic/prognose.py`, siehe Punkt 17).

**Prüfung (jeweils gegen den Stand vor dem Umbau, VGF per CSV und Oracle, Abellio und MOB live aus Oracle):**
- Struktur-Fingerabdruck der geladenen Flotte (alle Einheiten, Drehgestelle, Achsen, Räder, Messreihen, Messpunkte,
  Status, Prognosen, Lager): **identisch** für alle drei Profile; auch VGF über Oracle mit 64 prognostizierten Messreihen.
- 84 gerenderte Ansichten je Lauf (Flotte, Einheit, Drehgestell, Achse mit mehreren Reitern und km-Modus, Lager,
  alle Seiten des Einstellungsdialogs; Uhr eingefroren): **pixelgleich**. Dabei wurde ein echter Fehler gefunden
  und behoben (das Radachsen-Bild fehlte nach dem Verschieben von `views.py`, der Dateipfad war eine Ebene zu flach).
- `plot_messreihen`: alle 3.960 VGF-Diagramme (alle Achsen inkl. Lager, alle Messgrößen, drei Radauswahlen, beide
  X-Achsen) alt gegen neu: **0 Abweichungen**.
- `collect_gantt_entries`: alle Gruppen alt gegen neu bei eingefrorener Uhr: VGF 72, Abellio 653, **0 Abweichungen**.

## 19. Backend: Lager-Achse über Positionen hinweg als eine Reihe

Dateien (Backend `Wheelset Analyzer_new_approach`): `radsatz_axis_labels.py`,
`Radsatz_Bahn_DB_new_Approach.py`; Doku `Programm_Doku_new_Approach.md` Rev. 7 (13.10).

**Anlass:** Für das VGF-Drehgestell `s SLGx / 176320` gab es keine Prognose. Dieselbe Achse saß bis 2013
in Laufdrehgestell 2 und danach in Laufdrehgestell 1; das Backend führte sie deshalb als zwei Reihen mit
je 3 Messpunkten, und die Mindestpunktzahl (Kreuzvalidierung wählt 4) war nicht erreicht.

**Änderung:** Eine Lager-Achse wird über ihre `RSEINHEITID` geführt, ihre Position ist die der jüngsten
Messung. Ergebnis an einer Kopie: 81 statt 79 Lager-Radsätze mit Prognose, `176320` wird berechnet.
**Nebenwirkung** (siehe Backend-Doku 13.10): Einzelne Werte weiterer Achsen verschieben sich geringfügig,
da das Reprof-Lernen die zusammengeführten Achsen sieht (6 Lager-Radsätze, 1 eingebaute Achse;
größter Ausschlag `176489` mit ca. +219 Tage beim Grenzdatum). Wirksam wird die Änderung in der Datenbank
erst mit dem nächsten Backend-Lauf („Prognose neu berechnen“).


## 20. „Prognose neu berechnen“: INI-Werte per Kommandozeile statt INI umschreiben

Dateien: Backend `radsatz_settings.py`, `Radsatz_Bahn_DB_new_Approach.py` (Doku 13.11); Dashboard
`logic/backend_runner.py`, `tests/test_backend_runner.py`.

**Anlass:** Ob beim Lauf aus dem Dashboard Plotfenster erscheinen, hing allein von `radsatz_config.ini`
ab (`show_plot`/`plot_show_window`). Stand beides auf `true`, hing der Lauf an einem Fenster, bis das
Zeitlimit (30 min) ihn abbrach.

**Umsetzung:** Das Backend nimmt `--set abschnitt.schluessel=wert` entgegen (Vorrang vor der INI). Das
Dashboard übergibt `pipeline.use_database`, `pipeline.write_prog_data=true`, `plot.show_plot=false`,
`plot.plot_show_window=false`. Die INI wird **nicht mehr verändert** (früher wurden `use_database` und
`write_prog_data` in die Datei geschrieben und eine `.ini.bak` angelegt).

**Prüfung:** Backend-Kopie mit `show_plot = plot_show_window = true` in der INI, Lauf über
`run_backend_prognose`: erfolgreich nach 10 s, INI danach byte-gleich. Derselbe Lauf ohne Plot-Überschreibung
bleibt an einem Fenster hängen. 15 neue Tests (Befehlszeile, INI unverändert, Fehlerfälle, Vorrang vor der INI).


## 21. Wirkungslose Prognose-Einstellungen entfernt

Dateien: `ui/settings_dialog.py`, `ui/main_window.py`, `data/models.py` (`PrognoseConfig.show_ci_band`),
`doc/Anwenderhandbuch.md`, `tests/test_settings_dialog.py`.

Anlass: „Konfidenzband anzeigen“ zeigte nichts im Diagramm. Das Band wurde aus dem dashboard-eigenen
Prognose-Fit berechnet und mit der Umstellung auf die Prognose aus der Tabelle (`4fdc39a`, 5.11.) aus dem
Diagramm entfernt; die Tabelle enthält keine Konfidenzwerte. Eine Prüfung ergab, dass **keine** der
Prognose-Einstellungen mehr gelesen wurde (nur vom ungenutzten Code in `logic/prognose.py`).

Entfernt sind: Konfidenzband und Konfidenzniveau, Reprofilierungs-Erkennung (Auto-Erkennung, Sprung-Schwelle),
Standard-Werte (Sprung, Intervall) und „Treppen-Prognose“, jeweils mit Dialogseite, Baumeintrag,
Konfigurationsschlüsseln und der Übergabe im Hauptfenster. Der Dialog enthält unter „Prognose“ nur noch
die Neuberechnung (der Eintrag „Prognose“ zeigt dieselbe Seite). Der Hinweistext dort stimmt wieder („das
Dashboard bleibt bedienbar“).

Unverändert: `PrognoseConfig` bleibt als Datenklasse mit Standardwerten für den erhaltenen, ungenutzten
Prognose-Code bestehen, ebenso die durchgereichten Parameter in den Ansichten (ohne Wirkung). Das PRD nennt
weiter ein optionales 90-%-KI-Band; es ist nicht umgesetzt. Ein Band bräuchte die Steigungsgrenzen aus dem
Backend (zusätzliche Spalten in `BO_RADSATZDATEN_PROGNOSE`).


## 22. Optional: Zeitachse mit Sprung zum aktuellen Datum

Dateien: `ui/time_axis.py` (neu), `ui/plot_widget.py`, `ui/settings_dialog.py`, `ui/main_window.py`,
`ui/views/achse.py` (`redraw()`), `data/models.py` (`PrognoseConfig.time_jump`), `tests/test_time_axis.py`,
`tests/test_settings_dialog.py`, `doc/Anwenderhandbuch.md`.

Anlass: Im Achsen-Diagramm liegen die letzten Messwerte oft Jahre zurück; die Prognose schließt sich direkt
an und steht damit in der Vergangenheit, während Kacheln und Gantt die Termine auf „heute“ verschieben
(`faelligkeit_shift`).

Umsetzung (neue Einstellungsseite *Darstellung*, Standard **aus**, nicht gespeichert): Das Diagramm bleibt
unverändert (eine durchgehende Achse, gleicher Maßstab, Prognose am Verlauf). Nur die **Beschriftung** der
Zeitachse ändert sich: links vom Übergang (letzter Messwert) echte Daten, rechts davon das um den Abstand
zu heute verschobene Datum. Am Übergang steht eine senkrechte Linie mit der Überschrift „heute (Datum)“
über der Achse (links der Linie, wenn sie im rechten Teil liegt, damit die Legende sie nie verdeckt);
das Wort „heute“ steht nicht an der Achse. Die Marken liegen auf runden Zeitpunkten (Jahresmarken am
1. Januar, Monatsmarken an Vielfachen des Intervalls) und werden bei jedem Zeichnen neu berechnet. Alle
Marken mit Text bleiben sichtbar; nur wenn sich die letzte linke und die erste rechte Marke berühren würden
(< 56 px), entfällt die linke. Wirkt nur bei X-Achse „Datum“, mit gezeichneter Prognose und wenn der letzte
Messwert mehr als 90 Tage zurückliegt. Bei ausgeschalteter Option läuft derselbe Code wie vorher
(die bisherige Heute-Linie bleibt); die Linien und Achsengrenzen sind mit der Option an identisch.

Schalter im Diagramm: In der Steuerleiste des Achsen-Diagramms (neben X-Achse und Rad) steht die Checkbox
„Zeitachse mit Prognose ab heute“. Sie stellt sofort um und meldet den Stand (`time_jump_changed`)
an das Hauptfenster, das ihn in `PrognoseConfig.time_jump` merkt; Einstellungsdialog und weitere Diagramme
übernehmen ihn. Der Schalter hat Vorrang vor der Konfiguration (`AchseView._effective_config`), ist bei
X-Achse „Laufleistung“ gesperrt und erklärt im Tooltip, wenn er keine Wirkung hat (keine Prognose oder letzter
Messwert höchstens 90 Tage zurück; Hilfsattribut `PlotCanvas.time_jump_active`). Das Achsen-Diagramm ist das
einzige Diagramm der Anwendung.

Kachel „letzter Messwert“ im Achsen-Diagramm: zeigt unter dem Wert das Datum der Messung („Messung JJJJ-MM-TT“,
`AchseView._cards_for`). Beschriftung von Schalter und Einstellung: „Zeitachse mit Prognose ab heute“.

Folgeänderungen:
- Der Schalter „Zeitachse mit Prognose ab heute“ ist **ausgeblendet**, wo er nichts bewirken kann: bei
  X-Achse „Laufleistung“, bei Diagrammen ohne Prognose und wenn der letzte Messwert höchstens 90 Tage
  zurückliegt (`PlotCanvas.time_jump_possible`, `AchseView._update_jump_control`). Sein Stand bleibt erhalten.
- Die Datumsangaben in den Kacheln unter dem Diagramm (letzter Messwert, Grenz-/Warntermin) haben einheitlich
  das Format TT.MM.JJJJ (`views/common.fmt_date`). Die Tabellen und das Gantt sind unverändert.
- **Neue Spalte ganz rechts in den Tabellen Flotte, Einheit, Drehgestell und Lager: „Prognosewerte
  vorhanden“** (Symbol: Diagramm mit durchgezogener, gepunktet fortgesetzter Linie, selbst gezeichnet;
  Tooltip, 30 px, sortierbar). Regel `logic/aggregation.has_prognose`: mindestens eine Messreihe mit
  Messwerten hat eine Treppenkurve oder einen Termin/eine Laufleistung aus der Prognose-Tabelle. Das
  Messdaten-Symbol steht jetzt in der vorletzten Spalte. In der Einheit-Tabelle war die Symbolspalte bisher
  nicht auf 30 px festgelegt; das ist nachgeholt. Tests: `tests/test_prognose_icon.py`.

- Texte der beiden Symbole: „Historische Daten vorhanden“ (Diagramm) und „Prognose vorhanden“ (Linie, gepunktet
  fortgesetzt). Sie erscheinen beim Überfahren mit der Maus (Tooltip der Zelle und der Spaltenüberschrift) und
  beim Anklicken des Symbols (`BaseView._on_cell_clicked`, `QToolTip` an der Mauszeigerposition). Tests dazu in
  `tests/test_prognose_icon.py` (Gesamt jetzt 226 Tests).

- **„Messwerte anzeigen“:** Das Status-Symbol in der ersten Spalte (Gesamtstatus der Zeile) blieb bei eingeschalteter
  Option leer, weil dort kein Messwert übergeben wird. Es wird jetzt immer angezeigt
  (`set_ampel_cell(..., always_dot=True)` in den vier Tabellen); die Messgrößen-Spalten zeigen wie bisher Punkt und Wert.
- **Spaltenbreiten** (`views/common.py`: `fit_to_text`, `fill_column_min_text`): Die Zählspalten (Flotte: Drehgestelle,
  Achsen; Einheit: Achsen) sind so schmal, wie der Text samt Sortierpfeil es erfordert (statt der Qt-Standardbreite;
  z. B. 107 → 96 px und 77 → 68 px). Die Namensspalte (Flotte: Einheit, Einheit: DG-Position, Drehgestell:
  RS-Bezeichnung, Lager: letzte Einheit) füllt weiter den freien Platz, wird aber **nicht schmaler als ihr breitester
  Eintrag**; wird das Fenster noch schmaler, erscheint der waagerechte Scrollbalken. Tests: `tests/test_table_columns.py`.

- **Navigationsleiste im Lager-Kontext** (`MainWindow._navigate_lager`): Ein Klick auf das Lager-Drehgestell in der
  Leiste (Lager › Drehgestell › Achse) sprang sofort zur Lager-Tabelle, weil jeder Pfad mit „lager“ dorthin führte. Jetzt
  führt er zur Achsenliste dieses Drehgestells; „Lager“ führt zur Lager-Tabelle. Dafür merkt sich das Hauptfenster die
  zuletzt geöffnete Lager-Komponente (nach dem Neuladen verworfen, da die Objekte veraltet sind). Außerdem bleibt
  „Messwerte anzeigen“ in der Lager-Achsenliste jetzt in dieser Ansicht (sprang vorher zur Flotte). Tests:
  `tests/test_navigation_lager.py`.

Bewusst nicht umgesetzt: Speichern der Einstellung (erst prüfen, ob die Darstellung als Standard taugt).


## 23. Als EXE packen (PyInstaller): Startpunkt und App-Root-Pfad

Dateien: `run_dashboard.py` (neu), `config/app_paths.py`, `README.md` ("Als EXE packen"), `.gitignore`,
`tests/test_app_paths.py`.

Anlass: `pyinstaller wheelset_dashboard/main.py` (bzw. jeder direkte Aufruf dieser Datei als Skript) bricht
mit `ImportError: attempted relative import with no known parent package` ab — `main.py` benutzt relative
Imports (`from .config import ...`), die nur funktionieren, wenn Python die Datei als Teil des Pakets
`wheelset_dashboard` importiert, nicht als eigenstaendiges Skript.

Behoben durch `run_dashboard.py` im Projektordner (ausserhalb des Pakets), das `wheelset_dashboard.main.main`
ganz normal importiert und aufruft; PyInstaller baut auf dieser Datei statt auf `wheelset_dashboard/main.py`.
Dabei aufgefallen und mit behoben: `config/app_paths.py` leitete `APP_ROOT` bisher immer von `__file__` ab —
als PyInstaller-EXE zeigt das auf das Temp-Extraktionsverzeichnis (`sys._MEIPASS`), das `--onefile` nach jedem
Lauf verwirft. Die Betriebs-Konfiguration (Oracle-Connect-String, Logdatei) waere damit bei jedem Start weg
gewesen. `APP_ROOT` wird jetzt im gefrorenen Betrieb (`sys.frozen`) aus `sys.executable` berechnet und liegt
damit dauerhaft neben der `.exe`; im normalen Betrieb (Tests, `python -m wheelset_dashboard.main`) unveraendert
der Projektordner. Mit einem echten `pyinstaller --onedir`-Build geprueft: Start ohne Fehler, Logdatei und
(sobald benoetigt) `config/` liegen neben der `.exe`.

Zwei Folgepunkte beim ersten EXE-Test: Der Ordner `config/` (Connect-String) wird nicht mitgebaut — er muss
einmalig neben die `.exe` kopiert werden, sonst bleibt die Oracle-Verbindung leer (Einstellungsdialog zeigt das
dann richtig). Und ohne Parameter startet die EXE wie gewohnt mit `--source csv` und sucht CSV-Dateien relativ
zum Arbeitsverzeichnis — fuer Oracle sind `--profile`/`--source oracle` noetig. Dafuer gibt es jetzt
`start_exe_vgf_oracle.bat` / `start_exe_abellio_oracle.bat` / `start_exe_mob_oracle.bat` (analog zu
`start_vgf_oracle.bat` fuer die Python-Entwicklungsumgebung); beide, Batches und `config/`, muessen mit in
`dist/` kopiert werden. Dokumentiert in `README.md` ("Als EXE packen").

Bewusst nicht umgesetzt: echter Schutz vor Lesen/Veraendern des Codes — PyInstaller verpackt nur, der
Python-Bytecode bleibt mit Aufwand extrahierbar.


## Tests

`tests/test_abellio_profile.py` (33 Fälle): Namensvarianten inkl. des
Laufradsatz-Falls, Nullwerte, kollidierende Drehgestelle, Einheit ohne
Struktur, Toleranzbereiche als Grenzwerte, nicht zuordenbare Lager-Zeilen und
dass VGF unverändert bleibt. `tests/test_donut_counts.py` (4 Fälle) sichert die Donut-Zählung, `tests/test_mob_profile.py` (23 Fälle) das MOB-Profil (echte Bezeichnungen, Messpositionen, unvollständige Termine, Lager, Drehgestell-Wechsel), `tests/test_lager_reinstalled.py` (5 Fälle) das Ausblenden wieder eingebauter Komponenten. Gesamt 239 Tests grün (neu: `test_navigation_lager.py` 5 Fälle, `test_table_columns.py` 6 Fälle, `test_prognose_icon.py` 12 Fälle, `test_time_axis.py` 21 Fälle, `test_smoke_profiles.py` 15 Fälle, `test_background_loading.py` 9, `test_aggregation.py` 10, `test_app_paths.py` 18 (neu: App-Root als PyInstaller-EXE), `test_repository.py` 7, `test_achse_view_controls.py` 6, `test_messdaten_icon.py` 8, `test_structure.py` 19, `test_perf.py` 5, `test_backend_runner.py` 15, `test_settings_dialog.py` 7); zusätzlich ein
Strukturvergleich VGF vor/nach der Änderung (identischer Fingerabdruck).
