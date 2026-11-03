"""Zentrales Logging-Setup mit RotatingFileHandler."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

DEFAULT_LOG_FILE = "wheelset_dashboard.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 5


def setup_logging(
    log_file: str = DEFAULT_LOG_FILE,
    level: str = "INFO",
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    console: bool = True,
    console_level: Optional[str] = None,
) -> Path:
    """Richtet rotierenden File-Handler + optional Konsole ein.

    Die Datei bekommt den vollen ``level`` (Default INFO), damit alles
    nachvollziehbar bleibt. Die Konsole wird standardmaessig auf
    ``WARNING`` gedrosselt, damit beim Start keine „info/failed"-
    Meldungen stoeren. Mit ``console_level`` oder ``--verbose`` kann
    man das anheben.
    """
    file_level_num = getattr(logging, level.upper(), logging.INFO)
    if console_level is None:
        # Verbose (DEBUG) → Konsole auch DEBUG; sonst still (WARNING).
        console_level_num = (
            logging.DEBUG if file_level_num <= logging.DEBUG else logging.WARNING
        )
    else:
        console_level_num = getattr(logging, console_level.upper(), logging.WARNING)

    root = logging.getLogger()
    root.handlers.clear()
    # Root-Level muss das niedrigste der angemeldeten Handler sein.
    root.setLevel(min(file_level_num, console_level_num))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = Path(log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8",
    )
    fh.setLevel(file_level_num)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(console_level_num)
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
