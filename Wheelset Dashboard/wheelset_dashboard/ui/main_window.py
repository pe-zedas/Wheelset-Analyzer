"""Hauptfenster mit Side-Nav, Breadcrumb und Stacked-Views."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import qtawesome as qta
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QMenuBar, QMessageBox, QPushButton, QStackedWidget, QStatusBar, QVBoxLayout,
    QWidget,
)

from ..data.models import ComponentState, Flotte, PrognoseConfig
from ..data.repository import Repository, RepositoryConfig
from ..logic.export import export_raw_csv, werkstattliste_to_xlsx
from ..logic.lager_state import recompute_all as recompute_lager
from ..logic.status import recompute_all as recompute_status
from .settings_dialog import SettingsDialog
from . import views as _views
from .views import AchseView, DrehgestellView, EinheitView, FlotteView, LagerView

log = logging.getLogger(__name__)


class SideNav(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SideNav")
        self.setFixedWidth(190)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(0)
        self._buttons = {}

        def section(title):
            lab = QLabel(title)
            lab.setProperty("class", "NavSection")
            lay.addWidget(lab)

        def item(key, label, icon_name):
            btn = QPushButton(f"  {label}")
            btn.setIconSize(QSize(16, 16))
            btn.setIcon(QIcon(qta.icon(icon_name, color="#4A4E57").pixmap(16, 16)))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(False)
            lay.addWidget(btn)
            self._buttons[key] = btn
            return btn

        section("Flotte")
        item("flotte", "Übersicht", "mdi.view-dashboard-outline")

        section("Lager")
        item("lager_alle", "Komponenten", "mdi.package-variant")

        section("System")
        item("settings", "Einstellungen", "mdi.cog-outline")
        lay.addStretch(1)

    def set_active(self, key: str):
        for k, btn in self._buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def button(self, key: str) -> QPushButton:
        return self._buttons[key]


class Breadcrumb(QWidget):
    """Einfacher Breadcrumb aus klickbaren Buttons."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Breadcrumb")
        self._h = QHBoxLayout(self)
        self._h.setContentsMargins(16, 6, 16, 2)
        self._h.setSpacing(4)
        self._owner: Optional["MainWindow"] = None

    def set_owner(self, owner):
        self._owner = owner

    def set_path(self, segments: List[Tuple[str, str]]):
        """segments: Liste (level_key, label). level_key wird fuer Rueckspruenge genutzt."""
        while self._h.count():
            w = self._h.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, (key, label) in enumerate(segments):
            if i > 0:
                sep = QLabel("›")
                sep.setStyleSheet("color: #B4B7BF; padding: 0 4px;")
                self._h.addWidget(sep)
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            is_last = (i == len(segments) - 1)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; padding: 2px 4px; "
                + (f"color: #1A1C20; font-weight: 500;" if is_last else "color: #378ADD;")
                + " }"
            )
            # Rueckspruenge: bis zu diesem Pfad schneiden; Wurzel ("flotte","Flotte") entfaellt,
            # da navigate() nur die inhaltlichen Segmente erwartet.
            path_slice = [seg for seg in segments[: i + 1] if seg[0] != "flotte"]
            btn.clicked.connect(lambda _, p=path_slice: self._owner.navigate(p) if self._owner else None)
            self._h.addWidget(btn)
        self._h.addStretch(1)


