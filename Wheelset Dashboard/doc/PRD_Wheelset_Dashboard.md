# PRD — Wheelset Dashboard

Stand: 2026-10-27, Rev. 0 (Entwurf)
Autor: Peter Engel
Projekt: parallel zu `Wheelset Analyzer_new_approach` (Prognose-Backend)

---

## 1. Zweck und Abgrenzung

### 1.1 Ziel
Interaktive Desktop-Anwendung, die dem Instandhaltungsplaner die Radsatzdaten einer **Fahrzeugflotte** auf allen Hierarchie-Ebenen übersichtlich darstellt und auf einen Blick erkennen lässt, **welche Einheit, welches Drehgestell oder welche Achse demnächst in die Werkstatt** muss.

### 1.2 Abgrenzung
- **Keine** Neu-Berechnung von Prognosen — das Dashboard **liest ausschließlich** die vom bestehenden Programm `Radsatz_Bahn_DB_new_Approach.py` erzeugten Daten aus `BO_RADSATZDATEN_PROGNOSE` sowie die Rohmesswerte aus `BO_RADSATZDATEN`.
- **Kein** Eingriff in die Prognose-Pipeline — Dashboard und Prognose-Backend sind lose gekoppelt über die DB-Tabellen bzw. CSV-Export.
- **Read-only** gegenüber den fachlichen Tabellen; eigene Konfiguration (DB-Verbindung, Log-Level, Favoriten) in lokaler Config.

### 1.3 Zielgruppe
- Instandhaltungsplaner (Flotten-Überblick, Werkstattplanung)
- Werkstattleiter (Detailansicht einzelner Fahrzeuge/Achsen)
- Technischer Support / Analytiker (Test-Modus über CSV)

---

## 2. Nutzungsszenarien

| # | Szenario | Nutzer-Aktion | Ergebnis |
|---|----------|---------------|----------|
| S1 | Täglicher Flottenblick | Anwendung öffnen | Ampel-Status aller Einheiten; Liste der demnächst fälligen Werkstattaufenthalte |
| S2 | Werkstattplanung 4 Wochen | Zeitfilter "nächste 4 Wochen" | Alle Achsen, deren `DATUM_WARNWERT` oder `DATUM_GRENZWERT` im Zeitraum liegt |
| S3 | Analyse einer Einheit | Drill-down auf Zug/Lok/Waggon | Zeitachse mit Warn-/Grenzwert-Terminen aller Drehgestelle und Achsen |
| S4 | Detail einer Achse | Drill-down bis Achse | Historie LKD1/LKD2 + Prognosekurven + Warn-/Grenzwerte als Diagramm |
| S5 | Export für Bericht | Export-Button | Excel-Datei mit aktuellem Ausschnitt |
| S6 | Offline-Test | CSV-Import | Dashboard arbeitet ohne DB auf Testdaten |
| S7 | DB-Verbindung prüfen | Einstellungen → Testverbindung | OK / Fehlermeldung mit Diagnose |

---

## 3. Funktionale Anforderungen

### 3.1 Hierarchische Navigation
Zwei parallele Hauptzweige in der Side-Nav: **eingebaut** (im Fahrzeugbetrieb) und **Lager** (Ersatz-/überholte Komponenten).

#### Zweig A — Flotte (eingebaut, `AUSBAU IS NULL`)
Vier Ebenen mit Drill-down und Breadcrumb:

| Ebene | Entität | Quelle (DB-Feld) |
|-------|---------|------------------|
| L1 | **Flotte** (alle `TOPEINHEIT`) | aggregiert |
| L2 | **Einheit** (Zug / Lok / Waggon) | `TOPEINHEITID`, `TOPEINHEITBEZEICHNUNG` |
| L3 | **Drehgestell** (fest im Fahrzeug oder im DG eingebaute Achsen) | `DGEINHEITID`, `DGEINBAUPOS` |
| L4 | **Achse / Radsatz** (zwei Räder LKD1/LKD2) | `RSEINHEITID`, `RSEINBAUPOS` |

#### Zweig B — Lager (nicht eingebaut)
Komponenten, die nicht in einer Einheit verbaut sind: Drehgestelle mit Achsen oder Einzel-Achsen, jeweils in zwei Zuständen:
- **Zu überholen** — Komponente ausgebaut (`AUSBAU IS NOT NULL`), noch keine neue Reprofilierung/Wiederinbetriebnahme dokumentiert.
- **Überholt / einsatzbereit** — Reprofilierung/Wiederaufarbeitung abgeschlossen, wartet auf Einbau.

| Ebene | Entität |
|-------|---------|
| L1-L | **Lager-Übersicht** (alle Lager-Komponenten, gruppiert nach Zustand) |
| L2-L | **Lager-Drehgestell** mit seinen Achsen |
| L3-L | **Lager-Achse** (einzeln, nicht in einem Lager-DG) |
| L4-L | **Achse Detail** (identisch zu L4 Zweig A: Historie, letzte Prognose, letzter LKD, Reprofilierungs-Historie) |

