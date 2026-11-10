"""Prognose- und Reprofilierungs-Logik, nachgebaut aus dem Backend
``Radsatz_Bahn_DB_new_Approach.py`` / ``prognosis_new_core.py`` / ``reprof_learning.py``.

STAND (Entscheidung 2026-11-10): Dieser Code rechnet die Prognose direkt in der App.
Er wird **aktuell nicht genutzt** — die Anzeige liest die Prognose aus der Tabelle
``BO_RADSATZDATEN_PROGNOSE`` (``Messreihe.prognose``). Er bleibt bewusst **erhalten**
(z.B. fuer eine eigene Prognose bei Kunden, deren Schema das Backend nicht rechnet) und
soll nicht als toter Code geloescht werden. Genutzt wird nur ``faelligkeit_shift``.
Alle uebrigen Funktionen sind ohne Aufrufer und ungetestet; bei einer Reaktivierung
gegen das Backend (``prognosis_new_core.py``) abgleichen.

Wichtige Konventionen:
- Reprofilierung = **negativer** LKD-Sprung (vom Rad wird Material abgetragen).
- Positive LKD-Spruenge = Rad-Tausch, werden explizit ausgeschlossen.
- Zukuenftige Reprofilierungen werden im festen km-Intervall ausgeloest
  (NICHT abhaengig von GELB_MIN).
- Zyklus-Fit nutzt nur Punkte seit der letzten Reprofilierung.
- Lebensende: wenn der LKD-Wert nach der naechsten Reprof unter MIN faellt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np

from ..data.models import Messpunkt, Messreihe, PrognoseConfig


def faelligkeit_shift(prog_dt: Optional[datetime], mr: Messreihe) -> Optional[datetime]:
    """Verschiebt ein Prognose-Faelligkeitsdatum fuer die Anzeige ab heute.

    Hintergrund: Das Backend schreibt alle Prognose-Datumswerte direkt
    ab dem letzten Messwert. Fuer ruhende Raeder (Lagerkomponenten oder
    eingebaute Raeder ohne neue Messungen) laegen Warn-, Grenz- und
    Reprof-Termine damit in der Vergangenheit. Weil eine ruhende Achse
    nicht verschleisst, gilt die Restlebensdauer erst ab der Wieder-
    inbetriebnahme — Faelligkeiten werden daher um
    ``delta = heute - letzter_messwert`` verschoben.

    Diese Verschiebung wirkt NUR auf Anzeige-Ebene (Kachel, KpiCards,
    Info-Box, Werkstattlisten-Export). Diagramm und Treppe bleiben am
    echten letzten Messwert verankert.
    """
    if prog_dt is None:
        return None
    letzt = mr.letzter_wert()
    if letzt is None:
        return prog_dt
    heute = datetime.now()
    if letzt.datum >= heute:
        return prog_dt
    return prog_dt + (heute - letzt.datum)


@dataclass
class ReprofPoint:
    """Erkannte Reprofilierung in der Historie (LKD sinkt um ``drop`` mm)."""
    km_vor: float
    stand_vor: float
    km_nach: float
    stand_nach: float
    drop: float            # positive mm (= abs(stand_nach - stand_vor))


@dataclass
class LearnedParams:
    dkm_threshold: float
    dlkd_abs_min: float
    typical_interval_km: float
    typical_magnitude_mm: float


def _percentile(sorted_xs: List[float], q: float) -> float:
    """Lineare Interpolation (numpy.percentile-aequivalent fuer eine sortierte Liste)."""
    if not sorted_xs:
        return 0.0
    n = len(sorted_xs)
    if n == 1:
        return sorted_xs[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_xs[lo]
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def _sorted_pts(mr: Messreihe) -> List[Messpunkt]:
    return sorted((mp for mp in mr.historie if mp.laufleistung is not None),
                  key=lambda mp: mp.laufleistung)


# ----------------------------------------------------------------------
# 1) Reprof-Erkennung (reprof_learning._fit_reprof_params)
# ----------------------------------------------------------------------

def detect_reprofilierungen(mr: Messreihe, dkm_threshold: float,
                             dlkd_abs_min: float) -> List[ReprofPoint]:
    """Negative LKD-Spruenge: ``dlkd <= -dlkd_abs_min``, ``0 <= dkm <= dkm_threshold``.
    Positive Spruenge (Rad-Tausch) werden verworfen; km-Rueckschritte ignoriert.
    dkm = 0 ist zulaessig: in vielen Datenbasen wird Reprofilierung als
    zwei Messungen am selben km-Stand (vor/nach dem Abtrag) dokumentiert."""
    pts = _sorted_pts(mr)
    out: List[ReprofPoint] = []
    for a, b in zip(pts, pts[1:]):
        dkm = b.laufleistung - a.laufleistung
        if dkm < 0 or dkm > dkm_threshold:
            continue
        dlkd = b.stand - a.stand
        if dlkd >= 0:
            continue
        drop = -dlkd
        if drop < dlkd_abs_min:
            continue
        out.append(ReprofPoint(km_vor=a.laufleistung, stand_vor=a.stand,
                                km_nach=b.laufleistung, stand_nach=b.stand,
                                drop=drop))
    return out


def learn_reprof_params(mr: Messreihe, cfg: PrognoseConfig) -> Optional[LearnedParams]:
    """Lernt dkm_threshold, dlkd_abs_min, typisches Intervall und Magnitude
    aus der Historie. Liefert None, wenn zu wenig Seeds (< 3) vorhanden sind.
    """
    pts = _sorted_pts(mr)
    seeds = []
    for a, b in zip(pts, pts[1:]):
        dkm = b.laufleistung - a.laufleistung
        if dkm < 0 or dkm > 2000:   # strenger Seed-Filter aus Backend (dkm = 0 ok)
            continue
        dlkd = b.stand - a.stand
        if dlkd >= 0:
            continue
        drop = -dlkd
        if drop < 2.0:
            continue
        seeds.append((dkm, drop))

    # Fallback-Schwellen, wenn zu wenige Seeds zum Schaetzen -> Standard aus cfg
    if len(seeds) >= 2:
        seed_dkm = sorted(x[0] for x in seeds)
        seed_drop = sorted(x[1] for x in seeds)
        dkm_thr = max(2000.0, min(10000.0, _percentile(seed_dkm, 0.95)))
        # Bei vielen Seeds P25 (robust gegen Ausreisser); bei wenigen das
        # Minimum, damit kein echter Seed vom finalen Match ausgeschlossen wird.
        if len(seeds) >= 4:
            dlkd_min = max(2.0, _percentile(seed_drop, 0.25))
        else:
            dlkd_min = max(2.0, min(seed_drop) - 0.01)
    else:
        dkm_thr = cfg.reprof_dkm_threshold
        dlkd_min = cfg.reprof_dlkd_abs_min

    reprofs = detect_reprofilierungen(mr, dkm_thr, dlkd_min)
    # Backend lernt bereits ab 2 erkannten Reprofs: 2 Reprofs geben 1 Intervall,
    # das ist der tatsaechliche Fahrzyklus dieser Achse.
    if len(reprofs) < 2:
        return None
    mags = sorted(r.drop for r in reprofs)
    magnitude = mags[len(mags) // 2]
    intervals = sorted(b.km_nach - a.km_nach for a, b in zip(reprofs, reprofs[1:]))
    interval = intervals[len(intervals) // 2]
    return LearnedParams(dkm_threshold=dkm_thr, dlkd_abs_min=dlkd_min,
                         typical_interval_km=interval,
                         typical_magnitude_mm=magnitude)


def _axle_merged_params(achse, cfg: PrognoseConfig, mr: Messreihe
                         ) -> Optional[LearnedParams]:
    """Lernt Reprof-Parameter achsen-weit (links + rechts zusammen).

    Beide Raeder einer Achse werden immer gleichzeitig reprofiliert, also
    sollten sie auch dasselbe Intervall liefern. Um das zu erreichen:

    1. Reprof-km-Marken werden ueber beide Raeder vereinigt (dedup mit
       Toleranz 500 km), weil ein Reprof oft auf einer Seite knapp unter
       der individuellen Schwelle liegt und sonst verloren geht.
    2. Intervall = Median der Abstaende dieser vereinten km-Liste.
    3. Magnitude = aus der eigenen Messreihe (jede Seite hat ihre eigene
       Abtragstiefe).
    """
    if achse is None:
        return None
    # Pro Rad die eigenen Seeds + Reprofs sammeln (strikter Seed-Filter wie
    # in learn_reprof_params)
    all_seeds_drop: List[float] = []
    per_wheel = []
    for rad in achse.raeder.values():
        mr2 = rad.messreihen.get(mr.messgroesse)
        if mr2 is None or not mr2.historie:
            continue
        pts = _sorted_pts(mr2)
        seeds = []
        for a, b in zip(pts, pts[1:]):
            dkm = b.laufleistung - a.laufleistung
            if dkm < 0 or dkm > 2000:
                continue
            dlkd = b.stand - a.stand
            if dlkd >= 0:
                continue
            drop = -dlkd
            if drop < 2.0:
                continue
            seeds.append((dkm, drop))
            all_seeds_drop.append(drop)
        per_wheel.append((mr2, seeds))
    if not per_wheel:
        return None
    # Gemeinsame Schwellen aus allen Seeds beider Raeder — robuster gegen
    # Einzel-Rad-Ausreisser.
    if len(all_seeds_drop) >= 2:
        all_seeds_drop.sort()
        if len(all_seeds_drop) >= 4:
            dlkd_min = max(2.0, _percentile(all_seeds_drop, 0.25))
        else:
            dlkd_min = max(2.0, min(all_seeds_drop) - 0.01)
    else:
        dlkd_min = cfg.reprof_dlkd_abs_min
    dkm_thr = 2000.0

    # Reprof-km-Marken ueber alle Raeder vereinigen (Toleranz 500 km)
    km_marks: List[float] = []
    for mr2, _ in per_wheel:
        for r in detect_reprofilierungen(mr2, dkm_thr, dlkd_min):
            km_marks.append(r.km_nach)
    if len(km_marks) < 2:
        return None
    km_marks.sort()
    merged: List[float] = [km_marks[0]]
    for k in km_marks[1:]:
        if k - merged[-1] > 500:
            merged.append(k)
    if len(merged) < 2:
        return None
    intervals = sorted(b - a for a, b in zip(merged, merged[1:]))
    interval = intervals[len(intervals) // 2]

    # Magnitude: aus der EIGENEN Messreihe (jede Seite hat ihren eigenen Abtrag)
    own_reprofs = detect_reprofilierungen(mr, dkm_thr, dlkd_min)
    if own_reprofs:
        mags = sorted(r.drop for r in own_reprofs)
        magnitude = mags[len(mags) // 2]
    else:
        magnitude = cfg.reprof_typical_magnitude_mm
    return LearnedParams(dkm_threshold=dkm_thr, dlkd_abs_min=dlkd_min,
                         typical_interval_km=interval,
                         typical_magnitude_mm=magnitude)


def _fleet_median_params(flotte, cfg: PrognoseConfig,
                          messgroesse: str = "LKD") -> Optional[LearnedParams]:
    """Flotten-Fallback: Median der gelernten Parameter ueber ALLE Achsen,
    bei denen die Historie reichhaltig genug ist. Wird genutzt, wenn eine
    einzelne Achse zu wenige Reprofs hat (Backend-Kaskade)."""
    if flotte is None:
        return None
    intervals, magnitudes, dkm_thrs, dlkd_mins = [], [], [], []
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            for a in dg.achsen.values():
                for r in a.raeder.values():
                    mr2 = r.messreihen.get(messgroesse)
                    if mr2 is None:
                        continue
                    lp = learn_reprof_params(mr2, cfg)
                    if lp is None:
                        continue
                    intervals.append(lp.typical_interval_km)
                    magnitudes.append(lp.typical_magnitude_mm)
                    dkm_thrs.append(lp.dkm_threshold)
                    dlkd_mins.append(lp.dlkd_abs_min)
    if not intervals:
        return None
    intervals.sort(); magnitudes.sort(); dkm_thrs.sort(); dlkd_mins.sort()
    return LearnedParams(
        dkm_threshold=dkm_thrs[len(dkm_thrs) // 2],
        dlkd_abs_min=dlkd_mins[len(dlkd_mins) // 2],
        typical_interval_km=intervals[len(intervals) // 2],
        typical_magnitude_mm=magnitudes[len(magnitudes) // 2],
    )


def effective_params(mr: Messreihe, cfg: PrognoseConfig,
                      flotte=None, achse=None) -> LearnedParams:
    """Liefert die effektiv verwendeten Parameter nach Kaskade:

    1) **Achsen-Scope** (wenn ``achse`` gegeben): gemeinsames Intervall
       beider Raeder, individuelle Magnitude pro Seite. So haben linkes
       und rechtes Rad das gleiche Reprof-Intervall — physikalisch
       korrekt, weil beide Raeder gleichzeitig reprofiliert werden.
    2) **Rad-Scope**: nur aus der eigenen Historie gelernt
       (``learn_reprof_params``).
    3) **Flotten-Fallback**: Median ueber alle Achsen der Flotte.
    4) Fallback-Defaults aus der Config.
    """
    if cfg.auto_from_history:
        if achse is not None:
            axle = _axle_merged_params(achse, cfg, mr)
            if axle is not None:
                return axle
        learned = learn_reprof_params(mr, cfg)
        if learned is not None:
            return learned
        fleet = _fleet_median_params(flotte, cfg, mr.messgroesse)
        if fleet is not None:
            return fleet
    return LearnedParams(
        dkm_threshold=cfg.reprof_dkm_threshold,
        dlkd_abs_min=cfg.reprof_dlkd_abs_min,
        typical_interval_km=cfg.reprof_typical_interval_km,
        typical_magnitude_mm=cfg.reprof_typical_magnitude_mm,
    )


# ----------------------------------------------------------------------
# 2) Zyklus-Fit (lineare Steigung ab letzter Reprofilierung)
# ----------------------------------------------------------------------

def _ols_slope(xs: List[float], ys: List[float]) -> Tuple[float, float, float]:
    """OLS-Steigung, Achsenabschnitt, RMSE."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0, my, 0.0
    slope = num / den
    intercept = my - slope * mx
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    rmse = math.sqrt(sum(r * r for r in residuals) / max(n - 2, 1))
    return slope, intercept, rmse


