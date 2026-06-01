"""Einheitliche Achsen- und Diagramm-Beschriftung (TOPEINHEITBEZEICHNUNG aus Messdaten)."""

from __future__ import annotations

import csv
import os
import re
from typing import List, Sequence, Tuple, Union

from VehicleAxis import VehicleAxis
from radsatz_settings import PROGNOSIS_METHOD_GAUSS, RadsatzConfig

# Trennzeichen im Dictionary-Schlüssel (nicht mehr r[0]+r[1]+r[2] ohne Trennung)
AXIS_KEY_SEP = "\x1e"

RowLike = Union[Sequence, Tuple]


def make_axis_key(
    te_or_row: RowLike,
    dg: str | None = None,
    rs: str | None = None,
) -> str:
    """Achsschlüssel aus Messzeile oder (TOPEINHEITBEZEICHNUNG, DGEINBAUPOS, RSEINBAUPOS)."""
    if dg is None and rs is None:
        row = te_or_row
        te, dg, rs = row[0], row[1], row[2]
    else:
        te = te_or_row
    return AXIS_KEY_SEP.join(
        [
            (str(te) if te is not None else "").strip(),
            (str(dg) if dg is not None else "").strip(),
            (str(rs) if rs is not None else "").strip(),
        ]
    )


def parse_axis_key(key: str) -> Tuple[str, str, str]:
    if AXIS_KEY_SEP in key:
        parts = key.split(AXIS_KEY_SEP, 2)
        while len(parts) < 3:
            parts.append("")
        return parts[0], parts[1], parts[2]
    return key, "", ""


def sync_axis_labels_from_measurement_row(vehicle: VehicleAxis, row: Sequence) -> None:
    """TOPEINHEITBEZEICHNUNG / DG / Achse aus Messzeile (res2) in VehicleAxis."""
    if len(row) < 3:
        return
    te = (row[0] or "").strip() if row[0] is not None else ""
    dg = (row[1] or "").strip() if row[1] is not None else ""
    rs = (row[2] or "").strip() if row[2] is not None else ""
    if te:
        vehicle.setstrVDesc(te)
    if dg:
        vehicle.setstrBogie(dg)
    if rs:
        vehicle.setstrPosAxis(rs)


def axis_identity_from_vehicle(vehicle: VehicleAxis) -> Tuple[str, str, str]:
    return (
        vehicle.getstrVDesc().strip(),
        vehicle.getstrBogie().strip(),
        vehicle.getstrPosAxis().strip(),
    )


def prognosis_method_plot_label(cfg: RadsatzConfig) -> str:
    if cfg.prognosis_method == PROGNOSIS_METHOD_GAUSS:
        return "Gauss-Newton"
    return "Theil-Sen"


def format_axis_plot_title(vehicle: VehicleAxis, method_label: str) -> str:
    """
    Diagrammtitel: Zeile 1 Methode, Zeile 2 TOPEINHEITBEZEICHNUNG | DG | Achse
    (wie compare_prognose_csv, lesbar z. B. „FLIRT 101“).
    """
    te, dg, achse = axis_identity_from_vehicle(vehicle)
    return f"Prognose ({method_label})\n{te} | {dg} | {achse}"


def axis_plot_file_slug(vehicle: VehicleAxis) -> str:
    te, dg, achse = axis_identity_from_vehicle(vehicle)
    raw = "|".join([te, dg, achse])
    return re.sub(r"[^\w\-.]+", "_", raw, flags=re.UNICODE)[:180]


def axis_matches_plot_filter(vehicle: VehicleAxis, cfg: RadsatzConfig) -> bool:
    """Optional: nur Achsen plotten, deren Bezeichnung den Filter-Teilstring enthält."""
    flt = (cfg.plot_top_einheit_filter or "").strip()
    if not flt:
        return True
    blob = " | ".join(axis_identity_from_vehicle(vehicle)).upper()
    return flt.upper() in blob


def write_plot_manifest(
    cfg: RadsatzConfig,
    method_slug: str,
    entries: List[Tuple[str, str, str]],
) -> str:
    """Schreibt plot_manifest_<methode>.csv für Vergleich Theil-Sen vs. Gauss (gleiche Achsen finden)."""
    out_dir = cfg.plot_output_dir or cfg.script_dir
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"plot_manifest_{method_slug}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["PLOT_NR", "TOPEINHEITBEZEICHNUNG", "DGEINBAUPOS", "RSEINBAUPOS"])
        for i, (te, dg, rs) in enumerate(entries, start=1):
            w.writerow([i, te, dg, rs])
    return path
