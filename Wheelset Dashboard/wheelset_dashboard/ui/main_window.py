"""Hauptfenster mit Side-Nav, Breadcrumb und Stacked-Views."""
from __future__ import annotations

import dataclasses
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import qtawesome as qta
from PySide6.QtCore import Qt, QSize, QTimer, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)

from ..config.app_paths import build_connect_string
from ..data.models import Achse, Drehgestell, Einheit, Flotte, PrognoseConfig
from ..data.repository import Repository, RepositoryConfig
from ..logic.export import export_raw_csv, werkstattliste_to_xlsx
from ..logic.lager_state import recompute_all as recompute_lager
from ..logic.status import recompute_all as recompute_status
from ..perf import Timer, timed
from .jobs import BackgroundJob
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
    def __init__(self, repo: Repository, parent=None, async_load: bool = True):
        """``async_load=False`` wartet nach jedem Laden/Backend-Lauf auf das
        Ende (Tests, Skripte). Die Anwendung selbst laedt im Hintergrund."""
        self._startup = Timer()          # Dauer seit dem Fensterstart (Startzeit-Log)
        super().__init__(parent)
        self._repo = repo
        self._flotte: Optional[Flotte] = None
        self._flotte_repo: Optional[Repository] = None   # Quelle der angezeigten Daten
        self._prog_cfg = PrognoseConfig()
        self._async_load = async_load
        self._load_job: Optional[BackgroundJob] = None
        self._backend_job: Optional[BackgroundJob] = None
        self._reload_pending = False
        self._first_data_logged = False
        self._current_path: List[Tuple[str, str]] = []
        self._lager_komp = None          # zuletzt geoeffnete Lager-Komponente (Rueckspruenge)
        self._lager_achse = None

        self.setWindowTitle("Wheelset Analyzer Dashboard")
        self.resize(1200, 740)
        log.debug("MW phase: super+title+resize=%.2fs", self._startup.seconds)
        # Zustand: hat der jeweilige Drilldown bereits eine aktive
        # Verbindung? disconnect() nur aufzurufen, wenn verbunden,
        # vermeidet die PySide6-``libpyside: Failed to disconnect``
        # RuntimeWarning auf stderr.
        self._dg_drilldown_connected = False
        self._achse_drilldown_connected = False

        self.setCentralWidget(self._build_central())
        self._build_statusbar()
        with timed("MW phase: Menue", None) as t_menu:
            self._build_menu()
        log.debug("MW phases: pre_reload_total=%.2fs (menu=%.2fs)",
                  self._startup.seconds, t_menu.seconds)
        self._wire_navigation()

        # Auto-Refresh Timer (default off hier; wird nach Einstellungen gesetzt)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_reload)

        # erste Ladung (im Hintergrund: das Fenster erscheint sofort)
        self._update_schema_label()
        self.reload_data()
        self.navigate([])

    # ------------------- aufbau ----------------------------

    def _build_central(self) -> QWidget:
        """Side-Nav links; rechts Kopfzeile und gestapelte Ansichten."""
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        with timed("MW phase: SideNav (mit qta.icons)", log):
            self._nav = SideNav()
        root.addWidget(self._nav)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addLayout(self._build_header())
        right_lay.addWidget(self._build_views(), 1)
        root.addWidget(right, 1)
        return central

    def _build_header(self) -> QHBoxLayout:
        """Kopfzeile: Breadcrumb links, Schema-Etikett und zedas-asset-Logo rechts."""
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 12, 0)
        header.setSpacing(0)
        self._breadcrumb = Breadcrumb()
        self._breadcrumb.set_owner(self)
        header.addWidget(self._breadcrumb, 1)

        # Aktives Kundenschema (Profil) sichtbar machen.
        self._schema_lbl = QLabel("")
        self._schema_lbl.setStyleSheet(
            "QLabel { color: #185FA5; background: #E8F0FD; border: 1px solid #C9DDF7; "
            "border-radius: 10px; padding: 2px 12px; font-size: 11px; font-weight: 600; }"
        )
        header.addWidget(self._schema_lbl, 0, Qt.AlignVCenter)
        header.addSpacing(12)

        logo_path = Path(__file__).parent / "assets" / "zedas_asset.svg"
        with timed("MW phase: Logo (QSvgWidget)", log):
            if logo_path.exists():
                from PySide6.QtSvgWidgets import QSvgWidget
                logo = QSvgWidget(str(logo_path))
                # SVG-Verhaeltnis ~5.59:1 (342.9 x 61.38 mm) → 32 px hoch → ~179 breit
                logo.setFixedSize(QSize(179, 32))
                logo.setToolTip("zedas® asset")
                header.addWidget(logo, 0, Qt.AlignVCenter)
        return header

    def _build_views(self) -> QStackedWidget:
        """Die fuenf Ansichten (Flotte, Einheit, Drehgestell, Achse, Lager)."""
        self._stack = QStackedWidget()
        times = []
        for name, attr, cls in (("flotte", "_view_flotte", FlotteView),
                                ("einheit", "_view_einheit", EinheitView),
                                ("dg", "_view_dg", DrehgestellView),
                                ("achse", "_view_achse", AchseView),
                                ("lager", "_view_lager", LagerView)):
            with timed(name, None) as t:
                setattr(self, attr, cls())
            times.append(f"{name}={t.seconds:.2f}s")
            self._stack.addWidget(getattr(self, attr))
        log.debug("MW views: %s", " ".join(times))

        # drilldown signals verbinden (Flotte und Einheit fest)
        self._view_flotte.drilldown.connect(self.navigate)
        self._view_einheit.drilldown.connect(self.navigate)
        self._view_achse.time_jump_changed.connect(self._on_time_jump_changed)
        # DG- und Achse-drilldown werden je nach Kontext umgeschaltet (Flotte vs. Lager)
        self._set_dg_drilldown_mode("flotte")
        self._set_achse_drilldown_mode("flotte")
        return self._stack

    def _build_statusbar(self):
        self.setStatusBar(QStatusBar())
        self._status_lbl = QLabel("")
        self.statusBar().addWidget(self._status_lbl)
        # Laufanzeige fuer Laden / Backend-Lauf (unbestimmter Fortschritt)
        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.setFixedSize(110, 10)
        self._busy_bar.hide()
        self.statusBar().addWidget(self._busy_bar)
        # Checkbox fuer Messwert-Anzeige (links von Neu laden)
        self._values_cb = QCheckBox("Messwerte anzeigen")
        self._values_cb.setToolTip(
            "Statt der Zustandskreise den letzten Messwert anzeigen "
            "(farblich entsprechend des Zustands).")
        self._values_cb.toggled.connect(self._toggle_show_values)
        self.statusBar().addPermanentWidget(self._values_cb)
        # Prognose-Neuberechnung ist im Einstellungsdialog
        # (Extras → Einstellungen → Prognose · Neuberechnung).
        self._reload_btn = QPushButton("Neu laden")
        self._reload_btn.setIconSize(QSize(16, 16))
        self._reload_btn.setIcon(QIcon(qta.icon("mdi.refresh", color="#4A4E57").pixmap(16, 16)))
        self._reload_btn.clicked.connect(self.reload_data)
        self.statusBar().addPermanentWidget(self._reload_btn)

        # Checkbox 'Messwerte anzeigen' nur bei Tabellen-Views sichtbar.
        self._stack.currentChanged.connect(
            lambda *_: self._update_values_cb_visibility())
        self._update_values_cb_visibility()

    def _wire_navigation(self):
        self._nav.button("flotte").clicked.connect(lambda: self.navigate([]))
        self._nav.button("lager_alle").clicked.connect(lambda: self._show_lager())
        self._nav.button("settings").clicked.connect(self.open_settings)
        # Lager-Drilldown: Doppelklick auf eine Achse zeigt deren Historie
        self._view_lager.lager_drilldown.connect(self._open_lager_axle)

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
        shown = self._flotte_repo or self._repo     # Profil der angezeigten Daten
        default = f"bo_radsatzdaten_export_{shown.profile.name}.csv"
        p, _ = QFileDialog.getSaveFileName(self, "Rohdaten als CSV speichern",
                                            default, "CSV (*.csv)")
        if not p:
            return
        try:
            n = export_raw_csv(self._flotte, shown.profile, Path(p))
            self.statusBar().showMessage(f"CSV gespeichert: {n} Zeilen → {p}", 7000)
        except Exception as exc:
            log.exception("CSV-Export fehlgeschlagen")
            QMessageBox.critical(self, "CSV-Export fehlgeschlagen", str(exc))

    # ------------------- data ----------------------------

    def _update_schema_label(self):
        """Zeigt Kundenschema (Profil) im Kopf und im Fenstertitel."""
        prof = self._repo.profile
        name = prof.name.upper() if len(prof.name) <= 3 else prof.name.capitalize()
        self._schema_lbl.setText(f"Schema: {name}")
        self._schema_lbl.setToolTip(prof.description or prof.name)
        self.setWindowTitle(f"Wheelset Analyzer Dashboard — {name}")

    # ------------------- laden (im Hintergrund) ----------

    def reload_data(self):
        """Laedt die Daten im Hintergrund; die Oberflaeche bleibt bedienbar.

        Laeuft bereits ein Laden oder der Backend-Lauf, wird danach genau
        einmal neu geladen (z.B. nach einem Profilwechsel).
        """
        if self._load_job is not None or self._backend_job is not None:
            self._reload_pending = True
            return
        self._start_load()

    def _auto_reload(self):
        """Timer-Aufruf: laufende Aktionen nicht durch weitere Laeufe stapeln."""
        if self._load_job is None and self._backend_job is None:
            self._start_load()

    def _set_busy(self, text: str):
        self._status_lbl.setText(text)
        self._busy_bar.show()
        self._reload_btn.setEnabled(False)

    def _clear_busy(self):
        self._busy_bar.hide()
        self._reload_btn.setEnabled(True)

    def is_busy(self) -> bool:
        return self._load_job is not None or self._backend_job is not None

    def wait_for_load(self, timeout_s: float = 120.0) -> bool:
        """Wartet (bei laufender Ereignisschleife) bis Laden und Backend-Lauf
        fertig sind. ``False`` bei Zeitueberschreitung. Fuer Tests/Skripte."""
        deadline = time.monotonic() + timeout_s
        app = QApplication.instance()
        while self.is_busy() or self._reload_pending:
            if time.monotonic() > deadline:
                return False
            app.processEvents()
            time.sleep(0.005)
        return True

    def _start_load(self):
        repo = self._repo

        def work():
            with timed("repo.load", None) as t_load:
                flotte = repo.load()
            with timed("status", None) as t_status:
                recompute_status(flotte)
            with timed("lager", None) as t_lager:
                recompute_lager(flotte)
            log.debug("reload_data timing: repo.load=%.2fs, status=%.2fs, lager=%.2fs",
                      t_load.seconds, t_status.seconds, t_lager.seconds)
            return repo, flotte

        self._set_busy(f"Lade Daten …  (Profil: {repo.profile.name})")
        job = BackgroundJob(work, name="laden", parent=self)
        job.done.connect(self._on_load_done)
        job.failed.connect(self._on_load_failed)
        self._load_job = job
        job.start()
        if not self._async_load:
            self.wait_for_load()

    @Slot(object)
    def _on_load_done(self, result):
        self._load_job = None
        repo, flotte = result
        if repo is not self._repo:
            # Profil/Quelle wurde waehrend des Ladens gewechselt -> verwerfen
            log.info("Ladeergebnis (%s) verworfen: Einstellungen wurden inzwischen geaendert",
                     repo.profile.name)
            self._reload_pending = True
        else:
            try:
                self._flotte = flotte
                self._flotte_repo = repo
                self._update_schema_label()
                self._status_lbl.setText(
                    f"Stand {datetime.now().strftime('%H:%M:%S')}  ·  Profil: {repo.profile.name}  "
                    f"·  {len(flotte.einheiten)} Einheiten, {len(flotte.lager)} Lager-Komp."
                )
                self._lager_komp = self._lager_achse = None     # Objekte der alten Daten
                self.navigate(self._current_path)
                if not self._first_data_logged:
                    self._first_data_logged = True
                    log.debug("Start-Timing: erste Daten sichtbar nach %.2fs (seit MainWindow-Start)",
                              self._startup.seconds)
            except Exception as exc:  # noqa: BLE001
                log.exception("Fehler beim Anzeigen der geladenen Daten")
                QMessageBox.critical(self, "Fehler beim Laden", str(exc))
        self._clear_busy()
        self._run_pending()

    @Slot(str)
    def _on_load_failed(self, message: str):
        self._load_job = None
        self._clear_busy()
        self._status_lbl.setText("Laden fehlgeschlagen")
        QMessageBox.critical(self, "Fehler beim Laden", message)
        self._run_pending()

    def _run_pending(self):
        """Nach Ende einer Aktion: aufgelaufenen Neu-Lade-Wunsch ausfuehren."""
        if self._reload_pending and not self.is_busy():
            self._reload_pending = False
            self._start_load()

    def set_refresh_minutes(self, value: str):
        if value == "off":
            self._timer.stop()
        else:
            self._timer.start(int(value) * 60 * 1000)

    # ------------------- backend-prognose ----------------
    def recalc_prognose(self):
        """Startet das Backend-Skript (Wheelset Analyzer_new_approach),
        das die Prognose neu rechnet und in die Prognose-Tabelle schreibt.
        Laeuft synchron (blockiert die UI) mit Wait-Cursor; nach Erfolg
        werden die Daten neu geladen.
        """
        from ..logic.backend_runner import run_backend_prognose
        if not self._repo.profile.backend_prognosis:
            # Das Backend liest immer die VGF-Datenbank (eigener Connect-String,
            # VGF-Spaltennamen) und wuerde hier die falsche Prognose rechnen.
            QMessageBox.information(
                self, "Prognose neu berechnen",
                f"Die Prognose-Neuberechnung ist derzeit nur für das Profil "
                f"'vgf' verfügbar. Das Backend ist auf das VGF-Schema "
                f"ausgelegt; für '{self._repo.profile.name}' würde es die "
                f"falschen Daten rechnen.",
            )
            return
        reply = QMessageBox.question(
            self, "Prognose neu berechnen",
            "Das Backend-Skript 'Wheelset Analyzer_new_approach' wird "
            "jetzt gestartet. Es rechnet die Prognose neu und schreibt "
            "sie in die Prognose-Tabelle. Je nach Datenmenge dauert "
            "das einige Minuten. Das Dashboard bleibt währenddessen "
            "bedienbar; danach werden die Daten neu geladen.\n\nFortfahren?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        if self._backend_job is not None:
            return
        use_db = (self._repo.config.source == "oracle")
        self._set_busy("Prognose wird neu berechnet …")
        job = BackgroundJob(lambda: run_backend_prognose(use_database=use_db),
                            name="backend-prognose", parent=self)
        job.done.connect(self._on_backend_done)
        job.failed.connect(self._on_backend_failed)
        self._backend_job = job
        job.start()
        if not self._async_load:
            self.wait_for_load()

    @Slot(object)
    def _on_backend_done(self, result):
        self._backend_job = None
        self._clear_busy()
        if result.ok:
            self._status_lbl.setText("Prognose neu berechnet · lade Daten …")
            QMessageBox.information(
                self, "Prognose neu berechnet",
                f"{result.message}\n\n"
                f"Logdatei: {result.log_path or '(nicht gefunden)'}",
            )
            self._reload_pending = False
            self.reload_data()
        else:
            self._status_lbl.setText("Prognose-Neuberechnung fehlgeschlagen")
            tail = (result.stderr or result.stdout or "")[-2000:]
            QMessageBox.critical(
                self, "Prognose-Neuberechnung fehlgeschlagen",
                f"{result.message}\n\n"
                f"Logdatei: {result.log_path or '(nicht gefunden)'}\n\n"
                f"Letzte Ausgabezeilen:\n{tail}",
            )
            self._run_pending()

    @Slot(str)
    def _on_backend_failed(self, message: str):
        self._backend_job = None
        self._clear_busy()
        self._status_lbl.setText("Prognose-Neuberechnung fehlgeschlagen")
        QMessageBox.critical(self, "Prognose-Neuberechnung fehlgeschlagen", message)
        self._run_pending()

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
            self._navigate_lager(path)
            return
        self._breadcrumb.set_path(bc)

    def _navigate_lager(self, path):
        """Rueckspruenge ueber die Navigationsleiste im Lager-Kontext.

        ``Lager`` → Lager-Tabelle; ``Lager › <Drehgestell>`` → Achsenliste dieses Lager-Drehgestells;
        ``Lager › <Drehgestell> › <Achse>`` → Diagramm dieser Achse (der Pfad ist der zuletzt geoeffnete)."""
        komp = self._lager_komp
        if len(path) >= 2 and path[1][0] == "lager-dg" and komp is not None:
            if len(path) == 2:
                self._open_lager_axle(komp, None)
            elif self._lager_achse is not None:
                self._open_lager_axle(komp, self._lager_achse)
            return
        self._show_lager()

    def _show_lager(self):
        if self._flotte is None:
            return
        self._view_lager.set_prognose_config(self._prog_cfg)
        self._view_lager.set_flotte(self._flotte, None)
        self._stack.setCurrentWidget(self._view_lager)
        self._nav.set_active("lager_alle")
        self._breadcrumb.set_path([("lager", "Lager · Komponenten")])
        self._current_path = []
        self._lager_komp = self._lager_achse = None

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
        # Nur disconnecten, wenn vorher connected wurde — sonst feuert
        # PySide6 vor der Exception bereits eine RuntimeWarning auf stderr.
        if self._dg_drilldown_connected:
            try:
                self._view_dg.drilldown.disconnect()
            except Exception:
                pass
            self._dg_drilldown_connected = False
        if mode == "lager" and komp is not None:
            self._view_dg.drilldown.connect(
                lambda path, _k=komp: self._lager_dg_axle_clicked(_k, path))
        else:
            self._view_dg.drilldown.connect(self.navigate)
        self._dg_drilldown_connected = True

    def _set_achse_drilldown_mode(self, mode: str, komp=None):
        """Setzt den Achse-Drilldown-Empfaenger je nach Kontext um.

        Im Lager-Kontext fangen wir KPI-Klicks ab und routen sie zurueck
        in die Lager-Hierarchie (Lager-Tabelle bzw. Lager-DG-Achsenliste).
        """
        if self._achse_drilldown_connected:
            try:
                self._view_achse.drilldown.disconnect()
            except Exception:
                pass
            self._achse_drilldown_connected = False
        if mode == "lager" and komp is not None:
            self._view_achse.drilldown.connect(
                lambda path, _k=komp: self._lager_back_from_achse(_k, path))
        else:
            self._view_achse.drilldown.connect(self.navigate)
        self._achse_drilldown_connected = True

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
        self._lager_komp = komp
        self._lager_achse = achse
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
            # fuer "Messwerte anzeigen" (Neuaufbau ueber navigate) und Rueckspruenge
            self._current_path = [("lager", "Lager"), ("lager-dg", dg.dg_einbaupos)]
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
            self._current_path = [("lager", "Lager"), ("lager-dg", dg.dg_einbaupos),
                                  ("lager-achse", achse.rs_einbaupos or achse.rs_bez or "Achse")]

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

    def _on_time_jump_changed(self, on: bool):
        """Schalter im Diagramm umgestellt: Stand merken (Einstellungsdialog, naechste Diagramme)."""
        self._prog_cfg = dataclasses.replace(self._prog_cfg, time_jump=bool(on))

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
            "p_time_jump": self._prog_cfg.time_jump,
        }
        dlg = SettingsDialog(cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new = dlg.get_config()
            # Darstellung: gilt sofort (auch im geoeffneten Diagramm), nicht gespeichert
            self._prog_cfg = dataclasses.replace(self._prog_cfg, time_jump=bool(new["p_time_jump"]))
            self._view_achse.set_prognose_config(self._prog_cfg)
            new_repo_cfg = RepositoryConfig(
                profile_name=new["profile"],
                source=new["source"],
                csv_raw_path=Path(new["csv_raw"]) if new["csv_raw"] else None,
                csv_prognose_path=Path(new["csv_prognose"]) if new["csv_prognose"] else None,
                oracle_dsn=new["oracle_dsn"] or None,
                oracle_user=new["oracle_user"] or None,
                oracle_password=new["oracle_password"] or None,
                oracle_connect_string=build_connect_string(
                    new["oracle_user"], new["oracle_password"], new["oracle_dsn"]),
            )
            self._repo = Repository(new_repo_cfg)
            self.set_refresh_minutes(new["refresh_min"])
            self.reload_data()
            # Wenn im Dialog "Prognose jetzt neu berechnen" geklickt wurde,
            # startet nach dem Uebernehmen der Einstellungen das Backend.
            if getattr(dlg, "recalc_requested", False):
                self.recalc_prognose()
