"""
Kreuzvalidierung der LKD-Prognose im letzten Zyklus (expanding window).

Für jeden Messpunkt j ab min_points_fit: Trainingspräfix km[0:j], lkd[0:j] wird
IQR-gefiltert; darauf wird Theil-Sen (linear) gefittet und der LKD-Wert an km[j]
vorhergesagt. Der Fehler ist (y_hat - Ist-LKD[j]) in mm.

Optional: Gitter über iqr_factor und min_points_fit, Zielgrösse MAE oder RMSE
(siehe radsatz_config.ini [prognose_new] cv_tune_*).
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from dataclasses import replace
from typing import Dict, List, Tuple

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from datetime2matlabdn import datetime2matlabdn
from MeterList import MeterList
from VehicleAxis import VehicleAxis
from prognosis_new_core import PrognosisParams, _fit_theilsen, _outlier_filter_iqr
from radsatz_csv_io import load_bo_radsatz_from_csv
from radsatz_settings import RadsatzConfig, load_radsatz_config
from toolsWheelset import getStartIndexLastCycle


def _build_vehicle_dict(res1, res2):
    dict_v: Dict[str, VehicleAxis] = {}
    for str_vehicle in res1:
        dict_v[str_vehicle[0] + str_vehicle[1] + str_vehicle[2]] = VehicleAxis(
            str_vehicle[0], str_vehicle[1], str_vehicle[2],
            MeterList([], [], [], [], [], [], []),
            MeterList([], [], [], [], [], [], []),
        )
    if not res2:
        return dict_v
    for r in res2:
        axis_key = r[0] + r[1] + r[2]
        t_vehicle = dict_v.get(axis_key)
        if t_vehicle is None:
            continue
        if None in (r[4], r[5], r[6], r[7], r[8], r[9]):
            continue
        met = t_vehicle.getmeterList1() if r[3] == "Rad-Laufkreisdurchmesser-1" else t_vehicle.getmeterList2()
        met.getstrDates().append(r[4])
        met.getvalues().append(r[5])
        met.getkm().append(r[6])
        met.getmin().append(r[7])
        met.getmax().append(r[8])
        met.getgelb_min().append(r[9])
        met.setzaehlerartid(r[18])
        met.setzartbez(r[3])
        t_vehicle.settopeinheitid(r[10])
        t_vehicle.setdgeinheitid(r[11])
        t_vehicle.setdgbezeichnung(r[12])
        t_vehicle.setrseinheitid(r[13])
        t_vehicle.setrsbezeichnung(r[14])
        t_vehicle.seteinbau(r[15])
        t_vehicle.setausbau(r[16])
        t_vehicle.setaktuell(r[17])

    for _key, tmp_vehicle in dict_v.items():
        for met in (tmp_vehicle.getmeterList1(), tmp_vehicle.getmeterList2()):
            dates = met.getstrDates()
            if len(dates) > 1:
                met.setnDates([datetime2matlabdn(d) for d in dates])
            else:
                met.setnDates([])

    return dict_v


def expanding_window_cv_errors(
    km_cycle: np.ndarray,
    lkd_cycle: np.ndarray,
    axis_key: str,
    params: PrognosisParams,
) -> np.ndarray:
    """Fehler in mm pro erfolgreicher Faltung (signed: y_hat - y_true)."""
    errs: List[float] = []
    n = int(len(km_cycle))
    mp = params.min_points_fit
    for j in range(mp, n):
        km_p = km_cycle[:j]
        lkd_p = lkd_cycle[:j]
        k_j = float(km_cycle[j])
        y_j = float(lkd_cycle[j])
        km_c, lkd_c, _ = _outlier_filter_iqr(
            km_p, lkd_p, params.iqr_factor, f"{axis_key}_cv_j{j}",
        )
        if len(km_c) < mp:
            continue
        slope, intercept, _, _, _ = _fit_theilsen(km_c, lkd_c, params.ci_alpha)
        y_hat = slope * k_j + intercept
        errs.append(y_hat - y_j)
    return np.asarray(errs, dtype=float)


def aggregate_cv_metrics(
    dict_v: Dict[str, VehicleAxis],
    diff_lkd: float,
    params: PrognosisParams,
    verbose: bool = False,
) -> Tuple[int, int, float, float]:
    """
    Aggregiert CV über alle Achsen/Zähler (letzter Zyklus).
    Rückgabe: (n_axes_mit_folds, n_folds_gesamt, mae, rmse).
    """
    all_errs: List[float] = []
    n_axes_used = 0
    n_folds = 0
    mp = params.min_points_fit
    for key, tmp_vehicle in dict_v.items():
        for label, met in (
            ("LKD1", tmp_vehicle.getmeterList1()),
            ("LKD2", tmp_vehicle.getmeterList2()),
        ):
            if len(met.getstrDates()) <= 1:
                continue
            n_idx = getStartIndexLastCycle(met.getkm(), met.getvalues(), diff_lkd)
            km_all = np.array(met.getkm(), dtype=float)
            lkd_all = np.array(met.getvalues(), dtype=float)
            km_cy = km_all[n_idx:]
            lkd_cy = lkd_all[n_idx:]
            sort_idx = np.argsort(km_cy)
            km_cy = km_cy[sort_idx]
            lkd_cy = lkd_cy[sort_idx]
            if len(km_cy) <= mp:
                continue
            axis_key = f"{key}_{label}"
            e = expanding_window_cv_errors(km_cy, lkd_cy, axis_key, params)
            if e.size == 0:
                continue
            n_axes_used += 1
            n_folds += int(e.size)
            all_errs.extend(e.tolist())
            if verbose:
                mae_ax = float(np.mean(np.abs(e)))
                rmse_ax = float(np.sqrt(np.mean(e ** 2)))
                logging.info(
                    "CV %s: n_cycle=%d folds=%d MAE=%.3f mm RMSE=%.3f mm",
                    axis_key, len(km_cy), e.size, mae_ax, rmse_ax,
                )
    if not all_errs:
        return 0, 0, float("nan"), float("nan")
    arr = np.asarray(all_errs, dtype=float)
    mae = float(np.mean(np.abs(arr)))
    rmse = float(np.sqrt(np.mean(arr ** 2)))
    return n_axes_used, n_folds, mae, rmse


def tune_prognosis_params_by_cv(
    dict_v: Dict[str, VehicleAxis],
    cfg: RadsatzConfig,
) -> Tuple[PrognosisParams, float, int]:
    """
    Gittersuche über cv_tune_iqr_factors x cv_tune_min_points_fit.
    Behält alle übrigen Felder aus cfg-basiertem PrognosisParams bei.
    Bei keinem Kandidaten mit genug Folds: Basisparameter unverändert.
    """
    from prognosis_new_core import prognosis_params_from_radsatz_config

    base = prognosis_params_from_radsatz_config(cfg)
    iqr_grid = list(cfg.progn_new_cv_tune_iqr_factors)
    mp_grid = list(cfg.progn_new_cv_tune_min_points_fit)
    objective = cfg.progn_new_cv_tune_objective
    min_folds = max(1, int(cfg.progn_new_cv_tune_min_total_folds))

    best = base
    best_score = float("inf")
    best_folds = 0
    best_mae = float("nan")
    best_rmse = float("nan")

    for iqr in iqr_grid:
        for mp in mp_grid:
            if mp < 3:
                continue
            cand = replace(base, iqr_factor=float(iqr), min_points_fit=int(mp))
            _n_ax, n_fd, mae, rmse = aggregate_cv_metrics(dict_v, cfg.diff_lkd, cand, verbose=False)
            if n_fd < min_folds:
                continue
            score = mae if objective == "mae" else rmse
            if math.isnan(score):
                continue
            if score < best_score:
                best_score = score
                best = cand
                best_folds = n_fd
                best_mae = mae
                best_rmse = rmse

    if best_folds == 0:
        logging.warning(
            "CV-Tuning: kein Gitterpunkt erfüllte cv_tune_min_total_folds=%d — "
            "Basisparameter aus [prognose_new] bleiben aktiv.",
            min_folds,
        )
        _n_ax, n_fd, mae, rmse = aggregate_cv_metrics(dict_v, cfg.diff_lkd, base, verbose=False)
        return base, (mae if objective == "mae" else rmse), n_fd

    logging.info(
        "CV-Tuning: gewählt iqr_factor=%.3f min_points_fit=%d | %s=%.4f mm "
        "(MAE=%.4f RMSE=%.4f, folds=%d, Ziel=%s)",
        best.iqr_factor,
        best.min_points_fit,
        objective,
        best_score,
        best_mae,
        best_rmse,
        best_folds,
        objective,
    )
    return best, best_score, best_folds


def run_crossval(
    csv_path: str,
    dt_start: str,
    diff_lkd: float,
    params: PrognosisParams,
    verbose: bool,
) -> Tuple[int, int, float, float]:
    res1, res2 = load_bo_radsatz_from_csv(csv_path, dt_start)
    dict_v = _build_vehicle_dict(res1, res2)
    return aggregate_cv_metrics(dict_v, diff_lkd, params, verbose=verbose)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kreuzvalidierung LKD (Theil-Sen, expanding window).")
    parser.add_argument(
        "--csv",
        default=None,
        help="Pfad zu BO_RADSATZDATEN-CSV (Standard: csv_bo_radsatzdaten aus radsatz_config.ini)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Pro Achse MAE/RMSE ausgeben.",
    )
    args = parser.parse_args()

    cfg = load_radsatz_config(SCRIPT_DIR)
    from prognosis_new_core import prognosis_params_from_radsatz_config, set_prognosis_params

    set_prognosis_params(prognosis_params_from_radsatz_config(cfg))
    params = prognosis_params_from_radsatz_config(cfg)

    csv_path = args.csv or cfg.csv_bo_radsatzdaten
    if not os.path.isfile(csv_path):
        raise SystemExit(f"CSV nicht gefunden: {csv_path}")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    n_ax, n_fd, mae, rmse = run_crossval(
        csv_path, cfg.dt_start_data, cfg.diff_lkd, params, args.verbose,
    )
    print("Kreuzvalidierung (expanding window, Theil-Sen linear, IQR auf Praefix)")
    print(f"  CSV: {csv_path}")
    print(f"  iqr_factor={params.iqr_factor} min_points_fit={params.min_points_fit}")
    print(f"  Achsen mit mindestens einem CV-Falt: {n_ax}")
    print(f"  Summe Einzelfehler (Messungen):     {n_fd}")
    if n_fd:
        print(f"  MAE (|Fehler|):  {mae:.4f} mm")
        print(f"  RMSE (Fehler):   {rmse:.4f} mm")
    else:
        print("  Keine auswertbaren Fälle (zu wenige Punkte pro Zyklus).")


if __name__ == "__main__":
    main()
