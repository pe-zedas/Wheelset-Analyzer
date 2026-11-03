"""Zentrale Pfad-Helfer fuer das App-eigene Config-Verzeichnis.

Das Config-Verzeichnis liegt **neben** dem Python-Package, nicht darin:
``<App-Root>/config/`` — damit sind Code (``wheelset_dashboard/``) und
Betriebs-Konfiguration (DB-Credentials, …) sauber getrennt.
"""
from __future__ import annotations

from pathlib import Path

# wheelset_dashboard/config/app_paths.py → …/wheelset_dashboard/ → App-Root
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
APP_ROOT = _PACKAGE_DIR.parent

CONFIG_DIR = APP_ROOT / "config"
ORACLE_CONNECT_FILE = CONFIG_DIR / "oracle_connect_string.txt"


def ensure_config_dir() -> Path:
    """Legt das Config-Verzeichnis an, falls es noch nicht existiert."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def read_oracle_connect_string() -> str | None:
    """Liest die Connect-String-Datei. ``None`` wenn sie fehlt oder leer ist."""
    if not ORACLE_CONNECT_FILE.exists():
        return None
    lines = ORACLE_CONNECT_FILE.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def write_oracle_connect_string(connect_string: str) -> Path:
    """Schreibt den Connect-String in die Config-Datei (ueberschreibt).
    Legt das Config-Verzeichnis an, falls noetig."""
    ensure_config_dir()
    ORACLE_CONNECT_FILE.write_text(connect_string.strip() + "\n", encoding="utf-8")
    return ORACLE_CONNECT_FILE
