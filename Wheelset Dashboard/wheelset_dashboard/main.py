"""Einstiegspunkt der Wheelset-Dashboard-Anwendung."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .config.app_paths import ORACLE_CONNECT_FILE, read_oracle_connect_string
from .config.logging_setup import install_global_exception_handler, setup_logging
from .data.repository import Repository, RepositoryConfig
from .ui.main_window import MainWindow

DEFAULT_CSV_RAW = Path("../Wheelset Analyzer_new_approach/bo_radsatzdaten_export.csv")
DEFAULT_CSV_PROG = Path("../Wheelset Analyzer_new_approach/bo_radsatzdaten_prognose_recalc.csv")


def main():
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
    logging.getLogger(__name__).info("Log-Datei: %s", log_path)

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

    app = QApplication(sys.argv)
    # QSS laden
    qss_path = Path(__file__).parent / "ui" / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    win = MainWindow(repo)

    def _ui_crash(exc_type, exc_value, exc_tb):
        QMessageBox.critical(win, "Unerwarteter Fehler",
                             f"{exc_type.__name__}: {exc_value}\n\nDetails im Log: {log_path}")
    install_global_exception_handler(_ui_crash)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
