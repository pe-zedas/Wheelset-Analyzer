# Änderungen vom 2026-11-03

Nur bleibende Änderungen. Pfade relativ zum Dashboard-Package
`C:\User\GitHub\Wheelset-Analyzer\Wheelset Dashboard\wheelset_dashboard\`.


## 1. KPI-Kacheln in allen Views entfernt

Datei: `ui/views.py`.

Ergänzend zur Änderung vom 2026-11-02 (Flotte, Lager) ist die KPI-Zeile
jetzt auch in den Detailansichten leer:

- **EinheitView** (`set_einheit`): „Einheit", „Drehgestelle", „Achsen",
  „Status" entfernt.
- **DrehgestellView** (`set_dg`): klickbare „Einheit"-Kachel, „DG",
  „Achsen", „Status" entfernt.
- **AchseView** (`set_achse`): klickbare „Einheit"- und „DG"-Kachel,
  „Achse", „Status" entfernt.

### Warum

Dieselbe Information steht in der Breadcrumb-Zeile und im Donut; die
Zeile nahm vertikalen Platz weg, ohne eigenen Nutzen. Die
Navigationsfunktion der klickbaren Kacheln liegt weiterhin auf der
Breadcrumb-Zeile.


## 2. Oracle-Connect-String im eigenen Config-Verzeichnis

Neues Modul: `config/app_paths.py`. Betroffen: `main.py`, `oracle_e2e.py`.

### Was sich geändert hat

- **Neues Config-Verzeichnis** `<App-Root>/config/` **neben** dem
  Python-Package. (`App-Root` = `Wheelset Dashboard/`, nicht
  `wheelset_dashboard/`.)
- **Zentraler Pfad-Helfer** `config/app_paths.py`:
  - `APP_ROOT`, `CONFIG_DIR`, `ORACLE_CONNECT_FILE`
  - `ensure_config_dir()`, `read_oracle_connect_string()`,
    `write_oracle_connect_string(cs)`
- **Datei-Standardpfad** jetzt
  `<App-Root>/config/oracle_connect_string.txt`
  (vorher `../Wheelset Analyzer_new_approach/oracle_connect_string.txt`
  im Backend-Verzeichnis).
- **Reihenfolge der Quellen** in `main.py` und `oracle_e2e.py`:
  1. `--connect-file <pfad>`
  2. Umgebungsvariable `ORACLE_CONNECT_STRING`
  3. `<App-Root>/config/oracle_connect_string.txt` (Default)
- `read_oracle_connect_string()` ignoriert Leerzeilen und Zeilen, die
  mit `#` beginnen (Kommentare); liefert `None`, wenn die Datei fehlt
  oder leer ist.

### Was wurde migriert

- Die vorhandene Backend-Datei wurde nach `config/oracle_connect_string.txt`
  **kopiert**. Die Backend-Datei bleibt an ihrem Platz unverändert; das
  Dashboard greift aber nicht mehr darauf zu.

### Warum

- Credentials gehören nicht in den Code-Package-Baum und erst recht nicht
  in das Nachbar-Backend-Verzeichnis.
- Ein eigenes Config-Verzeichnis macht die Betriebs-Konfiguration
  explizit auffindbar (`config/`) und ist unabhängig vom
  Backend-Projekt.
- Der Helper trennt das Lesen der Datei an **einer Stelle** und
  verhindert, dass sich die Pfadlogik in `main.py`, `oracle_e2e.py` und
  einem potenziellen Settings-Dialog unterschiedlich entwickelt.

### Hinweis für die Zukunft

- Der Settings-Dialog kann über `write_oracle_connect_string(...)` die
  Datei direkt pflegen. Alternativ bleibt die Datei vom Nutzer manuell
  pflegbar.
- `.gitignore` sollte das Verzeichnis bzw. die Datei ausschließen (ist
  Betriebs-Konfiguration, nicht Code).


## 3. Fälligkeiten-Kachel zeigt alle Einheiten der Tabelle

Dateien: `ui/views.py` (`_collect_gantt_entries`),
`ui/overview_widgets.py` (`GanttCanvas.set_entries`).