def _theil_sen(xs: List[float], ys: List[float], alpha: float = 0.90
                ) -> Tuple[float, float, float, float]:
    """Theil-Sen-Steigung + Konfidenzintervall (slope_low, slope_high).

    Vollstaendig NumPy-basiert, numerisch deckungsgleich zu
    ``scipy.stats.theilslopes(y, x, alpha=alpha, method='separate')``:

    * slope = Median aller paarweisen Steigungen (fuer dx > 0)
    * intercept = median(y) - slope * median(x)  (``separate``-Variante)
    * Konfidenzintervall nach Sen (1968, Gl. 2.6): symmetrische Indizes
      um den Median der sortierten Paar-Steigungen, mit Normal-Quantil
      aus ``alpha/2`` und einer Standardabweichung, die Repeats in x
      und y korrigiert.

    Rueckgabe ist ein 4-Tupel ``(slope, intercept, slope_low, slope_high)``.
    """
    xs_arr = np.asarray(xs, dtype=float)
    ys_arr = np.asarray(ys, dtype=float)
    n = len(xs_arr)
    if n < 2:
        return 0.0, 0.0, 0.0, 0.0

    # Paarweise Steigungen fuer alle (i, j) mit x[j] > x[i].
    dx = xs_arr[:, None] - xs_arr
    dy = ys_arr[:, None] - ys_arr
    mask = dx > 0
    if not mask.any():
        return 0.0, 0.0, 0.0, 0.0
    slopes = dy[mask] / dx[mask]
    slopes.sort()
    med_slope = float(np.median(slopes))
    med_inter = float(np.median(ys_arr) - med_slope * np.median(xs_arr))

    # Konfidenzintervall (Sen 1968, 2.6). alpha ist symmetrisch um 0.5.
    a = alpha
    if a > 0.5:
        a = 1.0 - a
    # Normal-Quantil ohne scipy: inverse Standardnormal via Acklam/Beasley–Springer-
    # Approximation (Fehler < 4.5e-4). Fuer die typischen alpha-Werte
    # (0.80, 0.90, 0.95, 0.99) bringt das <<1e-6 Abweichung vom scipy-Wert.
    z = _norm_ppf(a / 2.0)
    nxreps = _count_repeats(xs_arr)
    nyreps = _count_repeats(ys_arr)
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
    return med_slope, med_inter, lo, hi