**F-NAV-1**: Baum- oder Kachel-Navigation durch beide Zweige.
**F-NAV-2**: Breadcrumb mit Rücksprung auf jede Ebene; Zweig-Umschaltung in Side-Nav.
**F-NAV-3**: Suche/Filter über **beide** Zweige (Fahrzeug-, DG- oder Achsen-Bezeichnung, `RSEINHEITID`).
**F-NAV-4**: Filter-Chip "Zustand" im Lager-Zweig: `alle` / `zu überholen` / `überholt`.
**F-NAV-5**: Querverweis — in der Detailansicht einer Achse ist die vollständige Einbau-/Ausbau-Historie sichtbar (welche Einheit → wann ausgebaut → Lager → ggf. wieder eingebaut).

**F-NAV-6 Drill-Down-Interaktion**: Drei gleichwertige Wege zur Zielebene:

1. **Klick-Kaskade** (Hauptweg, max. 4–5 Klicks):
   - L1 Flotte → Zeile anklicken → L2 Einheit
   - L2 Einheit → Drehgestell-Kachel/-Zeile → L3 Drehgestell
   - L3 Drehgestell → Achsen-Zeile → L4 Achse (beide Räder gemeinsam)
   - L4 Achse → Klick auf Mess­größen-Reiter oder einzelne Kurve → **Rad-Isolation** (nur LKD1 bzw. LKD2) mit vollem Plot und Vergleichs-Overlays.
