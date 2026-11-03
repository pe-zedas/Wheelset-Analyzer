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
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


class SettingsDialog(QDialog):
    """QGIS-aehnliche Baumnavigation: ein Baum links, Seiten rechts."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.resize(820, 520)
        self._config = dict(config)

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

        # Trenner
        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Splitter: Baum links, Seiten rechts
        self._splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self._splitter, 1)

        # ---- Baum links -------------------------------------------
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

        # ---- Seiten rechts ----------------------------------------
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(
            "QStackedWidget { background: #FFFFFF; border: 1px solid #E2E4EA; "
            "border-radius: 6px; }"
        )
        self._splitter.addWidget(self._stack)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)

        # Seitenregister: {baum-pfad → page-index}
        self._pages: dict[str, int] = {}

        # ---- Seiten anlegen ---------------------------------------
        self._build_page_general(config)
        self._build_page_source(config)
        self._build_page_csv(config)
        self._build_page_oracle(config)
        self._build_page_prognose_lkd_reprof(config)
        self._build_page_prognose_lkd_standard(config)
        self._build_page_prognose_lkd_darstellung(config)

        # ---- Baum befuellen ---------------------------------------
        g_allgemein = QTreeWidgetItem(["Allgemein"])
        self._tree.addTopLevelItem(g_allgemein)
        g_allgemein.setExpanded(True)

        g_quelle = QTreeWidgetItem(["Datenquelle"])
        self._tree.addTopLevelItem(g_quelle)
        g_quelle.setExpanded(True)
        it_csv = QTreeWidgetItem(["CSV"])
        it_oracle = QTreeWidgetItem(["Oracle"])
        g_quelle.addChild(it_csv)
        g_quelle.addChild(it_oracle)

        g_prognose = QTreeWidgetItem(["Prognose"])
        self._tree.addTopLevelItem(g_prognose)
        g_prognose.setExpanded(True)
        g_lkd = QTreeWidgetItem(["LKD"])
        g_prognose.addChild(g_lkd)
        g_lkd.setExpanded(True)
        it_reprof = QTreeWidgetItem(["Reprofilierungs-Erkennung"])
        it_standard = QTreeWidgetItem(["Standard-Werte"])
        it_dar = QTreeWidgetItem(["Darstellung"])
        g_lkd.addChild(it_reprof)
        g_lkd.addChild(it_standard)
        g_lkd.addChild(it_dar)

        # Pfade → page-index
        self._item_to_page = {
            id(g_allgemein): ("Allgemein", self._pages["general"]),
            id(g_quelle): ("Datenquelle", self._pages["source"]),
            id(it_csv): ("Datenquelle · CSV", self._pages["csv"]),
            id(it_oracle): ("Datenquelle · Oracle", self._pages["oracle"]),
            id(g_prognose): ("Prognose", self._pages["prognose_overview"]),
            id(g_lkd): ("Prognose · LKD", self._pages["prognose_overview"]),
            id(it_reprof): ("Prognose · LKD · Reprofilierungs-Erkennung",
                            self._pages["prognose_reprof"]),
            id(it_standard): ("Prognose · LKD · Standard-Werte",
                              self._pages["prognose_standard"]),
            id(it_dar): ("Prognose · LKD · Darstellung",
                         self._pages["prognose_darstellung"]),
        }
        self._tree.currentItemChanged.connect(self._on_tree_select)
        self._tree.setCurrentItem(g_allgemein)

        # ---- Button-Zeile unten -----------------------------------
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

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

    def _build_page_prognose_lkd_reprof(self, config: dict):
        form = self._new_page(
            "prognose_reprof",
            "Erkennung der Reprofilierungs-Ereignisse aus der Historie. "
            "Bei aktiver Auto-Erkennung werden die Standard-Werte nur als "
            "Fallback verwendet, wenn in der Historie kein Reprofilieren "
            "zu erkennen ist."
        )
        self.p_auto = QCheckBox("Reprofilierungs-Werte aus Historie ableiten")
        self.p_auto.setChecked(bool(config.get("p_auto", True)))
        form.addRow("Auto-Erkennung", self.p_auto)

        self.p_min_jump = QDoubleSpinBox()
        self.p_min_jump.setRange(0.1, 20.0); self.p_min_jump.setSingleStep(0.5)
        self.p_min_jump.setSuffix(" mm")
        self.p_min_jump.setValue(float(config.get("p_min_jump", 2.0)))
        form.addRow("Sprung-Schwelle für Erkennung", self.p_min_jump)

    def _build_page_prognose_lkd_standard(self, config: dict):
        form = self._new_page(
            "prognose_standard",
            "Fallback-Werte, wenn aus der Historie keine Reprofilierungs-"
            "Muster abgeleitet werden koennen."
        )
        self.p_delta = QDoubleSpinBox()
        self.p_delta.setRange(1.0, 50.0); self.p_delta.setSingleStep(0.5)
        self.p_delta.setSuffix(" mm")
        self.p_delta.setValue(float(config.get("p_delta", 15.0)))
        form.addRow("Reprofilierungs-Sprung", self.p_delta)

        self.p_interval = QDoubleSpinBox()
        self.p_interval.setRange(1000, 1000000); self.p_interval.setSingleStep(5000)
        self.p_interval.setSuffix(" km")
        self.p_interval.setValue(float(config.get("p_interval", 150000.0)))
        form.addRow("Reprofilierungs-Intervall", self.p_interval)

    def _build_page_prognose_lkd_darstellung(self, config: dict):
        form = self._new_page(
            "prognose_darstellung",
            "Visualisierung der Prognose im Achsen-Detailplot."
        )
        self.p_show_steps = QCheckBox("Reprofilierungs-Treppen in der Prognose zeichnen")
        self.p_show_steps.setChecked(bool(config.get("p_show_steps", True)))
        form.addRow("Treppen-Prognose", self.p_show_steps)

        self.p_show_ci = QCheckBox("Konfidenzband um die Prognose zeichnen")
        self.p_show_ci.setChecked(bool(config.get("p_show_ci", False)))
        form.addRow("KI-Band", self.p_show_ci)

        self.p_ci_level = QComboBox()
        self.p_ci_level.addItems(["80", "90", "95", "99"])
        self.p_ci_level.setCurrentText(
            str(int(float(config.get("p_ci_level", 0.90)) * 100)))
        form.addRow("Konfidenzniveau (%)", self.p_ci_level)

        # Uebersichts-Platzhalter (wenn der Nutzer "Prognose" oder "LKD"
        # direkt im Baum anklickt — die Darstellungs-Seite dient als
        # sinnvollster Default).
        self._pages["prognose_overview"] = self._pages["prognose_darstellung"]

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
            # Prognose
            "p_auto": self.p_auto.isChecked(),
            "p_delta": self.p_delta.value(),
            "p_interval": self.p_interval.value(),
            "p_min_jump": self.p_min_jump.value(),
            "p_show_steps": self.p_show_steps.isChecked(),
            "p_show_ci": self.p_show_ci.isChecked(),
            "p_ci_level": float(self.p_ci_level.currentText()) / 100.0,
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
