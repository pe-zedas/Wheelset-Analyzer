"""
Vergleich zweier Prognose-CSV-Dateien (z. B. Gauss/alt vs. Theil-Sen/neu).

Liest BO_RADSATZDATEN_PROGNOSE-kompatible CSVs (Semikolon, UTF-8-sig), gruppiert nach
Fahrzeug / DG / Achse / ZARTBEZ und erzeugt pro gemeinsamer Gruppe ein LKD-km-Diagramm
ähnlich dem Hauptprogramm (Messbereich-Achse: Laufleistung, Ordinate: STAND = LKD mm).

Zusätzlich: Uebersichtsdiagramm Streuung Delta km Warn/Grenze (neu minus alt).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import numpy as np

try:
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib erforderlich: python -m pip install matplotlib") from exc

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from radsatz_settings import load_radsatz_config


def _parse_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    t = str(s).strip().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _row_axis_key(d: dict) -> Tuple[str, str, str, str]:
    return (
        (d.get("TOPEINHEITBEZEICHNUNG") or "").strip(),
        (d.get("DGEINBAUPOS") or "").strip(),
        (d.get("RSEINBAUPOS") or "").strip(),
        (d.get("ZARTBEZ") or "").strip(),
    )


def _title_from_row(d: dict) -> str:
    return (
        f"{(d.get('TOPEINHEITBEZEICHNUNG') or '').strip()} | "
        f"{(d.get('DGEINBAUPOS') or '').strip()} | "
        f"{(d.get('RSEINBAUPOS') or '').strip()} | "
        f"{(d.get('ZARTBEZ') or '').strip()}"
    )


def load_prognose_rows(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def group_rows(rows: List[dict]) -> Dict[Tuple[str, str, str, str], List[dict]]:
    g: DefaultDict[Tuple[str, str, str, str], List[dict]] = defaultdict(list)
    for d in rows:
        g[_row_axis_key(d)].append(d)
    for key in g:
        g[key].sort(key=lambda r: (_parse_float(r.get("LAUFLEISTUNG")) or 0.0))
    return dict(g)


def _curve_arrays(rows: List[dict]) -> Tuple[np.ndarray, np.ndarray]:
    km = []
    st = []
    for r in rows:
        k = _parse_float(r.get("LAUFLEISTUNG"))
        y = _parse_float(r.get("STAND"))
        if k is None or y is None:
            continue
        km.append(k)
        st.append(y)
    return np.asarray(km, dtype=float), np.asarray(st, dtype=float)


def _thresholds_from_last(rows: List[dict]) -> Tuple[float, float]:
    """KM_WARNWERT, KM_GRENZWERT (0 wenn leer/ungueltig)."""
    if not rows:
        return 0.0, 0.0
    last = rows[-1]
    kw = _parse_float(last.get("KM_WARNWERT")) or 0.0
    kg = _parse_float(last.get("KM_GRENZWERT")) or 0.0
    return kw, kg


def _safe_vline(ax, x: float, **kwargs) -> None:
    if x and x > 0 and np.isfinite(x):
        ax.axvline(x, **kwargs)


def plot_axis_compare(
    key: Tuple[str, str, str, str],
    rows_old: List[dict],
    rows_new: List[dict],
    out_path: str,
    figsize: Tuple[float, float],
    dpi: int,
) -> None:
    km_o, st_o = _curve_arrays(rows_old)
    km_n, st_n = _curve_arrays(rows_new)
    kw_o, kg_o = _thresholds_from_last(rows_old)
    kw_n, kg_n = _thresholds_from_last(rows_new)

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    if km_o.size:
        ax.plot(
            km_o, st_o, "o-", ms=4, lw=1.3, color="#cc5500", alpha=0.9,
            label="Gauss (alt)",
        )
    if km_n.size:
        ax.plot(
            km_n, st_n, "o-", ms=4, lw=1.3, color="#0a5f9e", alpha=0.9,
            label="Theil-Sen (neu)",
        )

    _safe_vline(ax, kw_o, color="#cc5500", ls=":", lw=1.2, alpha=0.55)
    _safe_vline(ax, kg_o, color="#cc5500", ls="--", lw=1.2, alpha=0.55)
    _safe_vline(ax, kw_n, color="#0a5f9e", ls=":", lw=1.2, alpha=0.55)
    _safe_vline(ax, kg_n, color="#0a5f9e", ls="--", lw=1.2, alpha=0.55)

    stats = (
        f"km Warn:  alt {kw_o:.0f}  neu {kw_n:.0f}  (Diff {kw_n - kw_o:+.0f})\n"
        f"km Grenze: alt {kg_o:.0f}  neu {kg_n:.0f}  (Diff {kg_n - kg_o:+.0f})"
    )
    ax.text(0.02, 0.02, stats, transform=ax.transAxes, fontsize=7, family="monospace",
            verticalalignment="bottom", bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.35))

    ax.set_xlabel("Laufleistung [km]", fontsize=11)
    ax.set_ylabel("Laufkreisdurchmesser [mm]", fontsize=11)
    ax.set_title("Prognose-Vergleich\n" + _title_from_row(rows_new[0] if rows_new else rows_old[0]), fontsize=9)
    ax.legend(fontsize=7, loc="upper right")
    ax.xaxis.set_ticks_position("bottom")
    ax.yaxis.set_ticks_position("left")
    y_all = np.concatenate([st_o, st_n]) if st_o.size or st_n.size else np.array([0.0])
    if y_all.size:
        m, M = float(np.min(y_all)), float(np.max(y_all))
        pad = max(2.0, (M - m) * 0.05)
        ax.set_ylim(m - pad, M + pad)
    fig.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


def _slug_key(key: Tuple[str, str, str, str]) -> str:
    raw = "|".join(key)
    s = re.sub(r"[^\w\-.]+", "_", raw, flags=re.UNICODE)[:160]
    return s or "achse"


def plot_delta_scatter(
    deltas: List[Tuple[str, float, float]],
    out_path: str,
    figsize: Tuple[float, float],
    dpi: int,
) -> None:
    if not deltas:
        return
    _, dw, dg = zip(*deltas)
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.scatter(dw, dg, s=22, alpha=0.65, c=np.arange(len(dw)), cmap="viridis")
    ax.axhline(0, color="gray", lw=0.8)
    ax.axvline(0, color="gray", lw=0.8)
    ax.set_xlabel("Delta km Warn (neu - alt)")
    ax.set_ylabel("Delta km Grenze (neu - alt)")
    ax.set_title("Streuung: Schwellen-Verschiebung je Zaehler/Achse")
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


def plot_summary_deltas(
    deltas: List[Tuple[str, float, float]],
    out_path: str,
    figsize: Tuple[float, float],
    dpi: int,
) -> None:
    if not deltas:
        return
    labels, d_warn, d_grenz = zip(*deltas)
    fig, ax = plt.subplots(figsize=(max(figsize[0], 12), figsize[1]), dpi=dpi)
    x = np.arange(len(labels))
    w = 0.35
    ax.bar(x - w / 2, d_warn, width=w, label="Delta km Warn (neu - alt)", color="#2a6f9a")
    ax.bar(x + w / 2, d_grenz, width=w, label="Delta km Grenze (neu - alt)", color="#cc5500")
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_ylabel("km")
    ax.set_title("Abstand Prognose-Schwellen: neu minus alt (je Zaehler/Achse)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=75, ha="right", fontsize=6)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prognose-CSV alt vs. neu vergleichen und plotten.")
    parser.add_argument(
        "--gauss",
        default=os.path.join(SCRIPT_DIR, "bo_radsatzdaten_prognose_recalc - Gauss_verb_Version.csv"),
        help="CSV Gauss / altes Verfahren",
    )
    parser.add_argument(
        "--neu",
        default=os.path.join(SCRIPT_DIR, "bo_radsatzdaten_prognose_recalc.csv"),
        help="CSV neues Verfahren",
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.join(SCRIPT_DIR, "prognose_vergleich_plots"),
        help="Ausgabeverzeichnis fuer PNGs",
    )
    parser.add_argument("--max-plots", type=int, default=0, help="Max. Achsen-Zeilenplots (0 = alle)")
    parser.add_argument("--no-summary", action="store_true", help="Kein Balkendiagramm Deltas")
    args = parser.parse_args()

    cfg = load_radsatz_config(SCRIPT_DIR)
    figsize = cfg.plot_figsize
    dpi = cfg.plot_dpi

    if not os.path.isfile(args.gauss):
        raise SystemExit(f"Gauss-CSV fehlt: {args.gauss}")
    if not os.path.isfile(args.neu):
        raise SystemExit(f"Neu-CSV fehlt: {args.neu}")

    rows_g = load_prognose_rows(args.gauss)
    rows_n = load_prognose_rows(args.neu)
    grp_g = group_rows(rows_g)
    grp_n = group_rows(rows_n)
    common = sorted(set(grp_g.keys()) & set(grp_n.keys()))
    only_g = set(grp_g.keys()) - set(grp_n.keys())
    only_n = set(grp_n.keys()) - set(grp_g.keys())

    print(f"Zeilen Gauss: {len(rows_g)}, Zeilen neu: {len(rows_n)}")
    print(f"Gruppen Gauss: {len(grp_g)}, neu: {len(grp_n)}, gemeinsam: {len(common)}")
    if only_g:
        print(f"Nur in Gauss-Datei: {len(only_g)} Gruppen (werden nicht einzeln geplottet)")
    if only_n:
        print(f"Nur in Neu-Datei: {len(only_n)} Gruppen")

    os.makedirs(args.out_dir, exist_ok=True)

    deltas: List[Tuple[str, float, float]] = []
    for key in common:
        kw_g, kg_g = _thresholds_from_last(grp_g[key])
        kw_n, kg_n = _thresholds_from_last(grp_n[key])
        short = f"{key[0][:12]}..." if len(key[0]) > 12 else key[0]
        z = key[3].replace("Rad-Laufkreisdurchmesser-", "D")
        deltas.append((f"{short} / {z}", kw_n - kw_g, kg_n - kg_g))

    n_plot = 0
    limit = args.max_plots if args.max_plots > 0 else len(common)
    for key in common:
        if n_plot >= limit:
            break
        slug = _slug_key(key)
        out_png = os.path.join(args.out_dir, f"prognose_vergleich_{slug}.png")
        plot_axis_compare(key, grp_g[key], grp_n[key], out_png, figsize, dpi)
        n_plot += 1

    print(f"Gespeichert: {n_plot} Diagramme unter {args.out_dir}")

    if not args.no_summary and deltas:
        sum_path = os.path.join(args.out_dir, "prognose_vergleich_delta_schwellen.png")
        # Bei sehr vielen Balken nur erste max 80 fuer Lesbarkeit
        d_use = deltas[:80] if len(deltas) > 80 else deltas
        plot_summary_deltas(d_use, sum_path, figsize, dpi)
        print(f"Uebersicht Delta-Schwellen: {sum_path}")
        if len(deltas) > 80:
            print("(Uebersicht Balken gekuerzt auf 80 Eintraege; Streudiagramm nutzt alle.)")
        sc_path = os.path.join(args.out_dir, "prognose_vergleich_delta_scatter.png")
        plot_delta_scatter(deltas, sc_path, figsize, dpi)
        print(f"Streudiagramm Deltas: {sc_path}")


if __name__ == "__main__":
    main()
