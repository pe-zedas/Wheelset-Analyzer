"""Zentrales Logging-Setup mit RotatingFileHandler."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

DEFAULT_LOG_FILE = "wheelset_dashboard.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 5


def setup_logging(
    log_file: str = DEFAULT_LOG_FILE,
    level: str = "INFO",
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    console: bool = True,
) -> Path:
    """Richtet rotierenden File-Handler + optional Konsole ein."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = Path(log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        root.addHandler(ch)

    return log_path


def install_global_exception_handler(ui_callback=None):
    """Faengt ungefangene Exceptions ab, loggt sie und ruft optional ein UI-Callback."""
    def handler(exc_type, exc_value, exc_tb):
        logging.getLogger(__name__).critical(
            "Ungefangene Exception", exc_info=(exc_type, exc_value, exc_tb))
        if ui_callback is not None:
            try:
                ui_callback(exc_type, exc_value, exc_tb)
            except Exception:
                pass
    sys.excepthook = handler
