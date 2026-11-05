"""Einstiegspunkt der Wheelset-Dashboard-Anwendung."""
from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from .config.app_paths import ORACLE_CONNECT_FILE, read_oracle_connect_string
from .config.logging_setup import install_global_exception_handler, setup_logging
from .data.repository import Repository, RepositoryConfig
from .ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Stille beim Start: Qt- und PySide6-interne Warnungen auf stderr dämpfen.
# Logging-Hinweise gehen nach wie vor in wheelset_dashboard.log.
# ---------------------------------------------------------------------------

# 1) PySide6-RuntimeWarnings (z. B. "libpyside: Failed to disconnect …"):
#    Harmlose Lebenszyklus-Meldungen, nicht nutzerwirksam.
warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message=r".*libpyside.*",
)

# 2) Qt-C++-Messages (qWarning/qDebug): landen sonst roh auf stderr.
#    Wir reichen sie an den Python-Logger weiter — Qt-Warnings erscheinen
#    damit in der Logdatei (und ab WARNING auch in der Konsole), aber
#    typische kosmetische Hinweise wie "QFont::setPointSize: Point size
#    <= 0 (-1)" werden ausgefiltert.
_QT_SILENCE_PATTERNS = (
    "QFont::setPointSize",
    "libpyside: Failed to disconnect",
    # Qt-ICC-Profil-Parser meldet beim Laden mancher PNG/JPG-Dateien
    # "fromIccProfile: Failed to parse description" — kosmetisch, Bild
    # wird trotzdem korrekt dargestellt.
    "fromIccProfile",
)
_qt_log = logging.getLogger("qt")


def _qt_message_handler(mode, ctx, msg):
    for pat in _QT_SILENCE_PATTERNS:
        if pat in msg:
            return
    if mode == QtMsgType.QtDebugMsg:
        _qt_log.debug(msg)
    elif mode == QtMsgType.QtInfoMsg:
        _qt_log.info(msg)
    elif mode == QtMsgType.QtWarningMsg:
        _qt_log.warning(msg)
    elif mode == QtMsgType.QtCriticalMsg:
        _qt_log.error(msg)
    elif mode == QtMsgType.QtFatalMsg:
        _qt_log.critical(msg)
    else:
        _qt_log.info(msg)


qInstallMessageHandler(_qt_message_handler)

DEFAULT_CSV_RAW = Path("../Wheelset Analyzer_new_approach/bo_radsatzdaten_export.csv")
DEFAULT_CSV_PROG = Path("../Wheelset Analyzer_new_approach/bo_radsatzdaten_prognose_recalc.csv")


def main():
    import time as _time
    t_start = _time.monotonic()

    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="vgf", help="Kundenprofil (vgf/abellio/mob)")
    ap.add_argument("--source", choices=["csv", "oracle"], default="csv")
    ap.add_argument("--csv-raw", default=str(DEFAULT_CSV_RAW))
    ap.add_argument("--csv-prognose", default=str(DEFAULT_CSV_PROG))
    ap.add_argument("--connect-file", default=None,
                    help="Oracle-Connect-String-Datei (nur bei --source oracle). "
                         f"Default: {ORACLE_CONNECT_FILE}")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    log_path = setup_logging(
        log_file="wheelset_dashboard.log",
        level="DEBUG" if args.verbose else "INFO",
    )
    _log = logging.getLogger(__name__)
    _log.info("Log-Datei: %s", log_path)
    _log.debug("Start-Timing: imports=%.2fs (vom Prozessstart bis hier)", _time.monotonic() - t_start)

    if args.source == "oracle":
        import os
        from pathlib import Path as _P
        env = os.environ.get("ORACLE_CONNECT_STRING", "").strip()
        if args.connect_file:
            cf = _P(args.connect_file)
            connect_string = (env or (cf.read_text(encoding="utf-8").splitlines()[0].strip()
                                      if cf.exists() else None))
            cf_shown = cf
        else:
            # Standard: eigenes Config-Verzeichnis des Dashboards
            connect_string = env or read_oracle_connect_string()
            cf_shown = ORACLE_CONNECT_FILE
        if not connect_string:
            raise SystemExit(f"Oracle-Modus: Connect-String nicht gefunden ({cf_shown}).")
        repo = Repository(RepositoryConfig(
            profile_name=args.profile,
            source="oracle",
            oracle_connect_string=connect_string,
        ))
    else:
        repo = Repository(RepositoryConfig(
            profile_name=args.profile,
            source="csv",
            csv_raw_path=Path(args.csv_raw),
            csv_prognose_path=Path(args.csv_prognose) if Path(args.csv_prognose).exists() else None,
        ))

    t0 = _time.monotonic()
    app = QApplication(sys.argv)
    # QSS laden
    qss_path = Path(__file__).parent / "ui" / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
    t1 = _time.monotonic()
    _log.debug("Start-Timing: QApplication+QSS=%.2fs", t1 - t0)

    win = MainWindow(repo)
    t2 = _time.monotonic()
    _log.debug("Start-Timing: MainWindow-Init (inkl. reload_data)=%.2fs", t2 - t1)

    def _ui_crash(exc_type, exc_value, exc_tb):
        QMessageBox.critical(win, "Unerwarteter Fehler",
                             f"{exc_type.__name__}: {exc_value}\n\nDetails im Log: {log_path}")
    install_global_exception_handler(_ui_crash)

    win.show()
    t3 = _time.monotonic()
    _log.debug("Start-Timing: GESAMT bis show()=%.2fs", t3 - t_start)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
