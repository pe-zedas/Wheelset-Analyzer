"""
Radsatz_Bahn_DB_KM_Gauss_Class_All_Enhanced.py

Legacy-Standalone (eigene Prognose-CSV mit Suffix _gauss_enhanced).
Empfohlen: Radsatz_Bahn_DB_new_Approach.py mit prognosis_method = gauss in radsatz_config.ini.

Nutzt prognosis_gauss.run_gauss_prognosis_for_vehicle (gemeinsame Gauss-Logik).
"""

import csv
import os
import re
import logging
from datetime import datetime, timedelta
from typing import Tuple

import numpy as np

try:
    import oracledb
except ModuleNotFoundError as exc:
    raise ImportError(
        "Oracle-Treiber nicht gefunden. Installiere mit: python -m pip install oracledb"
    ) from exc

from datetime2matlabdn import datetime2matlabdn
from MeterList import MeterList
from VehicleAxis import VehicleAxis
from radsatz_settings import axis_key_matches_debug, load_radsatz_config
from radsatz_csv_io import load_bo_radsatz_from_csv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
cfg = load_radsatz_config(SCRIPT_DIR)

from radsatz_matplotlib import configure_matplotlib_backend

MPL_BACKEND = configure_matplotlib_backend(
    cfg.plot_matplotlib_backend,
    cfg.plot_show_window and cfg.show_plot,
)
import matplotlib.pyplot as plt

from prognosis_gauss import (
    progn_result_for_plot_from_gauss_meter,
    run_gauss_prognosis_for_vehicle,
)
from radsatz_axis_labels import (
    format_axis_plot_title,
    prognosis_method_plot_label,
    sync_axis_labels_from_measurement_row,
)
from reprof_learning import (
    learn_reprofiling_params,
    learn_reprofiling_params_per_axis,
    reprofiling_params_from_radsatz_config,
    set_reprofiling_params_per_axis,
)

useDatabase = cfg.use_database
write_Prog_Data = cfg.write_prog_data
showPlot = cfg.show_plot
CSV_BO_RADSATZDATEN = cfg.csv_bo_radsatzdaten


def _gauss_enhanced_prognose_csv_path(base_path: str) -> str:
    root, ext = os.path.splitext(base_path)
    if not ext:
        ext = ".csv"
    return f"{root}_gauss_enhanced{ext}"


CSV_BO_PROGNOSE_OUT = _gauss_enhanced_prognose_csv_path(cfg.csv_bo_prognose_out)

dtStartData = cfg.dt_start_data
nDays2Delete = cfg.n_days_2_delete

