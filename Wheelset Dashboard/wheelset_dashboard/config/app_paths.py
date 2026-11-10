"""Zentrale Pfad-Helfer fuer das App-eigene Config-Verzeichnis.

Das Config-Verzeichnis liegt **neben** dem Python-Package, nicht darin:
``<App-Root>/config/`` — damit sind Code (``wheelset_dashboard/``) und
Betriebs-Konfiguration (DB-Credentials, …) sauber getrennt.
"""
from __future__ import annotations

import re
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


DEFAULT_PROFILE = "vgf"

# "<profil> = user/passwort@dsn". Ein '/' vor dem '=' (z. B. Passwort mit '=')
# kann nie als Label missverstanden werden, weil Labels nur aus
# Buchstaben/Ziffern/_/- bestehen.
_LABELED = re.compile(r"^([A-Za-z][\w-]*)\s*=\s*(\S.*)$")


def _connect_entries(path: Path) -> tuple[dict[str, str], str | None]:
    """Liest die Connect-String-Datei.

    Rueckgabe: ``({profil: connect_string}, erste_unbeschriftete_zeile)``.
    Kommentar- (``#``) und Leerzeilen werden ignoriert.
    """
    labeled: dict[str, str] = {}
    unlabeled: str | None = None
    if not path.exists():
        return labeled, unlabeled
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LABELED.match(line)
        if m:
            labeled.setdefault(m.group(1).lower(), m.group(2).strip())
        elif unlabeled is None:
            unlabeled = line
    return labeled, unlabeled


def read_oracle_connect_string(profile: str | None = None) -> str | None:
    """Connect-String des Kundenprofils aus ``oracle_connect_string.txt``.

    Die Datei enthaelt eine Zeile je Kunde: ``vgf = user/pw@dsn``,
    ``abellio = …``, ``mob = …``. ``None`` wenn fuer das Profil nichts
    hinterlegt ist. Eine alte, unbeschriftete Zeile gilt nur fuer ``vgf``
    (bzw. ohne Profilangabe) — sonst wuerden VGF-Zugangsdaten bei anderen
    Kunden landen.
    """
    wanted = (profile or DEFAULT_PROFILE).strip().lower()
    labeled, unlabeled = _connect_entries(ORACLE_CONNECT_FILE)
    if wanted in labeled:
        return labeled[wanted]
    return unlabeled if wanted == DEFAULT_PROFILE else None


def parse_connect_string(connect_string: str) -> tuple[str, str, str]:
    """Zerlegt ``user/passwort@dsn`` in ``(user, passwort, dsn)``.
    Fehlende Teile kommen als leerer String zurueck."""
    cs = (connect_string or "").strip()
    cred, sep, dsn = cs.rpartition("@")
    if not sep:
        cred, dsn = cs, ""
    user, _, pw = cred.partition("/")
    return user.strip(), pw, dsn.strip()


def build_connect_string(user: str, password: str, dsn: str) -> str | None:
    """Baut ``user/passwort@dsn``; ``None`` wenn ein Teil fehlt."""
    if not (user and password and dsn):
        return None
    return f"{user}/{password}@{dsn}"
