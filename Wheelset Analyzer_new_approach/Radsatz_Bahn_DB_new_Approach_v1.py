"""
Radsatz_Bahn_DB_new_Approach.py

Hauptskript für Radsatz-Verschleißprognose (VGF / ZEDAS).
Methode wählbar in radsatz_config.ini ([prognose] prognosis_method):

  theil_sen — IQR, Theil-Sen, optional Power-Law, Reprof-Szenario (Standard)
  gauss     — Gauss-Newton-Exponentialfit (VehicleAxis.CalcPrognostic) mit IQR
              und gelernten Reprof-Parametern (wie Gauss_Class_All_Enhanced)

DB-Ausgabeschema bleibt kompatibel zu BO_RADSATZDATEN_PROGNOSE.
"""

import csv
import copy
import os
import re
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Iterator, List, Optional, Tuple

try:
    import oracledb
except ModuleNotFoundError as exc:
    raise ImportError(
        "Oracle-Treiber nicht gefunden. Installiere mit: python -m pip install oracledb"
    ) from exc

from dates_np import (
    NAT,
    add_days,
    days_to_timedelta64,
    is_nat,
    timedelta64_to_days,
    to_datetime64_array,
)
from toolsWheelset import getStartIndexLastCycle
from MeterList import MeterList
from VehicleAxis import VehicleAxis
from radsatz_settings import (
    PROGNOSIS_METHOD_GAUSS,
    PROGNOSIS_METHOD_THEIL_SEN,
    axis_key_matches_debug,
    load_radsatz_config,
)
from radsatz_axis_labels import (
    axis_identity_from_vehicle,
    axis_matches_plot_filter,
    axis_plot_file_slug,
    format_axis_plot_title,
    make_axis_key,
    sync_axis_labels_from_measurement_row,
    write_plot_manifest,
)
from radsatz_csv_io import load_bo_radsatz_from_csv

# ── Basis-Config laden (gemeinsam mit bisherigem Programm) ─────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
cfg = load_radsatz_config(SCRIPT_DIR)

# Backend VOR pyplot (PyQt5 wirkt nur so; sonst bleibt Windows oft bei TkAgg).
from radsatz_matplotlib import configure_matplotlib_backend

MPL_BACKEND = configure_matplotlib_backend(
    cfg.plot_matplotlib_backend,
    cfg.plot_show_window and cfg.show_plot,
)
import matplotlib.pyplot as plt

from prognosis_new_core import (
    _PrognResult,
    _calc_prognosis_axis,
    prognosis_params_from_radsatz_config,
    set_prognosis_params,
)
from reprof_learning import (
    learn_reprofiling_params,
    learn_reprofiling_params_per_axis,
    reprofiling_params_from_radsatz_config,
    set_reprofiling_params_per_axis,
)
from prognosis_gauss import (
    progn_result_for_plot_from_gauss_meter,
    run_gauss_prognosis_for_vehicle,
)

useDatabase         = cfg.use_database
write_Prog_Data     = cfg.write_prog_data
showPlot            = cfg.show_plot
CSV_BO_RADSATZDATEN = cfg.csv_bo_radsatzdaten
CSV_BO_PROGNOSE_OUT = cfg.csv_bo_prognose_out
dtStartData         = cfg.dt_start_data
nKm                 = cfg.n_km
diffLKD             = cfg.diff_lkd
# nKmRepro / nValueRepro werden aus der Config geladen, im neuen Ansatz aber nicht
# verwendet (kein periodisches Reprofilierungs-Einbau in die Prognosekurve mehr).
# Reserviert für ein späteres optionales Szenario "mit Reprofilierung".
nDays2Delete        = cfg.n_days_2_delete