### Was sich geändert hat

- Der Helper `_collect_gantt_entries` liefert jetzt pro Gruppe immer
  einen Eintrag — auch wenn keine Marker erzeugt werden konnten. Das
  Rückgabe-Tuple hat ein zusätzliches Feld `note`:
  `(label, reprofs, warns, grenze, note | None)`.
- `note` ist einer der beiden Platzhaltertexte:
  - `keine historischen Daten vorhanden - Prognose konnte nicht
    erzeugt werden`
    → wenn für kein Rad der Gruppe eine LKD-Historie existiert.
  - `zu wenige historische Daten vorhanden - Prognose konnte nicht
    erzeugt werden`
    → wenn Historie vorhanden ist, aber die Treppen-Prognose für
    keines der Räder etwas Verwertbares erzeugen konnte (zu wenige
    Punkte, keine km/Tag-Rate schätzbar, …).
- `GanttCanvas.set_entries` akzeptiert jetzt zusätzlich das
  5er-Tuple-Format und zeichnet die Note italic/grau direkt in die
  Zeile. Zeilen mit Note erscheinen weiterhin mit grauer Zeitlinie.
- **Der 12-Zeilen-Cap ist entfernt** — alle Einheiten der Tabelle
  erscheinen.
- Die Kachelhöhe passt sich der Zeilenzahl an (`~22 px pro Zeile`,
  gedeckelt bei 520 px), damit kleine Flotten kompakt bleiben und
  größere nicht abgeschnitten werden.
- Sortierung: Zeilen mit Markern nach frühestem Termin, Zeilen ohne
  Marker (reine Notes) hängen hinten an.

### Warum

Vorher wurde eine Einheit ohne auswertbare Prognose ganz
weggelassen; der Nutzer sah dann in der Fälligkeiten-Kachel nicht,
dass die Einheit überhaupt existiert, und konnte den Grund nicht
unterscheiden (fehlt die Historie oder reicht sie nur nicht aus?). Die
beiden Notes benennen die Ursache und bringen die
Fälligkeiten-Kachel in 1:1-Deckung mit der Tabelle darüber.


## 4. Fälligkeiten-Kachel folgt der Tabellensortierung (live)

Dateien: `ui/views.py` (`FlotteView`, `EinheitView`, `DrehgestellView`),
`ui/overview_widgets.py` (`GanttCanvas.set_entries`).

### Was sich geändert hat

- Die Kachel sortiert die Zeilen nicht mehr selbst (vorher: nach
  frühestem Marker). Stattdessen übernimmt sie **1:1 die Reihenfolge
  der darüberliegenden Tabelle**.
- In jeder der drei Views (`FlotteView`, `EinheitView`,
  `DrehgestellView`) wird einmalig das `QTableWidget.model()`-
  Signal `layoutChanged` verbunden mit einer neuen Methode
  `_rebuild_gantt_from_table()`, die die Gantt-Entries aus der
  aktuellen Zeilenreihenfolge neu zusammenstellt und auf das
  `GanttCanvas` legt.
- Der Freitext-Filter in der Tabelle versteckt Zeilen; die Kachel folgt
  dem ebenfalls — `_apply_filter` wird in jeder View überschrieben
  und ruft nach dem Filtern den Rebuild.
- Der Signal-Trigger ist bewusst `layoutChanged` (statt
  `sortIndicatorChanged`): `layoutChanged` feuert **nach** der
  internen Zeilen-Umordnung, so dass der Rebuild die bereits sortierte
  Reihenfolge liest; `sortIndicatorChanged` würde zu früh feuern und
  die alte Reihenfolge sehen.

### Verifikation (Smoke-Test)

Für alle drei Ebenen (Flotte · Einheit · DG) wurde jeweils Default +
Spalte 1 absteigend getestet; Tabellen- und Gantt-Reihenfolge sind
identisch.

### Warum

