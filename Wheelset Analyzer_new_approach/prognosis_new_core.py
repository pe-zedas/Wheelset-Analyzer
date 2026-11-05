"""
Gemeinsamer Kern: IQR-Filter, Theil-Sen, optional Power-Law, Zyklus-Prognose (MeterList).

Theil-Sen laeuft reine NumPy, numerisch deckungsgleich zur
``scipy.stats.theilslopes``-Variante mit ``method='separate'`` (siehe
``_theilslopes``). ``scipy.optimize.curve_fit`` wird nur fuer die
optionale Power-Law-Alternative benoetigt und daher **lazy** geladen:
Wer nur die Standard-Prognose (Theil-Sen) nutzt, braucht kein scipy.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, NamedTuple, Optional, Tuple

import numpy as np

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


# ─────────────────────────────────────────────────────────────────────────────
# CI-Verbesserungen (Dashboard-kompatibel):
# - Pooled Achsen-CI, wenn Residuen-RMSE beider Räder ähnlich (Verhältnis ≤ 2).
# - Clamp der CI-Grenzen auf max. ±CI_CLAMP_FACTOR × |slope|, damit absurde
#   Werte aus Theil-Sen bei kleinen n (dkm=0-Paare → fast senkrechte paarweise
#   Steigungen) nicht in die konservativen Schwellen laufen.
# Beides spiegelt die Logik aus wheelset_dashboard/logic/prognose.py wider.
# ─────────────────────────────────────────────────────────────────────────────
POOL_RMSE_RATIO = 2.0     # beide Räder gelten als "ähnlich streuend", wenn
                          # max(rmse)/min(rmse) ≤ dieser Faktor
CI_CLAMP_FACTOR = 3.0     # CI-Halbbreite = max. CI_CLAMP_FACTOR × |slope|


def _clamp_slope_bounds(
    slope: float,
    slope_low: float,
    slope_high: float,
    max_half: Optional[float] = None,
) -> Tuple[float, float]:
    """Klemmt (slope_low, slope_high) um ``slope`` auf eine Halbbreite.

    Default: ``max_half = CI_CLAMP_FACTOR × |slope|``. Für pooled Achsen-CI
    wird ``max_half`` explizit mit dem Mittelwert beider Rad-|slope|
    übergeben, damit beide Räder dieselbe Band-Breite behalten.
    Der Punkt-Schätzer bleibt immer innerhalb des Bands.
    """
    if max_half is None:
        if slope == 0.0:
            return slope_low, slope_high
        max_half = CI_CLAMP_FACTOR * abs(slope)
    lo_c = max(slope - max_half, slope_low)
    hi_c = min(slope + max_half, slope_high)
    lo_c = min(lo_c, slope)
    hi_c = max(hi_c, slope)
    return lo_c, hi_c


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


class _TheilResult(NamedTuple):
    slope: float
    intercept: float
    low_slope: float
    high_slope: float


# Inverse Standard-Normal (Acklam-Approximation, ohne scipy).
_ACKLAM_A = [-3.969683028665376e+01, 2.209460984245205e+02,
             -2.759285104469687e+02, 1.383577518672690e+02,
             -3.066479806614716e+01, 2.506628277459239e+00]
_ACKLAM_B = [-5.447609879822406e+01, 1.615858368580409e+02,
             -1.556989798598866e+02, 6.680131188771972e+01,
             -1.328068155288572e+01]
_ACKLAM_C = [-7.784894002430293e-03, -3.223964580411365e-01,
             -2.400758277161838e+00, -2.549732539343734e+00,
             4.374664141464968e+00, 2.938163982698783e+00]
_ACKLAM_D = [7.784695709041462e-03, 3.224671290700398e-01,
             2.445134137142996e+00, 3.754408661907416e+00]


def _norm_ppf(p: float) -> float:
    """Inverse Standardnormal-CDF (Acklam-Approximation). Ersetzt
    ``scipy.stats.norm.ppf`` im CI-Index der Theil-Sen-Schranken.
    Max. Fehler ca. 1.15e-9 im zentralen Bereich — weit genauer als
    der nachfolgende ``round()``-Schritt."""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (((((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q +
               _ACKLAM_C[3]) * q + _ACKLAM_C[4]) * q + _ACKLAM_C[5]) /
            ((((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q +
              _ACKLAM_D[3]) * q + 1.0)
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((_ACKLAM_A[0] * r + _ACKLAM_A[1]) * r + _ACKLAM_A[2]) * r +
               _ACKLAM_A[3]) * r + _ACKLAM_A[4]) * r + _ACKLAM_A[5]) * q /
            (((((_ACKLAM_B[0] * r + _ACKLAM_B[1]) * r + _ACKLAM_B[2]) * r +
               _ACKLAM_B[3]) * r + _ACKLAM_B[4]) * r + 1.0)
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(
        (((((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q +
           _ACKLAM_C[3]) * q + _ACKLAM_C[4]) * q + _ACKLAM_C[5]) /
        ((((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q +
          _ACKLAM_D[3]) * q + 1.0)
    )


def _count_repeats(a: np.ndarray) -> List[int]:
    """Multiplizitaet jedes mindestens zweimal vorkommenden Wertes in
    ``a``. Entspricht ``scipy.stats._stats_py._find_repeats(a)[1]``."""
    if len(a) == 0:
        return []
    sa = np.sort(a)
    diffs = np.diff(sa) != 0
    idx = np.concatenate(([0], np.where(diffs)[0] + 1, [len(sa)]))
    counts = np.diff(idx)
    return [int(c) for c in counts if c > 1]


def theilslopes(y, x=None, alpha: float = 0.95) -> _TheilResult:
    """Theil-Sen-Steigung + Konfidenzintervall, numerisch deckungsgleich
    zu ``scipy.stats.theilslopes(y, x, alpha=alpha, method='separate')``.

    * ``slope`` = Median aller paarweisen Steigungen (fuer dx > 0)
    * ``intercept`` = ``median(y) - slope * median(x)``  (method='separate')
    * CI nach Sen (1968, Gl. 2.6) mit Repeats-Korrektur in x und y;
      Normal-Quantil per Acklam-Approximation (ohne scipy).

    Rueckgabe ist ein NamedTuple mit den Attributen ``slope``,
    ``intercept``, ``low_slope`` und ``high_slope`` — kompatibel zum
    scipy-``TheilslopesResult``.
    """
    y_arr = np.asarray(y, dtype=float).ravel()
    if x is None:
        x_arr = np.arange(len(y_arr), dtype=float)
    else:
        x_arr = np.asarray(x, dtype=float).ravel()
    n = len(x_arr)
    if n < 2 or len(y_arr) != n:
        return _TheilResult(0.0, 0.0, 0.0, 0.0)

    dx = x_arr[:, None] - x_arr
    dy = y_arr[:, None] - y_arr
    mask = dx > 0
    if not mask.any():
        return _TheilResult(0.0, 0.0, 0.0, 0.0)
    slopes = dy[mask] / dx[mask]
    slopes.sort()
    med_slope = float(np.median(slopes))
    med_inter = float(np.median(y_arr) - med_slope * np.median(x_arr))

    a = alpha
    if a > 0.5:
        a = 1.0 - a
    z = _norm_ppf(a / 2.0)
    nxreps = _count_repeats(x_arr)
    nyreps = _count_repeats(y_arr)
    nt = len(slopes)
    sigsq = (
        n * (n - 1) * (2 * n + 5)
        - sum(k * (k - 1) * (2 * k + 5) for k in nxreps)
        - sum(k * (k - 1) * (2 * k + 5) for k in nyreps)
    ) / 18.0
    try:
        sigma = math.sqrt(max(sigsq, 0.0))
        Ru = min(int(round((nt - z * sigma) / 2.0)), nt - 1)
        Rl = max(int(round((nt + z * sigma) / 2.0)) - 1, 0)
        lo = float(slopes[Rl])
        hi = float(slopes[Ru])
    except (ValueError, IndexError):
        lo = hi = float("nan")
    return _TheilResult(med_slope, med_inter, lo, hi)


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
    """Optionale Alternative zu Theil-Sen. Benoetigt
    ``scipy.optimize.curve_fit`` — scipy wird hier **lazy** importiert,
    damit die Standard-Prognose (Theil-Sen) ohne scipy auskommt."""
    try:
        from scipy.optimize import curve_fit as _scipy_curve_fit  # type: ignore
    except ImportError:
        logging.info(
            "Power-Law uebersprungen: scipy nicht installiert "
            "(nur noetig fuer die Power-Law-Alternative, nicht fuer Theil-Sen)."
        )
        return None

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
            # Reprofilierung würde unter MIN fallen → kein sicherer Eingriff mehr möglich.
            # Linie aber bis MIN verlaengern (statt bei lkd_at_reprof oberhalb MIN
            # abzubrechen), damit die Prognose vollstaendig bis zur Verschleissgrenze
            # dokumentiert ist. Analog zur alten Dashboard-Live-Logik
            # (project_with_reprofs, Fall B).
            #
            # Begrenzung: bei sehr flachen Trend-Steigungen (z.B. Lagerachsen
            # mit kaum Abrieb) kann (min_val - lkd_at_reprof) / slope ins
            # Astronomische laufen. Harte Obergrenze = 1x reprof_interval_km.
            # Reicht die Verlaengerung nicht aus, um MIN zu erreichen, endet
            # die Treppe halt bei dem erreichbaren Wert — die Prognose ist
            # dann fachlich sowieso wenig aussagekraeftig.
            if slope < 0:
                extra_km_raw = (min_val - lkd_at_reprof) / slope  # positiv, slope<0
                extra_km = min(extra_km_raw, reprof_interval_km)
                km_end = km_next_reprof + extra_km
                lkd_end = lkd_at_reprof + slope * extra_km
                for km_pt in np.linspace(km_next_reprof, km_end, n_pts_per_segment):
                    km_pts.append(float(km_pt))
                    lkd_pts.append(float(lkd_at_reprof + slope * (km_pt - km_next_reprof)))
                # km_limit nur setzen, wenn MIN tatsaechlich erreicht wurde.
                km_limit = km_end if lkd_end <= min_val + 1e-6 else km_next_reprof
            else:
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
    ci_override: Optional[Tuple[float, float]] = None,
    ci_clamp_max_half: Optional[float] = None,
) -> _PrognResult:
    """Berechnet die Prognose für ein Rad.

    Zusätzliche Parameter (für Achsen-Pooling, siehe
    :func:`_calc_prognosis_axis_pair`):

    - ``ci_override``: optionale (slope_low, slope_high), die nach dem
      Theil-Sen-Fit die eigenen CI-Grenzen ersetzen (für gepooltes CI
      beider Räder einer Achse).
    - ``ci_clamp_max_half``: optionale explizite Halbbreite für den
      CI-Clamp. Default: ``CI_CLAMP_FACTOR × |slope|``. Für pooled CI
      wird hier der Mittelwert beider Rad-|slope| übergeben.
    """
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

    # ── CI-Verbesserungen ────────────────────────────────────────────────
    # 1) Falls ein gepooltes Achsen-CI übergeben wurde (siehe
    #    _calc_prognosis_axis_pair), überschreiben dessen Grenzen
    #    die eigenen Theil-Sen-Grenzen.
    if ci_override is not None:
        slope_low, slope_high = ci_override
    # 2) Clamp gegen Pairwise-Ausreisser (max. CI_CLAMP_FACTOR × |slope|).
    slope_low, slope_high = _clamp_slope_bounds(
        slope, slope_low, slope_high, max_half=ci_clamp_max_half,
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

    # km_end_prog begrenzen: bei sehr flachen Trend-Steigungen (z.B.
    # Lagerachsen mit kaum Abrieb) wuerde km_limit astronomisch, der
    # Prognose-Horizont waere Millionen von km lang und das KI-Band im
    # Plot unleserlich. Harte Obergrenze: last_km + n_km_horizon
    # (Default 300.000 km aus radsatz_config.ini).
    km_max_horizon = last_km + n_km_horizon
    if km_limit is not None and last_km < km_limit < km_max_horizon:
        km_end_prog = km_limit
    else:
        km_end_prog = km_max_horizon
    km_prog = np.linspace(last_km, km_end_prog, num=prm.n_prog_points)

    if model == "LINEAR":
        lkd_prog = last_lkd + slope * (km_prog - last_km)
    else:
        lkd_prog = last_lkd - b_pw * np.abs(km_prog - last_km) ** c_pw

    days_per_km = _calc_days_per_km_robust(km_cycle, date_cycle, axis_key)

    # last_date als np.datetime64-Skalar; date_prog als datetime64-Array.
    # Alle Prognose-Datumswerte (Treppe, Warn/Grenz) sind an das echte
    # letzte Messdatum geankert. Die Verschiebung auf "heute" fuer
    # ruhende Raeder passiert ausschliesslich im Dashboard, und auch
    # dort nur in der Faelligkeits-Kachel — nicht im Diagramm.
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


# ─────────────────────────────────────────────────────────────────────────────
# Achsen-Pair-Prognose mit gepooltem CI (Dashboard-kompatibel)
# ─────────────────────────────────────────────────────────────────────────────

def _fit_residuals_rmse(
    met: MeterList, axis_key: str
) -> Optional[Tuple[np.ndarray, np.ndarray, float, float, float]]:
    """Hilfs-Fit zur Residuen-Berechnung (für Pool-Entscheidung).

    Liefert (km_clean, residuals, slope, intercept, rmse) oder None, wenn
    die Datenlage für den Fit nicht reicht. Verwendet dieselben Filter
    wie :func:`_calc_prognosis_axis`.
    """
    prm = get_prognosis_params()
    nIndex = met.getindexStartLastCycle()
    km_all = np.array(met.getkm(), dtype=float)
    lkd_all = np.array(met.getvalues(), dtype=float)
    km_cycle = km_all[nIndex:]
    lkd_cycle = lkd_all[nIndex:]
    sort_idx = np.argsort(km_cycle)
    km_cycle = km_cycle[sort_idx]
    lkd_cycle = lkd_cycle[sort_idx]
    # Sub-Zyklus-Erkennung (konsistent zum Haupt-Fit)
    reprof_params = get_reprofiling_params(axis_key)
    if reprof_params is not None and len(km_cycle) >= 3:
        last_reprof = _find_last_reprofiling_in_cycle(km_cycle, lkd_cycle, reprof_params)
        if last_reprof is not None:
            sub_km = km_cycle[last_reprof + 1:]
            if len(sub_km) >= prm.min_points_fit:
                km_cycle = sub_km
                lkd_cycle = lkd_cycle[last_reprof + 1:]
    if len(km_cycle) < prm.min_points_fit:
        return None
    km_clean, lkd_clean, _ = _outlier_filter_iqr(
        km_cycle, lkd_cycle, prm.iqr_factor, axis_key,
    )
    if len(km_clean) < prm.min_points_fit:
        return None
    slope, intercept, _lo, _hi, rmse = _fit_theilsen(km_clean, lkd_clean, prm.ci_alpha)
    residuals = lkd_clean - (slope * km_clean + intercept)
    return km_clean, residuals, slope, intercept, rmse


def _calc_prognosis_axis_pair(
    met1: MeterList,
    met2: MeterList,
    axis_key1: str,
    axis_key2: str,
    n_km_horizon: int,
) -> Tuple[_PrognResult, _PrognResult]:
    """Prognose für beide Räder einer Achse mit achsenweit konsistentem CI.

    Vorgehen (identisch zur Dashboard-Logik):

    1. Pre-Fit jedes Rads einzeln → eigene Theil-Sen-Steigung + Residuen.
    2. RMSE-Vergleich der Rad-Residuen. Nur wenn das Verhältnis
       ≤ ``POOL_RMSE_RATIO`` ist, werden die Residuen beider Räder gepoolt
       und daraus eine gemeinsame CI-Steigungs-Grenze berechnet
       (symmetrisches, robusteres Band).
    3. Wenn asymmetrisch gestreut → jedes Rad behält sein eigenes CI
       (asymmetrische Streuung bleibt sichtbar).
    4. CI-Clamp (max. ±CI_CLAMP_FACTOR × |slope|; im Pooled-Fall gegen
       den Mittel-|slope| beider Räder → symmetrische Bandbreite).

    Rückgabe: Ergebnisse beider Räder. Alle `MeterList`-Setter werden
    ganz normal von ``_calc_prognosis_axis`` befüllt.
    """
    pre1 = _fit_residuals_rmse(met1, axis_key1)
    pre2 = _fit_residuals_rmse(met2, axis_key2)

    pooled_bounds: Optional[Tuple[float, float]] = None
    clamp_max_half: Optional[float] = None

    if pre1 is not None and pre2 is not None:
        km1, res1, slope1, _i1, rmse1 = pre1
        km2, res2, slope2, _i2, rmse2 = pre2
        lo = min(rmse1, rmse2)
        hi = max(rmse1, rmse2)
        if lo > 1e-9 and (hi / lo) <= POOL_RMSE_RATIO:
            # Pooled Theil-Sen auf (km, residuum) → gemeinsame Streuung
            # der Steigung um 0.
            km_pool = np.concatenate([km1, km2])
            res_pool = np.concatenate([res1, res2])
            try:
                pr = theilslopes(y=res_pool, x=km_pool, alpha=get_prognosis_params().ci_alpha)
                pooled_lo = float(pr.low_slope)
                pooled_hi = float(pr.high_slope)
                # Band wird in _calc_prognosis_axis um das eigene slope
                # verschoben: slope ± pooled_bounds.  Da _calc_prognosis_axis
                # das Override direkt als slope_low/slope_high einsetzt,
                # schieben wir hier schon pro Rad die Pooled-Residuen-Grenzen
                # auf das jeweilige slope auf.
                pooled_bounds = (pooled_lo, pooled_hi)
                clamp_max_half = CI_CLAMP_FACTOR * 0.5 * (abs(slope1) + abs(slope2))
                logging.info(
                    "Pooled Achsen-CI (RMSE %.3f / %.3f, Verh. %.2f): "
                    "slope_low_add=%.5f  slope_high_add=%.5f | %s",
                    rmse1, rmse2, hi / lo, pooled_lo, pooled_hi, axis_key1,
                )
            except Exception as exc:
                logging.warning("Pooled Theil-Sen fehlgeschlagen: %s | %s", exc, axis_key1)
        else:
            logging.info(
                "Kein Pooling (RMSE %.3f / %.3f, Verh. %.2f > %.1f): "
                "individuelles CI je Rad | %s",
                rmse1, rmse2, (hi / lo if lo > 0 else float("inf")),
                POOL_RMSE_RATIO, axis_key1,
            )

    # Pooled-Werte sind Steigungs-Offsets um 0 (Residuen-Fit). Pro Rad
    # werden sie auf das Rad-eigene slope aufgeschlagen. _calc_prognosis_axis
    # verwendet ci_override aber direkt als (slope_low, slope_high) — also
    # muss die Addition hier passieren.
    def _pooled_override_for(slope_self: float) -> Optional[Tuple[float, float]]:
        if pooled_bounds is None:
            return None
        return (slope_self + pooled_bounds[0], slope_self + pooled_bounds[1])

    slope1_est = pre1[2] if pre1 is not None else 0.0
    slope2_est = pre2[2] if pre2 is not None else 0.0

    res1 = _calc_prognosis_axis(
        met1, axis_key1, n_km_horizon,
        ci_override=_pooled_override_for(slope1_est),
        ci_clamp_max_half=clamp_max_half,
    )
    res2 = _calc_prognosis_axis(
        met2, axis_key2, n_km_horizon,
        ci_override=_pooled_override_for(slope2_est),
        ci_clamp_max_half=clamp_max_half,
    )
    return res1, res2
