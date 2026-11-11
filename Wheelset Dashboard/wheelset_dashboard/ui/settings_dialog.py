"""Einstellungsdialog im QGIS-Stil: links Baumnavigation, rechts die
Felder des gewaehlten Abschnitts.

Der Dialog ist nicht modal-blockierend fuer die Fachlogik: beim Oeffnen
werden die aktuellen Config-Werte in die Felder gelegt; beim Klick auf
OK liefert :meth:`get_config` ein Dictionary mit genau denselben
Schluesseln wie der alte Dialog, so dass das Hauptfenster keine
Anpassungen braucht.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


class SettingsDialog(QDialog):
    """QGIS-aehnliche Baumnavigation: ein Baum links, Seiten rechts."""

    # Baum: (Text, Seitenschluessel, Titel im Kopf, Unterpunkte)
    _TREE = (
        ("Allgemein", "general", "Allgemein", ()),
        ("Datenquelle", "source", "Datenquelle", (
            ("CSV", "csv", "Datenquelle · CSV", ()),
            ("Oracle", "oracle", "Datenquelle · Oracle", ()),
        )),
        ("Darstellung", "darstellung", "Darstellung", ()),
        ("Prognose", "prognose_overview", "Prognose", (
            ("Neuberechnung", "prognose_recalc", "Prognose · Neuberechnung", ()),
        )),
    )

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.resize(820, 520)
        self._config = dict(config)
        # Vom Hauptfenster abgefragt: wurde im Dialog die Neuberechnung
        # angefordert? Dann startet das Hauptfenster nach dem Uebernehmen
        # der Einstellungen das Backend-Skript.
        self.recalc_requested: bool = False

        root = self._build_frame()

        # Seitenregister: {Seitenschluessel → page-index}
        self._pages: dict[str, int] = {}
        self._build_page_general(config)
        self._build_page_source(config)
        self._build_page_csv(config)
        self._build_page_oracle(config)
        self._build_page_darstellung(config)
        self._build_page_prognose_recalc(config)
        self._build_tree()

        # ---- Button-Zeile unten -----------------------------------
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _build_frame(self) -> QVBoxLayout:
        """Kopfzeile mit dem gewaehlten Abschnitt, Baum links, Seitenstapel rechts."""
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Headline — zeigt den gerade gewaehlten Abschnitt
        self._page_header = QLabel("")
        self._page_header.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #1A1C20; "
            "padding: 0 0 4px 0;"
        )
        root.addWidget(self._page_header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Splitter: Baum links, Seiten rechts
        self._splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self._splitter, 1)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setMinimumWidth(200)
        self._tree.setMaximumWidth(260)
        self._tree.setStyleSheet(
            "QTreeWidget { background: #F5F6F8; border: 1px solid #E2E4EA; "
            "border-radius: 6px; padding: 4px; }"
            "QTreeWidget::item { padding: 4px 2px; }"
            "QTreeWidget::item:selected { background: #E8F0FD; color: #185FA5; }"
        )
        self._splitter.addWidget(self._tree)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(
            "QStackedWidget { background: #FFFFFF; border: 1px solid #E2E4EA; "
            "border-radius: 6px; }"
        )
        self._splitter.addWidget(self._stack)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        return root

    def _build_tree(self):
        """Baum aus ``_TREE`` aufbauen und mit den Seiten verknuepfen."""
        self._item_to_page = {}      # id(Baumeintrag) -> (Titel, page-index)

        def add(spec, parent):
            text, page_key, title, children = spec
            item = QTreeWidgetItem([text])
            if parent is None:
                self._tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._item_to_page[id(item)] = (title, self._pages[page_key])
            for child in children:
                add(child, item)
            if children or parent is None:
                item.setExpanded(True)
            return item

        first = None
        for spec in self._TREE:
            item = add(spec, None)
            first = first or item
        self._tree.currentItemChanged.connect(self._on_tree_select)
        self._tree.setCurrentItem(first)

    # ------------------------------------------------------------------
    # Seiten-Builder — jede Seite ein kompaktes Formular
    # ------------------------------------------------------------------

    def _new_page(self, key: str, intro: str = "") -> QFormLayout:
        """Legt eine Seite im Stack an und liefert deren Form-Layout zurueck."""
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(8)
        if intro:
            lab = QLabel(intro)
            lab.setWordWrap(True)
            lab.setStyleSheet("color: #6B6F78; font-size: 11px;")
            pl.addWidget(lab)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        pl.addLayout(form)
        pl.addStretch(1)
        self._pages[key] = self._stack.addWidget(page)
        page.setProperty("_form", form)
        page.setProperty("_outer", pl)
        return form

    def _build_page_general(self, config: dict):
        form = self._new_page(
            "general",
            "Grundeinstellungen des Dashboards. Der Kundenprofil-Eintrag "
            "steuert, welche Spalten-Mapping-YAML geladen wird."
        )
        self.profile = QComboBox()
        self.profile.addItems(["vgf", "abellio", "mob"])
        self.profile.setCurrentText(config.get("profile", "vgf"))
        form.addRow("Kundenprofil", self.profile)

        self.refresh_min = QComboBox()
        self.refresh_min.addItems(["off", "5", "15", "30", "60"])
        self.refresh_min.setCurrentText(str(config.get("refresh_min", "15")))
        form.addRow("Auto-Refresh (min)", self.refresh_min)

    def _build_page_source(self, config: dict):
        form = self._new_page(
            "source",
            "Hauptschalter fuer die Datenquelle. Details zu CSV- und "
            "Oracle-Zugaengen stehen in den jeweiligen Unterseiten."
        )
        self.source = QComboBox()
        self.source.addItems(["csv", "oracle"])
        self.source.setCurrentText(config.get("source", "csv"))
        form.addRow("Datenquelle", self.source)

    def _build_page_csv(self, config: dict):
        form = self._new_page(
            "csv",
            "Pfade zu den CSV-Exportdateien. Die Rohdaten sind zwingend; "
            "die Prognose-CSV ist optional."
        )
        self.csv_raw = _file_row(self, config.get("csv_raw", ""),
                                 "CSV auswählen", form, "CSV Rohdaten")
        self.csv_prognose = _file_row(self, config.get("csv_prognose", ""),
                                      "CSV auswählen", form, "CSV Prognose")

    def _build_page_oracle(self, config: dict):
        form = self._new_page(
            "oracle",
            "Verbindung zur Oracle-Datenbank. Die Felder werden nur beim "
            "Umschalten der Datenquelle auf \"oracle\" wirklich verwendet."
        )
        self.oracle_dsn = QLineEdit(config.get("oracle_dsn", ""))
        self.oracle_user = QLineEdit(config.get("oracle_user", ""))
        self.oracle_pw = QLineEdit(config.get("oracle_password", ""))
        self.oracle_pw.setEchoMode(QLineEdit.Password)
        # Beim Profilwechsel die Zugangsdaten des Kunden laden. Beim Oeffnen
        # nur, wenn die Felder leer sind (App wurde mit Connect-String-Datei
        # gestartet) — bereits gesetzte Werte bleiben unangetastet.
        self.profile.currentTextChanged.connect(self._load_oracle_for_profile)
        form.addRow("Oracle DSN", self.oracle_dsn)
        form.addRow("Oracle User", self.oracle_user)
        form.addRow("Oracle Passwort", self.oracle_pw)

        # Testverbindung + Ergebnis-Label
        test_row = QHBoxLayout()
        test_btn = QPushButton("DB-Testverbindung")
        test_btn.clicked.connect(self._on_test_connection)
        test_row.addWidget(test_btn)
        test_row.addStretch(1)
        form.addRow("", _wrap_hbox(test_row))

        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._test_result.setStyleSheet("color: #6B6F78; font-size: 11px;")
        form.addRow("", self._test_result)

        if not (self.oracle_dsn.text() or self.oracle_user.text()
                or self.oracle_pw.text()):
            self._load_oracle_for_profile(self.profile.currentText())

    def _build_page_darstellung(self, config: dict):
        form = self._new_page(
            "darstellung",
            "Die Prognose haengt am letzten Messwert. Liegt er Jahre zurueck, steht sie im "
            "Diagramm in der Vergangenheit. Mit dieser Einstellung bleibt die Zeitachse durchgehend, "
            "zeigt aber ab dem ersten Prognosewert das um den Abstand zu heute verschobene Datum "
            "(senkrechte Linie \"heute\"). Wirkt nur bei X-Achse \"Datum\" und wenn der letzte "
            "Messwert mehr als 90 Tage zurueckliegt. Im Diagramm laesst sich die Darstellung "
            "mit demselben Schalter umstellen. Die Einstellung gilt, bis das Programm beendet wird."
        )
        self.p_time_jump = QCheckBox("Zeitachse mit Prognose ab heute")
        self.p_time_jump.setChecked(bool(config.get("p_time_jump", False)))
        form.addRow("Zeitachse", self.p_time_jump)

    def _build_page_prognose_recalc(self, config: dict):
        form = self._new_page(
            "prognose_recalc",
            "Startet das Backend-Skript 'Wheelset Analyzer_new_approach' und "
            "schreibt die neu berechnete Prognose in die Prognose-Tabelle. "
            "Je nach Datenmenge dauert das einige Minuten; das Dashboard "
            "bleibt dabei bedienbar. Die Neuberechnung startet erst nach OK "
            "(die aktuellen Einstellungen werden vorher uebernommen)."
        )
        # Der Baumeintrag "Prognose" zeigt ebenfalls diese Seite.
        self._pages["prognose_overview"] = self._pages["prognose_recalc"]
        btn_row = QHBoxLayout()
        self._recalc_btn_dlg = QPushButton("Prognose jetzt neu berechnen")
        self._recalc_btn_dlg.setToolTip(
            "Backend-Skript starten. Nach OK wird der Dialog geschlossen und "
            "die Neuberechnung ausgefuehrt.")
        self._recalc_btn_dlg.clicked.connect(self._on_recalc_clicked)
        btn_row.addWidget(self._recalc_btn_dlg)
        btn_row.addStretch(1)
        form.addRow("Backend-Lauf", _wrap_hbox(btn_row))

    def _on_recalc_clicked(self):
        """Markiert, dass das Hauptfenster nach dem Schliessen des Dialogs
        die Neuberechnung starten soll, und akzeptiert den Dialog."""
        self.recalc_requested = True
        self.accept()

    # ------------------------------------------------------------------

    def _on_tree_select(self, current: QTreeWidgetItem, _prev):
        if current is None:
            return
        info = self._item_to_page.get(id(current))
        if info is None:
            return
        title, page_idx = info
        self._page_header.setText(title)
        self._stack.setCurrentIndex(page_idx)

    def _load_oracle_for_profile(self, profile: str):
        """Fuellt DSN, Nutzer und Passwort aus der Connect-String-Datei des
        Kundenprofils. Gibt es keine, werden die Felder geleert, damit keine
        Zugangsdaten eines anderen Kunden stehen bleiben."""
        from ..config.app_paths import (
            ORACLE_CONNECT_FILE, parse_connect_string, read_oracle_connect_string,
        )
        cs = read_oracle_connect_string(profile)
        if cs:
            user, pw, dsn = parse_connect_string(cs)
            hint = ""
        else:
            user = pw = dsn = ""
            hint = (f"Kein Connect-String für '{profile}' hinterlegt. Erwartet "
                    f"in {ORACLE_CONNECT_FILE} als Zeile: {profile} = user/passwort@dsn")
        self.oracle_user.setText(user)
        self.oracle_pw.setText(pw)
        self.oracle_dsn.setText(dsn)
        self._test_result.setStyleSheet("color: #6B6F78; font-size: 11px;")
        self._test_result.setText(hint)

    def _on_test_connection(self):
        from ..data.oracle_source import OracleConnectionError, test_connection
        try:
            msg = test_connection(
                dsn=self.oracle_dsn.text().strip(),
                user=self.oracle_user.text().strip(),
                password=self.oracle_pw.text(),
            )
            self._test_result.setStyleSheet("color: #3B6D11; font-size: 11px;")
            self._test_result.setText(msg)
        except OracleConnectionError as exc:
            self._test_result.setStyleSheet("color: #A32D2D; font-size: 11px;")
            self._test_result.setText(f"Fehler: {exc}")

    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Alle Felder in ein Dict mit den vom Hauptfenster erwarteten
        Schluesseln. Reihenfolge und Namen sind identisch zum alten Dialog."""
        return {
            "profile": self.profile.currentText(),
            "source": self.source.currentText(),
            "csv_raw": self.csv_raw["edit"].text(),
            "csv_prognose": self.csv_prognose["edit"].text(),
            "oracle_dsn": self.oracle_dsn.text(),
            "oracle_user": self.oracle_user.text(),
            "oracle_password": self.oracle_pw.text(),
            "refresh_min": self.refresh_min.currentText(),
            "p_time_jump": self.p_time_jump.isChecked(),
        }


# ----------------------------------------------------------------------

def _file_row(parent, initial: str, caption: str, form: QFormLayout, label: str):
    container = QWidget(parent)
    h = QHBoxLayout(container)
    h.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit(initial)
    btn = QPushButton("…")
    btn.setFixedWidth(32)
    def pick():
        p, _ = QFileDialog.getOpenFileName(parent, caption, edit.text() or "", "CSV (*.csv)")
        if p:
            edit.setText(p)
    btn.clicked.connect(pick)
    h.addWidget(edit, 1)
    h.addWidget(btn)
    form.addRow(label, container)
    return {"edit": edit, "btn": btn}


def _wrap_hbox(h: QHBoxLayout) -> QWidget:
    w = QWidget()
    w.setLayout(h)
    return w
