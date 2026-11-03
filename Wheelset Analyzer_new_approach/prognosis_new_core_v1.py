"""
Gemeinsamer Kern: IQR-Filter, Theil-Sen, optional Power-Law, Zyklus-Prognose (MeterList).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

try:
    from scipy.stats import theilslopes
    from scipy.optimize import curve_fit as _scipy_curve_fit
except ImportError as _exc:
    raise ImportError(
        "scipy nicht gefunden. Installiere mit: python -m pip install scipy"
    ) from _exc

from MeterList import MeterList
from reprof_learning import ReprofilingParams, get_reprofiling_params, is_reprofiling
from dates_np import NAT, add_days, days_to_timedelta64, is_nat, timedelta64_to_days


@dataclass(frozen=True)
class PrognosisParams:
    """Einstellbare Parameter für IQR-/Theil-Sen-/Power-Law-Prognose."""

    min_points_fit: int = 4
    min_points_quality: int = 8
    iqr_factor: float = 2.0
    ci_alpha: float = 0.90
    rmse_threshold_mm: float = 0.5
    n_prog_points: int = 20


DEFAULT_PROGNOSIS_PARAMS = PrognosisParams()
_active_params: PrognosisParams = DEFAULT_PROGNOSIS_PARAMS


def get_prognosis_params() -> PrognosisParams:
    return _active_params


def set_prognosis_params(p: PrognosisParams) -> None:
    global _active_params
    _active_params = p


def prognosis_params_from_radsatz_config(cfg: "RadsatzConfig") -> PrognosisParams:
    """Baut PrognosisParams aus dem geladenen RadsatzConfig."""
    return PrognosisParams(
        min_points_fit=cfg.progn_new_min_points_fit,
        min_points_quality=cfg.progn_new_min_points_quality,
        iqr_factor=cfg.progn_new_iqr_factor,
        ci_alpha=cfg.progn_new_ci_alpha,
        rmse_threshold_mm=cfg.progn_new_rmse_threshold_mm,
        n_prog_points=cfg.progn_new_n_prog_points,
    )


# Rückwärtskompatibel: Werte entsprechen DEFAULT_PROGNOSIS_PARAMS (nach Tuning get_prognosis_params() nutzen).
MIN_POINTS_FIT = DEFAULT_PROGNOSIS_PARAMS.min_points_fit
MIN_POINTS_QUALITY = DEFAULT_PROGNOSIS_PARAMS.min_points_quality
IQR_FACTOR = DEFAULT_PROGNOSIS_PARAMS.iqr_factor
CI_ALPHA = DEFAULT_PROGNOSIS_PARAMS.ci_alpha
RMSE_THRESHOLD_MM = DEFAULT_PROGNOSIS_PARAMS.rmse_threshold_mm
N_PROG_POINTS = DEFAULT_PROGNOSIS_PARAMS.n_prog_points

QUALITY_OK = "OK"
QUALITY_LOW = "LOW"
QUALITY_INSUFFICIENT = "INSUFFICIENT"


@dataclass
class _PrognResult:
    """Zwischenergebnis der Prognoseberechnung für eine Zählerliste."""
    quality: str
    model: str
    n_points_fit: int
    n_outliers: int
    cycle_source: str
    slope: float
    slope_low: float
    slope_high: float
    days_per_km: float
    km_warn: Optional[float]
    km_limit: Optional[float]
    km_warn_conservative: Optional[float]
    km_limit_conservative: Optional[float]
    # Szenario "mit Reprofilierung" (None/[] wenn nicht berechenbar)
    km_warn_reprof: Optional[float] = None
    km_limit_reprof: Optional[float] = None
    km_prog_reprof: list = field(default_factory=list)
    lkd_prog_reprof: list = field(default_factory=list)
    """True, wenn kmProg/valuesProg/nDatesProg aus dem Reprof-Szenario stammen."""
    prog_curve_uses_reprof: bool = False


def _outlier_filter_iqr(
    km: np.ndarray,
    lkd: np.ndarray,
    iqr_factor: float,
    axis_key: str,
) -> Tuple[np.ndarray, np.ndarray, int]:
    if len(km) < 3:
        return km, lkd, 0
    try:
        coeffs = np.polyfit(km, lkd, 1)
    except (np.linalg.LinAlgError, ValueError):
        logging.warning("IQR-Filter: polyfit fehlgeschlagen für %s, Filter übersprungen", axis_key)
        return km, lkd, 0
    residuals = lkd - np.polyval(coeffs, km)
    q25, q75 = np.percentile(residuals, [25, 75])
    iqr = q75 - q25
    if iqr == 0:
        return km, lkd, 0
    mask = np.abs(residuals) <= iqr_factor * iqr
    n_removed = int(np.sum(~mask))
    if n_removed > 0:
        logging.info(
            "IQR-Filter: %d Ausreißer entfernt (IQR=%.3f, Faktor=%.1f) für %s",
            n_removed, iqr, iqr_factor, axis_key,
        )
    return km[mask], lkd[mask], n_removed


def _fit_theilsen(
    km: np.ndarray,
    lkd: np.ndarray,
    ci_alpha: float,
) -> Tuple[float, float, float, float, float]:
    result = theilslopes(y=lkd, x=km, alpha=ci_alpha)
    slope = float(result.slope)
    intercept = float(result.intercept)
    slope_low = float(result.low_slope)
    slope_high = float(result.high_slope)
    residuals = lkd - (slope * km + intercept)
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    return slope, intercept, slope_low, slope_high, rmse


def _fit_powerlaw(
    km: np.ndarray,
    lkd: np.ndarray,
    last_km: float,
    last_lkd: float,
) -> Optional[Tuple[float, float, float]]:
    km_shifted = km - last_km

    def _model(x, b, c):
        return last_lkd - b * np.abs(x) ** c

    try:
        with np.errstate(all="ignore"):
            popt, _ = _scipy_curve_fit(
                _model, km_shifted, lkd,
                p0=[1e-5, 1.0],
                bounds=([0, 0.1], [1.0, 3.0]),
                maxfev=2000,
            )
        b, c = float(popt[0]), float(popt[1])
        residuals = lkd - _model(km_shifted, b, c)
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        return b, c, rmse
    except Exception:
        return None


def _km_threshold_linear(
    last_km: float,
    last_lkd: float,
    slope: float,
    y_thresh: float,
) -> Optional[float]:
    if slope >= 0:
        return None
    rest_km = (last_lkd - y_thresh) / (-slope)
    if rest_km <= 0:
        return None
    return last_km + rest_km


def _km_threshold_powerlaw(
    last_km: float,
    last_lkd: float,
    b: float,
    c: float,
    y_thresh: float,
) -> Optional[float]:
    if b <= 0 or c <= 0:
        return None
    delta_lkd = last_lkd - y_thresh
    if delta_lkd <= 0:
        return None
    try:
        rest_km = (delta_lkd / b) ** (1.0 / c)
        return last_km + rest_km
    except Exception:
        return None


def _find_last_reprofiling_in_cycle(
    km: np.ndarray,
    lkd: np.ndarray,
    params: ReprofilingParams,
) -> Optional[int]:
    """
    Sucht den letzten Reprofilierungssprung im Zyklus.

    Gibt Index i zurück, bei dem der Sprung zwischen km[i] und km[i+1] liegt.
    None wenn kein Sprung gefunden.
    """
    last_idx: Optional[int] = None
    for i in range(len(km) - 1):
        dkm = float(km[i + 1] - km[i])
        dlkd = float(lkd[i + 1] - lkd[i])
        if is_reprofiling(dkm, dlkd, params):
            last_idx = i
    return last_idx


def _calc_days_per_km_robust(
    km_cycle: np.ndarray,
    date_cycle: np.ndarray,
    axis_key: str,
) -> float:
    """date_cycle als np.ndarray[datetime64[s]] erwartet → liefert Tage/km als float."""
    dk = km_cycle[1:] - km_cycle[:-1]
    # Differenz zweier datetime64 → timedelta64, dann in Tage als float
    dd = timedelta64_to_days(np.diff(date_cycle))
    valid = dk > 0
    if not np.any(valid):
        logging.warning("daysPerKm: keine gültigen Paare für %s, nutze Standardwert", axis_key)
        return 0.01
    rates = dd[valid] / dk[valid]
    dpkm = float(np.median(rates))
    if dpkm <= 0:
        logging.warning(
            "daysPerKm: negativer Medianwert (%.4f) für %s, nutze Standardwert", dpkm, axis_key
        )
        return 0.01
    return dpkm


def _simulate_with_reprofilings(
    last_km: float,
    last_lkd: float,
    slope: float,
    reprof_interval_km: float,
    reprof_magnitude_mm: float,
    gelb_min: float,
    min_val: float,
    n_km_horizon: float,
    n_pts_per_segment: int = 5,
) -> Tuple[list, list, Optional[float], Optional[float]]:
    """
    Simuliert den LKD-Verlauf mit periodisch geplanten Reprofilierungen.

    An jedem Vielfachen von reprof_interval_km (ab last_km) wird die LKD um
    reprof_magnitude_mm abgesenkt. Die Kurve ist stückweise linear mit
    nahezu-vertikalen Drops an den Reprofilierungspunkten.

    Returns
    -------
    km_pts, lkd_pts : Listen für den Plot
    km_warn  : km, bei dem LKD (nach Reprofilierung) erstmals ≤ gelb_min
    km_limit : km, bei dem keine weitere Reprofilierung mehr sicher möglich ist
               (LKD danach ≤ min_val) oder Verschleiß allein min_val unterschreitet
    """
    if slope >= 0 or reprof_interval_km <= 0 or reprof_magnitude_mm <= 0:
        return [], [], None, None

    km_pts: list = [last_km]
    lkd_pts: list = [last_lkd]
    km_warn: Optional[float] = None
    km_limit: Optional[float] = None

    km_cur = last_km
    lkd_cur = last_lkd
    max_reprofs = max(50, int(n_km_horizon / reprof_interval_km) + 5)

    for _ in range(max_reprofs):
        km_next_reprof = km_cur + reprof_interval_km

        # Schnittpunkt Verschleiß allein mit Schwellen in diesem Segment
        km_to_gelb = _km_threshold_linear(km_cur, lkd_cur, slope, gelb_min)
        km_to_min  = _km_threshold_linear(km_cur, lkd_cur, slope, min_val)

        # Verschleiß erreicht MIN vor der nächsten Reprofilierung
        if km_to_min is not None and km_to_min <= km_next_reprof:
            for km_pt in np.linspace(km_cur, km_to_min, n_pts_per_segment):
                km_pts.append(float(km_pt))
                lkd_pts.append(float(lkd_cur + slope * (km_pt - km_cur)))
            if km_warn is None and km_to_gelb is not None and km_to_gelb <= km_to_min:
                km_warn = km_to_gelb
            km_limit = km_to_min
            break

        # Verschleiß erreicht GELB vor der nächsten Reprofilierung
        if km_warn is None and km_to_gelb is not None and km_to_gelb <= km_next_reprof:
            km_warn = km_to_gelb

        # Segment bis zur Reprofilierung
        lkd_at_reprof = lkd_cur + slope * (km_next_reprof - km_cur)
        for km_pt in np.linspace(km_cur, km_next_reprof, n_pts_per_segment):
            km_pts.append(float(km_pt))
            lkd_pts.append(float(lkd_cur + slope * (km_pt - km_cur)))

        # Reprofilierungsdrop (gleiche km, niedrigere LKD → vertikaler Absatz im Plot)
        lkd_after_reprof = lkd_at_reprof - reprof_magnitude_mm

        if lkd_after_reprof <= min_val:
            # Reprofilierung würde unter MIN fallen → kein sicherer Eingriff mehr möglich
            km_limit = km_next_reprof
            break

        if km_warn is None and lkd_after_reprof <= gelb_min:
            km_warn = km_next_reprof

        km_pts.append(float(km_next_reprof))
        lkd_pts.append(float(lkd_after_reprof))

        km_cur = km_next_reprof
        lkd_cur = lkd_after_reprof

    return km_pts, lkd_pts, km_warn, km_limit


def _calc_prognosis_axis(
    met: MeterList,
    axis_key: str,
    n_km_horizon: int,
) -> _PrognResult:
    prm = get_prognosis_params()
    nIndex = met.getindexStartLastCycle()

    km_all = np.array(met.getkm(), dtype=float)
    lkd_all = np.array(met.getvalues(), dtype=float)
    # nDates ist np.ndarray[datetime64[s]] (oder leere Liste, wenn keine Messdaten)
    n_dates_raw = met.getnDates()
    if hasattr(n_dates_raw, "dtype") and np.issubdtype(n_dates_raw.dtype, np.datetime64):
        date_num_all = np.asarray(n_dates_raw, dtype="datetime64[s]")
    else:
        date_num_all = np.array(list(n_dates_raw), dtype="datetime64[s]")

    km_cycle = km_all[nIndex:]
    lkd_cycle = lkd_all[nIndex:]
    date_cycle = date_num_all[nIndex:]

    sort_idx = np.argsort(km_cycle)
    km_cycle = km_cycle[sort_idx]
    lkd_cycle = lkd_cycle[sort_idx]
    date_cycle = date_cycle[sort_idx]
    if np.any(np.diff(km_cycle) < 0):
        logging.warning("Laufleistung nicht monoton steigend (auch nach Sort): %s", axis_key)

    cycle_source = "HEURISTIC"

    # ── Reprofilierung im aktuellen Zyklus erkennen ──────────────────────────
    # Falls innerhalb des Zyklus noch eine Reprofilierung liegt (kleiner, aber
    # deutlicher negativer Sprung), verwenden wir nur den Sub-Zyklus danach.
    reprof_params = get_reprofiling_params(axis_key)
    if reprof_params is not None and len(km_cycle) >= 3:
        last_reprof = _find_last_reprofiling_in_cycle(km_cycle, lkd_cycle, reprof_params)
        if last_reprof is not None:
            drop_mm = float(lkd_cycle[last_reprof + 1] - lkd_cycle[last_reprof])
            sub_km = km_cycle[last_reprof + 1:]
            if len(sub_km) >= prm.min_points_fit:
                logging.info(
                    "Reprofilierung im Zyklus erkannt: km=%.0f, dLKD=%.1f mm → "
                    "Sub-Zyklus ab Punkt %d (%d Punkte) | %s",
                    float(km_cycle[last_reprof]), drop_mm, last_reprof + 1,
                    len(sub_km), axis_key,
                )
                km_cycle = sub_km
                lkd_cycle = lkd_cycle[last_reprof + 1:]
                date_cycle = date_cycle[last_reprof + 1:]
                cycle_source = "HEURISTIC+REPROF"
            else:
                logging.info(
                    "Reprofilierung bei km=%.0f erkannt, Sub-Zyklus nur %d Punkte "
                    "(min %d) → gesamter Zyklus (%d Punkte) | %s",
                    float(km_cycle[last_reprof]), len(sub_km), prm.min_points_fit,
                    len(km_cycle), axis_key,
                )

    if len(km_cycle) < prm.min_points_fit:
        logging.warning(
            "QUALITY=INSUFFICIENT: nur %d Punkte im Zyklus (min %d) für %s",
            len(km_cycle), prm.min_points_fit, axis_key,
        )
        return _PrognResult(
            quality=QUALITY_INSUFFICIENT, model="NONE",
            n_points_fit=len(km_cycle), n_outliers=0,
            cycle_source=cycle_source,
            slope=0.0, slope_low=0.0, slope_high=0.0,
            days_per_km=0.0,
            km_warn=None, km_limit=None,
            km_warn_conservative=None, km_limit_conservative=None,
        )

    km_clean, lkd_clean, n_outliers = _outlier_filter_iqr(
        km_cycle, lkd_cycle, prm.iqr_factor, axis_key
    )
    if len(km_clean) < prm.min_points_fit:
        logging.warning(
            "QUALITY=INSUFFICIENT: nach Filter nur %d Punkte für %s",
            len(km_clean), axis_key,
        )
        return _PrognResult(
            quality=QUALITY_INSUFFICIENT, model="NONE",
            n_points_fit=len(km_clean), n_outliers=n_outliers,
            cycle_source=cycle_source,
            slope=0.0, slope_low=0.0, slope_high=0.0,
            days_per_km=0.0,
            km_warn=None, km_limit=None,
            km_warn_conservative=None, km_limit_conservative=None,
        )

    quality = QUALITY_OK if len(km_clean) >= prm.min_points_quality else QUALITY_LOW
    if quality == QUALITY_LOW:
        logging.info(
            "QUALITY=LOW: nur %d Punkte nach Filter (min %d für OK) für %s",
            len(km_clean), prm.min_points_quality, axis_key,
        )

    slope, intercept, slope_low, slope_high, rmse_linear = _fit_theilsen(
        km_clean, lkd_clean, prm.ci_alpha
    )

    last_km = float(km_cycle[-1])
    last_lkd = float(lkd_cycle[-1])
    model = "LINEAR"
    b_pw = c_pw = None

    if rmse_linear > prm.rmse_threshold_mm and len(km_clean) >= 6:
        pl = _fit_powerlaw(km_clean, lkd_clean, last_km, last_lkd)
        if pl is not None:
            b_pw, c_pw, rmse_power = pl
            if rmse_power < rmse_linear:
                model = "POWER"
                logging.info(
                    "Power-Law gewählt (RMSE_lin=%.3f > RMSE_pow=%.3f) für %s",
                    rmse_linear, rmse_power, axis_key,
                )

    logging.info(
        "Fit: %s | slope=%.4f [mm/km] | slope_low=%.4f | RMSE=%.3f mm | "
        "n_fit=%d | n_outliers=%d | quality=%s | cycle=%s | %s",
        model, slope, slope_low, rmse_linear,
        len(km_clean), n_outliers, quality, cycle_source, axis_key,
    )

    gelb_min = float(met.getgelb_min()[-1])
    min_val = float(met.getmin()[-1])

    if model == "LINEAR":
        km_warn = _km_threshold_linear(last_km, last_lkd, slope, gelb_min)
        km_limit = _km_threshold_linear(last_km, last_lkd, slope, min_val)
        km_warn_c = _km_threshold_linear(last_km, last_lkd, slope_low, gelb_min)
        km_limit_c = _km_threshold_linear(last_km, last_lkd, slope_low, min_val)
    else:
        km_warn = _km_threshold_powerlaw(last_km, last_lkd, b_pw, c_pw, gelb_min)
        km_limit = _km_threshold_powerlaw(last_km, last_lkd, b_pw, c_pw, min_val)
        km_warn_c = _km_threshold_linear(last_km, last_lkd, slope_low, gelb_min)
        km_limit_c = _km_threshold_linear(last_km, last_lkd, slope_low, min_val)

    # ── Szenario "mit Reprofilierung" ────────────────────────────────────────
    km_warn_reprof: Optional[float] = None
    km_limit_reprof: Optional[float] = None
    km_prog_reprof: list = []
    lkd_prog_reprof: list = []

    if (reprof_params is not None
            and reprof_params.typical_interval_km > 0
            and reprof_params.typical_magnitude_mm > 0):
        km_prog_reprof, lkd_prog_reprof, km_warn_reprof, km_limit_reprof = \
            _simulate_with_reprofilings(
                last_km, last_lkd, slope,
                reprof_params.typical_interval_km,
                reprof_params.typical_magnitude_mm,
                gelb_min, min_val,
                float(n_km_horizon),
            )
        logging.info(
            "Szenario mit Reprofilierung: km_warn=%.0f km_limit=%.0f "
            "(Intervall=%.0f km, Größe=%.1f mm) | %s",
            km_warn_reprof or 0, km_limit_reprof or 0,
            reprof_params.typical_interval_km, reprof_params.typical_magnitude_mm,
            axis_key,
        )

    km_end_prog = km_limit if km_limit else (last_km + n_km_horizon)
    km_prog = np.linspace(last_km, km_end_prog, num=prm.n_prog_points)

    if model == "LINEAR":
        lkd_prog = last_lkd + slope * (km_prog - last_km)
    else:
        lkd_prog = last_lkd - b_pw * np.abs(km_prog - last_km) ** c_pw

    days_per_km = _calc_days_per_km_robust(km_cycle, date_cycle, axis_key)

    # last_date als np.datetime64-Skalar; date_prog als datetime64-Array
    last_date = date_cycle[-1]
    date_prog = last_date + days_to_timedelta64((km_prog - last_km) * days_per_km)

    def _km_to_datenum(km_thresh: Optional[float]):
        """km-Schwellwert → np.datetime64 (NaT bei ungültig)."""
        if km_thresh is None or days_per_km <= 0 or is_nat(last_date):
            return NAT
        return add_days(last_date, (float(km_thresh) - last_km) * days_per_km)

    dt_warn = _km_to_datenum(km_warn)
    dt_limit = _km_to_datenum(km_limit)
    dt_warn_c = _km_to_datenum(km_warn_c)
    dt_limit_c = _km_to_datenum(km_limit_c)

    # CSV/DB (BO_RADSATZDATEN_PROGNOSE): KM_WARNWERT / KM_GRENZWERT aus Reprof-Szenario,
    # falls berechnet; sonst lineare Schwellen.
    def _km_for_export(
        reprof_km: Optional[float],
        linear_km: Optional[float],
    ) -> Optional[float]:
        if reprof_km is not None and reprof_km > 0:
            return float(reprof_km)
        return linear_km

    km_export_warn = _km_for_export(km_warn_reprof, km_warn)
    km_export_limit = _km_for_export(km_limit_reprof, km_limit)
    dt_export_warn = _km_to_datenum(km_export_warn)
    dt_export_limit = _km_to_datenum(km_export_limit)
    if (km_warn_reprof and km_warn_reprof > 0) or (km_limit_reprof and km_limit_reprof > 0):
        logging.info(
            "Export-Schwellen (Reprof. wenn vorhanden): km_warn=%.0f km_limit=%.0f | %s",
            km_export_warn or 0,
            km_export_limit or 0,
            axis_key,
        )

    prog_curve_uses_reprof = False
    if len(km_prog_reprof) >= 2 and len(lkd_prog_reprof) == len(km_prog_reprof):
        km_list = [float(k) for k in km_prog_reprof]
        lkd_list = [float(y) for y in lkd_prog_reprof]
        km_arr = np.asarray(km_list, dtype=float)
        date_arr = last_date + days_to_timedelta64((km_arr - last_km) * days_per_km)
        met.setkmProg(km_list)
        met.setvaluesProg(lkd_list)
        met.setnDatesProg(date_arr)
        prog_curve_uses_reprof = True
        logging.info(
            "Prognosekurve (Export/Plot): Reprof-Szenario, %d Punkte | %s",
            len(km_list),
            axis_key,
        )
    else:
        met.setkmProg(km_prog.tolist())
        met.setvaluesProg(lkd_prog.tolist())
        met.setnDatesProg(date_prog)

    met.setgelb_min_Prog_km(km_export_warn if km_export_warn is not None and km_export_warn > 0 else 0.0)
    met.setmin_Prog_km(km_export_limit if km_export_limit is not None and km_export_limit > 0 else 0.0)
    met.setgelb_min_Prog_dt(dt_export_warn)  # datetime64 oder NaT
    met.setmin_Prog_dt(dt_export_limit)      # datetime64 oder NaT

    logging.info(
        "Prognose: km_warn=%.0f km_limit=%.0f km_warn_konservativ=%.0f "
        "km_limit_konservativ=%.0f | %s",
        km_warn or 0, km_limit or 0,
        km_warn_c or 0, km_limit_c or 0,
        axis_key,
    )

    return _PrognResult(
        quality=quality,
        model=model,
        n_points_fit=len(km_clean),
        n_outliers=n_outliers,
        cycle_source=cycle_source,
        slope=slope,
        slope_low=slope_low,
        slope_high=slope_high,
        days_per_km=days_per_km,
        km_warn=km_warn,
        km_limit=km_limit,
        km_warn_conservative=km_warn_c,
        km_limit_conservative=km_limit_c,
        km_warn_reprof=km_warn_reprof,
        km_limit_reprof=km_limit_reprof,
        km_prog_reprof=km_prog_reprof,
        lkd_prog_reprof=lkd_prog_reprof,
        prog_curve_uses_reprof=prog_curve_uses_reprof,
    )
