"""Repository-Fassade: einheitlicher Zugriff auf Flotten-Daten (CSV oder Oracle)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config.app_paths import build_connect_string
from ..perf import timed
from .csv_source import load_prognose_csv, load_raw_csv
from .models import Flotte
from .profile import Profile, load_profile_by_name

log = logging.getLogger(__name__)


@dataclass
class RepositoryConfig:
    profile_name: str
    source: str                        # "csv" | "oracle"
    csv_raw_path: Optional[Path] = None
    csv_prognose_path: Optional[Path] = None
    # Oracle: entweder fertiger Connect-String (user/pw@dsn) oder die Einzelangaben,
    # aus denen er gebaut wird (Einstellungsdialog).
    oracle_dsn: Optional[str] = None
    oracle_user: Optional[str] = None
    oracle_password: Optional[str] = None
    oracle_connect_string: Optional[str] = None
    oracle_thick_lib_dir: Optional[str] = None

    def connect_string(self) -> Optional[str]:
        """Connect-String fuer Oracle (``None``, wenn Angaben fehlen)."""
        return self.oracle_connect_string or build_connect_string(
            self.oracle_user or "", self.oracle_password or "", self.oracle_dsn or "")


class Repository:
    def __init__(self, config: RepositoryConfig):
        self.config = config
        self.profile: Profile = load_profile_by_name(config.profile_name)
        self._flotte: Optional[Flotte] = None

    def load(self) -> Flotte:
        cfg = self.config
        if cfg.source == "csv":
            if not cfg.csv_raw_path:
                raise ValueError("csv_raw_path fehlt")
            flotte = load_raw_csv(Path(cfg.csv_raw_path), self.profile)
            if cfg.csv_prognose_path:
                load_prognose_csv(Path(cfg.csv_prognose_path), self.profile, flotte)
        elif cfg.source == "oracle":
            connect = cfg.connect_string()
            if not connect:
                raise ValueError("Oracle: Zugangsdaten unvollständig "
                                 "(Benutzer, Passwort und DSN bzw. Connect-String)")
            # Eine Oracle-Verbindung je Abfrage, beide parallel (Rohdaten + Prognose).
            # Fehler beim Lesen der Prognose-Tabelle blockieren die Rohdaten nicht.
            with timed("repo: import oracle_source (inkl. oracledb)", log):
                from .oracle_source import load_flotte_and_prognose_from_connect_string
            flotte = load_flotte_and_prognose_from_connect_string(
                connect, profile=self.profile, thick_mode_lib_dir=cfg.oracle_thick_lib_dir)
        else:
            raise ValueError(f"Unbekannte Quelle: {cfg.source}")
        self._flotte = flotte
        return flotte

    @property
    def flotte(self) -> Flotte:
        if self._flotte is None:
            return self.load()
        return self._flotte
