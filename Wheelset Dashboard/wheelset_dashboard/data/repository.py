"""Repository-Fassade: einheitlicher Zugriff auf Flotten-Daten (CSV oder Oracle)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .csv_source import load_prognose_csv, load_raw_csv
from .models import Flotte
from .profile import Profile, load_profile_by_name


@dataclass
class RepositoryConfig:
    profile_name: str
    source: str                        # "csv" | "oracle"
    csv_raw_path: Optional[Path] = None
    csv_prognose_path: Optional[Path] = None
    oracle_dsn: Optional[str] = None
    oracle_user: Optional[str] = None
    oracle_password: Optional[str] = None
    oracle_connect_string: Optional[str] = None  # Backend-Format user/pw@dsn
    oracle_thick_lib_dir: Optional[str] = None


class Repository:
    def __init__(self, config: RepositoryConfig):
        self.config = config
        self.profile: Profile = load_profile_by_name(config.profile_name)
        self._flotte: Optional[Flotte] = None

    def load(self) -> Flotte:
        if self.config.source == "csv":
            if not self.config.csv_raw_path:
                raise ValueError("csv_raw_path fehlt")
            flotte = load_raw_csv(Path(self.config.csv_raw_path), self.profile)
            if self.config.csv_prognose_path:
                load_prognose_csv(Path(self.config.csv_prognose_path), self.profile, flotte)
            self._flotte = flotte
            return flotte
        elif self.config.source == "oracle":
            import logging as _logging, time as _time
            _rl = _logging.getLogger(__name__)
            if self.config.oracle_connect_string:
                # Eine Oracle-Session fuer beide Queries → spart den
                # zweiten Connect-Handshake (typisch 1–3 s). Fehler beim
                # Lesen der Prognose-Tabelle werden darin schon geloggt
                # und blockieren die Rohdaten nicht.
                _ti0 = _time.monotonic()
                from .oracle_source import (
                    load_flotte_and_prognose_from_connect_string,
                )
                _ti1 = _time.monotonic()
                _rl.debug("repo: import oracle_source (inkl. oracledb)=%.2fs", _ti1 - _ti0)
                flotte = load_flotte_and_prognose_from_connect_string(
                    self.config.oracle_connect_string,
                    profile=self.profile,
                    thick_mode_lib_dir=self.config.oracle_thick_lib_dir,
                )
            else:
                from .oracle_source import load_flotte_from_oracle
                flotte = load_flotte_from_oracle(
                    dsn=self.config.oracle_dsn,
                    user=self.config.oracle_user,
                    password=self.config.oracle_password,
                    profile=self.profile,
                    thick_mode_lib_dir=self.config.oracle_thick_lib_dir,
                )
            self._flotte = flotte
            return flotte
        else:
            raise ValueError(f"Unbekannte Quelle: {self.config.source}")

    @property
    def flotte(self) -> Flotte:
        if self._flotte is None:
            return self.load()
        return self._flotte