def _count_repeats(a: "np.ndarray") -> List[int]:
    """Multiplizitaet jedes mehrfach auftretenden Werts in ``a``.

    Entspricht ``scipy.stats._stats_py._find_repeats(a)[1]``: Rueckgabe
    sind nur die Zaehlungen jener Werte, die mindestens zweimal
    vorkommen. Reine ``numpy``-Umsetzung.
    """
    if len(a) == 0:
        return []
    sorted_a = np.sort(a)
    # Position jedes Blockbeginns
    diffs = np.diff(sorted_a) != 0
    idx = np.concatenate(([0], np.where(diffs)[0] + 1, [len(sorted_a)]))
    counts = np.diff(idx)
    return [int(c) for c in counts if c > 1]


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
    """Inverse Standardnormal-CDF (Acklam-Approximation). Ersatz fuer
    ``scipy.stats.norm.ppf``. Maximaler Fehler ca. 1.15e-9 im zentralen
    Bereich; weit genauer als der Rundungsschritt im CI-Index."""
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


def _last_positive_jump_index(pts: List[Messpunkt], diff_lkd: float = 10.0) -> int:
    """Index des Punktes NACH dem letzten positiven LKD-Sprung (= Rad-Tausch).

    Backend-Logik aus ``toolsWheelset.getStartIndexLastCycle``: ein echter
    Rad-Tausch zeigt sich als sprunghaft steigender LKD um > ``diff_lkd`` mm.
    Alle Punkte davor gehoeren zum Vorgaengerrad und werden verworfen.
    """
    idx = 0
    for i in range(1, len(pts)):
        if pts[i].stand - pts[i - 1].stand > diff_lkd:
            idx = i
    return idx