Visueller Zusammenhang zwischen Tabelle und Kachel wird nicht mehr
unterbrochen. Wenn der Nutzer die Tabelle z. B. nach „Achsen" oder
„Status" sortiert, folgen die Zeilen der Kachel direkt nach — der
Blick von Tabelle nach Kachel bleibt in einer Zeile.


## 5. Fälligkeiten-Kachel auch im Lager-View

Dateien: `ui/views.py` (`LagerView`), `ui/main_window.py`
(`_show_lager`).

### Was sich geändert hat

- Die Lager-Übersicht hat jetzt neben dem Donut auch eine
  **„Prognose Fälligkeiten LKD : Lager"**-Kachel (bei gefiltertem
  Zustand erweitert um „einsatzbereit" / „zu überholen").
- `_rebuild_gantt_from_table` baut die Entries aus der aktuellen
  Zeilenreihenfolge der Lagertabelle; Sortierung und Freitext-Filter
  wirken live.
- Für jede Komponente wird eine Pseudo-DG-Struktur gebaut, damit der
  bestehende `_collect_gantt_entries`-Helper unverändert benutzt werden
  kann:
  - `kind == 'drehgestell'` → Pseudo-DG mit den eingebauten Achsen.
  - `kind == 'achse'` → Pseudo-DG mit einer Pseudo-Achse, die nur die
    Räder der Lagerachse enthält.