logging.basicConfig(
    filename=cfg.log_file,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.info("=== Radsatz_Bahn_DB_KM_Gauss_Class_All_Enhanced gestartet ===")
logging.info("Matplotlib-Backend: %s", MPL_BACKEND)
logging.info("Prognose-CSV: %s", CSV_BO_PROGNOSE_OUT)

_PROGNOSE_CSV_HEADER = [
    "TOPEINHEITID",
    "TOPEINHEITBEZEICHNUNG",
    "DGEINHEITID",
    "DGBEZEICHNUNG",
    "DGEINBAUPOS",
    "RSEINHEITID",
    "RSBEZEICHNUNG",
    "RSEINBAUPOS",
    "EINBAU",
    "AUSBAU",
    "AKTUELL",
    "ZAEHLERARTID",
    "ZARTBEZ",
    "STAND",
    "DATUM",
    "LAUFLEISTUNG",
    "LETZTEAENDZEIT",
    "KM_GRENZWERT",
    "DATUM_GRENZWERT",
    "KM_WARNWERT",
    "DATUM_WARNWERT",
]


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


def _show_plot_figure(fig, title: str = "") -> None:
    if not cfg.plot_show_window:
        plt.close(fig)
        return
    from radsatz_matplotlib import block_until_figure_closed

    block_until_figure_closed(fig, title=title)


def _plot_meter_history(
    ax,
    met: MeterList,
    n_cycle_start: int,
    color: str,
    meter_label: str,
) -> Tuple[np.ndarray, np.ndarray]:
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


def _plot_axis_gauss(tmpVehicle: VehicleAxis, key: str, n_km_repro: float, n_val_repro: float) -> None:
    n_index1 = tmpVehicle.getmeterList1().getindexStartLastCycle()
    n_index2 = tmpVehicle.getmeterList2().getindexStartLastCycle()
    m1 = tmpVehicle.getmeterList1()
    m2 = tmpVehicle.getmeterList2()

    fig, ax = plt.subplots(figsize=cfg.plot_figsize, dpi=cfg.plot_dpi)
    if cfg.plot_show_window:
        from radsatz_matplotlib import ensure_interactive_plot_session

        ensure_interactive_plot_session()

    km1_all, lkd1_all = _plot_meter_history(ax, m1, n_index1, "blue", "LKD1")
    km2_all, lkd2_all = _plot_meter_history(ax, m2, n_index2, "green", "LKD2")

    if m1.getkmProg():
        ax.plot(
            m1.getkmProg(),
            m1.getvaluesProg(),
            color="blue",
            lw=1.3,
            ls=":",
            label="LKD1 Prognose (Gauss)",
        )
    if m2.getkmProg():
        ax.plot(
            m2.getkmProg(),
            m2.getvaluesProg(),
            color="green",
            lw=1.3,
            ls=":",
            label="LKD2 Prognose (Gauss)",
        )

    if len(m1.getmin()) > 0:
        ax.axhline(
            m1.getmin()[-1],
            color="red",
            lw=1.8,
            ls="-",
            label=f"MIN ({m1.getmin()[-1]:.0f} mm)",
        )
        ax.axhline(m1.getmax()[-1], color="red", lw=1.8, ls="-")
        ax.axhline(
            m1.getgelb_min()[-1],
            color="gold",
            lw=1.8,
            ls="-",
            label=f"GELB_MIN ({m1.getgelb_min()[-1]:.0f} mm)",
        )

    def _annotate_gelb(met: MeterList, color: str, text: str) -> None:
        km_g = met.getgelb_min_Prog_km()
        gelb = met.getgelb_min()[-1] if met.getgelb_min() else None
        if km_g and km_g > 0 and gelb is not None:
            ax.plot([km_g], [gelb], marker="v", color=color, ms=8, zorder=5, linestyle="None")
            ax.annotate(
                text,
                xy=(km_g, gelb),
                xytext=(km_g, gelb + 8),
                fontsize=8,
                color=color,
                arrowprops=dict(arrowstyle="->", color=color, lw=0.8),
            )

    _annotate_gelb(m1, "blue", "D1 Gelb")
    _annotate_gelb(m2, "green", "D2 Gelb")

    ax.set_xlabel("Laufleistung [km]", fontsize=11)
    ax.set_ylabel("Laufkreisdurchmesser [mm]", fontsize=11)
    method_label = prognosis_method_plot_label(cfg)
    plot_title = format_axis_plot_title(tmpVehicle, method_label)
    ax.set_title(plot_title, fontsize=10)

    if len(m1.getmin()) > 0:
        margin = 5
        y_lo = float(m1.getmin()[-1]) - margin
        y_hi = float(m1.getmax()[-1]) + margin
        meas = np.concatenate(
            [a for a in (lkd1_all, lkd2_all) if a.size > 0],
            dtype=float,
        )
        if meas.size:
            y_lo = min(y_lo, float(np.min(meas)) - margin)
            y_hi = max(y_hi, float(np.max(meas)) + margin)
        ax.set_ylim(y_lo, y_hi)

    ax.legend(fontsize=7, loc="upper right")
    ax.xaxis.set_ticks_position("bottom")
    ax.yaxis.set_ticks_position("left")

    if cfg.plot_output_dir:
        os.makedirs(cfg.plot_output_dir, exist_ok=True)
        safe = re.sub(r"[^\w\-.]+", "_", key, flags=re.UNICODE)[:180]
        plot_path = os.path.join(cfg.plot_output_dir, f"prognose_gauss_{safe}.png")
        plt.savefig(plot_path, dpi=cfg.plot_dpi)
        logging.info("Diagramm gespeichert: %s", plot_path)

    if cfg.plot_show_window:
        logging.info("Plot-Fenster: %s", key)
        print(f"Plot: {key}  — Fenster schließen für die nächste Achse.")
        _show_plot_figure(fig, title=plot_title)
    else:
        plt.close(fig)


def main() -> None:
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

    dict_VehicleAxis = {}
    for strVehicle in res1:
        dict_VehicleAxis[strVehicle[0] + strVehicle[1] + strVehicle[2]] = VehicleAxis(
            strVehicle[0],
            strVehicle[1],
            strVehicle[2],
            MeterList([], [], [], [], [], [], []),
            MeterList([], [], [], [], [], [], []),
        )

    if not res2:
        print("Keine Messdaten gefunden.")
        logging.warning("Keine Messdaten gefunden (res2 leer).")
        logging.info("=== Gauss Enhanced beendet ===")
        return

    try:
        for r in res2:
            axis_key = r[0] + r[1] + r[2]
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

            met = (
                tVehicle.getmeterList1()
                if r[3] == "Rad-Laufkreisdurchmesser-1"
                else tVehicle.getmeterList2()
            )
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

        for tmpVehicle in dict_VehicleAxis.values():
            for met in (tmpVehicle.getmeterList1(), tmpVehicle.getmeterList2()):
                dates = met.getstrDates()
                if len(dates) > 1:
                    met.setnDates([datetime2matlabdn(d) for d in dates])

        ini_reprof = reprofiling_params_from_radsatz_config(cfg)
        fleet_reprof = learn_reprofiling_params(dict_VehicleAxis)
        per_axis_reprof = learn_reprofiling_params_per_axis(
            dict_VehicleAxis,
            ini_fallback=ini_reprof,
        )
        set_reprofiling_params_per_axis(per_axis_reprof, fleet_fallback=ini_reprof)
        logging.info("Reprofilierung ini-Fallback: %s", ini_reprof)
        logging.info("Reprofilierung Flotte (Vergleich): %s", fleet_reprof)

        plot_count = 0
        if showPlot:
            plt.ioff()
            if cfg.plot_show_window:
                print(
                    f"Matplotlib-Backend: {MPL_BACKEND} — "
                    "jedes Plotfenster schließen (X), dann erscheint die nächste Achse."
                )

        for key, tmpVehicle in dict_VehicleAxis.items():
            m1 = tmpVehicle.getmeterList1()
            m2 = tmpVehicle.getmeterList2()

            if len(m1.getstrDates()) <= 1 or len(m2.getstrDates()) <= 1:
                logging.warning(
                    "Zu wenig Messdaten (LKD1=%d, LKD2=%d): %s %s %s",
                    len(m1.getstrDates()),
                    len(m2.getstrDates()),
                    tmpVehicle.getstrVDesc(),
                    tmpVehicle.getstrBogie(),
                    tmpVehicle.getstrPosAxis(),
                )
                continue

            if axis_key_matches_debug(
                cfg,
                tmpVehicle.getstrVDesc(),
                tmpVehicle.getstrBogie(),
                tmpVehicle.getstrPosAxis(),
            ):
                print(key)

            try:
                gauss_res = run_gauss_prognosis_for_vehicle(tmpVehicle, key, cfg)
                if not gauss_res.ok:
                    continue

                if showPlot:
                    plot_count += 1
                    if cfg.plot_show_window:
                        print(f"Plot {plot_count}: {key}")
                    _plot_axis_gauss(
                        tmpVehicle,
                        key,
                        gauss_res.n_km_repro,
                        gauss_res.n_value_repro,
                    )

            except Exception:
                logging.exception("Gauss-Prognose fehlgeschlagen für: %s", key)

        if showPlot and cfg.plot_show_window:
            print(f"Alle Plotfenster fertig ({plot_count} Diagramm(e)).")

    except Exception:
        logging.exception("Fehler beim Aufbereiten der Messdaten.")

    if write_Prog_Data:
        if useDatabase:
            con = oracledb.connect(str_connection)
            cur = con.cursor()
            date_cutoff = datetime.now() - timedelta(days=nDays2Delete)
            cur.execute(
                "delete from BO_RADSATZDATEN_PROGNOSE where LETZTEAENDZEIT < :dtLAend",
                {"dtLAend": date_cutoff},
            )
            con.commit()
            for tmpVehicle in dict_VehicleAxis.values():
                tmpVehicle.write_Prog_Data(cur, con)
            cur.close()
            con.close()
        else:
            with open(CSV_BO_PROGNOSE_OUT, "w", newline="", encoding="utf-8-sig") as csvfile:
                writer = csv.writer(csvfile, delimiter=";")
                writer.writerow(_PROGNOSE_CSV_HEADER)
                for tmpVehicle in dict_VehicleAxis.values():
                    for zeile in tmpVehicle.iter_prognose_insert_tuples():
                        writer.writerow(
                            [_prognose_csv_zelle(i, z) for i, z in enumerate(zeile)]
                        )
            print(f"Prognose-CSV geschrieben: {CSV_BO_PROGNOSE_OUT}")
            logging.info("Prognose-CSV geschrieben: %s", CSV_BO_PROGNOSE_OUT)

    logging.info("=== Radsatz_Bahn_DB_KM_Gauss_Class_All_Enhanced beendet ===")


if __name__ == "__main__":
    main()