# -----------------------------------------------------------
# MainWindow
# -----------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, repo: Repository, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._flotte: Optional[Flotte] = None
        self._prog_cfg = PrognoseConfig()
        self.setWindowTitle("Wheelset Analyzer Dashboard")
        self.resize(1200, 740)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._nav = SideNav()
        root.addWidget(self._nav)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # Kopfzeile: Breadcrumb links, zedas-asset-Logo rechts
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 12, 0)
        header.setSpacing(0)
        self._breadcrumb = Breadcrumb()
        self._breadcrumb.set_owner(self)
        header.addWidget(self._breadcrumb, 1)

        logo_path = Path(__file__).parent / "assets" / "zedas_asset.svg"
        if logo_path.exists():
            from PySide6.QtSvgWidgets import QSvgWidget
            logo = QSvgWidget(str(logo_path))
            # SVG-Verhaeltnis ~5.59:1 (342.9 x 61.38 mm) → 32 px hoch → ~179 breit
            logo.setFixedSize(QSize(179, 32))
            logo.setToolTip("zedas® asset")
            header.addWidget(logo, 0, Qt.AlignVCenter)
        right_lay.addLayout(header)

        self._stack = QStackedWidget()
        self._view_flotte = FlotteView()
        self._view_einheit = EinheitView()
        self._view_dg = DrehgestellView()
        self._view_achse = AchseView()
        self._view_lager = LagerView()
        for v in (self._view_flotte, self._view_einheit, self._view_dg,
                  self._view_achse, self._view_lager):
            self._stack.addWidget(v)

        # drilldown signals verbinden (alle vier Views)
        self._view_flotte.drilldown.connect(self.navigate)
        self._view_einheit.drilldown.connect(self.navigate)
        # DG- und Achse-drilldown werden je nach Kontext umgeschaltet (Flotte vs. Lager)
        self._set_dg_drilldown_mode("flotte")
        self._set_achse_drilldown_mode("flotte")

        right_lay.addWidget(self._stack, 1)
        root.addWidget(right, 1)
        self.setCentralWidget(central)

        # Statusbar
        self.setStatusBar(QStatusBar())
        self._status_lbl = QLabel("")
        self.statusBar().addWidget(self._status_lbl)
        # Checkbox fuer Messwert-Anzeige (links von Neu laden)
        self._values_cb = QCheckBox("Messwerte anzeigen")
        self._values_cb.setToolTip(
            "Statt der Zustandskreise den letzten Messwert anzeigen "
            "(farblich entsprechend des Zustands).")
        self._values_cb.toggled.connect(self._toggle_show_values)
        self.statusBar().addPermanentWidget(self._values_cb)
        self._reload_btn = QPushButton("Neu laden")
        self._reload_btn.setIconSize(QSize(16, 16))
        self._reload_btn.setIcon(QIcon(qta.icon("mdi.refresh", color="#4A4E57").pixmap(16, 16)))
        self._reload_btn.clicked.connect(self.reload_data)
        self.statusBar().addPermanentWidget(self._reload_btn)

        # Checkbox 'Messwerte anzeigen' nur bei Tabellen-Views sichtbar.
        self._stack.currentChanged.connect(
            lambda *_: self._update_values_cb_visibility())
        self._update_values_cb_visibility()

        # Menueleiste
        self._build_menu()

        # Nav-Buttons verdrahten
        self._nav.button("flotte").clicked.connect(lambda: self.navigate([]))
        self._nav.button("lager_alle").clicked.connect(lambda: self._show_lager())
        self._nav.button("settings").clicked.connect(self.open_settings)
        # Lager-Drilldown: Doppelklick auf eine Achse zeigt deren Historie
        self._view_lager.lager_drilldown.connect(self._open_lager_axle)

        # Auto-Refresh Timer (default off hier; wird nach Einstellungen gesetzt)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload_data)

        # erste Ladung
        self.reload_data()
        self.navigate([])

    # ------------------- menu ----------------------------

    def _build_menu(self):
        def _ic(name):
            return QIcon(qta.icon(name, color="#4A4E57").pixmap(16, 16))

        bar = self.menuBar()
        datei = bar.addMenu("&Datei")
        a_werk = QAction(_ic("mdi.file-excel-outline"), "Werkstattliste exportieren (.xlsx)…", self)
        a_werk.setShortcut("Ctrl+E")
        a_werk.triggered.connect(self._export_werkstattliste)
        datei.addAction(a_werk)

        a_csv = QAction(_ic("mdi.file-delimited-outline"), "Rohdaten als CSV exportieren…", self)
        a_csv.triggered.connect(self._export_rohdaten_csv)
        datei.addAction(a_csv)
        datei.addSeparator()

        a_reload = QAction(_ic("mdi.refresh"), "Neu laden", self)
        a_reload.setShortcut("F5")
        a_reload.triggered.connect(self.reload_data)
        datei.addAction(a_reload)
        datei.addSeparator()

        a_quit = QAction("Beenden", self)
        a_quit.setShortcut("Ctrl+Q")
        a_quit.triggered.connect(self.close)
        datei.addAction(a_quit)

        extras = bar.addMenu("&Extras")
        a_set = QAction(_ic("mdi.cog-outline"), "Einstellungen…", self)
        a_set.triggered.connect(self.open_settings)
        extras.addAction(a_set)

    def _export_werkstattliste(self):
        if self._flotte is None:
            return
        default = f"Werkstattliste_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
        p, _ = QFileDialog.getSaveFileName(self, "Werkstattliste exportieren",
                                            default, "Excel (*.xlsx)")
        if not p:
            return
        try:
            n = werkstattliste_to_xlsx(self._flotte, Path(p))
            self.statusBar().showMessage(f"Werkstattliste gespeichert: {n} Zeilen → {p}", 7000)
        except Exception as exc:
            log.exception("Export fehlgeschlagen")
            QMessageBox.critical(self, "Export fehlgeschlagen", str(exc))

    def _export_rohdaten_csv(self):
        if self._flotte is None:
            return
        default = f"bo_radsatzdaten_export_{self._repo.profile.name}.csv"
        p, _ = QFileDialog.getSaveFileName(self, "Rohdaten als CSV speichern",
                                            default, "CSV (*.csv)")
        if not p:
            return
        try:
            n = export_raw_csv(self._flotte, self._repo.profile, Path(p))
            self.statusBar().showMessage(f"CSV gespeichert: {n} Zeilen → {p}", 7000)
        except Exception as exc:
            log.exception("CSV-Export fehlgeschlagen")
            QMessageBox.critical(self, "CSV-Export fehlgeschlagen", str(exc))

    # ------------------- data ----------------------------

    def reload_data(self):
        try:
            flotte = self._repo.load()
            recompute_status(flotte)
            recompute_lager(flotte)
            self._flotte = flotte
            self._status_lbl.setText(
                f"Stand {datetime.now().strftime('%H:%M:%S')}  ·  Profil: {self._repo.profile.name}  "
                f"·  {len(flotte.einheiten)} Einheiten, {len(flotte.lager)} Lager-Komp."
            )
            # aktuelle Ansicht neu zeichnen
            self.navigate(getattr(self, "_current_path", []))
        except Exception as exc:
            log.exception("Fehler beim Laden")
            QMessageBox.critical(self, "Fehler beim Laden", str(exc))

    def set_refresh_minutes(self, value: str):
        if value == "off":
            self._timer.stop()
        else:
            self._timer.start(int(value) * 60 * 1000)

    # ------------------- navigation ----------------------

    def _update_values_cb_visibility(self):
        """Die Checkbox 'Messwerte anzeigen' betrifft nur die
        Tabellen-Views (Flotte/Einheit/DG/Lager). In der AchseView
        (reine Diagramm-Ansicht) wird sie ausgeblendet."""
        cur = self._stack.currentWidget()
        self._values_cb.setVisible(cur is not self._view_achse)

    def navigate(self, path: List[Tuple[str, str]]):
        self._current_path = list(path)
        if self._flotte is None:
            return
        bc = [("flotte", "Flotte")]
        if not path:
            self._view_flotte.set_prognose_config(self._prog_cfg)
            self._view_flotte.set_flotte(self._flotte)
            self._stack.setCurrentWidget(self._view_flotte)
            self._nav.set_active("flotte")
        elif path[0][0] == "einheit":
            einheit = self._flotte.einheiten.get(path[0][1])
            if einheit is None:
                return
            bc.append(("einheit", einheit.topeinheit_bez))
            if len(path) == 1:
                self._view_einheit.set_prognose_config(self._prog_cfg)
                self._view_einheit.set_flotte(self._flotte)
                self._view_einheit.set_einheit(einheit)
                self._stack.setCurrentWidget(self._view_einheit)
            elif path[1][0] == "drehgestell":
                dg = einheit.drehgestelle.get(path[1][1])
                if dg is None:
                    return
                bc.append(("drehgestell", dg.dg_einbaupos))
                if len(path) == 2:
                    self._set_dg_drilldown_mode("flotte")
                    self._view_dg.set_prognose_config(self._prog_cfg)
                    self._view_dg.set_flotte(self._flotte)
                    self._view_dg.set_dg(einheit, dg)
                    self._stack.setCurrentWidget(self._view_dg)
                elif path[2][0] == "achse":
                    achse = dg.achsen.get(path[2][1])
                    if achse is None:
                        return
                    bc.append(("achse", achse.rs_einbaupos))
                    self._set_achse_drilldown_mode("flotte")
                    self._view_achse.set_prognose_config(self._prog_cfg)
                    self._view_achse.set_flotte(self._flotte)
                    self._view_achse.set_achse(einheit, dg, achse)
                    self._stack.setCurrentWidget(self._view_achse)
            self._nav.set_active("flotte")
        elif path[0][0] == "lager":
            self._show_lager()
            return
        self._breadcrumb.set_path(bc)

    def _show_lager(self):
        if self._flotte is None:
            return
        self._view_lager.set_prognose_config(self._prog_cfg)
        self._view_lager.set_flotte(self._flotte, None)
        self._stack.setCurrentWidget(self._view_lager)
        self._nav.set_active("lager_alle")
        self._breadcrumb.set_path([("lager", "Lager · Komponenten")])
        self._current_path = []

    def _toggle_show_values(self, checked: bool):
        _views.set_show_values(checked)
        cur = self._stack.currentWidget()
        if cur is self._view_lager:
            self._show_lager()
        elif cur is self._view_achse:
            # AchseView zeichnet selbst neu, keine Tabelle
            return
        else:
            self.navigate(self._current_path)

    def _set_dg_drilldown_mode(self, mode: str, komp=None):
        """Setzt den DG-Drilldown-Empfaenger je nach Kontext um."""
        try:
            self._view_dg.drilldown.disconnect()
        except Exception:
            pass
        if mode == "lager" and komp is not None:
            self._view_dg.drilldown.connect(
                lambda path, _k=komp: self._lager_dg_axle_clicked(_k, path))
        else:
            self._view_dg.drilldown.connect(self.navigate)

    def _set_achse_drilldown_mode(self, mode: str, komp=None):
        """Setzt den Achse-Drilldown-Empfaenger je nach Kontext um.

        Im Lager-Kontext fangen wir KPI-Klicks ab und routen sie zurueck
        in die Lager-Hierarchie (Lager-Tabelle bzw. Lager-DG-Achsenliste).
        """
        try:
            self._view_achse.drilldown.disconnect()
        except Exception:
            pass
        if mode == "lager" and komp is not None:
            self._view_achse.drilldown.connect(
                lambda path, _k=komp: self._lager_back_from_achse(_k, path))
        else:
            self._view_achse.drilldown.connect(self.navigate)

    def _lager_back_from_achse(self, komp, path):
        """KPI-Klick in der AchseView, wenn die Achse aus dem Lager stammt.
        path = [("einheit", ...)]              → zurueck zur Lager-Tabelle
        path = [("einheit", ...), ("drehgestell", ...)] → zurueck zur Lager-DG-Achsenliste
        """
        if not path:
            return
        if len(path) == 1:
            self._show_lager()
        else:
            # Zur Achsenliste des Lager-DGs
            self._open_lager_axle(komp, None)

    def _synth_einheit_dg(self, komp):
        """Baut Platzhalter-Einheit und -DG fuer eine Lager-Komponente."""
        from ..data.models import Einheit, Drehgestell
        label_dg = komp.dg_bez or komp.rs_bez or "Lager-Komponente"
        einheit = Einheit(topeinheit_id=None,
                          topeinheit_bez=f"Lager · {komp.letzte_einheit or '-'}")
        dg = Drehgestell(dg_id=None, dg_bez=label_dg, dg_einbaupos=label_dg,
                         achsen=dict(komp.achsen))
        return einheit, dg

    def _open_lager_axle(self, komp, achse):
        """Zweistufiger Drill-Down ab Lager-Tabelle.

        - komp.kind == 'drehgestell' und achse is None → zeige Achsenliste (DrehgestellView)
        - komp.kind == 'drehgestell' und achse gegeben → zeige AchseView fuer diese Achse
        - komp.kind == 'achse' → zeige direkt AchseView
        """
        from ..data.models import Achse, Einheit, Drehgestell

        # Achsen-Komponente ohne DG-Zwischenschritt
        if komp.kind == "achse":
            a = Achse(
                rs_id=komp.rs_id, rs_bez=komp.rs_bez,
                rs_einbaupos="(Lager)",
                einbau=komp.einbau, ausbau=komp.ausbau,
                aktuell=0, state=komp.state,
                raeder=dict(komp.raeder),
            )
            einheit, dg = self._synth_einheit_dg(komp)
            self._set_achse_drilldown_mode("lager", komp)
            self._view_achse.set_prognose_config(self._prog_cfg)
            self._view_achse.set_flotte(self._flotte)
            self._view_achse.set_achse(einheit, dg, a)
            self._stack.setCurrentWidget(self._view_achse)
            self._breadcrumb.set_path([
                ("lager", "Lager"),
                ("lager-achse", komp.rs_bez or "Achse"),
            ])
            return

        # DG-Komponente ohne Achsenvorauswahl → Achsenliste zeigen
        if komp.kind == "drehgestell" and achse is None:
            einheit, dg = self._synth_einheit_dg(komp)
            self._set_dg_drilldown_mode("lager", komp)
            self._view_dg.set_prognose_config(self._prog_cfg)
            self._view_dg.set_flotte(self._flotte)
            self._view_dg.set_dg(einheit, dg)
            self._stack.setCurrentWidget(self._view_dg)
            self._breadcrumb.set_path([
                ("lager", "Lager"),
                ("lager-dg", dg.dg_einbaupos),
            ])
            return

        # DG-Komponente mit konkreter Achse → AchseView
        if komp.kind == "drehgestell" and achse is not None:
            einheit, dg = self._synth_einheit_dg(komp)
            self._set_achse_drilldown_mode("lager", komp)
            self._view_achse.set_prognose_config(self._prog_cfg)
            self._view_achse.set_flotte(self._flotte)
            self._view_achse.set_achse(einheit, dg, achse)
            self._stack.setCurrentWidget(self._view_achse)
            self._breadcrumb.set_path([
                ("lager", "Lager"),
                ("lager-dg", dg.dg_einbaupos),
                ("lager-achse", achse.rs_einbaupos or achse.rs_bez or "Achse"),
            ])

    def _lager_dg_axle_clicked(self, komp, path):
        """Verbindung aus DrehgestellView.drilldown im Lager-Kontext.

        Mögliche Pfade:
        - [("einheit", ...)]                → KPI-Klick „Einheit" → zurueck zur Lager-Tabelle
        - [... , ("achse", <rs_einbaupos>)] → Doppelklick auf Zeile → Achse öffnen
        """
        if not path:
            return
        if path[-1][0] != "achse":
            # KPI-Klick in der DG-Achsenliste → zurueck zur Lager-Tabelle
            self._show_lager()
            return
        axle_key = path[-1][1]
        a = komp.achsen.get(axle_key)
        if a is None:
            for cand in komp.achsen.values():
                if cand.rs_einbaupos == axle_key:
                    a = cand
                    break
        if a is not None:
            self._open_lager_axle(komp, a)

    # ------------------- settings -----------------------

    def open_settings(self):
        cfg = {
            "profile": self._repo.profile.name,
            "source": self._repo.config.source,
            "csv_raw": str(self._repo.config.csv_raw_path or ""),
            "csv_prognose": str(self._repo.config.csv_prognose_path or ""),
            "oracle_dsn": self._repo.config.oracle_dsn or "",
            "oracle_user": self._repo.config.oracle_user or "",
            "oracle_password": self._repo.config.oracle_password or "",
            "refresh_min": "15",
            "p_auto": self._prog_cfg.auto_from_history,
            "p_delta": self._prog_cfg.reprof_typical_magnitude_mm,
            "p_interval": self._prog_cfg.reprof_typical_interval_km,
            "p_min_jump": self._prog_cfg.reprof_dlkd_abs_min,
            "p_show_steps": self._prog_cfg.show_reprof_steps,
            "p_show_ci": self._prog_cfg.show_ci_band,
            "p_ci_level": self._prog_cfg.ci_level,
        }
        dlg = SettingsDialog(cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new = dlg.get_config()
            self._prog_cfg = PrognoseConfig(
                reprof_typical_magnitude_mm=new["p_delta"],
                reprof_typical_interval_km=new["p_interval"],
                reprof_dlkd_abs_min=new["p_min_jump"],
                auto_from_history=new["p_auto"],
                show_reprof_steps=new["p_show_steps"],
                show_ci_band=new["p_show_ci"],
                ci_level=new["p_ci_level"],
            )
            self._view_achse.set_prognose_config(self._prog_cfg)
            new_repo_cfg = RepositoryConfig(
                profile_name=new["profile"],
                source=new["source"],
                csv_raw_path=Path(new["csv_raw"]) if new["csv_raw"] else None,
                csv_prognose_path=Path(new["csv_prognose"]) if new["csv_prognose"] else None,
                oracle_dsn=new["oracle_dsn"] or None,
                oracle_user=new["oracle_user"] or None,
                oracle_password=new["oracle_password"] or None,
            )
            self._repo = Repository(new_repo_cfg)
            self.set_refresh_minutes(new["refresh_min"])
            self.reload_data()
