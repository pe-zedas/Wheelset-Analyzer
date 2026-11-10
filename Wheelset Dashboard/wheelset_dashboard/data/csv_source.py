"""CSV-Loader fuer bo_radsatzdaten / bo_radsatzdaten_prognose, profilgesteuert.

Liest nur die Dateien; Aufbau der Struktur steht in ``structure.build_flotte``,
Anreicherung um Prognosen in ``prognose_source.attach_prognose``.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from .models import Flotte
from .profile import Profile
from .prognose_source import attach_prognose
from .structure import build_flotte

log = logging.getLogger(__name__)


def load_raw_csv(path: Path, profile: Profile) -> Flotte:
    """Liest bo_radsatzdaten_export.csv und baut die Flotten-/Lager-Struktur auf."""
    with open(path, "r", encoding=profile.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=profile.delimiter)
        header = next(reader)
        idx = profile.map_raw_header(header)
        if "zartbez" not in idx or "datum" not in idx or "stand" not in idx:
            missing = [k for k in ("zartbez", "datum", "stand") if k not in idx]
            raise ValueError(
                f"Pflicht-Spalten fehlen nach Mapping (Profil {profile.name}): {missing}. "
                f"Header war: {header[:5]}..."
            )
        return build_flotte(reader, idx, profile, label="CSV geladen")


def load_prognose_csv(path: Path, profile: Profile, flotte: Flotte) -> int:
    """Reichert die Flotte um Prognosewerte aus der Prognose-CSV an."""
    if not Path(path).exists():
        log.warning("Prognose-CSV nicht gefunden: %s", path)
        return 0
    with open(path, "r", encoding=profile.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=profile.delimiter)
        header = next(reader)
        idx = profile.map_prognose_header(header)
        return attach_prognose(flotte, profile, reader, idx, label="Prognose-CSV")
