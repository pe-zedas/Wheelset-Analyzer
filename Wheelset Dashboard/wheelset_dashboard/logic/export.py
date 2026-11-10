"""Export-Funktionen: Werkstattliste (xlsx) und Rohtabellen (CSV)."""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..data.models import (
    Achse, ComponentState, Drehgestell, Einheit, Flotte, Rad, StatusAmpel,
)
from ..data.profile import Profile

log = logging.getLogger(__name__)


# ---------- Werkstattliste (xlsx) -----------------------------------

_PILL_FILL = {
    StatusAmpel.RED: PatternFill("solid", fgColor="FCEBEB"),
    StatusAmpel.YELLOW: PatternFill("solid", fgColor="FAEEDA"),
    StatusAmpel.GREEN: PatternFill("solid", fgColor="EAF3DE"),
    StatusAmpel.GRAY: PatternFill("solid", fgColor="F1EFE8"),
}
_PILL_FONT = {
    StatusAmpel.RED: Font(color="791F1F", bold=True),
    StatusAmpel.YELLOW: Font(color="633806", bold=True),
    StatusAmpel.GREEN: Font(color="3B6D11", bold=True),
    StatusAmpel.GRAY: Font(color="444441"),
}
_STATUS_TEXT = {
    StatusAmpel.RED: "Grenz",
    StatusAmpel.YELLOW: "Warn",
    StatusAmpel.GREEN: "OK",
    StatusAmpel.GRAY: "unbekannt",
}


def _iter_lkd_entries(flotte: Flotte):
    """Yields (einheit, dg, achse, rad, messreihe) nur fuer LKD-Reihen."""
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            for a in dg.achsen.values():
                for seite, rad in a.raeder.items():
                    mr = rad.messreihen.get("LKD")
                    if mr is not None:
                        yield e, dg, a, seite, rad, mr


def werkstattliste_to_xlsx(
    flotte: Flotte,
    out_path: Path,
    horizon_days: int = 90,
    now: Optional[datetime] = None,
) -> int:
    """Schreibt eine xlsx mit allen LKD-Reihen, deren Warn-/Grenz-Termin im Horizont liegt."""
    now = now or datetime.now()
    horizon_end = now + timedelta(days=horizon_days)

    rows = []
    for e, dg, a, seite, rad, mr in _iter_lkd_entries(flotte):
        prog = mr.prognose
        if prog is None:
            continue
        warn = prog.datum_warnwert
        grenz = prog.datum_grenzwert
        if (warn is None or warn > horizon_end) and (grenz is None or grenz > horizon_end):
            if (grenz is None or grenz >= now) and (warn is None or warn >= now):
                continue
        letzt = mr.letzter_wert()
        aktueller_lkd = letzt.stand if letzt else None
        aktuelle_km = letzt.laufleistung if letzt else None
        rest_km_warn = (prog.km_warnwert - aktuelle_km) if (prog.km_warnwert and aktuelle_km) else None
        rest_km_grenz = (prog.km_grenzwert - aktuelle_km) if (prog.km_grenzwert and aktuelle_km) else None
        rows.append({
            "Einheit": e.topeinheit_bez,
            "DG-Pos": dg.dg_einbaupos,
            "Achse-Pos": a.rs_einbaupos,
            "Rad": "LKD1" if seite.value == "left" else ("LKD2" if seite.value == "right" else "–"),
            "aktueller LKD [mm]": aktueller_lkd,
            "aktuelle Laufleistung [km]": aktuelle_km,
            "nächster Warn-Termin": warn,
            "Rest-km bis Warn": rest_km_warn,
            "nächster Grenz-Termin": grenz,
            "Rest-km bis Grenz": rest_km_grenz,
            "Status": mr.status,
            "Qualität": prog.qualitaet.value,
            "Methode": prog.methode or "–",
        })

    # Sortierung: dringendste zuerst
    rows.sort(key=lambda r: (
        r["nächster Grenz-Termin"] or datetime.max,
        r["nächster Warn-Termin"] or datetime.max,
    ))

    wb = Workbook()
    ws = wb.active
    ws.title = "Werkstattliste"

    headers = list(rows[0].keys()) if rows else [
        "Einheit", "DG-Pos", "Achse-Pos", "Rad",
        "aktueller LKD [mm]", "aktuelle Laufleistung [km]",
        "nächster Warn-Termin", "Rest-km bis Warn",
        "nächster Grenz-Termin", "Rest-km bis Grenz",
        "Status", "Qualität", "Methode",
    ]
    ws.append(headers)
    header_font = Font(bold=True, color="4A4E57")
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.font = header_font
        c.alignment = Alignment(horizontal="left")

    status_col = headers.index("Status") + 1
    for r in rows:
        row_values = []
        for h in headers:
            v = r[h]
            if isinstance(v, datetime):
                v = v.date().isoformat()
            if isinstance(v, StatusAmpel):
                v = _STATUS_TEXT[v]
            if isinstance(v, float):
                v = round(v, 2)
            row_values.append(v)
        ws.append(row_values)
        row_idx = ws.max_row
        status = r["Status"]
        cell = ws.cell(row=row_idx, column=status_col)
        cell.fill = _PILL_FILL[status]
        cell.font = _PILL_FONT[status]
        cell.alignment = Alignment(horizontal="center")

    if not rows:
        ws.append(["Keine Einträge im gewählten Zeitraum"])

    # Spaltenbreiten
    for col_idx, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = max(14, len(h) + 2)

    ws.auto_filter.ref = ws.dimensions
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    log.info("Werkstattliste exportiert: %s (%d Zeilen)", out_path, len(rows))
    return len(rows)