def cycle_fit(mr: Messreihe, cfg: PrognoseConfig, flotte=None, achse=None
               ) -> Optional[Tuple[float, float, float, float, List[Messpunkt]]]:
    """Theil-Sen-Fit ueber den juengsten Zyklus (Backend-Konvention).

    Zweistufige Abschneidung:

    1. **Zyklus-Start** = Index nach dem letzten positiven LKD-Sprung
       (Rad-Tausch), siehe ``_last_positive_jump_index``.
       → alle Punkte vor dem Rad-Tausch gehoeren zum Vorgaengerrad und
       werden verworfen.
    2. **Sub-Zyklus (optional)** = ab der letzten Reprofilierung innerhalb
       des Zyklus. Nur verwendet, wenn danach noch ``min_points_fit`` Punkte
       uebrig sind; sonst wird der volle Zyklus benutzt. So faellt die
       Prognose NICHT auf alle historischen Punkte zurueck (das wuerde die
       Steigung durch alte Zyklen flach ziehen).

    Vor Theil-Sen wird ein IQR-Filter (Faktor ``cfg.iqr_factor``) angewendet,
    der die Reprof-Spruenge als Ausreisser verwirft, so dass die
    verbleibende reine Verschleiss-Steigung uebrig bleibt.

    Liefert ``(slope, intercept, slope_low, slope_high, pts)`` oder None,
    wenn zu wenig Punkte vorhanden sind (< min_points_fit).
    """
    pts = _sorted_pts(mr)
    if len(pts) < cfg.min_points_fit:
        return None

    # 1) Stufe A: nach letztem Rad-Tausch abschneiden
    start_idx = _last_positive_jump_index(pts, diff_lkd=10.0)
    cycle_pts = pts[start_idx:]
    if len(cycle_pts) < cfg.min_points_fit:
        cycle_pts = pts

    # 2) Stufe B: letzte Reprofilierung innerhalb des Zyklus — nur verwenden,
    # wenn danach genug Punkte bleiben.
    params = effective_params(mr, cfg, flotte=flotte, achse=achse)
    reprofs_in_cycle = detect_reprofilierungen(
        _mr_from_pts(mr, cycle_pts), params.dkm_threshold, params.dlkd_abs_min
    )
    if reprofs_in_cycle:
        km_sub = reprofs_in_cycle[-1].km_nach
        sub = [mp for mp in cycle_pts if mp.laufleistung >= km_sub]
        if len(sub) >= cfg.min_points_fit:
            cycle_pts = sub
        # sonst: Zyklus bleibt wie er ist; IQR filtert die Reprof-Spruenge raus

    xs = [mp.laufleistung for mp in cycle_pts]
    ys = [mp.stand for mp in cycle_pts]

    # IQR-Filter: OLS-Vorfit, Residuen → Ausreisser (Reprof-Spruenge) verwerfen
    pre_slope, pre_intercept, _ = _ols_slope(xs, ys)
    residuals = sorted(y - (pre_slope * x + pre_intercept) for x, y in zip(xs, ys))
    if len(residuals) >= 4:
        q1 = _percentile(residuals, 0.25)
        q3 = _percentile(residuals, 0.75)
        iqr = q3 - q1
        if iqr > 0:
            keep = [(x, y) for x, y in zip(xs, ys)
                    if abs(y - (pre_slope * x + pre_intercept)) <= cfg.iqr_factor * iqr]
            if len(keep) >= cfg.min_points_fit:
                xs = [p[0] for p in keep]
                ys = [p[1] for p in keep]
                keep_set = set(keep)
                cycle_pts = [mp for mp in cycle_pts
                             if (mp.laufleistung, mp.stand) in keep_set]

    slope, intercept, lo, hi = _theil_sen(xs, ys)
    return slope, intercept, lo, hi, cycle_pts