- Komponenten ohne auswertbare LKD-Historie fallen auf die beiden
  bereits bestehenden Notes zurück („keine historischen Daten…" /
  „zu wenige historische Daten…"), so dass auch Lagerware, die nie
  verbaut war, in der Kachel erscheint.
- `main_window._show_lager()` übergibt die PrognoseConfig vor dem
  `set_flotte`-Aufruf.

### Verifikation

58 Lager-Komponenten im Testdatensatz; Tabellen- und
Gantt-Reihenfolge identisch, Sortierwechsel wirkt live.


## 6. zedas-asset-Logo in der Kopfzeile

Dateien: `ui/main_window.py`, Asset:
`ui/assets/zedas_asset.svg`.

### Was sich geändert hat

- Die Original-Logo-SVG
  (`M:\iso9000\Vorlagen\[ Logos ]\zedas_asset\farbe\zedas_asset_300dpi_CMYK_transp.svg`)
  wurde einmalig nach `wheelset_dashboard/ui/assets/zedas_asset.svg`
  **kopiert**. Die Anwendung lädt sie zur Laufzeit aus dem Package;
  das Netz-Share wird nicht benötigt.
- Das Logo erscheint oben rechts in einer neuen Kopfzeile, die
  Breadcrumb (links, stretch) und Logo (rechts, feste Größe) enthält.
- Darstellung über `QSvgWidget` mit fixer Höhe 32 px (Breite ~179 px
  gemäß dem SVG-Verhältnis 342.9 × 61.38 mm ≈ 5.59:1).

### Warum

Branding des Produkts zedas® asset in der Anwendungsoberfläche.
Die SVG wird im Package mitgeliefert, damit die App ohne
Netzlaufwerks-Zugriff startet.


## 7. Scrollbalken in der Fälligkeiten-Kachel + luftigere Zeilen in der Flotte

Dateien: `ui/overview_widgets.py` (`GanttPane`, `GanttCanvas`),
`ui/views.py` (`FlotteView.set_flotte`).

### Was sich geändert hat

- Die `GanttPane` ist jetzt ein Container mit **festem Höhenfenster**
  (180–220 px, wie vor der adaptiven Umstellung) um ein `QScrollArea`,
  in dem die `GanttCanvas` liegt.
  - Horizontaler Scrollbalken: aus (`ScrollBarAlwaysOff`).
  - Vertikaler Scrollbalken: `ScrollBarAsNeeded` — erscheint erst,
    wenn die Canvas höher ist als die Pane.
- Die Canvas wird in `set_entries` weiterhin mit 22 px pro Zeile
  dimensioniert, aber **ohne obere Deckelung** (die 520-px-Grenze ist
  weg); das Scrollen übernimmt das Begrenzen der sichtbaren Höhe.
- `FlotteView.set_flotte` setzt
  `verticalHeader().setDefaultSectionSize(36)` (vorher Standard ~28)
  — die Zeilen der Flottenübersicht wirken dadurch luftiger.
- Der horizontale Zeitachsen-Slider sitzt weiterhin fest unterhalb des
  Scrollbereichs.

### Verifikation

- Flotte (5 Einheiten): Canvas 170 px, Pane 220 px, kein vertikaler
  Scrollbalken.
- Lager (58 Komponenten): Canvas ~1336 px, Pane 220 px, vertikaler
  Scrollbalken sichtbar.
- Flotten-Tabellenzeile 36 px hoch.

### Warum

Lange Listen (vor allem im Lager) sprengten vorher die Kachel; die
adaptive Höhe wurde unübersichtlich. Die alte Kompaktheit kehrt
zurück, lange Listen bleiben über Scroll erreichbar.


## 8. Erst-Zeichnen-Bug beim View-Wechsel in die Lager-Komponente

Datei: `ui/overview_widgets.py` (`GanttCanvas._resize_for_rows`).

### Was war das Problem

Nach einem Wechsel von der Lager-Übersicht (Canvas ~1336 px) in die
DG-Ansicht einer Lager-Komponente (Canvas 140 px) war die Gantt-Kachel
beim **ersten** Zeichnen zu kompakt: die wenigen Zeilen rückten eng
zusammen, die Note „zu wenige historische Daten…" überlagerte sich.
Beim zweiten Betreten war alles korrekt.

Ursache: Qt verarbeitet das `setMinimumHeight/setMaximumHeight` erst im
nächsten Layout-Zyklus. Matplotlib rechnete `tight_layout` beim ersten
`draw_idle()` noch mit der alten Widget-Größe (vom vorherigen View) —
die Figure war also fälschlich sehr hoch, die wenigen Zeilen deshalb
ganz nach oben gestaucht.

### Was sich geändert hat

- `_resize_for_rows` setzt jetzt nach `setMin/MaxHeight` zusätzlich
  `self.resize(width, px)` und
  `self.figure.set_size_inches(w/dpi, px/dpi, forward=False)` — die
  Pixel- und Zoll-Größe von Canvas und Figure stimmen schon vor dem
  ersten Draw überein.

### Verifikation

Flow „Lager-Übersicht → Lager-DG öffnen → zurück → wieder öffnen":
Canvas 140 px, Figure 6.19 × 1.4 inches bei beiden Durchläufen
identisch. Keine Darstellungsunterschiede mehr zwischen erstem und
zweitem Besuch.


## 9. Konstanter oberer Rand in der Fälligkeiten-Kachel

Datei: `ui/overview_widgets.py` (`GanttCanvas`).

### Was war das Problem

In der Lager-Kachel begannen die Komponentenzeilen erst mit viel
Leerfläche oben; bei der Flotte war der Abstand knapp. Ursache:
`tight_layout` skaliert die Figur-Ränder proportional zur Figur-Höhe,
und zusätzlich fügte matplotlib einen automatischen y-Padding ober
der ersten Zeile ein. Bei 1336 px Canvas (58 Zeilen) wurden daraus
oben leicht 100+ Leerpixel; bei 170 px passte es zufällig.

### Was sich geändert hat

- `GanttCanvas` hat jetzt `tight_layout=False` und steuert die
  Plot-Area-Ränder selbst über `Figure.subplots_adjust`.
- Neue Methode `_apply_margins()` rechnet feste Pixel-Margins
  (`_MARGIN_TOP_PX = 14`, `_MARGIN_BOTTOM_PX = 40` für die Monats-
  und Jahr-Labels) in Figur-Fraktionen um — der obere/untere Rand
  bleibt dadurch bei jeder Zeilenzahl absolut gleich groß.
- `_resize_for_rows` ruft nach dem Resize `_apply_margins()`.
- Zusätzlich setzt `set_entries` jetzt explizit
  `ax.set_ylim(len(norm) - 0.5, -0.8)`, so dass matplotlib keinen
  automatischen y-Padding mehr dazurechnet.

### Scrollbalken-Konsistenz

Der GanttPane-Scrollbalken existiert für alle Ebenen (Flotte, Einheit,
DG, Lager) über die gleiche `GanttPane`-Klasse. In der Flottenübersicht
mit nur wenigen Zeilen wird er korrekt ausgeblendet, bei vielen
Zeilen (z. B. 58 Lager-Komponenten) blendet er sich automatisch ein.

### Verifikation

- Flotte: 5 Zeilen, Canvas 170 px, Scrollbar unsichtbar, erste Zeile
  direkt unter dem oberen Rand.
- Lager: 58 Zeilen, Canvas 1336 px, Scrollbar sichtbar, erste Zeile
  direkt unter dem oberen Rand.


## 10. Kennzahlen-Zeile in der AchseView horizontal scrollbar

Datei: `ui/views.py` (`AchseView.__init__`).

### Was war das Problem

Wenn beide Räder einer Achse Daten haben, zeigt die Kennzahlen-Zeile
pro Rad bis zu drei Kacheln (Letzter, Grenz, Warn) plus die
Hinweis-Box ganz rechts. Bei schmaleren Fenstern passte das nicht in
eine Zeile; die rechten Kacheln rutschten aus dem sichtbaren Bereich
und wirkten „weg".

Beispiel sSTGx/185437-S Treibradsatz 1: links und rechts jeweils
Letzter + Grenz vorhanden, aber bei schmalem Fenster war das rechte
Rad nicht zu sehen. (Warn-Kacheln fehlen bei dieser Komponente aus
fachlichem Grund — die Warnschwelle ist bereits unterschritten,
Treppen-Prognose kreuzt die Warnlinie nicht mehr.)

### Was sich geändert hat

- `self._kennzahlen_row` sitzt jetzt in einem `QScrollArea`
  (`horizontalScrollBarPolicy = AsNeeded`,
  `verticalScrollBarPolicy = AlwaysOff`), fixe Höhe 72 px.
- Keine Verhaltensänderung bei breitem Fenster — kein Scrollbalken
  sichtbar; alle Kacheln passen rein.
- Bei schmalem Fenster erscheint der horizontale Scrollbalken; alle
  Kacheln bleiben erreichbar.

### Verifikation

- 1500 px breit → kein Scrollbalken, alle 4 Kacheln + Hinweisbox
  sichtbar.
- 1100 px breit → horizontaler Scrollbalken (327 px Scrollbereich),
  rechte Kacheln per Scroll erreichbar.


## 11. Radsatz-Illustration in der Kennzahlen-Zeile der AchseView

Dateien: `ui/views.py` (`AchseView._redraw_current`), Asset:
`ui/assets/radachse.jpg`.

### Was sich geändert hat

- Zwischen den Kacheln des linken und des rechten Rades steht jetzt
  eine kleine Illustration der Achse (Höhe 56 px, Breite ≈ 101 px,
  proportional skaliert aus `ui/assets/radachse.jpg`).
- Die Kennzahlen-Zeile ist dadurch intuitiver zu lesen: alles, was
  links vom Bild steht, gehört zum **linken Rad**; alles rechts vom
  Bild zum **rechten Rad**. Die Hinweisbox mit
  Reprofilierungs-Intervall/Abtrag hängt wie bisher am rechten Ende.
- Räder ohne eindeutige Seitenangabe („unspecified") werden vor den
  linken Kacheln einsortiert, damit das Mittelbild immer zwischen
  Links und Rechts bleibt.
- Das Bild stammt aus einer von Google Generative AI erzeugten Datei;
  die C2PA-/SynthID-Metadaten wurden beim Übernehmen entfernt (nur
  Pixel kopiert). Das unsichtbare SynthID-Pixelwasserzeichen bleibt
  bauartbedingt im Bild bestehen.

### Verifikation

sSTGx/185437-S Treibradsatz 1, LKD-Tab, Reihenfolge der Widgets:
`LKD links (letzter)` · `links · Grenz` · `[Radbild 101×56]` ·
`LKD rechts (letzter)` · `rechts · Grenz` · Hinweisbox.