# ---------- CSV-Export Rohdaten --------------------------------------

def export_raw_csv(flotte: Flotte, profile: Profile, out_path: Path) -> int:
    """Schreibt die Rohdaten im Backend-Format zurueck."""
    out_path = Path(out_path)
    # Reverse-Mapping: intern -> CSV-Spalte in Profil-Reihenfolge
    csv_cols = list(profile.columns_raw.keys())
    inverse = {v: k for k, v in profile.columns_raw.items()}

    with open(out_path, "w", encoding=profile.encoding, newline="") as fh:
        w = csv.writer(fh, delimiter=profile.delimiter)
        w.writerow(csv_cols)

        n = 0
        # eingebaut
        for e in flotte.einheiten.values():
            for dg in e.drehgestelle.values():
                for a in dg.achsen.values():
                    for seite, rad in a.raeder.items():
                        for mg, mr in rad.messreihen.items():
                            for mp in mr.historie:
                                w.writerow(_build_raw_row(csv_cols, profile, e, dg, a,
                                                          seite, mg, mp, aktuell=1))
                                n += 1
                for mg, mr in dg.direkt_messreihen.items():
                    for mp in mr.historie:
                        w.writerow(_build_raw_row(csv_cols, profile, e, dg, None,
                                                  None, mg, mp, aktuell=1))
                        n += 1
        # Lager (sowohl flache messreihen als auch pro Rad)
        for comp in flotte.lager:
            for mg, mr in comp.messreihen.items():
                for mp in mr.historie:
                    w.writerow(_build_lager_row(csv_cols, profile, comp, mg, mp))
                    n += 1
            for rad in comp.raeder.values():
                for mg, mr in rad.messreihen.items():
                    for mp in mr.historie:
                        w.writerow(_build_lager_row(csv_cols, profile, comp, mg, mp))
                        n += 1
            # Lager-Drehgestell: die Messwerte haengen an seinen Achsen
            for a in comp.achsen.values():
                for seite, rad in a.raeder.items():
                    for mg, mr in rad.messreihen.items():
                        for mp in mr.historie:
                            w.writerow(_build_lager_row(csv_cols, profile, comp, mg, mp,
                                                        achse=a, seite=seite))
                            n += 1

    log.info("Rohdaten-CSV exportiert: %s (%d Zeilen)", out_path, n)
    return n


def _fmt(v, profile: Profile):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime(profile.date_format)
    if isinstance(v, float):
        return (f"{v:g}").replace(".", profile.decimal) if profile.decimal != "." else f"{v:g}"
    return str(v)


def _build_raw_row(csv_cols, profile, e, dg, a, seite, mg_name, mp, aktuell):
    # Fuer das Rueckschreiben nutzen wir das ZARTBEZ-"Standard"-Muster des Profils
    # (nehmen das erste Pattern, das die gewuenschte Seite hat).
    zartbez_text = _choose_zartbez(profile, mg_name, seite)
    data = {
        "topeinheit_id": e.topeinheit_id,
        "topeinheit_bez": e.topeinheit_bez,
        "dg_id": dg.dg_id,
        "dg_bez": dg.dg_bez,
        "dg_einbaupos": dg.dg_einbaupos,
        "rs_id": a.rs_id if a else None,
        "rs_bez": a.rs_bez if a else "",
        "rs_einbaupos": a.rs_einbaupos if a else "",
        "einbau": a.einbau if a else None,
        "ausbau": a.ausbau if a else None,
        "aktuell": aktuell,
        "zartbez": zartbez_text,
        "stand": mp.stand,
        "datum": mp.datum,
        "min_val": mp.min_val,
        "max_val": mp.max_val,
        "gelb_min": mp.gelb_min,
        "gelb_max": mp.gelb_max,
        "laufleistung": mp.laufleistung,
    }
    return [_fmt(data.get(profile.columns_raw[c]), profile) for c in csv_cols]


def _build_lager_row(csv_cols, profile, comp, mg_name, mp, achse=None, seite=None):
    """Zeile fuer eine Lager-Komponente. Bei einem Lager-Drehgestell werden
    ``achse``/``seite`` mitgegeben (Drehgestell- und Achsangaben wie bei
    eingebauten Zeilen)."""
    zartbez_text = _choose_zartbez(profile, mg_name, seite)
    data = {
        "topeinheit_bez": comp.letzte_einheit,
        "dg_id": comp.dg_id,
        "dg_bez": comp.dg_bez,
        "rs_id": achse.rs_id if achse else comp.rs_id,
        "rs_bez": achse.rs_bez if achse else comp.rs_bez,
        "rs_einbaupos": achse.rs_einbaupos if achse else "",
        "ausbau": comp.ausbau,
        "einbau": comp.einbau,
        "aktuell": 0,
        "zartbez": zartbez_text,
        "stand": mp.stand,
        "datum": mp.datum,
        "min_val": mp.min_val,
        "max_val": mp.max_val,
        "gelb_min": mp.gelb_min,
        "gelb_max": mp.gelb_max,
        "laufleistung": mp.laufleistung,
    }
    return [_fmt(data.get(profile.columns_raw[c]), profile) for c in csv_cols]


def _choose_zartbez(profile: Profile, mg_name: str, seite):
    """Reproduziert eine ZARTBEZ fuer die kanonische Messgroesse + Seite.

    Kein 100%-Roundtrip (die urspruengliche Rohbezeichnung ging im Mapping verloren).
    Wir rekonstruieren ein kanonisches Label: ``<MG> (left|right|unspec)``.
    """
    s = "" if seite is None else f" ({seite.value})"
    return f"{mg_name}{s}"