def _mr_from_pts(template: Messreihe, pts: List[Messpunkt]) -> Messreihe:
    """Hilfs-Konstruktor: eine Messreihe mit nur den gegebenen Punkten."""
    return Messreihe(messgroesse=template.messgroesse, einheit=template.einheit,
                     direction=template.direction, historie=list(pts))


# ----------------------------------------------------------------------
# 3) Treppen-Prognose mit festen km-Intervallen (prognosis_new_core._simulate_with_reprofilings)
# ----------------------------------------------------------------------

def project_with_reprofs(mr: Messreihe, cfg: PrognoseConfig, flotte=None,
                          achse=None) -> Optional[List[Tuple[float, float]]]:
    """Baut die Treppen-Prognose nach Backend-Konvention:

    1. Zyklus-Fit → Steigung ``slope`` (mm/km, negativ).
    2. Start am letzten Messwert (km_cur, lkd_cur).
    3. Alle ``typical_interval_km`` eine Reprofilierung:
       - Linie faellt linear von (km_cur, lkd_cur) nach (km_next, lkd_at).
       - Vertikaler Sprung nach unten um ``typical_magnitude_mm``.
       - Lebensende, wenn ``lkd_after <= MIN``.
    """
    letzt = mr.letzter_wert()
    if letzt is None or letzt.laufleistung is None or letzt.min_val is None:
        return None
    fit = cycle_fit(mr, cfg, flotte=flotte, achse=achse)
    if fit is None:
        return None
    slope, _intercept, _lo, _hi, _pts = fit
    if slope >= 0:
        return None  # keine sinnvolle Prognose fuer steigende/ebene Reihen

    params = effective_params(mr, cfg, flotte=flotte, achse=achse)
    interval = params.typical_interval_km
    magnitude = params.typical_magnitude_mm
    min_v = letzt.min_val

    km_cur, lkd_cur = letzt.laufleistung, letzt.stand
    pts: List[Tuple[float, float]] = [(km_cur, lkd_cur)]

    # Lebenszeit-Guard (Backend: >50 Iterationen moeglich; hier 20 reichen)
    for _ in range(20):
        km_next = km_cur + interval
        lkd_at = lkd_cur + slope * interval
        # Fall A: MIN wird vor der naechsten Reprof erreicht
        if slope < 0:
            km_to_min = (min_v - lkd_cur) / slope
        else:
            km_to_min = math.inf
        if km_to_min <= interval:
            pts.append((km_cur + km_to_min, min_v))
            break
        # Normal: Linie zur km_next
        pts.append((km_next, lkd_at))
        lkd_after = lkd_at - magnitude
        # Fall B: nach der Reprof unter MIN → keine Reprof mehr sinnvoll,
        # Linie wird aber bis MIN verlaengert (statt vorzeitig abzubrechen),
        # damit im Plot der Prognoseverlauf vollstaendig bis zur Grenze
        # sichtbar bleibt.
        if lkd_after <= min_v:
            extra_km = (min_v - lkd_at) / slope if slope < 0 else 0
            pts.append((km_next + extra_km, min_v))
            break
        # Vertikaler Sprung
        pts.append((km_next, lkd_after))
        km_cur = km_next
        lkd_cur = lkd_after
    return pts