2. **Side-Nav-Baum**: alle Ebenen aufklappbar; direkter Sprung auf jede Ebene, unabhängig vom aktuellen Kontext.
3. **Suche**: Freitext-Feld springt direkt zur Ziel-Ebene (z. B. „Lok 42 DG1 R1 LKD1").

**Tastatur**: Pfeile zur Auswahl, `↵` öffnet markierte Zeile, `⌫` / `Alt + ←` zurück zur Elternebene, `Strg + F` fokussiert die Suche.

**Breadcrumb** oben zeigt den vollen Pfad bis zur aktuellen Ebene (`Flotte › Lok 42 › DG 1 › Radsatz 1 › LKD1 (links)`); jedes Segment ist anklickbar und springt in einem Schritt dorthin zurück.

**Rad-Ebene (L5)**: ergänzt die bisherigen vier Ebenen und ist nur im Detail-Zweig relevant; sie ist keine eigene Entität im Datenmodell, sondern ein Darstellungsmodus der Achse (eine Mess­reihe des Rades isoliert).

### 3.2 Statusdarstellung (Ampel)

**F-STATUS-1**: Jede Entität zeigt eine **Ampel**. Die Ampel speist sich aus **zwei Quellen** (die schlechtere gewinnt) — Details in F-STATUS-5:
- 🔴 **rot** — Prognose: `DATUM_GRENZWERT` innerhalb Schwelle_rot (z. B. ≤ 30 Tage) oder überschritten. **Oder** Ist-Wert einer Messgröße ≤ `MIN` / ≥ `MAX`.
- 🟡 **gelb** — Prognose: `DATUM_WARNWERT` innerhalb Schwelle_gelb (z. B. ≤ 90 Tage). **Oder** Ist-Wert im Warnband.
- 🟢 **grün** — alle Prognose-Termine außerhalb Beobachtungsfenster **und** alle Ist-Werte außerhalb Warnband.
- ⚪ **grau** — weder Prognose berechenbar noch Schwellen zur Ist-Bewertung vorhanden (`INSUFFICIENT` / `NO_DATA_FOR_PROGNOSIS`).

**F-STATUS-2**: Ampel einer übergeordneten Ebene = **schlechtester** Status der untergeordneten Entitäten und Messgrößen.
**F-STATUS-3**: Schwellenwerte (Tage) in Einstellungen konfigurierbar.
**F-STATUS-4**: Prognose-Beitrag zum Status existiert **nur für LKD** (siehe F-MODEL-2); alle anderen Messgrößen tragen nur über ihren Ist-Wert bei.

### 3.3 Ansichten pro Ebene

#### L1/L2/L3 — Übersicht mit Zeitachse
**F-VIEW-AGG-1**: Zeitachse (horizontaler Balken) `heute … heute + N Monate` (N konfigurierbar, Default 12).
**F-VIEW-AGG-2**: Pro Achse (bzw. aggregiert pro DG/Einheit) ein Marker auf der Zeitachse für `DATUM_WARNWERT` (gelb) und `DATUM_GRENZWERT` (rot).
**F-VIEW-AGG-3**: Tabellarische Liste mit Spalten: Bezeichnung, Status-Ampel, nächster Warn-Termin, nächster Grenz-Termin, Rest-km, Qualität. **Sortierbar in allen Spalten** — Status-Spalten mit Ampelpunkten sortieren nach Ampelstufe (grau < grün < gelb < rot).
**F-VIEW-AGG-4**: **Einfacher Zeilenklick** aktualisiert Donut/Gantt-Visualisierungen unterhalb auf die selektierte Entität; **Doppelklick** öffnet die nächsttiefere Ebene (Drilldown).
**F-VIEW-AGG-5**: **Freitextfilter** oberhalb jeder Tabelle; durchsucht alle Textspalten zeilenweise und blendet Nicht-Treffer aus. Anzeige `n/total`.
**F-VIEW-AGG-6**: **Umschaltbare Zellanzeige** über eine Checkbox in der Statusleiste: Standard = Ampelpunkt; aktiv = Ampelpunkt + letzter Messwert in Ampelfarbe. Keine Daten → leere Zelle. Zahlenformat europäisch (Komma als Dezimaltrenner).
**F-VIEW-AGG-7**: Bei aggregierten Zeilen (Einheit, DG) zeigt die Messwert-Spalte den Wert der **numerisch schlechtesten** Messreihe aus allen enthaltenen Rädern. Richtung aus dem Profil (fallende Messgrößen: Minimum; steigende: Maximum).
**F-VIEW-LAGER-1**: Komplette Drehgestelle werden als eine einzige Lager-Komponente dargestellt (Typ „Drehgestell (n)" mit n = Anzahl eingebauter Achsen). Fachregel: Hat eine ausgebaute Achse eine DG-Zuordnung, wurde das komplette DG ausgebaut.
**F-VIEW-LAGER-2**: Zweistufiger Drilldown ab Lager-Tabelle — Doppelklick auf eine DG-Komponente zeigt deren Achsenliste (gleiche Darstellung wie aus der Flotte); Doppelklick auf eine Achse öffnet den Detail-Plot.

#### L4 — Detailansicht einer Achse
**F-VIEW-AXIS-1**: Diagramm (Plot) analog zum bestehenden Backend-Plot:
- Historische Messpunkte LKD1 (blau) und LKD2 (grün)
- Prognosekurven (gleich eingefärbt, methodenspezifisch gestrichelt)
- Horizontale Linien `GELB_MIN` (gelb) und `MIN` (rot)
- Vertikale Linien bei `DATUM_WARNWERT` / `DATUM_GRENZWERT`
- Optional: 90%-KI-Band (Theil-Sen)

**F-VIEW-AXIS-2**: Begleitende Tabelle mit allen numerischen Prognose-Ergebnissen (`KM_WARNWERT`, `DATUM_WARNWERT`, `KM_GRENZWERT`, `DATUM_GRENZWERT`, Methode, Qualität).
**F-VIEW-AXIS-3**: Umschaltung X-Achse: **Laufleistung [km]** vs. **Datum**.

### 3.4 Datenquellen

**F-DATA-1**: **Oracle-Modus** — Daten lesen aus:
- `BO_RADSATZDATEN` **ohne** `AUSBAU IS NULL`-Filter — Unterscheidung über `AUSBAU` + `AKTUELL`:
  - **Zweig A (eingebaut)**: `AUSBAU IS NULL AND AKTUELL = 1`
  - **Zweig B (Lager)**: `AUSBAU IS NOT NULL OR AKTUELL = 0` — gruppiert nach `RSEINHEITID` / `DGEINHEITID`
  - **Zustand "überholt" vs. "zu überholen"** innerhalb Zweig B wird aus der Messhistorie der Lager-Komponente **nach** dem letzten `AUSBAU`-Datum abgeleitet:
    - **überholt / einsatzbereit** — nach dem Ausbau existiert mindestens ein Messpunkt mit positivem LKD-Sprung (Reprofilierung dokumentiert) **oder** ein deutlich höherer LKD-Wert als beim Ausbau.
    - **zu überholen** — keine Messung nach dem Ausbau, oder LKD unverändert / weiter abfallend.
  - Zusätzlich: Zeitstempel des Zustandswechsels aus `LETZTEAENDZEIT` des neuesten Messpunkts.
- `BO_RADSATZDATEN_PROGNOSE` (Prognosewerte für aktuell eingebaute Komponenten)
Verbindung über `oracledb` (Thick-Mode), Instant-Client wie im Backend.

**F-DATA-2**: **CSV-Modus** — vollwertige alternative Datenquelle (nicht nur Test):
- `bo_radsatzdaten_export.csv` (Rohmessungen, Format und Spaltensatz identisch zum Backend-Export `export_bo_radsatzdaten_csv.py`: `;`-getrennt, UTF-8-BOM, Spalten wie `BO_RADSATZDATEN`).
- `bo_radsatzdaten_prognose_export.csv` (Prognosewerte, Format identisch zum Backend-Export `export_bo_radsatzdaten_prognose_csv.py`).
- Umschaltung Oracle ⇄ CSV in Einstellungen; Pfade zu beiden Dateien konfigurierbar.
- Lager-/Historie-Auswertung (F-DATA-1) funktioniert identisch im CSV-Modus, da auch die CSV die Spalten `AUSBAU` und `AKTUELL` enthält.

**F-DATA-3**: **CSV-Export der Rohtabellen** — zwei Buttons in Einstellungen bzw. Menü:
- "Export `BO_RADSATZDATEN` → CSV" erzeugt Datei im Format von `bo_radsatzdaten_export.csv`.
- "Export `BO_RADSATZDATEN_PROGNOSE` → CSV" erzeugt Datei im Format von `bo_radsatzdaten_prognose_export.csv`.
- Default-Dateinamen und -Pfad konfigurierbar; UTF-8-BOM, `;`-Trenner, Spaltenreihenfolge wie Backend-Export.
- Zweck: unabhängig vom DB-Zugriff Daten weitergeben, archivieren, offline analysieren.

**F-DATA-4**: **CSV-Import** als alternative Datenquelle — Nutzer wählt im Dialog zwei CSV-Dateien (Roh + Prognose); Dashboard arbeitet dann ausschließlich auf diesen Dateien. Nützlich für Offline-Analyse, Weitergabe an Dritte und Tests ohne DB-Zugriff.

**F-DATA-6**: **Kundenprofil mit Spalten-Mapping** — Grundlage für die Mehrkunden-Fähigkeit (siehe Abschnitt 4a).

- In Einstellungen wählbares **Kundenprofil** (z. B. `VGF`, `Abellio`, `MOB`, `generic`). Jedes Profil ist eine YAML-/JSON-Datei im Konfigurationsordner und beschreibt:
  - **Spalten-Mapping** `csv_spalte → interner_name` für `BO_RADSATZDATEN` und `BO_RADSATZDATEN_PROGNOSE` (z. B. `MIN_BEREICH → gelb_min`, `LASTUPDATE → letzteaendzeit`).
  - **Pflichtfelder je Messgröße** (ein Messpunkt zählt nur dann als vollständig, wenn alle hier gelisteten Felder vorhanden/belegt sind). Für MOB/Abellio darf die Liste gezielt kürzer sein, wenn die Daten die VGF-Vollständigkeit nicht liefern können (siehe Abschnitt 4a / ZAR-3219).
  - **Datumsformat**, **Dezimaltrennzeichen**, **CSV-Delimiter** (Default `;`, UTF-8-BOM).
  - **Hierarchie-Tiefe**: `l4_pflicht` (Radsatz muss belegt sein) oder `l4_optional` (fallback auf DG-Ebene, siehe F-MODEL-1).
- Auto-Detection beim Laden: wenn der Header-Satz zu einem bekannten Profil passt, wird dieses vorgeschlagen; sonst Dialog "Profil wählen oder neu anlegen".
- Nutzer kann Mappings in einem einfachen Editor überschreiben (keine Codeänderung nötig) — relevant, weil Zählerbezeichnungen bei Kunden variieren.

**F-DATA-7**: **ZARTBEZ-Vokabular (Mess­größen-Katalog)** — eigene Mapping-Datei je Profil `semantische_messgroesse → List[ZARTBEZ-Muster]`.

- Interne, kanonische Messgrößen (sprach- und schreibweisen-unabhängig):
  `LKD`, `SPURKRANZDICKE_SD`, `SPURKRANZHOEHE_SH`, `SPURKRANZFLANKE_QR`, `HOHLLAUF`, `UEBERWALZUNG`, `RADBREITE`, `SPURMASS_SR`, `DURCHMESSERDIFFERENZ`, …
- Jedes Muster erfasst Regex + Rad-/Seiten-Erkennung (Suffix `-1`/`-2` → Rad 1/2; `(L)`/`(R)` oder `links`/`rechts` → links/rechts; französisch `gauche`/`droite`).
- Beispiel-Mapping-Einträge:
  - `LKD` ← `Rad-Laufkreisdurchmesser-1` (VGF, Rad 1), `Laufkreisdurchmesser Dlk [... (L)]` (Abellio, links), `Diamètre de roue` (MOB, keine L/R).
  - `SPURKRANZDICKE_SD` ← `Rad-Spurkranzdicke Sd …` (Abellio), `Epaisseur du boudin` (MOB).
- Unbekannte `ZARTBEZ` werden geloggt und als "unbekannte Messgröße" im UI angeboten; der Nutzer kann sie dem Katalog zuordnen.

**F-DATA-5**: **Werkstattliste-Export** — Ein-Klick-Export aller Räder, deren `DATUM_WARNWERT` oder `DATUM_GRENZWERT` im aktuell gewählten Zeithorizont liegt (bzw. bereits überschritten ist).

- **Auslöser:** Button "Werkstattliste exportieren" in L1/L2/L3-Ansicht; nutzt den aktuell aktiven Zeitfilter und Entitäten-Filter (Flotte / Einheit / DG) ohne weiteren Dialog.
- **Zielformat:** `.xlsx`, UTF-8, Default-Dateiname `Werkstattliste_YYYY-MM-DD_HHMM.xlsx` im konfigurierten Export-Pfad.
- **Spalten (fest):**

  | Spalte | Quelle |
  |--------|--------|
  | Einheit | `TOPEINHEITBEZEICHNUNG` |
  | DG-Pos | `DGEINBAUPOS` |
  | Achse-Pos | `RSEINBAUPOS` |
  | Rad | `LKD1` / `LKD2` |
  | aktueller LKD [mm] | letzter Messwert `STAND` |
  | aktuelle Laufleistung [km] | letzter `LAUFLEISTUNG` |
  | nächster Warn-Termin | `DATUM_WARNWERT` |
  | Rest-km bis Warn | `KM_WARNWERT − aktuelle LAUFLEISTUNG` |
  | nächster Grenz-Termin | `DATUM_GRENZWERT` |
  | Rest-km bis Grenz | `KM_GRENZWERT − aktuelle LAUFLEISTUNG` |
  | Status | 🔴 / 🟡 / 🟢 / ⚪ (vgl. F-STATUS-1) |
  | Qualität | Prognose-Qualitätsflag |
  | Methode | Prognose-Methode (z. B. `theil_sen`) |

- **Sortierung:** aufsteigend nach `DATUM_GRENZWERT`, dann `DATUM_WARNWERT` — dringlichste Fälle oben.
- **Formatierung:** Status-Spalte farbig hinterlegt (Zellfüllung rot/gelb/grün/grau); Datumsspalten als `YYYY-MM-DD`; Autofilter auf Kopfzeile; Spaltenbreiten optimiert.
- **Leere Liste:** Export erzeugt trotzdem die Datei mit Kopfzeile und Hinweis-Zelle "Keine Einträge im gewählten Zeitraum".

### 3.5 Einstellungsdialog (⚙)

**F-SET-1**: Datenquelle: Oracle / CSV / Excel umschalten.
**F-SET-2**: Oracle-Zugangsdaten (DSN, User, Passwort) — Passwort lokal verschlüsselt.
**F-SET-3**: **Testverbindung**-Button mit klarem OK / Fehler-Report.
**F-SET-4**: Ampel-Schwellen (Tage) für gelb/rot.
**F-SET-5**: Zeithorizont der Zeitachse (Monate).
**F-SET-6**: Log-Level: `DEBUG` / `INFO` / `WARNING` / `ERROR`.
**F-SET-7**: Pfad zu Log-Datei und CSV-Verzeichnis.

### 3.6 Logging und Fehlerbehandlung

**F-LOG-1**: Rotierende Log-Datei (Standard: `wheelset_dashboard.log`, max. 10 MB, 5 Backups).
**F-LOG-2**: Jede Aktion (Lesen DB, Export, Fehler, Einstellungsänderung) wird mit Zeitstempel geloggt.
**F-ERR-1**: DB-Verbindungsfehler → nicht-blockierender Toast + Statusleiste rot + Dialog mit Diagnoseoptionen; die zuletzt erfolgreich geladenen Daten bleiben sichtbar und sind als "veraltet (Stand …)" markiert.
**F-ERR-2**: Fehlende/korrupte Datensätze → Warnhinweis, aber Weiterarbeit mit vorhandenen Daten.
**F-ERR-3**: Keine Abstürze bei Teilausfall einzelner Achsen (robuste Isolation pro Achse).

### 3.7 Performance / Datenaktualität

**F-PERF-1**: Startansicht (Flotte, L1) < 3 s bei bis zu 10 000 aktiven Achsen.
**F-PERF-2**: Drill-down zwischen Ebenen < 500 ms.
**F-PERF-3**: Caching der zuletzt geladenen Daten. **Auto-Refresh alle 15 min** (Default), Intervall in Einstellungen änderbar (`off` / `5` / `15` / `30` / `60` min). **Manueller "Neu laden"-Button** in der Statusleiste jederzeit verfügbar; manuelle Aktion setzt den Timer zurück. Während eines Reloads bleibt die vorige Ansicht sichtbar; bei Fehler → Toast + Markierung "Stand: HH:MM (veraltet)".

---

## 4. Nicht-funktionale Anforderungen

| Kategorie | Anforderung |
|-----------|-------------|
| Plattform | Windows 10/11 (primär); Python 3.11+ |
| Sprache | Deutsche UI |
| Architektur | Python-Desktop-App, GUI-Framework: **PySide6** (Qt 6, LGPL — kommerziell unproblematisch; konsistent zum Qt-Matplotlib-Backend). Matplotlib-Plots über `matplotlib.backends.backend_qtagg`. |
| Lizenz | intern |
| Barrierefreiheit | Hoher Kontrast, Tastatur-Navigation grundlegend unterstützt |
| Internationalisierung | Vorerst nur Deutsch; UI-Strings zentralisiert für spätere i18n |
| Sicherheit | Keine eigene Nutzer-Anmeldung. Oracle-Modus: DB-Credentials verschlüsselt via `keyring`. CSV-Modus: keine Authentifizierung nötig. |
| Robustheit | Try/Except an jeder DB- und IO-Operation; keine ungefangenen Exceptions bis zum UI |

---

## 4a. Unterschiedliche Ausprägungen bei Kunden

Vergleich der drei bisher betrachteten Kunden-Exporte `bo_radsatzdaten_export.csv`:

### Gemeinsamkeiten (alle drei)
- **Erste 13 Spalten identisch**: `TOPEINHEITID`, `TOPEINHEITBEZEICHNUNG`, `DGEINHEITID`, `DGBEZEICHNUNG`, `DGEINBAUPOS`, `RSEINHEITID`, `RSBEZEICHNUNG`, `RSEINBAUPOS`, `EINBAU`, `AUSBAU`, `AKTUELL`, `ZAEHLERARTID`, `ZARTBEZ`.
- Zelltrenner `;`, UTF-8-BOM, Datumsformat `YYYY-MM-DD HH:MM:SS`.
- Semantik der Einbauhierarchie (TOP → DG → RS) identisch.
- Flag `AKTUELL`, Datum `AUSBAU` zur Unterscheidung eingebaut/Lager identisch (siehe F-DATA-1).

### Unterschiede

| Thema | VGF (Legacy-Schema) | Abellio (neues Schema) | MOB (neues Schema) |
|-------|---------------------|------------------------|---------------------|
| Spaltenzahl | 21 | 23 | 23 |
| Warnband unten | `GELB_MIN` | `MIN_BEREICH` | `MIN_BEREICH` |
| Warnband oben | `GELB_MAX` | `MAX_BEREICH` | `MAX_BEREICH` |
| Zusatz-Pflichtspalte | — | `ZAEHLERHISTORIEID NOT NULL` | `ZAEHLERHISTORIEID NOT NULL` |
| Export-Lauf-ID | — | `LASTRUNID NOT NULL` | `LASTRUNID NOT NULL` |
| Letzte Änderung | `LETZTEAENDZEIT` | `LASTUPDATE NOT NULL` | `LASTUPDATE NOT NULL` |
| Mess-Vokabular | **Deutsch**, nur LKD1/LKD2 (`Rad-Laufkreisdurchmesser-1/-2`) | **Deutsch**, breites Spektrum (LKD `Dlk`, Spurkranz Sd/Sh/qR, Hohllauf, Bremsscheiben, Radbreite, …) | **Französisch** (`Diamètre de roue`, `Hauteur du boudin`, `Epaisseur du boudin`, `Cote qR`, `Creux`, `Refoulement`, `Largeur de roue`) |
| Rad-/Seiten-Kodierung in `ZARTBEZ` | Suffix `-1` / `-2` | `(L)` / `(R)` bzw. `links` / `rechts` | **keine** — nur eine Messung pro Drehgestell |
| `DGEINBAUPOS`-Granularität | fein (`C00 Triebdrehgestell 2`) | mittel (`Drehgestell`) | sehr grob (einheitlich `Bogie EV 1 (IO)`) |
| `RSEINHEITID` / `RSBEZEICHNUNG` / `RSEINBAUPOS` | belegt | belegt | **leer** (keine Radsatz-Ebene vorhanden) |
| Vollständigkeit Pflichtfelder für LKD-Fit | hoch | **lückenhaft** (MIN, MAX, MIN_BEREICH, LAUFLEISTUNG oft leer, siehe ZAR-3219) | **lückenhaft** (dieselben Felder leer, siehe ZAR-3219) |

### Erkenntnisse aus ZAR-3219 (Prognose-Auswirkungen)

- **Abellio** und **MOB** liefern in `BO_RADSATZDATEN` LKD-Messungen, bei denen `MIN`, `MAX`, `MIN_BEREICH` und `LAUFLEISTUNG` **häufig leer** sind.
- Das bestehende Backend wertet alle sechs Felder (`DATUM`, `STAND`, `LAUFLEISTUNG`, `MIN`, `MAX`, `MIN_BEREICH`/`GELB_MIN`) als Pflicht; fehlt eines, verwirft es den Punkt und meldet "Zählerdaten nicht vollständig".
- Konsequenz für diese Kunden heute: Prognoselauf schlägt für die meisten LKD-Reihen fehl.
- **Ursache** auf Datenseite muss im Quellsystem behoben werden (lt. Ticket Zuständigkeit M. Hausdorf); Dashboard-Seite reagiert robust (siehe unten).

### Konsequenzen fürs Dashboard

1. **Mehrkundenfähigkeit über Kundenprofile** (F-DATA-6) ist Pflicht — ein hartcodierter Spaltensatz würde für zwei von drei Kunden brechen.
2. **Pflichtfeld-Set je Profil konfigurierbar** (F-DATA-6): für Abellio/MOB darf das Dashboard LKD-Reihen auch dann anzeigen, wenn `MIN`/`MAX`/`MIN_BEREICH`/`LAUFLEISTUNG` fehlen — nur eine Prognose ist dann nicht möglich, Historie bleibt sichtbar.
3. **Prognose-fehlt-Zustand** (`qualitaet = NO_DATA_FOR_PROGNOSIS`) wird in der UI als eigene Qualitätsstufe neben `INSUFFICIENT` ausgewiesen — Rohdaten anzeigen, Vorhersagemarker weglassen, Hinweis-Icon mit Tooltip auf die fehlenden Felder.
4. **Mehrsprachige, variantenreiche `ZARTBEZ`-Erkennung** (F-DATA-7) ist nicht optional — ohne sie bleiben MOB-Daten komplett unidentifiziert.
5. **Flexible Hierarchie** (F-MODEL-1): bei MOB fehlt die L4-Ebene; das Dashboard darf nicht abstürzen und bietet die Detailansicht auf L3 (Drehgestell) an.

---

## 5. Datenmodell

### 5.1 Eingabetabelle `BO_RADSATZDATEN`

Spalten je nach **Kundenprofil** (siehe Abschnitt 4a); nach Mapping (F-DATA-6) auf einheitliche interne Namen gebracht.

**Interne Pflichtfelder** (nach Mapping) für die Zuordnung einer Zeile zu Flotte/Lager:
`topeinheit_id`, `topeinheit_bezeichnung`, `dg_einheit_id`, `dg_einbaupos`, `rs_einheit_id` (optional, siehe F-MODEL-1), `rs_einbaupos` (optional), `zaehlerart_bez`, `datum`, `stand`, `ausbau` (nullable), `aktuell`.

**Für Prognose zusätzlich benötigt** (Profil-abhängig, siehe ZAR-3219):
`laufleistung`, `min`, `max`, `gelb_min` (ggf. aus `min_bereich`). Fehlen davon welche → Reihe wird angezeigt, aber keine Prognose berechnet (`qualitaet = NO_DATA_FOR_PROGNOSIS`).

### 5.2 Prognosetabelle `BO_RADSATZDATEN_PROGNOSE`
Zusätzlich: `KM_WARNWERT`, `DATUM_WARNWERT`, `KM_GRENZWERT`, `DATUM_GRENZWERT`, Zeitstempel (`LETZTEAENDZEIT` / `LASTUPDATE` je nach Profil), `AKTUELL`.

### 5.3 Interne Entitäten (Dashboard)
- `Flotte` → `List[Einheit]`
- `Einheit` (`topeinheit_id`, `bezeichnung`, `List[Drehgestell]`)
- `Drehgestell` (`dg_id`, `einbaupos`, `List[Achse]`, optional `List[Messreihe]` falls ohne Radsatz-Ebene)
- `Achse` (`rs_id`, `einbaupos`, `Rad_links`, `Rad_rechts`) — **optional**, siehe F-MODEL-1
- `Rad` (`seite`, `Dict[Messgroesse, Messreihe]`) — mehrere Messgrößen pro Rad, siehe F-MODEL-2
- `Messreihe` (`messgroesse`, `einheit`, `historie: List[Messpunkt]`, `prognose_kurve`, `km_warn`, `datum_warn`, `km_grenz`, `datum_grenz`, `qualitaet`)
- `Status` abgeleitet aus `datum_warn`/`datum_grenz` und Schwellen; aggregiert über alle Messgrößen (schlechtester Status gewinnt).

**F-MODEL-1 Flexible Hierarchie**: Die L4-Ebene (Radsatz / Rad) ist **optional**. Bei Kundenprofilen ohne Radsatz-Zuordnung (z. B. MOB) wird die Detailansicht an L3 (Drehgestell) angesiedelt; UI und Rollup müssen beide Varianten unterstützen. Rad-Zuordnung links/rechts ist ebenfalls optional (bei MOB nicht gegeben).

**F-MODEL-2 Mehrere Messgrößen pro Rad / Achse**: Datenmodell und UI führen alle vom Kunden gelieferten kanonischen Messgrößen (siehe F-DATA-7 Katalog). Jede Messgröße hat eigene Historie und eigene Schwellen (`MIN`, `MAX`, `GELB_MIN`/`MIN_BEREICH`, `GELB_MAX`/`MAX_BEREICH`). Detailansicht (L4 oder L3) bietet pro Rad einen **Reiter oder Dropdown je verfügbarer Messgröße**; Standard-Reiter `LKD`.

**Prognose nur für LKD (`Laufkreisdurchmesser`)**:
- Prognosekurve, `DATUM_WARNWERT`, `DATUM_GRENZWERT`, `KM_WARNWERT`, `KM_GRENZWERT` und die Werkstattliste-Zeitplanung (F-DATA-5) basieren **ausschließlich** auf LKD. Grund: nur für LKD ist die Verschleißentwicklung über Laufleistung belastbar modellierbar; für Spurkranzdicke, qR, Hohllauf etc. existiert keine entsprechende Backend-Prognose.
- Für alle anderen Messgrößen zeigt die UI **nur die Historie und den aktuellen Zustand** gegen die hinterlegten Warn-/Grenzwerte an — ohne Zukunfts-Marker auf der Zeitachse.

**F-STATUS-5 Status-Ampel aus allen Messgrößen** (Erweiterung zu F-STATUS-1):
- Der Status einer Entität (Rad / Achse / DG / Einheit / Flotte / Lager-Komponente) wird aus **zwei Quellen** gebildet und die schlechtere gewinnt:
  1. **Prognose-Status (LKD)** — wie bisher: 🔴 bei `DATUM_GRENZWERT` in Schwelle_rot, 🟡 bei `DATUM_WARNWERT` in Schwelle_gelb.
  2. **Ist-Status aus Messwerten** — pro verfügbarer Messgröße (LKD, Sd, Sh, qR, Hohllauf, …) wird der jüngste Messwert gegen die mitgelieferten Schwellen geprüft:
     - 🔴 wenn Messwert `≤ MIN` oder `≥ MAX`,
     - 🟡 wenn Messwert im Warnband `MIN … GELB_MIN` bzw. `GELB_MAX … MAX`,
     - 🟢 sonst,
     - ⚪ wenn Schwellen fehlen und keine Prognose möglich (siehe `NO_DATA_FOR_PROGNOSIS`).
- Pro Entität wird in der Detailansicht aufgeschlüsselt, **welche Messgröße** den schlechtesten Status liefert (z. B. "Status 🟡 wegen Spurkranzdicke Sd").

**F-STATUS-6 Richtungssensitive Schwellenauswertung**: Jede Messgröße trägt im Profilkatalog eine `direction` (`decreasing` | `increasing` | `both`). Die Ist-Status-Prüfung berücksichtigt nur die semantisch relevanten Schwellen:
- `decreasing` (LKD, Sd): nur `MIN` / `GELB_MIN`.
- `increasing` (Hohllauf, Überwalzung): nur `MAX` / `GELB_MAX`.
- `both`: beide Seiten.

Zusätzlich wird jede einzelne Schwelle auf Konsistenz geprüft (`gelb_min` muss zwischen `min_val` und `max_val` liegen etc.); unsinnige Werte in den Quelldaten (z. B. `GELB_MAX = MIN` in der VGF-CSV) werden ignoriert und führen nicht mehr zu falschen Warn-/Grenzstatus.

**F-STATUS-7 Stale-Prognose**: Eine Prognose, deren Warn- oder Grenz-Datum **bereits in der Vergangenheit** liegt und für die der aktuelle Ist-Status GRÜN ist, gilt als durch die Realität widerlegt. Sie wird als GRAU (nicht anwendbar) behandelt und zieht den Gesamtstatus nicht mehr auf GELB/ROT. Grund: die alte Vorhersage hat sich nicht erfüllt (meist weil zwischenzeitlich Reprofiliert wurde oder das Rad länger im Lager liegt).

**F-UI-4 Mess­größen-Spalten in Übersichten**: In den L1–L3-Tabellen (Flotte, Einheit, Drehgestell) **und** in der Lager-Übersicht erscheint eine Kompakt-Ampel-Zeile mit einem Status-Punkt **pro Messgröße** (LKD, Sd, Sh, qR, Hohllauf, …) — fehlende Messgrößen werden ausgegraut. So sieht der Nutzer auf einen Blick, dass z. B. ein Drehgestell beim LKD grün, bei Spurkranzdicke aber gelb ist.

---

## 6. Programm-Architektur (Vorschlag)

```
Wheelset Dashboard/
├── main.py                    # Einstieg, GUI starten
├── ui/
│   ├── main_window.py         # Hauptfenster, Breadcrumb
│   ├── view_flotte.py         # L1
│   ├── view_einheit.py        # L2
│   ├── view_drehgestell.py    # L3
│   ├── view_achse.py          # L4 (Plot)
│   ├── settings_dialog.py     # ⚙
│   └── widgets/               # Ampel, Zeitachse, Statusleiste
├── data/
│   ├── repository.py          # Fassade: lädt Daten (DB oder CSV/Excel)
│   ├── oracle_source.py
│   ├── csv_source.py
│   ├── excel_source.py
│   └── models.py              # Flotte / Einheit / … / Rad
├── logic/
│   ├── status.py              # Ampel-Berechnung
│   └── aggregation.py         # Rollup L4 → L3 → L2 → L1
├── config/
│   ├── settings.py            # Config-Datei (ini/json)
│   └── logging_setup.py
└── doc/
    └── PRD_Wheelset_Dashboard.md   # dieses Dokument
```

**Trennung**: UI ↔ Logic ↔ Data strikt getrennt (ermöglicht Tests ohne GUI).

---

## 6a. Visuelles Design (Azure-Dashboard-Stil)

**F-UI-1 Dashboard-Layout**: Flaches, modernes Layout analog Azure Portal:
- **Side-Nav links** (fester Rand, ~180 px): Zweige "Flotte" / "Lager" + Haupt-Links (Übersicht, Werkstattliste, Einstellungen) mit Tabler-Icons.
- **Content-Bereich** mit Breadcrumb oben.
- **KPI-Kachel-Reihe**: 4 Kacheln (z. B. "Einheiten", "Achsen gesamt", "Warn 90 T", "Grenz 30 T") — die beiden Risiko-Kacheln mit farbigem Links-Balken (gelb/rot).
- **Donut** mit Status-Verteilung (OK / Warn / Grenz / unbekannt) neben Zeitachse.
- **Gantt-Zeitachse** darunter (ein Zeilen-Balken pro Einheit oder Achse, farbige Punkte an Warn-/Grenz-Terminen, vertikale "heute"-Linie).
- **Tabelle** mit Status-Pills (abgerundete farbige Labels), Autofilter, Export-Button.

**F-UI-2 Styling**:
- Qt-Stylesheet (QSS), flach, keine Gradienten, abgerundete Ecken (`12 px` Karten, `6 px` Controls), 0.5 px Hairline-Border.
- Farbpalette an Backend-Plot-Konvention: Blau (#378ADD) = LKD1, Grün (#639922) = LKD2, Gelb (#EF9F27) = Warn, Rot (#E24B4A) = Grenz.
- **Dark-/Light-Theme-Umschalter** in Einstellungen.
- Icons über `qtawesome` (Tabler-Set) oder eingebettete SVGs.

**F-UI-3 Komponenten-Bibliothek**:
- Donut/Balken: **QtCharts** (nativ) oder Matplotlib `backend_qtagg`.
- Gantt-Zeitachse: Matplotlib (konsistent zum Backend-Detail-Plot, interaktiv per Click → Drill-down).
- Status-Pills: eigenes `QWidget`-Delegate für `QTableView`.

---

## 7. Phasenplan (Vorschlag)

| Phase | Inhalt | Ergebnis |
|-------|--------|----------|
| **P1 — Datenschicht** | `data/` + Models + CSV-Loader + Oracle-Loader | lauffähige Konsole-Abfrage |
| **P2 — Logik** | Aggregation, Status-Ampel, Unit-Tests | geprüfter Rollup |
| **P3 — UI-Skeleton** | Hauptfenster, Navigation, Settings-Dialog | klickbarer Prototyp mit Testdaten |
| **P4 — L4-Detail** | Achsen-Plot, Zeitfilter | funktionsfähige Detailansicht |
| **P5 — L1–L3-Übersicht** | Zeitachsen-Widget, Ampel-Rollup | Flotten-Dashboard |
| **P6 — Export / Robustheit** | Excel, Logging, Fehlerbehandlung | 1.0-Kandidat |
| **P7 — Test / Rollout** | End-to-End-Test mit echter DB; Doku | Freigabe |

---

## 8. Erfolgskriterien

- Flottenstatus auf einen Blick in < 3 s nach Start sichtbar.
- Nutzer kann in max. 3 Klicks von Flotte bis zu einer einzelnen Achse navigieren.
- Keine ungefangenen Exceptions, DB-Ausfall ohne Datenverlust.
- Export einer Werkstattliste als Excel in einem Klick.
- Deckungsgleiche Darstellung der Achsenprognose mit dem Backend-Plot.
