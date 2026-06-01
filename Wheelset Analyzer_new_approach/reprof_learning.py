"""
reprof_learning.py

Datengetriebenes Lernen von Reprofilierungs-Parametern.

- learn_reprofiling_params_per_axis: je VehicleAxis (LKD1 + LKD2 gemeinsam);
  bei zu wenig Daten: Median der erfolgreich gelernten Achsen
- learn_reprofiling_params: Flotten-Schätzung (nur noch Logging/Vergleich)
- reprofiling_params_from_radsatz_config: Fallback aus radsatz_config.ini
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True)
class ReprofilingParams:
    """Gelernte Schwellwerte zur Erkennung von Reprofilierungsereignissen."""

    dkm_threshold: float
    dlkd_abs_min: float
    typical_interval_km: float
    typical_magnitude_mm: float
    n_detected: int
    learned: bool

    def __str__(self) -> str:
        mode = "gelernt" if self.learned else "Fallback"
        return (
            f"ReprofilingParams ({mode}): "
            f"dkm_threshold={self.dkm_threshold:.0f} km, "
            f"dlkd_abs_min={self.dlkd_abs_min:.2f} mm, "
            f"typ.Intervall={self.typical_interval_km:.0f} km, "
            f"typ.Größe={self.typical_magnitude_mm:.1f} mm, "
            f"n_erkannt={self.n_detected}"
        )


_FALLBACK_PARAMS = ReprofilingParams(
    dkm_threshold=5000.0,
    dlkd_abs_min=3.0,
    typical_interval_km=100_000.0,
    typical_magnitude_mm=8.0,
    n_detected=0,
    learned=False,
)

_active_reprof_by_axis: Dict[str, ReprofilingParams] = {}
_fleet_fallback: Optional[ReprofilingParams] = None


def vehicle_axis_key_from_meter_key(meter_axis_key: str) -> str:
    """'Fahrzeug…_LKD1' → Schlüssel wie in dict_VehicleAxis."""
    if meter_axis_key.endswith("_LKD1"):
        return meter_axis_key[:-5]
    if meter_axis_key.endswith("_LKD2"):
        return meter_axis_key[:-5]
    return meter_axis_key


def get_reprofiling_params(meter_axis_key: Optional[str] = None) -> Optional[ReprofilingParams]:
    """
    Parameter für eine Achse (über meter_axis_key mit _LKD1/_LKD2-Suffix)
    oder Flotten-Fallback, wenn für die Achse nichts Gelerntes vorliegt.
    """
    if meter_axis_key is not None:
        vk = vehicle_axis_key_from_meter_key(meter_axis_key)
        per_axis = _active_reprof_by_axis.get(vk)
        if per_axis is not None:
            return per_axis
    return _fleet_fallback


def reprofiling_params_from_radsatz_config(cfg) -> ReprofilingParams:
    """Standard-Reprofilierung aus [prognose] in radsatz_config.ini."""
    return ReprofilingParams(
        dkm_threshold=float(cfg.reprof_dkm_threshold),
        dlkd_abs_min=float(cfg.reprof_dlkd_abs_min),
        typical_interval_km=float(cfg.n_km_repro),
        typical_magnitude_mm=float(cfg.n_value_repro),
        n_detected=0,
        learned=False,
    )


def set_reprofiling_params(p: ReprofilingParams) -> None:
    """Nur Flotten-Fallback setzen (Abwärtskompatibilität)."""
    global _fleet_fallback
    _fleet_fallback = p


def set_reprofiling_params_per_axis(
    per_axis: Dict[str, ReprofilingParams],
    fleet_fallback: Optional[ReprofilingParams] = None,
) -> None:
    """Pro-Achse-Parameter und optionalen Flotten-Fallback registrieren."""
    global _active_reprof_by_axis, _fleet_fallback
    _active_reprof_by_axis = dict(per_axis)
    if fleet_fallback is not None:
        _fleet_fallback = fleet_fallback


def is_reprofiling(dkm: float, dlkd: float, params: ReprofilingParams) -> bool:
    if dlkd >= 0.0:
        return False
    return dkm <= params.dkm_threshold and (-dlkd) >= params.dlkd_abs_min


def _sorted_km_lkd(met) -> Tuple[np.ndarray, np.ndarray]:
    km_arr = np.array(met.getkm(), dtype=float)
    lkd_arr = np.array(met.getvalues(), dtype=float)
    if len(km_arr) < 2:
        return km_arr, lkd_arr
    order = np.argsort(km_arr)
    return km_arr[order], lkd_arr[order]


def _collect_negative_steps(km_arr: np.ndarray, lkd_arr: np.ndarray) -> Tuple[List[float], List[float]]:
    neg_dkm: List[float] = []
    neg_drop: List[float] = []
    if len(km_arr) < 2:
        return neg_dkm, neg_drop
    dkm = np.diff(km_arr)
    dlkd = np.diff(lkd_arr)
    for i in range(len(dkm)):
        if dkm[i] < 0.0:
            continue
        if dlkd[i] < 0.0:
            neg_dkm.append(float(dkm[i]))
            neg_drop.append(float(-dlkd[i]))
    return neg_dkm, neg_drop


def _intervals_from_series(
    km_arr: np.ndarray,
    lkd_arr: np.ndarray,
    dkm_threshold: float,
    dlkd_abs_min: float,
) -> List[float]:
    if len(km_arr) < 3:
        return []
    repro_km: List[float] = []
    dkm = np.diff(km_arr)
    dlkd = np.diff(lkd_arr)
    for i in range(len(dkm)):
        if dkm[i] >= 0.0 and dlkd[i] < 0.0:
            if dkm[i] <= dkm_threshold and (-dlkd[i]) >= dlkd_abs_min:
                repro_km.append(float(km_arr[i + 1]))
    if len(repro_km) < 2:
        return []
    return np.diff(np.array(repro_km, dtype=float)).tolist()


def _fit_reprof_params(
    neg_dkm: Sequence[float],
    neg_drop: Sequence[float],
    interval_sources: Sequence[Tuple[np.ndarray, np.ndarray]],
    min_seeds: int,
    seed_dkm_max: float = 2000.0,
    seed_dlkd_min_abs: float = 2.0,
    log_label: str = "",
) -> Optional[ReprofilingParams]:
    if not neg_dkm:
        return None

    dkm_arr = np.asarray(neg_dkm, dtype=float)
    drop_arr = np.asarray(neg_drop, dtype=float)

    seed_mask = (dkm_arr <= seed_dkm_max) & (drop_arr >= seed_dlkd_min_abs)
    n_seeds = int(np.sum(seed_mask))
    if n_seeds < min_seeds:
        return None

    seed_dkm_vals = dkm_arr[seed_mask]
    seed_drop_vals = drop_arr[seed_mask]

    dkm_threshold = float(np.percentile(seed_dkm_vals, 95))
    dkm_threshold = float(np.clip(dkm_threshold, seed_dkm_max, seed_dkm_max * 5.0))
    dlkd_abs_min = float(np.percentile(seed_drop_vals, 25))
    dlkd_abs_min = max(dlkd_abs_min, seed_dlkd_min_abs)

    repro_mask = (dkm_arr <= dkm_threshold) & (drop_arr >= dlkd_abs_min)
    n_detected = int(np.sum(repro_mask))
    if n_detected < min_seeds:
        return None

    typical_magnitude_mm = float(np.median(drop_arr[repro_mask]))

    intervals: List[float] = []
    for km_arr, lkd_arr in interval_sources:
        intervals.extend(_intervals_from_series(km_arr, lkd_arr, dkm_threshold, dlkd_abs_min))
    typical_interval_km = float(np.median(intervals)) if intervals else 0.0

    if log_label:
        logging.info(
            "Reprofilierung %s: dkm_thr=%.0f dlkd_min=%.2f typ.Int=%.0f typ.Gr=%.1f n=%d",
            log_label,
            dkm_threshold,
            dlkd_abs_min,
            typical_interval_km,
            typical_magnitude_mm,
            n_detected,
        )

    return ReprofilingParams(
        dkm_threshold=dkm_threshold,
        dlkd_abs_min=dlkd_abs_min,
        typical_interval_km=typical_interval_km,
        typical_magnitude_mm=typical_magnitude_mm,
        n_detected=n_detected,
        learned=True,
    )


def _meter_series_list(vehicle) -> List[Tuple[np.ndarray, np.ndarray]]:
    series: List[Tuple[np.ndarray, np.ndarray]] = []
    for met_getter in (vehicle.getmeterList1, vehicle.getmeterList2):
        km, lkd = _sorted_km_lkd(met_getter())
        if len(km) >= 2:
            series.append((km, lkd))
    return series


def _median_reprof_params(
    learned: Sequence[ReprofilingParams],
    ini_fallback: Optional[ReprofilingParams] = None,
) -> ReprofilingParams:
    """Median über alle Felder der erfolgreich gelernten Achsen."""
    if not learned:
        return ini_fallback if ini_fallback is not None else _FALLBACK_PARAMS
    return ReprofilingParams(
        dkm_threshold=float(np.median([p.dkm_threshold for p in learned])),
        dlkd_abs_min=float(np.median([p.dlkd_abs_min for p in learned])),
        typical_interval_km=float(np.median([p.typical_interval_km for p in learned])),
        typical_magnitude_mm=float(np.median([p.typical_magnitude_mm for p in learned])),
        n_detected=0,
        learned=False,
    )


def learn_reprofiling_params_for_vehicle(
    vehicle,
    min_seeds: int = 3,
    seed_dkm_max: float = 2000.0,
    seed_dlkd_min_abs: float = 2.0,
    log_label: str = "",
) -> Optional[ReprofilingParams]:
    """Lernen aus beiden Zählern einer VehicleAxis."""
    neg_dkm: List[float] = []
    neg_drop: List[float] = []
    interval_sources: List[Tuple[np.ndarray, np.ndarray]] = []

    for km, lkd in _meter_series_list(vehicle):
        interval_sources.append((km, lkd))
        dkm_part, drop_part = _collect_negative_steps(km, lkd)
        neg_dkm.extend(dkm_part)
        neg_drop.extend(drop_part)

    return _fit_reprof_params(
        neg_dkm,
        neg_drop,
        interval_sources,
        min_seeds=min_seeds,
        seed_dkm_max=seed_dkm_max,
        seed_dlkd_min_abs=seed_dlkd_min_abs,
        log_label=log_label,
    )


def learn_reprofiling_params_per_axis(
    dict_VehicleAxis: Dict,
    ini_fallback: Optional[ReprofilingParams] = None,
    fleet_fallback: Optional[ReprofilingParams] = None,
    min_seeds_per_axis: int = 3,
) -> Dict[str, ReprofilingParams]:
    """
    Je Eintrag in dict_VehicleAxis eigene Reprofilierungsparameter.

    Fallback-Reihenfolge:
      1. individuell gelernt
      2. Median der erfolgreich gelernten Achsen
      3. ini_fallback (radsatz_config.ini) bzw. fleet_fallback (veraltet, gleiche Rolle)
    """
    if ini_fallback is None:
        ini_fallback = fleet_fallback
    if ini_fallback is None:
        ini_fallback = _FALLBACK_PARAMS

    per_axis: Dict[str, ReprofilingParams] = {}
    learned_ok: List[ReprofilingParams] = []
    failed_keys: List[Tuple[str, str]] = []

    for axis_key, vehicle in dict_VehicleAxis.items():
        label = f"{vehicle.getstrVDesc()} | {vehicle.getstrBogie()} | {vehicle.getstrPosAxis()}"
        learned = learn_reprofiling_params_for_vehicle(
            vehicle,
            min_seeds=min_seeds_per_axis,
            log_label=label,
        )
        if learned is not None and learned.typical_interval_km > 0 and learned.typical_magnitude_mm > 0:
            per_axis[axis_key] = learned
            learned_ok.append(learned)
        else:
            failed_keys.append((axis_key, label))

    if learned_ok:
        median_params = _median_reprof_params(learned_ok, ini_fallback=ini_fallback)
        logging.info(
            "Reprofilierung Median (%d Achsen): dkm_thr=%.0f dlkd_min=%.2f "
            "typ.Int=%.0f typ.Gr=%.1f",
            len(learned_ok),
            median_params.dkm_threshold,
            median_params.dlkd_abs_min,
            median_params.typical_interval_km,
            median_params.typical_magnitude_mm,
        )
        for axis_key, label in failed_keys:
            per_axis[axis_key] = median_params
            logging.info(
                "Reprofilierung %s: zu wenig Daten → Median anderer Achsen",
                label,
            )
    else:
        for axis_key, label in failed_keys:
            per_axis[axis_key] = ini_fallback
            logging.info(
                "Reprofilierung %s: kein Achsen-Lernen, kein Median → ini/Config",
                label,
            )
        logging.info(
            "Reprofilierung: keine Achse lernte → ini (%s)",
            ini_fallback,
        )

    logging.info(
        "Reprofilierung pro Achse: %d/%d individuell, %d per Median/ini",
        len(learned_ok),
        len(dict_VehicleAxis),
        len(failed_keys),
    )
    return per_axis


def learn_reprofiling_params(
    dict_VehicleAxis: Dict,
    seed_dkm_max: float = 2000.0,
    seed_dlkd_min_abs: float = 2.0,
    min_seeds: int = 5,
) -> ReprofilingParams:
    """Flottenweites Lernen über alle Achsen (Fallback / Vergleich)."""
    neg_dkm: List[float] = []
    neg_drop: List[float] = []
    interval_sources: List[Tuple[np.ndarray, np.ndarray]] = []

    for vehicle in dict_VehicleAxis.values():
        for km, lkd in _meter_series_list(vehicle):
            interval_sources.append((km, lkd))
            dkm_part, drop_part = _collect_negative_steps(km, lkd)
            neg_dkm.extend(dkm_part)
            neg_drop.extend(drop_part)

    if not neg_dkm:
        logging.warning(
            "Reprofilierungslernlauf (Flotte): keine negativen LKD-Schritte → Standardwerte."
        )
        return _FALLBACK_PARAMS

    params = _fit_reprof_params(
        neg_dkm,
        neg_drop,
        interval_sources,
        min_seeds=min_seeds,
        seed_dkm_max=seed_dkm_max,
        seed_dlkd_min_abs=seed_dlkd_min_abs,
        log_label="Flotte gesamt",
    )
    if params is None:
        logging.warning(
            "Reprofilierungslernlauf (Flotte): zu wenige Seeds → Standardwerte."
        )
        return _FALLBACK_PARAMS

    logging.info("Reprofilierungsparameter Flotte: %s", params)
    print(f"Reprofilierungsparameter (Flotte): {params}")
    return params