# ----------------------------------------------------------------------
# 4) KI-Band aus Theil-Sen-Steigungsgrenzen
# ----------------------------------------------------------------------

def _residual_rmse(mr: Messreihe, cfg: PrognoseConfig,
                    flotte=None, achse=None) -> Optional[Tuple[float, int]]:
    """RMSE der Zyklus-Punkte um ihre Theil-Sen-Trendlinie. Mass fuer
    die Streuung der eigenen Messreihe. Liefert (rmse, n) oder None."""
    fit = cycle_fit(mr, cfg, flotte=flotte, achse=achse)
    if fit is None:
        return None
    slope, intercept, _, _, cpts = fit
    if not cpts:
        return None
    res = [mp.stand - (slope * mp.laufleistung + intercept) for mp in cpts]
    rmse = math.sqrt(sum(r * r for r in res) / len(res))
    return rmse, len(cpts)


def _axle_pooled_ci(achse, cfg: PrognoseConfig, flotte=None
                     ) -> Optional[Tuple[float, float]]:
    """Gemeinsame CI-Steigungen aus den Residuen BEIDER Raeder einer Achse.

    Jedes Rad fittet seine eigene Trendlinie (unterschiedliche Niveaus
    links/rechts), die Residuen werden gepoolt und daraus Theil-Sen auf
    die Residuen-Steigungen angewendet. So entsteht ein **einheitliches
    CI** fuer beide Raeder — in der Breite identisch, weil beide Raeder
    denselben Fahrzyklus und dieselbe Streuung haben.

    **Nur sinnvoll, wenn beide Raeder tatsaechlich aehnlich streuen.**
    Deshalb wird vorher per RMSE-Vergleich geprueft (siehe
    ``_use_pooled_ci``).
    """
    if achse is None:
        return None
    all_x: List[float] = []
    all_res: List[float] = []
    for rad in achse.raeder.values():
        for mr2 in rad.messreihen.values():
            if mr2.messgroesse != "LKD":
                continue
            fit = cycle_fit(mr2, cfg, flotte=flotte, achse=achse)
            if fit is None:
                continue
            slope2, intercept2, _, _, cpts2 = fit
            for mp in cpts2:
                all_x.append(mp.laufleistung)
                all_res.append(mp.stand - (slope2 * mp.laufleistung + intercept2))
    if len(all_x) < max(cfg.min_points_fit, 6):
        return None
    _s, _i, lo, hi = _theil_sen(all_x, all_res)
    return lo, hi


