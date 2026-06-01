"""Laden von radsatz_config.ini (optional); Standardwerte wie zuvor im Skript."""

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass
from typing import Any, List, Tuple


CONFIG_BASENAME = "radsatz_config.ini"

PROGNOSIS_METHOD_THEIL_SEN = "theil_sen"
PROGNOSIS_METHOD_GAUSS = "gauss"

_PROGNOSIS_METHOD_ALIASES = {
    "gauss": PROGNOSIS_METHOD_GAUSS,
    "gauss_newton": PROGNOSIS_METHOD_GAUSS,
    "theil_sen": PROGNOSIS_METHOD_THEIL_SEN,
    "theilsen": PROGNOSIS_METHOD_THEIL_SEN,
    "new": PROGNOSIS_METHOD_THEIL_SEN,
    "neu": PROGNOSIS_METHOD_THEIL_SEN,
    "new_approach": PROGNOSIS_METHOD_THEIL_SEN,
}


def normalize_prognosis_method(raw: str) -> str:
    key = _strip(raw).lower().replace("-", "_")
    return _PROGNOSIS_METHOD_ALIASES.get(key, PROGNOSIS_METHOD_THEIL_SEN)


def normalize_prognosis_methods(raw: str) -> Tuple[str, ...]:
    """
    Liest eine einzelne Methode oder kommagetrennte Liste.
    Beispiel: "theil_sen, gauss" -> ("theil_sen", "gauss")
    """
    s = _strip(raw)
    if not s:
        return (PROGNOSIS_METHOD_THEIL_SEN,)
    out: List[str] = []
    for part in re.split(r"[;,]", s):
        m = normalize_prognosis_method(part)
        if m not in out:
            out.append(m)
    return tuple(out) if out else (PROGNOSIS_METHOD_THEIL_SEN,)


def _strip(s: Any) -> str:
    return str(s).strip() if s is not None else ""


def _bool(raw: str, default: bool) -> bool:
    s = _strip(raw).lower()
    if not s:
        return default
    if s in ("1", "true", "yes", "on", "ja"):
        return True
    if s in ("0", "false", "no", "off", "nein"):
        return False
    return default


def _int(raw: str, default: int) -> int:
    s = _strip(raw).replace(",", ".")
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def _float(raw: str, default: float) -> float:
    s = _strip(raw).replace(",", ".")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _float_list(raw: str, default: List[float]) -> List[float]:
    s = _strip(raw)
    if not s:
        return list(default)
    out: List[float] = []
    for part in re.split(r"[;,]", s):
        p = part.strip().replace(",", ".")
        if not p:
            continue
        try:
            out.append(float(p))
        except ValueError:
            continue
    return out if out else list(default)


def _int_list(raw: str, default: List[int]) -> List[int]:
    s = _strip(raw)
    if not s:
        return list(default)
    out: List[int] = []
    for part in re.split(r"[;,]", s):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(float(p)))
        except ValueError:
            continue
    return out if out else list(default)


def _abs_path(script_dir: str, path: str) -> str:
    path = _strip(path)
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(script_dir, path))


@dataclass(frozen=True)
class RadsatzConfig:
    script_dir: str
    use_database: bool
    write_prog_data: bool
    show_plot: bool
    plot_output_dir: str
    plot_show_window: bool
    plot_matplotlib_backend: str
    plot_figsize: Tuple[float, float]
    plot_dpi: int
    # Nur Achsen plotten, deren TOPEINHEITBEZEICHNUNG|DG|Achse den Text enthält (z. B. FLIRT 101)
    plot_top_einheit_filter: str
    debug_print_axis_keys: str
    log_file: str
    oracle_connect_filename: str
    oracle_arraysize: int
    csv_bo_radsatzdaten: str
    csv_bo_prognose_out: str
    dt_start_data: str
    n_km: int
    def_jump_repro: float
    n_km_repro: float
    n_value_repro: float
    reprof_dkm_threshold: float
    reprof_dlkd_abs_min: float
    def_param_exp: List[float]
    diff_lkd: float
    n_days_2_delete: int
    # theil_sen | gauss — Abschnitt [prognose], Schlüssel prognosis_method
    prognosis_method: str
    # Reihenfolge der auszuführenden Methoden (1..n), z. B. ("theil_sen","gauss")
    prognosis_methods: Tuple[str, ...]
    # Neuer Prognose-Ansatz (Theil-Sen / IQR), Abschnitt [prognose_new] in radsatz_config.ini
    progn_new_min_points_fit: int
    progn_new_min_points_quality: int
    progn_new_iqr_factor: float
    progn_new_ci_alpha: float
    progn_new_rmse_threshold_mm: float
    progn_new_n_prog_points: int
    progn_new_cv_tune: bool
    progn_new_cv_tune_iqr_factors: Tuple[float, ...]
    progn_new_cv_tune_min_points_fit: Tuple[int, ...]
    progn_new_cv_tune_objective: str
    progn_new_cv_tune_min_total_folds: int
    # Optionaler Fallback bei Theil-Sen INSUFFICIENT: Baureihen-Mittelanstieg nutzen
    progn_new_baureihe_fallback: bool