logging.basicConfig(
    filename=cfg.log_file,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.info("=== Radsatz_Bahn_DB_new_Approach gestartet ===")
logging.info("Matplotlib-Backend: %s", MPL_BACKEND)
logging.info("Prognosemethode(n) (ini): %s", ", ".join(cfg.prognosis_methods))

# ── CSV-Ausgabe-Header (identisch zu BO_RADSATZDATEN_PROGNOSE) ─────────────────
_PROGNOSE_CSV_HEADER = [
    "TOPEINHEITID", "TOPEINHEITBEZEICHNUNG", "DGEINHEITID", "DGBEZEICHNUNG",
    "DGEINBAUPOS", "RSEINHEITID", "RSBEZEICHNUNG", "RSEINBAUPOS",
    "EINBAU", "AUSBAU", "AKTUELL", "ZAEHLERARTID", "ZARTBEZ",
    "STAND", "DATUM", "LAUFLEISTUNG", "LETZTEAENDZEIT",
    "KM_GRENZWERT", "DATUM_GRENZWERT", "KM_WARNWERT", "DATUM_WARNWERT",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Achsen-Reihenfolge (stabil: Fahrzeug, DG, Achse)
# ═══════════════════════════════════════════════════════════════════════════════


def _vehicle_axis_sort_key(vehicle_tuple) -> Tuple[str, str, str]:
    return (str(vehicle_tuple[0]), str(vehicle_tuple[1]), str(vehicle_tuple[2]))


def _sorted_vehicle_axis_items(
    vehicle_axes: Dict[str, VehicleAxis],
) -> Iterator[Tuple[str, VehicleAxis]]:
    for key in sorted(vehicle_axes.keys()):
        yield key, vehicle_axes[key]


def _method_label(method_slug: str) -> str:
    if method_slug == PROGNOSIS_METHOD_GAUSS:
        return "Gauss-Newton"
    return "Theil-Sen"


def _extract_baureihe(vehicle_desc: str) -> str:
    """
    Robuste Baureihen-Ableitung:
    - "FLIRT 101" -> "FLIRT"
    - "FS102" -> "FS"
    - "3180 080 6101-8" -> "3180"
    """
    s = str(vehicle_desc or "").strip().upper()
    if not s:
        return ""
    token = s.split()[0]
    m = re.match(r"[A-Z]+", token)
    if m:
        return m.group(0)
    return token


def _calc_days_per_km_from_meter(met: MeterList) -> float:
    km = np.asarray(met.getkm(), dtype=float)
    nd_raw = met.getnDates()
    n_len = len(nd_raw) if hasattr(nd_raw, "__len__") else 0
    if km.size < 2 or n_len < 2 or km.size != n_len:
        return 0.01
    # nDates ist np.ndarray[datetime64[s]] — Differenz liefert timedelta64
    if hasattr(nd_raw, "dtype") and np.issubdtype(nd_raw.dtype, np.datetime64):
        nd = np.asarray(nd_raw)
    else:
        nd = np.array(list(nd_raw), dtype="datetime64[s]")
    dkm = np.diff(km)
    dday = timedelta64_to_days(np.diff(nd))
    mask = (dkm > 0) & np.isfinite(dkm) & np.isfinite(dday)
    if not np.any(mask):
        return 0.01
    rates = dday[mask] / dkm[mask]
    rates = rates[np.isfinite(rates) & (rates > 0)]
    if rates.size == 0:
        return 0.01
    return float(np.median(rates))


def _collect_baureihe_mean_slopes(
    vehicle_axes: Dict[str, VehicleAxis],
) -> Dict[Tuple[str, int], float]:
    """
    Mittlere (Median-)Steigung je Baureihe und Zähler (1/2) aus historischen Daten.
    """
    pools: Dict[Tuple[str, int], List[float]] = {}
    for _key, v in _sorted_vehicle_axis_items(vehicle_axes):
        br = _extract_baureihe(v.getstrVDesc())
        if not br:
            continue
        for meter_idx, met in ((1, v.getmeterList1()), (2, v.getmeterList2())):
            km = np.asarray(met.getkm(), dtype=float)
            lkd = np.asarray(met.getvalues(), dtype=float)
            if km.size < 2 or lkd.size < 2:
                continue
            order = np.argsort(km)
            km = km[order]
            lkd = lkd[order]
            try:
                slope = float(np.polyfit(km, lkd, 1)[0])
            except (np.linalg.LinAlgError, ValueError):
                continue
            if not np.isfinite(slope) or slope >= 0:
                continue
            pools.setdefault((br, meter_idx), []).append(slope)

    out: Dict[Tuple[str, int], float] = {}
    for k, vals in pools.items():
        arr = np.asarray(vals, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size:
            out[k] = float(np.median(arr))
    return out


def _build_theil_baureihe_fallback(
    met: MeterList,
    axis_key: str,
    meter_idx: int,
    vehicle_desc: str,
    n_km_horizon: int,
    slope_cache: Dict[Tuple[str, int], float],
) -> Optional[_PrognResult]:
    """
    Fallback wenn Theil-Sen INSUFFICIENT: lineare Prognose mit mittlerem
    Baureihen-Anstieg aus historischen Daten.
    """
    br = _extract_baureihe(vehicle_desc)
    slope = slope_cache.get((br, meter_idx))
    if slope is None or not np.isfinite(slope) or slope >= 0:
        return None

    km = np.asarray(met.getkm(), dtype=float)
    lkd = np.asarray(met.getvalues(), dtype=float)
    if km.size < 1 or lkd.size < 1:
        return None
    order = np.argsort(km)
    km = km[order]
    lkd = lkd[order]
    last_km = float(km[-1])
    last_lkd = float(lkd[-1])
    km_end = float(last_km + n_km_horizon)
    n_pts = max(3, int(cfg.progn_new_n_prog_points))
    km_prog = np.linspace(last_km, km_end, num=n_pts)
    lkd_prog = last_lkd + slope * (km_prog - last_km)

    gelb_min = float(met.getgelb_min()[-1]) if met.getgelb_min() else None
    min_val = float(met.getmin()[-1]) if met.getmin() else None

    def _km_threshold(target: Optional[float]) -> Optional[float]:
        if target is None or slope >= 0:
            return None
        dist = (target - last_lkd) / slope
        if not np.isfinite(dist) or dist <= 0:
            return None
        return float(last_km + dist)

    km_warn = _km_threshold(gelb_min)
    km_limit = _km_threshold(min_val)
    days_per_km = _calc_days_per_km_from_meter(met)

    nd_raw = met.getnDates()
    n_len = len(nd_raw) if hasattr(nd_raw, "__len__") else 0
    last_dn = nd_raw[-1] if n_len > 0 else NAT
    if is_nat(last_dn):
        date_prog = np.array([], dtype="datetime64[s]")
    else:
        date_prog = last_dn + days_to_timedelta64((km_prog - last_km) * days_per_km)

    def _km_to_datenum(km_thresh: Optional[float]):
        if km_thresh is None or days_per_km <= 0 or is_nat(last_dn):
            return NAT
        return add_days(last_dn, (float(km_thresh) - last_km) * days_per_km)

    met.setkmProg(km_prog.tolist())
    met.setvaluesProg(lkd_prog.tolist())
    met.setnDatesProg(date_prog if date_prog.size else [])
    met.setgelb_min_Prog_km(km_warn if km_warn is not None and km_warn > 0 else 0.0)
    met.setmin_Prog_km(km_limit if km_limit is not None and km_limit > 0 else 0.0)
    met.setgelb_min_Prog_dt(_km_to_datenum(km_warn))
    met.setmin_Prog_dt(_km_to_datenum(km_limit))

    logging.info(
        "Theil-Sen-Fallback Baureihe=%s D%d: slope=%.6f | %s",
        br,
        meter_idx,
        slope,
        axis_key,
    )
    return _PrognResult(
        quality="LOW",
        model="BAUREIHE_FALLBACK",
        n_points_fit=len(km),
        n_outliers=0,
        cycle_source="BAUREIHE",
        slope=slope,
        slope_low=slope,
        slope_high=slope,
        days_per_km=days_per_km,
        km_warn=km_warn,
        km_limit=km_limit,
        km_warn_conservative=km_warn,
        km_limit_conservative=km_limit,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Hilfsfunktionen: Datenladen (CSV / Oracle)
# ═══════════════════════════════════════════════════════════════════════════════

def load_connect_string(script_dir: str, connect_filename: str) -> str:
    env = os.environ.get("ORACLE_CONNECT_STRING", "").strip()
    if env:
        return env
    path = os.path.join(script_dir, connect_filename)
    try:
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError as exc:
        raise SystemExit(f"Connect-String-Datei fehlt: {path}\n{exc}") from exc
    if not line or line.startswith("#"):
        raise SystemExit(f"In {connect_filename} muss die Verbindungszeile stehen.")
    return line


def _prognose_csv_zelle(spalte: int, wert):
    if wert is None:
        return ""
    if isinstance(wert, datetime):
        return wert.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(wert, np.generic):
        wert = wert.item()
    if isinstance(wert, (float, int)) and not isinstance(wert, bool):
        x = float(wert)
        if spalte == 13:
            return f"{x:.2f}"
        if spalte in (15, 17, 19):
            return f"{x:.2f}"
    return wert


# ═══════════════════════════════════════════════════════════════════════════════
#  Plotfunktion (Theil-Sen-Linie + KI-Band + Schwellen)
# ═══════════════════════════════════════════════════════════════════════════════

def _show_plot_figure(fig, title: str = "") -> None:
    """Fenster anzeigen; nach Schließen weiter (Qt beendet sonst oft den ganzen Prozess)."""
    if not cfg.plot_show_window:
        plt.close(fig)
        return
    from radsatz_matplotlib import block_until_figure_closed

    block_until_figure_closed(fig, title=title)


def _plot_linear_ki_and_median(
    ax,
    km_last: float,
    lkd_last: float,
    res_m: _PrognResult,
    color: str,
    meter_label: str,
) -> None:
    """
    KI-Band und Median aus Theil-Sen (slope / slope_low / slope_high) auf linearer km-Achse.
    Dient der Einordnung, wenn die exportierte Prognosekurve das Reprof-Zickzack ist.
    """
    if res_m.km_limit is not None and res_m.km_limit > km_last:
        km_end = float(res_m.km_limit)
    else:
        km_end = float(km_last + nKm)
    npt = max(3, int(cfg.progn_new_n_prog_points))
    km_band = np.linspace(km_last, km_end, num=npt)
    dd = km_band - km_last
    lkd_med = lkd_last + res_m.slope * dd
    lkd_lo = lkd_last + res_m.slope_low * dd
    lkd_hi = lkd_last + res_m.slope_high * dd
    ax.fill_between(
        km_band, lkd_lo, lkd_hi,
        color=color, alpha=0.12, label=f"{meter_label} KI-Band (90%)",
    )
    ax.plot(
        km_band, lkd_med,
        color=color, lw=1.2, ls=":",
        label=f"{meter_label} Prognose (Median, linear)",
    )


def _plot_meter_history(
    ax,
    met: MeterList,
    n_cycle_start: int,
    color: str,
    meter_label: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Zeichnet den gesamten Messverlauf (ältere Historie + aktueller Zyklus) mit
    gestrichelter Linie; der aktuelle Zyklus wird zusätzlich in den Punkten hervorgehoben.
    """
    km_all = np.asarray(met.getkm(), dtype=float)
    lkd_all = np.asarray(met.getvalues(), dtype=float)
    n_cycle_start = max(0, min(n_cycle_start, len(km_all)))

    if len(km_all) >= 2:
        order = np.argsort(km_all)
        ax.plot(
            km_all[order],
            lkd_all[order],
            color=color,
            ls="--",
            lw=0.9,
            alpha=0.35,
            zorder=1,
        )

    if n_cycle_start > 0:
        ax.scatter(
            km_all[:n_cycle_start],
            lkd_all[:n_cycle_start],
            color=color,
            s=10,
            alpha=0.35,
            zorder=2,
            label=f"{meter_label} Historie",
        )
    if n_cycle_start < len(km_all):
        ax.scatter(
            km_all[n_cycle_start:],
            lkd_all[n_cycle_start:],
            color=color,
            s=14,
            alpha=0.95,
            zorder=4,
            label=f"{meter_label} Zyklus (Fit)",
        )
    return km_all, lkd_all


def _km_crossing_horizontal(
    km_pts,
    lkd_pts,
    y_thresh: float,
) -> Optional[float]:
    """
    Erster km, an dem die Polyline (km, LKD) die Horizontale y_thresh
    von oben kreuzt oder berührt (Verschleißabstieg oder Reprof-Sprung).
    """
    k = np.asarray(km_pts, dtype=float)
    y = np.asarray(lkd_pts, dtype=float)
    if k.size < 2 or y.size != k.size or not np.isfinite(y_thresh):
        return None
    for i in range(len(k) - 1):
        y0, y1 = float(y[i]), float(y[i + 1])
        k0, k1 = float(k[i]), float(k[i + 1])
        if not (np.isfinite(y0) and np.isfinite(y1) and np.isfinite(k0) and np.isfinite(k1)):
            continue
        # Kreuzung / Berührung: Start oberhalb oder auf Schwelle, Ende auf/unter Schwelle
        if y0 >= y_thresh and y1 <= y_thresh:
            if abs(y0 - y1) < 1e-12:
                return k0
            # Vertikaler Reprof-Sprung (gleiche km): Schnitt bei diesem km
            if abs(k1 - k0) < 1e-9:
                return k0
            t = (y_thresh - y0) / (y1 - y0)
            return float(k0 + t * (k1 - k0))
    return None


def _gelb_marker_on_threshold(
    met: MeterList,
    res_m: _PrognResult,
    gelb_min: Optional[float],
) -> Optional[Tuple[float, float]]:
    """
    Gelb-Marker immer auf der gelben Warnlinie: (Schnitt-km, GELB_MIN).
    Schnitt-km = erster Schnitt der gezeichneten Prognosekurve mit GELB_MIN.
    """
    if gelb_min is None or not np.isfinite(float(gelb_min)):
        return None
    y_gelb = float(gelb_min)

    km_curve = list(met.getkmProg() or [])
    lkd_curve = list(met.getvaluesProg() or [])
    if len(km_curve) < 2 and res_m.km_prog_reprof and res_m.lkd_prog_reprof:
        km_curve = list(res_m.km_prog_reprof)
        lkd_curve = list(res_m.lkd_prog_reprof)

    km_cross = _km_crossing_horizontal(km_curve, lkd_curve, y_gelb)
    if km_cross is None:
        if res_m.km_warn_reprof and res_m.km_warn_reprof > 0:
            km_cross = float(res_m.km_warn_reprof)
        elif res_m.km_warn and res_m.km_warn > 0:
            km_cross = float(res_m.km_warn)
        else:
            return None
    return float(km_cross), y_gelb


def _plot_axis(
    tmpVehicle: VehicleAxis,
    res1_m: _PrognResult,
    res2_m: _PrognResult,
    method_label: str,
):
    plot_title = format_axis_plot_title(tmpVehicle, method_label)
    show_ki_band = method_label != "Gauss-Newton"
    nIndex1 = tmpVehicle.getmeterList1().getindexStartLastCycle()
    nIndex2 = tmpVehicle.getmeterList2().getindexStartLastCycle()
    m1 = tmpVehicle.getmeterList1()
    m2 = tmpVehicle.getmeterList2()

    fig, ax = plt.subplots(figsize=cfg.plot_figsize, dpi=cfg.plot_dpi)
    if cfg.plot_show_window:
        from radsatz_matplotlib import ensure_interactive_plot_session

        ensure_interactive_plot_session()

    # Historische Messwerte (gesamt) + hervorgehobener letzter Zyklus
    km1_all, lkd1_all = _plot_meter_history(ax, m1, nIndex1, "blue", "LKD1")
    km2_all, lkd2_all = _plot_meter_history(ax, m2, nIndex2, "green", "LKD2")

    km1 = km1_all[nIndex1:] if nIndex1 < len(km1_all) else km1_all[:0]
    lkd1 = lkd1_all[nIndex1:] if nIndex1 < len(lkd1_all) else lkd1_all[:0]
    km2 = km2_all[nIndex2:] if nIndex2 < len(km2_all) else km2_all[:0]
    lkd2 = lkd2_all[nIndex2:] if nIndex2 < len(lkd2_all) else lkd2_all[:0]

    # Prognosekurven (Median) + 90%-KI-Band zwischen slope_low und slope_high
    # Das Band spannt sich symmetrisch um den Median: slope_low (unten, schnellerer
    # Verschleiß) bis slope_high (oben, langsamerer Verschleiß). Der Median läuft
    # durch die Mitte des Bands.
    if m1.getkmProg():
        km_p1  = np.array(m1.getkmProg())
        lkd_p1 = np.array(m1.getvaluesProg())
        if res1_m.prog_curve_uses_reprof:
            if show_ki_band:
                _plot_linear_ki_and_median(
                    ax, float(km1[-1]), float(lkd1[-1]), res1_m, "blue", "LKD1",
                )
            ax.plot(
                km_p1, lkd_p1, color="blue", lw=1.3, ls="-",
                label="LKD1 Prognose (mit Reprofilierung)",
            )
        else:
            lkd_p1_start = float(lkd_p1[0])
            km_delta1 = km_p1 - km_p1[0]
            lkd_p1_low  = lkd_p1_start + res1_m.slope_low  * km_delta1
            lkd_p1_high = lkd_p1_start + res1_m.slope_high * km_delta1
            if show_ki_band:
                ax.fill_between(
                    km_p1,
                    lkd_p1_low,
                    lkd_p1_high,
                    color="blue",
                    alpha=0.12,
                    label="LKD1 KI-Band (90%)",
                )
            ax.plot(km_p1, lkd_p1, color="blue", lw=1.2, ls=":", label="LKD1 Prognose (Median)")
            if res1_m.km_prog_reprof:
                ax.plot(
                    res1_m.km_prog_reprof, res1_m.lkd_prog_reprof,
                    color="blue", lw=1.0, ls="--", alpha=0.7,
                    label="LKD1 mit Reprofilierung",
                )

    if m2.getkmProg():
        km_p2  = np.array(m2.getkmProg())
        lkd_p2 = np.array(m2.getvaluesProg())
        if res2_m.prog_curve_uses_reprof:
            if show_ki_band:
                _plot_linear_ki_and_median(
                    ax, float(km2[-1]), float(lkd2[-1]), res2_m, "green", "LKD2",
                )
            ax.plot(
                km_p2, lkd_p2, color="green", lw=1.3, ls="-",
                label="LKD2 Prognose (mit Reprofilierung)",
            )
        else:
            lkd_p2_start = float(lkd_p2[0])
            km_delta2 = km_p2 - km_p2[0]
            lkd_p2_low  = lkd_p2_start + res2_m.slope_low  * km_delta2
            lkd_p2_high = lkd_p2_start + res2_m.slope_high * km_delta2
            if show_ki_band:
                ax.fill_between(
                    km_p2,
                    lkd_p2_low,
                    lkd_p2_high,
                    color="green",
                    alpha=0.12,
                    label="LKD2 KI-Band (90%)",
                )
            ax.plot(km_p2, lkd_p2, color="green", lw=1.2, ls=":", label="LKD2 Prognose (Median)")
            if res2_m.km_prog_reprof:
                ax.plot(
                    res2_m.km_prog_reprof, res2_m.lkd_prog_reprof,
                    color="green", lw=1.0, ls="--", alpha=0.7,
                    label="LKD2 mit Reprofilierung",
                )

    # Schwellen (GELB_MIN / MIN der letzten Messung LKD1)
    if len(m1.getmin()) > 0:
        ax.axhline(m1.getmin()[-1],     color="red",    lw=1.8, ls="-",  label=f"MIN ({m1.getmin()[-1]:.0f} mm)")
        ax.axhline(m1.getmax()[-1],     color="red",    lw=1.8, ls="-")
        ax.axhline(m1.getgelb_min()[-1], color="gold",  lw=1.8, ls="-",  label=f"GELB_MIN ({m1.getgelb_min()[-1]:.0f} mm)")

    def _xy_on_reprof_curve(res_m: _PrognResult, km_thresh: Optional[float]):
        """Schwell-km auf die Reprof-Kurve projizieren (Grenzmarker)."""
        if (
            not res_m.km_prog_reprof
            or not res_m.lkd_prog_reprof
            or km_thresh is None
            or km_thresh <= 0
        ):
            return None
        k = np.asarray(res_m.km_prog_reprof, dtype=float)
        y = np.asarray(res_m.lkd_prog_reprof, dtype=float)
        if k.size < 2:
            return None
        km_c = float(np.clip(km_thresh, k.min(), k.max()))
        yi = float(np.interp(km_c, k, y))
        return km_c, yi

    def _annotate_point(km_val: float, lkd_val: float, text: str, color: str, marker: str) -> None:
        if km_val and km_val > 0 and lkd_val is not None:
            ax.plot(
                [km_val], [lkd_val], marker=marker, color=color, ms=8, zorder=5,
                linestyle="None",
            )
            ax.annotate(
                text,
                xy=(km_val, lkd_val),
                xytext=(km_val, lkd_val + 8),
                fontsize=8,
                color=color,
                arrowprops=dict(arrowstyle="->", color=color, lw=0.8),
            )

    if res1_m:
        gelb1 = m1.getgelb_min()[-1] if m1.getgelb_min() else None
        min1 = m1.getmin()[-1] if m1.getmin() else None
        use_reprof = bool(res1_m.km_prog_reprof and res1_m.lkd_prog_reprof)
        xy_gelb1 = _gelb_marker_on_threshold(m1, res1_m, gelb1)
        if xy_gelb1:
            label_g1 = "D1 Gelb (Reprof.)" if use_reprof and res1_m.km_warn_reprof else "D1 Gelb"
            _annotate_point(xy_gelb1[0], xy_gelb1[1], label_g1, "blue", "v")
        if use_reprof and res1_m.km_limit_reprof and res1_m.km_limit_reprof > 0:
            xy = _xy_on_reprof_curve(res1_m, res1_m.km_limit_reprof)
            if xy:
                _annotate_point(xy[0], xy[1], "D1 Grenze (Reprof.)", "blue", "^")
        elif res1_m.km_limit and res1_m.km_limit > 0 and min1 is not None:
            _annotate_point(float(res1_m.km_limit), float(min1), "D1 Grenze", "blue", "^")

    if res2_m:
        gelb2 = m2.getgelb_min()[-1] if m2.getgelb_min() else None
        min2 = m2.getmin()[-1] if m2.getmin() else None
        use_reprof = bool(res2_m.km_prog_reprof and res2_m.lkd_prog_reprof)
        xy_gelb2 = _gelb_marker_on_threshold(m2, res2_m, gelb2)
        if xy_gelb2:
            label_g2 = "D2 Gelb (Reprof.)" if use_reprof and res2_m.km_warn_reprof else "D2 Gelb"
            _annotate_point(xy_gelb2[0], xy_gelb2[1], label_g2, "green", "v")
        if use_reprof and res2_m.km_limit_reprof and res2_m.km_limit_reprof > 0:
            xy = _xy_on_reprof_curve(res2_m, res2_m.km_limit_reprof)
            if xy:
                _annotate_point(xy[0], xy[1], "D2 Grenze (Reprof.)", "green", "^")
        elif res2_m.km_limit and res2_m.km_limit > 0 and min2 is not None:
            _annotate_point(float(res2_m.km_limit), float(min2), "D2 Grenze", "green", "^")

    ax.set_xlabel("Laufleistung [km]", fontsize=11)
    ax.set_ylabel("Laufkreisdurchmesser [mm]", fontsize=11)
    ax.set_title(plot_title, fontsize=10)
    if len(m1.getmin()) > 0:
        margin = 5
        y_lo = float(m1.getmin()[-1]) - margin
        y_hi = float(m1.getmax()[-1]) + margin
        meas = np.concatenate(
            [a for a in (lkd1_all, lkd2_all) if a.size > 0],
            dtype=float,
        ) if (lkd1_all.size or lkd2_all.size) else np.array([])
        if meas.size:
            y_lo = min(y_lo, float(np.min(meas)) - margin)
            y_hi = max(y_hi, float(np.max(meas)) + margin)
        ax.set_ylim(y_lo, y_hi)
    ax.legend(fontsize=7, loc="upper right")
    ax.xaxis.set_ticks_position("bottom")
    ax.yaxis.set_ticks_position("left")

    if cfg.plot_output_dir:
        os.makedirs(cfg.plot_output_dir, exist_ok=True)
        safe = axis_plot_file_slug(tmpVehicle)
        plot_path = os.path.join(cfg.plot_output_dir, f"prognose_new_{safe}.png")
        plt.savefig(plot_path, dpi=cfg.plot_dpi)
        logging.info("Diagramm gespeichert: %s", plot_path)

    if cfg.plot_show_window:
        logging.info("Plot-Fenster: %s (schließen für nächste Achse)", plot_title)
        print(f"Plot: {plot_title}  — Fenster schließen für die nächste Achse.")
        _show_plot_figure(fig, title=plot_title)
    else:
        plt.close(fig)


def _plot_axis_compare_methods(
    base_vehicle: VehicleAxis,
    method_series: Dict[str, Tuple[VehicleAxis, _PrognResult, _PrognResult]],
    method_order: Tuple[str, ...],
) -> None:
    """Historie einmal; Prognosekurven mehrerer Methoden im selben Diagramm."""
    first_method = method_order[0]
    first_vehicle = method_series[first_method][0]
    n1 = first_vehicle.getmeterList1().getindexStartLastCycle()
    n2 = first_vehicle.getmeterList2().getindexStartLastCycle()
    bm1 = base_vehicle.getmeterList1()
    bm2 = base_vehicle.getmeterList2()

    fig, ax = plt.subplots(figsize=cfg.plot_figsize, dpi=cfg.plot_dpi)
    if cfg.plot_show_window:
        from radsatz_matplotlib import ensure_interactive_plot_session

        ensure_interactive_plot_session()

    km1_all, lkd1_all = _plot_meter_history(ax, bm1, n1, "blue", "LKD1")
    km2_all, lkd2_all = _plot_meter_history(ax, bm2, n2, "green", "LKD2")
    km1_last = float(km1_all[n1:][-1]) if len(km1_all[n1:]) else float(km1_all[-1])
    lkd1_last = float(lkd1_all[n1:][-1]) if len(lkd1_all[n1:]) else float(lkd1_all[-1])
    km2_last = float(km2_all[n2:][-1]) if len(km2_all[n2:]) else float(km2_all[-1])
    lkd2_last = float(lkd2_all[n2:][-1]) if len(lkd2_all[n2:]) else float(lkd2_all[-1])

    style_map = {
        PROGNOSIS_METHOD_THEIL_SEN: "-",
        PROGNOSIS_METHOD_GAUSS: "--",
    }

    def _plot_one_meter(
        method_slug: str,
        method_label: str,
        meter_label: str,
        color: str,
        km_last: float,
        lkd_last: float,
        met: MeterList,
        res_m: _PrognResult,
    ) -> None:
        km_prog = np.asarray(met.getkmProg() or [], dtype=float)
        lkd_prog = np.asarray(met.getvaluesProg() or [], dtype=float)
        if km_prog.size == 0 or lkd_prog.size == 0:
            return
        show_ki = method_slug == PROGNOSIS_METHOD_THEIL_SEN
        if show_ki and res_m.prog_curve_uses_reprof:
            _plot_linear_ki_and_median(ax, km_last, lkd_last, res_m, color, meter_label)
        if show_ki and (not res_m.prog_curve_uses_reprof):
            lkd_p_start = float(lkd_prog[0])
            km_delta = km_prog - km_prog[0]
            lkd_p_low = lkd_p_start + res_m.slope_low * km_delta
            lkd_p_high = lkd_p_start + res_m.slope_high * km_delta
            ax.fill_between(
                km_prog,
                lkd_p_low,
                lkd_p_high,
                color=color,
                alpha=0.12,
                label=f"{meter_label} KI-Band (90%) [{method_label}]",
            )
        ax.plot(
            km_prog,
            lkd_prog,
            color=color,
            lw=1.4,
            ls=style_map.get(method_slug, "-"),
            label=f"{meter_label} Prognose [{method_label}]",
        )

    for method_slug in method_order:
        method_label = _method_label(method_slug)
        mv, res1_m, res2_m = method_series[method_slug]
        _plot_one_meter(
            method_slug,
            method_label,
            "LKD1",
            "blue",
            km1_last,
            lkd1_last,
            mv.getmeterList1(),
            res1_m,
        )
        _plot_one_meter(
            method_slug,
            method_label,
            "LKD2",
            "green",
            km2_last,
            lkd2_last,
            mv.getmeterList2(),
            res2_m,
        )

    if len(bm1.getmin()) > 0:
        ax.axhline(bm1.getmin()[-1], color="red", lw=1.8, ls="-", label=f"MIN ({bm1.getmin()[-1]:.0f} mm)")
        ax.axhline(bm1.getmax()[-1], color="red", lw=1.8, ls="-")
        ax.axhline(
            bm1.getgelb_min()[-1],
            color="gold",
            lw=1.8,
            ls="-",
            label=f"GELB_MIN ({bm1.getgelb_min()[-1]:.0f} mm)",
        )

    method_title = " + ".join(_method_label(m) for m in method_order)
    plot_title = format_axis_plot_title(base_vehicle, method_title)
    ax.set_xlabel("Laufleistung [km]", fontsize=11)
    ax.set_ylabel("Laufkreisdurchmesser [mm]", fontsize=11)
    ax.set_title(plot_title, fontsize=10)
    ax.legend(fontsize=7, loc="upper right")
    ax.xaxis.set_ticks_position("bottom")
    ax.yaxis.set_ticks_position("left")

    if cfg.plot_output_dir:
        os.makedirs(cfg.plot_output_dir, exist_ok=True)
        safe = axis_plot_file_slug(base_vehicle)
        plot_path = os.path.join(cfg.plot_output_dir, f"prognose_new_{safe}.png")
        plt.savefig(plot_path, dpi=cfg.plot_dpi)
        logging.info("Diagramm gespeichert: %s", plot_path)

    if cfg.plot_show_window:
        logging.info("Plot-Fenster: %s (schließen für nächste Achse)", plot_title)
        print(f"Plot: {plot_title}  — Fenster schließen für die nächste Achse.")
        _show_plot_figure(fig, title=plot_title)
    else:
        plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
#  Hauptprogramm
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    selected_methods = tuple(cfg.prognosis_methods)
    use_theil = PROGNOSIS_METHOD_THEIL_SEN in selected_methods
    set_prognosis_params(prognosis_params_from_radsatz_config(cfg))
    print(
        "Prognosemethode(n): "
        + ", ".join(_method_label(m) for m in selected_methods)
    )
    # Datenbankverbindung oder CSV
    str_connection = None
    if useDatabase:
        oracledb.init_oracle_client()
        str_connection = load_connect_string(SCRIPT_DIR, cfg.oracle_connect_filename)
        con = oracledb.connect(str_connection)
        cur = con.cursor()
        cur.arraysize = cfg.oracle_arraysize
    
        cur.prepare(
            "select topeinheitbezeichnung, dgeinbaupos, rseinbaupos from bo_radsatzdaten "
            "where ausbau is null group by topeinheitbezeichnung, dgeinbaupos, rseinbaupos "
            "order by topeinheitbezeichnung"
        )
        cur.execute(None, {})
        res1 = cur.fetchall()
    
        cur.prepare(
            "select topeinheitbezeichnung,dgeinbaupos,rseinbaupos,zartbez,datum,stand,Laufleistung,"
            "Min,Max,Gelb_Min,topeinheitid,dgeinheitid,dgbezeichnung,rseinheitid,rsbezeichnung,"
            "einbau,ausbau,aktuell,zaehlerartid from bo_radsatzdaten where zartbez in (:BezZ1,:BezZ2) "
            "and datum > TO_DATE(:StartDatum,:FormatString) and ausbau is null order by datum"
        )
        cur.execute(
            None,
            {
                "BezZ1": "Rad-Laufkreisdurchmesser-1",
                "BezZ2": "Rad-Laufkreisdurchmesser-2",
                "StartDatum": dtStartData,
                "FormatString": "YYYY-MM-DD",
            },
        )
        res2 = cur.fetchall()
        cur.close()
        con.close()
    else:
        res1, res2 = load_bo_radsatz_from_csv(CSV_BO_RADSATZDATEN, dtStartData)
    
    # ── Fahrzeugachsen-Dictionary aufbauen ─────────────────────────────────────────
    dict_VehicleAxis = {}
    for strVehicle in sorted(res1, key=_vehicle_axis_sort_key):
        dict_VehicleAxis[make_axis_key(strVehicle)] = VehicleAxis(
            strVehicle[0], strVehicle[1], strVehicle[2],
            MeterList([], [], [], [], [], [], []),
            MeterList([], [], [], [], [], [], []),
        )
    
    if not res2:
        print("Keine Messdaten gefunden.")
        logging.warning("Keine Messdaten gefunden (res2 leer).")
    else:
        try:
            # ── Messdaten in VehicleAxis-Objekte einsortieren ──────────────────────
            for r in res2:
                axis_key = make_axis_key(r)
                tVehicle = dict_VehicleAxis.get(axis_key)
                if tVehicle is None:
                    logging.warning(
                        "Achsschlüssel fehlt im Dictionary: %s | %s | %s", r[0], r[1], r[2]
                    )
                    continue
                if None in (r[4], r[5], r[6], r[7], r[8], r[9]):
                    print(f"Zählerdaten nicht vollständig für: {r[0]} {r[1]} {r[2]}")
                    logging.warning("Zählerdaten unvollständig: %s %s %s", r[0], r[1], r[2])
                    continue
    
                met = tVehicle.getmeterList1() if r[3] == "Rad-Laufkreisdurchmesser-1" \
                    else tVehicle.getmeterList2()
    
                met.getstrDates().append(r[4])
                met.getvalues().append(r[5])
                met.getkm().append(r[6])
                met.getmin().append(r[7])
                met.getmax().append(r[8])
                met.getgelb_min().append(r[9])
                met.setzaehlerartid(r[18])
                met.setzartbez(r[3])
    
                sync_axis_labels_from_measurement_row(tVehicle, r)

                tVehicle.settopeinheitid(r[10])
                tVehicle.setdgeinheitid(r[11])
                tVehicle.setdgbezeichnung(r[12])
                tVehicle.setrseinheitid(r[13])
                tVehicle.setrsbezeichnung(r[14])
                tVehicle.seteinbau(r[15])
                tVehicle.setausbau(r[16])
                tVehicle.setaktuell(r[17])
    
            # ── Datum als numpy.datetime64[s]-Array ablegen ─────────────────────────
            for key, tmpVehicle in _sorted_vehicle_axis_items(dict_VehicleAxis):
                for met in (tmpVehicle.getmeterList1(), tmpVehicle.getmeterList2()):
                    dates = met.getstrDates()
                    if len(dates) > 1:
                        met.setnDates(to_datetime64_array(dates))

            # ── Reprofilierungsparameter datengetrieben lernen ─────────────────
            ini_reprof = reprofiling_params_from_radsatz_config(cfg)
            fleet_reprof = learn_reprofiling_params(dict_VehicleAxis)
            per_axis_reprof = learn_reprofiling_params_per_axis(
                dict_VehicleAxis,
                ini_fallback=ini_reprof,
            )
            set_reprofiling_params_per_axis(
                per_axis_reprof,
                fleet_fallback=ini_reprof,
            )
            logging.info("Reprofilierung ini-Fallback: %s", ini_reprof)
            logging.info("Reprofilierung Flotte (Vergleich): %s", fleet_reprof)

            if cfg.progn_new_cv_tune and use_theil:
                from radsatz_crossval import tune_prognosis_params_by_cv

                best, _score, _folds = tune_prognosis_params_by_cv(dict_VehicleAxis, cfg)
                set_prognosis_params(best)
            elif cfg.progn_new_cv_tune and not use_theil:
                logging.info("cv_tune übersprungen (nur für prognosis_method=theil_sen)")

            # ── Prognoseberechnung: Hauptschleife ──────────────────────────────────
            plot_count = 0
            plot_manifest_entries: List[Tuple[str, str, str]] = []
            export_vehicle_by_key: Dict[str, VehicleAxis] = {}
            baureihe_slope_cache: Dict[Tuple[str, int], float] = {}
            if cfg.progn_new_baureihe_fallback:
                baureihe_slope_cache = _collect_baureihe_mean_slopes(dict_VehicleAxis)
                logging.info(
                    "Theil-Sen Baureihen-Fallback aktiv (n=%d Baureihe/Zähler-Einträge)",
                    len(baureihe_slope_cache),
                )
            else:
                logging.info("Theil-Sen Baureihen-Fallback deaktiviert")
            if showPlot:
                plt.ioff()
                if cfg.plot_show_window:
                    print(
                        f"Matplotlib-Backend: {MPL_BACKEND} — "
                        "jedes Plotfenster schließen (X), dann erscheint die nächste Achse."
                    )

            for key, tmpVehicle in _sorted_vehicle_axis_items(dict_VehicleAxis):
                m1 = tmpVehicle.getmeterList1()
                m2 = tmpVehicle.getmeterList2()

                if len(m1.getstrDates()) <= 1 or len(m2.getstrDates()) <= 1:
                    logging.warning(
                        "Zu wenig Messdaten (LKD1=%d, LKD2=%d): %s %s %s",
                        len(m1.getstrDates()), len(m2.getstrDates()),
                        tmpVehicle.getstrVDesc(), tmpVehicle.getstrBogie(),
                        tmpVehicle.getstrPosAxis(),
                    )
                    continue
    
                if axis_key_matches_debug(
                    cfg,
                    tmpVehicle.getstrVDesc(),
                    tmpVehicle.getstrBogie(),
                    tmpVehicle.getstrPosAxis(),
                ):
                    te, dg, achse = axis_identity_from_vehicle(tmpVehicle)
                    print(f"{te} | {dg} | {achse}")
    
                try:
                    method_series: Dict[str, Tuple[VehicleAxis, _PrognResult, _PrognResult]] = {}
                    method_errors: Dict[str, str] = {}
                    for method_slug in selected_methods:
                        try:
                            work_vehicle = copy.deepcopy(tmpVehicle)
                            wm1 = work_vehicle.getmeterList1()
                            wm2 = work_vehicle.getmeterList2()
                            if method_slug == PROGNOSIS_METHOD_GAUSS:
                                run_gauss_prognosis_for_vehicle(work_vehicle, key, cfg)
                                res1_m = progn_result_for_plot_from_gauss_meter(wm1)
                                res2_m = progn_result_for_plot_from_gauss_meter(wm2)
                            else:
                                n1 = getStartIndexLastCycle(wm1.getkm(), wm1.getvalues(), diffLKD)
                                n2 = getStartIndexLastCycle(wm2.getkm(), wm2.getvalues(), diffLKD)
                                wm1.setindexStartLastCycle(n1)
                                wm2.setindexStartLastCycle(n2)
                                res1_m = _calc_prognosis_axis(wm1, key + "_LKD1", nKm)
                                res2_m = _calc_prognosis_axis(wm2, key + "_LKD2", nKm)
                                if cfg.progn_new_baureihe_fallback and not (wm1.getkmProg() and wm2.getkmProg()):
                                    fb1 = _build_theil_baureihe_fallback(
                                        wm1,
                                        key + "_LKD1",
                                        1,
                                        work_vehicle.getstrVDesc(),
                                        nKm,
                                        baureihe_slope_cache,
                                    )
                                    fb2 = _build_theil_baureihe_fallback(
                                        wm2,
                                        key + "_LKD2",
                                        2,
                                        work_vehicle.getstrVDesc(),
                                        nKm,
                                        baureihe_slope_cache,
                                    )
                                    if fb1 is not None and fb2 is not None:
                                        res1_m = fb1
                                        res2_m = fb2

                            # Nur Methode als verfügbar markieren, wenn beide LKD-Prognosekurven existieren.
                            if wm1.getkmProg() and wm2.getkmProg():
                                method_series[method_slug] = (work_vehicle, res1_m, res2_m)
                            else:
                                method_errors[method_slug] = "keine vollständige Prognosekurve"
                        except Exception as meth_exc:
                            method_errors[method_slug] = str(meth_exc)
                            logging.exception(
                                "Methode %s fehlgeschlagen für Achse %s",
                                method_slug,
                                key,
                            )

                    available_methods = tuple(m for m in selected_methods if m in method_series)
                    if not available_methods:
                        logging.warning(
                            "Keine Methode erfolgreich für %s (%s %s %s). Fehler: %s",
                            key,
                            tmpVehicle.getstrVDesc(),
                            tmpVehicle.getstrBogie(),
                            tmpVehicle.getstrPosAxis(),
                            "; ".join(f"{m}: {e}" for m, e in method_errors.items()),
                        )
                        continue

                    # Export/DB-Schreiben: erste verfügbare Methode gemäß konfigurierter Reihenfolge.
                    export_method = available_methods[0]
                    export_vehicle_by_key[key] = method_series[export_method][0]

                    if (
                        showPlot
                        and axis_matches_plot_filter(tmpVehicle, cfg)
                    ):
                        plot_count += 1
                        te, dg, achse = axis_identity_from_vehicle(tmpVehicle)
                        plot_manifest_entries.append((te, dg, achse))
                        if cfg.plot_show_window:
                            print(
                                f"Plot {plot_count}: "
                                f"{te} | {dg} | {achse}  "
                                f"[{', '.join(_method_label(m) for m in available_methods)}]"
                            )
                        if len(available_methods) == 1:
                            _wv, r1, r2 = method_series[available_methods[0]]
                            _plot_axis(_wv, r1, r2, _method_label(available_methods[0]))
                        else:
                            _plot_axis_compare_methods(
                                tmpVehicle,
                                method_series,
                                available_methods,
                            )

                except Exception:
                    logging.exception("Prognose fehlgeschlagen für: %s", key)

            if showPlot and plot_manifest_entries:
                manifest_path = write_plot_manifest(
                    cfg,
                    "_".join(m.replace("-", "_") for m in selected_methods),
                    plot_manifest_entries,
                )
                print(f"Plot-Liste (Vergleich Methoden): {manifest_path}")

            if showPlot and cfg.plot_show_window:
                print(
                    f"Alle Plotfenster fertig ({plot_count} Diagramm(e) mit "
                    f"auswertbarer Prognose)."
                )
    
        except Exception:
            logging.exception("Fehler beim Aufbereiten der Messdaten.")
    
        # ── Prognosedaten speichern ────────────────────────────────────────────────
        if write_Prog_Data:
            if len(selected_methods) > 1:
                logging.warning(
                    "Mehrere Methoden aktiv (%s): Export nutzt nur die erste Methode (%s).",
                    ", ".join(selected_methods),
                    selected_methods[0],
                )
            if useDatabase:
                con = oracledb.connect(str_connection)
                cur = con.cursor()
                date_cutoff = datetime.now() - timedelta(days=nDays2Delete)
                cur.execute(
                    "delete from BO_RADSATZDATEN_PROGNOSE where LETZTEAENDZEIT < :dtLAend",
                    {"dtLAend": date_cutoff},
                )
                con.commit()
                source_dict = export_vehicle_by_key if export_vehicle_by_key else dict_VehicleAxis
                for key, tmpVehicle in _sorted_vehicle_axis_items(source_dict):
                    tmpVehicle.write_Prog_Data(cur, con)
                cur.close()
                con.close()
            else:
                with open(CSV_BO_PROGNOSE_OUT, "w", newline="", encoding="utf-8-sig") as csvfile:
                    writer = csv.writer(csvfile, delimiter=";")
                    writer.writerow(_PROGNOSE_CSV_HEADER)
                    source_dict = export_vehicle_by_key if export_vehicle_by_key else dict_VehicleAxis
                    for key, tmpVehicle in _sorted_vehicle_axis_items(source_dict):
                        for zeile in tmpVehicle.iter_prognose_insert_tuples():
                            writer.writerow(
                                [_prognose_csv_zelle(i, z) for i, z in enumerate(zeile)]
                            )
                print(f"Prognose-CSV geschrieben: {CSV_BO_PROGNOSE_OUT}")
                logging.info("Prognose-CSV geschrieben: %s", CSV_BO_PROGNOSE_OUT)
    
    logging.info("=== Radsatz_Bahn_DB_new_Approach beendet ===")


if __name__ == "__main__":
    main()