# Schwelle fuer "aehnliche Streuung": wenn das Verhaeltnis der Residuen-RMSE
# beider Raeder < diesem Faktor ist, duerfen die Raeder gepooled werden
# (symmetrisches, robusteres CI). Sonst erhaelt jedes Rad sein eigenes CI,
# weil die tatsaechliche Streuung physikalisch unterschiedlich ist.
_POOL_RMSE_RATIO = 2.0


def _axle_mean_abs_slope(achse, cfg: PrognoseConfig, flotte=None) -> Optional[float]:
    """Mittelwert von |slope| ueber beide Raeder einer Achse (fuer Clamp).

    Garantiert, dass beide Raeder im pooled-CI-Modus dieselbe Clamp-
    Grenze bekommen → symmetrische Bandbreite.
    """
    if achse is None:
        return None
    slopes = []
    for rad in achse.raeder.values():
        for mr2 in rad.messreihen.values():
            if mr2.messgroesse != "LKD":
                continue
            fit = cycle_fit(mr2, cfg, flotte=flotte, achse=achse)
            if fit is None:
                continue
            slopes.append(abs(fit[0]))
    if not slopes:
        return None
    return sum(slopes) / len(slopes)


def _use_pooled_ci(achse, cfg: PrognoseConfig, flotte=None) -> bool:
    """Entscheidet, ob das pooled Achsen-CI genutzt werden darf.

    Vergleicht die Residuen-RMSE der beiden Raeder. Nur wenn ihr
    Verhaeltnis innerhalb ``_POOL_RMSE_RATIO`` liegt (also beide Raeder
    aehnlich stark streuen), wird gepoolt. Sonst erhaelt jedes Rad sein
    eigenes CI, damit asymmetrische Streuung sichtbar bleibt.
    """
    if achse is None:
        return False
    rmses: List[float] = []
    for rad in achse.raeder.values():
        for mr2 in rad.messreihen.values():
            if mr2.messgroesse != "LKD":
                continue
            r = _residual_rmse(mr2, cfg, flotte=flotte, achse=achse)
            if r is not None and r[0] > 0:
                rmses.append(r[0])
    if len(rmses) < 2:
        return False  # kein Vergleich moeglich → eigenes CI je Rad
    lo = min(rmses); hi = max(rmses)
    if lo <= 1e-9:
        return False
    return (hi / lo) <= _POOL_RMSE_RATIO


def _clamp_ci(slope: float, lo: float, hi: float,
               max_half: Optional[float] = None) -> Tuple[float, float]:
    """Klemmt die CI-Grenzen auf einen plausiblen Bereich.

    Bei wenigen Punkten (n ≤ 5) kann die Theil-Sen-Pairwise-Statistik
    extreme Grenzwerte liefern (z. B. -22 mm/1000 km), vor allem wenn
    zwei Messungen am gleichen km-Stand liegen (dkm=0 → fast senkrechte
    paarweise Steigung). Diese Werte sind physikalisch sinnlos: das Band
    wird daher auf **``max_half`` auf jeder Seite der Mitte** begrenzt.

    Default: ``max_half = 3 × |slope|`` (slope-proportional). Fuer das
    pooled Achsen-CI wird ``max_half`` explizit uebergeben (Mittelwert
    beider Rad-Steigungen), damit beide Raeder dieselbe Band-Breite
    bekommen.
    """
    if max_half is None:
        if slope == 0:
            return lo, hi
        max_half = 3.0 * abs(slope)
    lo_c = max(slope - max_half, lo)
    hi_c = min(slope + max_half, hi)
    # Punkt-Schaetzer muss immer im Band liegen
    lo_c = min(lo_c, slope)
    hi_c = max(hi_c, slope)
    return lo_c, hi_c