def load_radsatz_config(script_dir: str) -> RadsatzConfig:
    ini_path = os.path.join(script_dir, CONFIG_BASENAME)
    cp = configparser.ConfigParser()
    if os.path.isfile(ini_path):
        cp.read(ini_path, encoding="utf-8")

    def opt(section: str, key: str, default: str) -> str:
        if cp.has_option(section, key):
            return cp.get(section, key)
        return default

    use_database = _bool(opt("pipeline", "use_database", "false"), False)
    write_prog_data = _bool(opt("pipeline", "write_prog_data", "false"), False)

    show_plot = _bool(opt("plot", "show_plot", "true"), True)
    plot_output_dir = _abs_path(script_dir, opt("plot", "plot_output_dir", ""))
    plot_show_window = _bool(opt("plot", "plot_show_window", "true"), True)
    plot_mpl_backend = _strip(opt("plot", "matplotlib_backend", "Qt5Agg"))
    plot_w = _float(opt("plot", "figure_width", "20"), 20.0)
    plot_h = _float(opt("plot", "figure_height", "8"), 8.0)
    plot_dpi = _int(opt("plot", "figure_dpi", "80"), 80)
    plot_te_filter = _strip(opt("plot", "plot_top_einheit_filter", ""))
    debug_keys = _strip(opt("plot", "debug_print_axis_keys", ""))

    log_rel = _strip(opt("logging", "log_file", "Prog_Radsatzdaten.log")) or "Prog_Radsatzdaten.log"
    log_file = _abs_path(script_dir, log_rel)

    oracle_fn = _strip(opt("paths", "oracle_connect_filename", "oracle_connect_string.txt"))
    oracle_arraysize = _int(opt("oracle", "arraysize", "500"), 500)

    csv_in = _strip(opt("paths", "csv_bo_radsatzdaten", "bo_radsatzdaten_export.csv"))
    csv_out = _strip(opt("paths", "csv_bo_prognose_out", "bo_radsatzdaten_prognose_recalc.csv"))

    dt_start = _strip(opt("prognose", "dt_start_data", "2014-01-01")) or "2014-01-01"
    n_km = _int(opt("prognose", "n_km", "300000"), 300000)
    def_jump = _float(opt("prognose", "def_jump_repro", "-150"), -150.0)
    n_km_repro = _float(opt("prognose", "n_km_repro", "30000"), 30000.0)
    n_value_repro = _float(opt("prognose", "n_value_repro", "6"), 6.0)
    reprof_dkm_thr = _float(opt("prognose", "reprof_dkm_threshold", "5000"), 5000.0)
    reprof_dlkd_min = _float(opt("prognose", "reprof_dlkd_abs_min", "3"), 3.0)
    a0 = _float(opt("prognose", "def_param_exp_a0", "-7.7"), -7.7)
    a1 = _float(opt("prognose", "def_param_exp_a1", "0.09"), 0.09)
    diff_lkd = _float(opt("prognose", "diff_lkd", "20"), 20.0)
    n_days_2_delete = _int(opt("prognose", "n_days_2_delete", "14"), 14)

    prognosis_methods = normalize_prognosis_methods(
        opt("prognose", "prognosis_method", "theil_sen")
    )
    prognosis_method = prognosis_methods[0]

    sec_new = "prognose_new"
    pn_min_fit = _int(opt(sec_new, "min_points_fit", "4"), 4)
    pn_min_qual = _int(opt(sec_new, "min_points_quality", "8"), 8)
    pn_iqr = _float(opt(sec_new, "iqr_factor", "2.0"), 2.0)
    pn_ci = _float(opt(sec_new, "ci_alpha", "0.90"), 0.90)
    pn_rmse = _float(opt(sec_new, "rmse_threshold_mm", "0.5"), 0.5)
    pn_nprog = _int(opt(sec_new, "n_prog_points", "20"), 20)
    pn_cv_tune = _bool(opt(sec_new, "cv_tune", "false"), False)
    pn_cv_iqrs = _float_list(opt(sec_new, "cv_tune_iqr_factors", "1.5,2.0,2.5"), [1.5, 2.0, 2.5])
    pn_cv_mpf = _int_list(opt(sec_new, "cv_tune_min_points_fit", "4,5,6"), [4, 5, 6])
    pn_cv_obj = _strip(opt(sec_new, "cv_tune_objective", "mae")).lower() or "mae"
    if pn_cv_obj not in ("mae", "rmse"):
        pn_cv_obj = "mae"
    pn_cv_min_folds = _int(opt(sec_new, "cv_tune_min_total_folds", "30"), 30)
    pn_baureihe_fallback = _bool(opt(sec_new, "baureihe_fallback", "false"), False)

    return RadsatzConfig(
        script_dir=script_dir,
        use_database=use_database,
        write_prog_data=write_prog_data,
        show_plot=show_plot,
        plot_output_dir=plot_output_dir,
        plot_show_window=plot_show_window,
        plot_matplotlib_backend=plot_mpl_backend,
        plot_figsize=(plot_w, plot_h),
        plot_dpi=plot_dpi,
        plot_top_einheit_filter=plot_te_filter,
        debug_print_axis_keys=debug_keys,
        log_file=log_file,
        oracle_connect_filename=oracle_fn or "oracle_connect_string.txt",
        oracle_arraysize=oracle_arraysize,
        csv_bo_radsatzdaten=_abs_path(script_dir, csv_in or "bo_radsatzdaten_export.csv"),
        csv_bo_prognose_out=_abs_path(script_dir, csv_out or "bo_radsatzdaten_prognose_recalc.csv"),
        dt_start_data=dt_start,
        n_km=n_km,
        def_jump_repro=def_jump,
        n_km_repro=n_km_repro,
        n_value_repro=n_value_repro,
        reprof_dkm_threshold=reprof_dkm_thr,
        reprof_dlkd_abs_min=reprof_dlkd_min,
        def_param_exp=[a0, a1],
        diff_lkd=diff_lkd,
        n_days_2_delete=n_days_2_delete,
        prognosis_method=prognosis_method,
        prognosis_methods=prognosis_methods,
        progn_new_min_points_fit=pn_min_fit,
        progn_new_min_points_quality=pn_min_qual,
        progn_new_iqr_factor=pn_iqr,
        progn_new_ci_alpha=pn_ci,
        progn_new_rmse_threshold_mm=pn_rmse,
        progn_new_n_prog_points=pn_nprog,
        progn_new_cv_tune=pn_cv_tune,
        progn_new_cv_tune_iqr_factors=tuple(pn_cv_iqrs),
        progn_new_cv_tune_min_points_fit=tuple(pn_cv_mpf),
        progn_new_cv_tune_objective=pn_cv_obj,
        progn_new_cv_tune_min_total_folds=pn_cv_min_folds,
        progn_new_baureihe_fallback=pn_baureihe_fallback,
    )


def axis_key_matches_debug(cfg: RadsatzConfig, vehicle_desc: str, bogie: str, axis_pos: str) -> bool:
    """True, wenn die Achse zu den konfigurierten Debug-Schlüsseln passt (Teilstrings)."""
    raw = cfg.debug_print_axis_keys
    if not raw:
        return False
    blob = f"{vehicle_desc}|{bogie}|{axis_pos}"
    for part in re.split(r"[;,]", raw):
        p = part.strip()
        if p and p in blob:
            return True
    return False
