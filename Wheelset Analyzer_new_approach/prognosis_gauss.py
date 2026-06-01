"""
Gauss-Newton-Prognose (VehicleAxis.CalcPrognostic) mit IQR-Vorfilter und
gelernten Reprofilierungsparametern pro Achse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from MeterList import MeterList
from VehicleAxis import VehicleAxis
from prognosis_new_core import (
    QUALITY_INSUFFICIENT,
    QUALITY_OK,
    _PrognResult,
    _fit_theilsen,
    _outlier_filter_iqr,
    get_prognosis_params,
)
from reprof_learning import get_reprofiling_params
from radsatz_settings import PROGNOSIS_METHOD_GAUSS, RadsatzConfig
from toolsWheelset import getStartIndexLastCycle


def uses_gauss_prognosis(cfg: RadsatzConfig) -> bool:
    return cfg.prognosis_method == PROGNOSIS_METHOD_GAUSS


@dataclass(frozen=True)
class GaussPrognosisResult:
    ok: bool
    n_km_repro: float = 0.0
    n_value_repro: float = 0.0


def _iqr_mask(km: np.ndarray, lkd: np.ndarray, iqr_factor: float) -> np.ndarray:
    if len(km) < 3:
        return np.ones(len(km), dtype=bool)
    try:
        coeffs = np.polyfit(km, lkd, 1)
    except (np.linalg.LinAlgError, ValueError):
        return np.ones(len(km), dtype=bool)
    residuals = lkd - np.polyval(coeffs, km)
    q25, q75 = np.percentile(residuals, [25, 75])
    iqr = q75 - q25
    if iqr == 0:
        return np.ones(len(km), dtype=bool)
    return np.abs(residuals) <= iqr_factor * iqr


def _filter_list_tail(lst: List, n_index: int, mask: np.ndarray) -> List:
    tail = lst[n_index:]
    return lst[:n_index] + [v for v, keep in zip(tail, mask) if keep]


def filter_meter_cycle_iqr(
    met: MeterList,
    n_index: int,
    iqr_factor: float,
    axis_key: str,
) -> int:
    """IQR auf Zyklusdaten (ab n_index); parallele Listen werden synchron gefiltert."""
    km = np.asarray(met.getkm()[n_index:], dtype=float)
    lkd = np.asarray(met.getvalues()[n_index:], dtype=float)
    if len(km) < 3:
        return len(km)
    km_c, _, n_removed = _outlier_filter_iqr(km, lkd, iqr_factor, axis_key)
    if n_removed == 0:
        return len(km_c)
    mask = _iqr_mask(km, lkd, iqr_factor)
    met.setkm(_filter_list_tail(met.getkm(), n_index, mask))
    met.setvalues(_filter_list_tail(met.getvalues(), n_index, mask))
    if len(met.getnDates()) == len(km) + n_index:
        met.setnDates(_filter_list_tail(met.getnDates(), n_index, mask))
    if len(met.getstrDates()) == len(km) + n_index:
        met.setstrDates(_filter_list_tail(met.getstrDates(), n_index, mask))
    if len(met.getmin()) == len(km) + n_index:
        met.setmin(_filter_list_tail(met.getmin(), n_index, mask))
    if len(met.getmax()) == len(km) + n_index:
        met.setmax(_filter_list_tail(met.getmax(), n_index, mask))
    if len(met.getgelb_min()) == len(km) + n_index:
        met.setgelb_min(_filter_list_tail(met.getgelb_min(), n_index, mask))
    return len(km_c)


def reprof_km_value_for_axis(cfg: RadsatzConfig, vehicle_key: str) -> Tuple[float, float]:
    rp = get_reprofiling_params(vehicle_key + "_LKD1")
    n_km = float(cfg.n_km_repro)
    n_val = float(cfg.n_value_repro)
    if rp is not None:
        if rp.typical_interval_km > 0:
            n_km = float(rp.typical_interval_km)
        if rp.typical_magnitude_mm > 0:
            n_val = float(rp.typical_magnitude_mm)
    return n_km, n_val


def run_gauss_prognosis_for_vehicle(
    vehicle: VehicleAxis,
    vehicle_key: str,
    cfg: RadsatzConfig,
) -> GaussPrognosisResult:
    """
    Zyklusgrenzen, IQR-Filter, Gauss-Newton-Fit für LKD1 und LKD2.
    Schreibt Prognosekurven in die MeterList-Objekte (wie CalcPrognostic).
    """
    m1 = vehicle.getmeterList1()
    m2 = vehicle.getmeterList2()
    iqr = cfg.progn_new_iqr_factor
    def_param_exp = list(cfg.def_param_exp)

    n1 = getStartIndexLastCycle(m1.getkm(), m1.getvalues(), cfg.diff_lkd)
    n2 = getStartIndexLastCycle(m2.getkm(), m2.getvalues(), cfg.diff_lkd)
    m1.setindexStartLastCycle(n1)
    m2.setindexStartLastCycle(n2)

    n_pts1 = filter_meter_cycle_iqr(m1, n1, iqr, vehicle_key + "_LKD1")
    n_pts2 = filter_meter_cycle_iqr(m2, n2, iqr, vehicle_key + "_LKD2")
    if n_pts1 < 2 or n_pts2 < 2:
        logging.warning(
            "Gauss: nach IQR zu wenig Zykluspunkte (LKD1=%d, LKD2=%d): %s",
            n_pts1,
            n_pts2,
            vehicle_key,
        )
        return GaussPrognosisResult(ok=False)

    n_km_repro, n_val_repro = reprof_km_value_for_axis(cfg, vehicle_key)

    vehicle.calcDaysPerKm()
    vehicle.CalcPrognostic(
        1,
        cfg.def_jump_repro,
        def_param_exp,
        cfg.n_km,
        n_km_repro,
        n_val_repro,
    )
    vehicle.CalcPrognostic(
        2,
        cfg.def_jump_repro,
        def_param_exp,
        cfg.n_km,
        n_km_repro,
        n_val_repro,
    )
    vehicle.calcnDatesProg()

    ok = bool(m1.getkmProg() and m2.getkmProg())
    return GaussPrognosisResult(
        ok=ok,
        n_km_repro=n_km_repro,
        n_value_repro=n_val_repro,
    )


def _slopes_for_plot_ki(met: MeterList) -> Tuple[float, float, float]:
    """Theil-Sen auf Zyklusdaten nur für KI-Band im Plot (wie Theil-Sen-Reprof-Zweig)."""
    n_idx = max(0, met.getindexStartLastCycle())
    km = np.asarray(met.getkm()[n_idx:], dtype=float)
    lkd = np.asarray(met.getvalues()[n_idx:], dtype=float)
    if len(km) < 2:
        return 0.0, 0.0, 0.0
    prm = get_prognosis_params()
    if len(km) >= max(2, prm.min_points_fit):
        try:
            slope, _, slope_low, slope_high, _ = _fit_theilsen(km, lkd, prm.ci_alpha)
            return slope, slope_low, slope_high
        except Exception:
            pass
    coeffs = np.polyfit(km, lkd, 1)
    slope = float(coeffs[0])
    return slope, slope, slope


def progn_result_for_plot_from_gauss_meter(met: MeterList) -> _PrognResult:
    """
    _PrognResult-Hülle für _plot_axis: gleiche Kurven-/Annotation-Logik wie Theil-Sen
    (Reprof-Kurve = kmProg, Schwellen aus CalcPrognostic).
    """
    km_prog = list(met.getkmProg() or [])
    lkd_prog = list(met.getvaluesProg() or [])
    if not km_prog or not lkd_prog:
        return _PrognResult(
            quality=QUALITY_INSUFFICIENT,
            model="gauss",
            n_points_fit=0,
            n_outliers=0,
            cycle_source="gauss",
            slope=0.0,
            slope_low=0.0,
            slope_high=0.0,
            days_per_km=0.0,
            km_warn=None,
            km_limit=None,
            km_warn_conservative=None,
            km_limit_conservative=None,
        )

    slope, slope_low, slope_high = _slopes_for_plot_ki(met)
    gelb_km = met.getgelb_min_Prog_km()
    min_km = met.getmin_Prog_km()
    gelb_km_f = float(gelb_km) if gelb_km and gelb_km > 0 else None
    min_km_f = float(min_km) if min_km and min_km > 0 else None
    n_idx = max(0, met.getindexStartLastCycle())
    n_fit = len(met.getkm()) - n_idx

    return _PrognResult(
        quality=QUALITY_OK,
        model="gauss",
        n_points_fit=n_fit,
        n_outliers=0,
        cycle_source="gauss",
        slope=slope,
        slope_low=slope_low,
        slope_high=slope_high,
        days_per_km=0.0,
        km_warn=gelb_km_f,
        km_limit=min_km_f,
        km_warn_conservative=gelb_km_f,
        km_limit_conservative=min_km_f,
        km_warn_reprof=gelb_km_f,
        km_limit_reprof=min_km_f,
        km_prog_reprof=km_prog,
        lkd_prog_reprof=lkd_prog,
        prog_curve_uses_reprof=True,
    )