def crossings(treppen: List[Tuple[float, float]], y_level: float
               ) -> List[Tuple[float, float]]:
    """Schnittpunkte der Treppen-Prognose mit einem horizontalen Wert.

    Durchlaeuft die aufeinanderfolgenden Segmente und interpoliert jedes
    Mal den (km, y_level) wenn y_level zwischen den beiden Enden liegt.
    Bei vertikalen Reprof-Spruengen (gleiches km) wird der Punkt direkt
    uebernommen, wenn y_level zwischen vor und nach liegt.
    """
    out: List[Tuple[float, float]] = []
    if not treppen or len(treppen) < 2:
        return out
    for (x1, y1), (x2, y2) in zip(treppen, treppen[1:]):
        y_min, y_max = (y1, y2) if y1 <= y2 else (y2, y1)
        if not (y_min <= y_level <= y_max):
            continue
        if x1 == x2:
            # Vertikaler Sprung: Schnittpunkt am gemeinsamen x
            out.append((x1, y_level))
        else:
            # Lineare Interpolation
            t = (y_level - y1) / (y2 - y1) if y2 != y1 else 0.0
            out.append((x1 + t * (x2 - x1), y_level))
    return out


def ci_band(mr: Messreihe, cfg: PrognoseConfig, x_vals: List[float],
             flotte=None, achse=None) -> Optional[Tuple[List[float], List[float]]]:
    """Berechnet (lower, upper) um die lineare Prognose aus den Theil-Sen-
    Steigungsgrenzen (slope_low, slope_high).

    Robustheit:

    - **Achsen-Scope** (wenn ``achse`` gegeben): die CI-Steigungen werden
      aus den gepoolten Residuen BEIDER Raeder berechnet → identische
      Band-Breite links/rechts. Fallback: eigenes Rad-CI.
    - **CI-Clamp**: Theil-Sen-Grenzen werden auf max. 3× |slope| begrenzt,
      damit bei wenigen Punkten keine physikalisch unsinnigen Werte
      entstehen (z. B. −22 mm/1000 km durch dkm=0-Paare).
    - **Mindest-Qualitaet**: unterhalb ``min_points_fit`` wird kein Band
      gezeigt (``cycle_fit`` liefert dann None).

    Linien gehen vom letzten Messpunkt aus; damit entspricht die
    Darstellung der Backend-Konvention.
    """
    letzt = mr.letzter_wert()
    if letzt is None or letzt.laufleistung is None:
        return None
    fit = cycle_fit(mr, cfg, flotte=flotte, achse=achse)
    if fit is None:
        return None
    slope, _intercept, slope_low, slope_high = fit[:4]

    # Achsen-weites CI nur, wenn die Streuung beider Raeder tatsaechlich
    # vergleichbar ist (siehe _use_pooled_ci). Sonst behaelt jedes Rad
    # sein eigenes, aus seiner Historie berechnetes CI — asymmetrische
    # Streuung (z. B. defektes Rad, Kurvenlast) bleibt sichtbar.
    pooled_used = False
    if _use_pooled_ci(achse, cfg, flotte=flotte):
        pooled = _axle_pooled_ci(achse, cfg, flotte=flotte)
        if pooled is not None:
            pooled_lo, pooled_hi = pooled
            # Pooled-Residuen liefern Streuung um Null → auf aktuellen slope
            # verschieben, so dass das Band um die eigene Rad-Prognose
            # liegt (aber in der Breite identisch zum anderen Rad ist).
            slope_low = slope + pooled_lo
            slope_high = slope + pooled_hi
            pooled_used = True

    # Clamp gegen Pairwise-Ausreisser:
    # - individuell: Clamp mit eigenem |slope| (eng, ehrlich bei kleinen n).
    # - pooled: Clamp mit MITTEL-|slope| beider Raeder, damit beide
    #   Raeder denselben max_half bekommen und die Band-Breite symmetrisch
    #   bleibt. Ohne diesen Shared-Clamp koennte ein Rad mit kleinem
    #   |slope| ein kuenstlich enges Band bekommen.
    if pooled_used:
        max_half = 3.0 * (_axle_mean_abs_slope(achse, cfg, flotte=flotte) or abs(slope))
        slope_low, slope_high = _clamp_ci(slope, slope_low, slope_high, max_half=max_half)
    else:
        slope_low, slope_high = _clamp_ci(slope, slope_low, slope_high)

    lower = [letzt.stand + slope_high * (x - letzt.laufleistung) for x in x_vals]
    upper = [letzt.stand + slope_low * (x - letzt.laufleistung) for x in x_vals]
    low_fixed = [min(a, b) for a, b in zip(lower, upper)]
    up_fixed = [max(a, b) for a, b in zip(lower, upper)]
    return low_fixed, up_fixed
