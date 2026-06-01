#import math
import csv
import os
import re
import numpy as np
import matplotlib.pyplot as plt
#from matplotlib.widgets import Cursor
#import pandas as pd
#import scipy as sc
import logging
#from scipy.linalg._solve_toeplitz import float64
from datetime import datetime,timedelta
#from pylab import *
#from GaussNewtonLinearReg_Exp import GaussNewtonLinearReg_ExpNorm
from datetime2matlabdn import datetime2matlabdn
from toolsWheelset import getStartIndexLastCycle
try:
    import oracledb
except ModuleNotFoundError as exc:
    raise ImportError(
        "Oracle-Treiber nicht gefunden. Installiere 'python-oracledb' "
        "mit: python -m pip install oracledb"
    ) from exc

from MeterList import MeterList
from VehicleAxis import VehicleAxis
from radsatz_settings import axis_key_matches_debug, load_radsatz_config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
cfg = load_radsatz_config(SCRIPT_DIR)

useDatabase = cfg.use_database
write_Prog_Data = cfg.write_prog_data
showPlot = cfg.show_plot
CSV_BO_RADSATZDATEN = cfg.csv_bo_radsatzdaten
CSV_BO_PROGNOSE_OUT = cfg.csv_bo_prognose_out

logging.basicConfig(
    filename=cfg.log_file,
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
    datefmt="%m/%d/%Y %I:%M:%S %p",
)
logging.info("Started")

# Spalten wie BO_RADSATZDATEN_PROGNOSE: STAND = prognost. LKD [mm] (typ. < 600),
# LAUFLEISTUNG / KM_GRENZWERT / KM_WARNWERT = Kilometer [km] (große Zahlen normal).
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


def load_connect_string(script_dir, connect_filename):
    env = os.environ.get("ORACLE_CONNECT_STRING", "").strip()
    if env:
        return env
    path = os.path.join(script_dir, connect_filename)
    try:
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError as exc:
        raise SystemExit(
            f"Connect-String-Datei fehlt oder nicht lesbar: {path}\n{exc}"
        ) from exc
    if not line or line.startswith("#"):
        raise SystemExit(
            f"In {connect_filename} muss die Verbindungszeile (eine Zeile) stehen."
        )
    return line


def _parse_csv_datetime(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_csv_number(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    return float(s)


def _ausbau_leer(d):
    v = d.get("AUSBAU")
    if v is None:
        return True
    return str(v).strip() == ""


def _csv_row_to_res2_tuple(d):
    """Reihenfolge wie die bisherige SQL-Abfrage (Indizes r[0]…r[18])."""
    return (
        d["TOPEINHEITBEZEICHNUNG"].strip(),
        d["DGEINBAUPOS"].strip(),
        d["RSEINBAUPOS"].strip(),
        d["ZARTBEZ"].strip(),
        _parse_csv_datetime(d.get("DATUM")),
        _parse_csv_number(d.get("STAND")),
        _parse_csv_number(d.get("LAUFLEISTUNG")),
        _parse_csv_number(d.get("MIN")),
        _parse_csv_number(d.get("MAX")),
        _parse_csv_number(d.get("GELB_MIN")),
        _parse_csv_number(d.get("TOPEINHEITID")),
        _parse_csv_number(d.get("DGEINHEITID")),
        (d.get("DGBEZEICHNUNG") or "").strip(),
        _parse_csv_number(d.get("RSEINHEITID")),
        (d.get("RSBEZEICHNUNG") or "").strip(),
        _parse_csv_datetime(d.get("EINBAU")),
        _parse_csv_datetime(d.get("AUSBAU")),
        int(_parse_csv_number(d.get("AKTUELL")))
        if _parse_csv_number(d.get("AKTUELL")) is not None
        else None,
        _parse_csv_number(d.get("ZAEHLERARTID")),
    )


def load_bo_radsatz_from_csv(csv_path, dt_start_str):
    """Liefert (res1, res2) wie die beiden Oracle-Abfragen."""
    dt_start = datetime.strptime(dt_start_str, "%Y-%m-%d")
    bez_z1 = "Rad-Laufkreisdurchmesser-1"
    bez_z2 = "Rad-Laufkreisdurchmesser-2"
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            rdr = csv.DictReader(f, delimiter=";")
            zeilen = list(rdr)
    except OSError as exc:
        raise SystemExit(f"CSV nicht lesbar: {csv_path}\n{exc}") from exc
    if not zeilen:
        return [], []

    res1_keys = set()
    res1 = []
    for d in zeilen:
        if not _ausbau_leer(d):
            continue
        key = (
            d["TOPEINHEITBEZEICHNUNG"].strip(),
            d["DGEINBAUPOS"].strip(),
            d["RSEINBAUPOS"].strip(),
        )
        if key not in res1_keys:
            res1_keys.add(key)
            res1.append(key)

    res2 = []
    for d in zeilen:
        if not _ausbau_leer(d):
            continue
        zb = (d.get("ZARTBEZ") or "").strip()
        if zb not in (bez_z1, bez_z2):
            continue
        dt_mess = _parse_csv_datetime(d.get("DATUM"))
        if dt_mess is None or dt_mess <= dt_start:
            continue
        res2.append(_csv_row_to_res2_tuple(d))

    res2.sort(key=lambda r: r[4] or datetime.min)
    return res1, res2


def _prognose_csv_zelle(spalte, wert):
    """Formatiert eine Zelle der Prognose-CSV (Spaltenindex 0..20 wie INSERT)."""
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

dtStartData = cfg.dt_start_data
nKm = cfg.n_km
defJumpRepro = cfg.def_jump_repro
nKmRepro = cfg.n_km_repro
nValueRepro = cfg.n_value_repro
defParamExp = list(cfg.def_param_exp)
diffLKD = cfg.diff_lkd
nDays2Delete = cfg.n_days_2_delete

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
# Gehe über alle Fahrzeuge
dict_VehicleAxis={}

for strVehicle in res1:
    dict_VehicleAxis[strVehicle[0] + strVehicle[1] + strVehicle[2]]=VehicleAxis(strVehicle[0], strVehicle[1],strVehicle[2], MeterList(list(),list(),list(),list(),list(),list(),list()),MeterList(list(),list(),list(),list(),list(),list(),list()))
    
#    nA=np.where(dy > diffLKD)
if len(res2) > 0:
    try:
        # Auslesen der Werte aus der DB-Ergebnisliste
        pDate1=list() 
        pKmValues1=list()
        qValues1=list() 
        pDate2=list() 
        pKmValues2=list()
        qValues2=list() 
        
        #zArt=list() 
        #tVehicle=VehicleAxis
        # Aufteilen in LKD1 und LKD2 in zwei Listen
        for r in res2:
            axis_key = r[0] + r[1] + r[2]
            tVehicle = dict_VehicleAxis.get(axis_key)
            if tVehicle is None:
                logging.warning(
                    "Eintrag nicht im Dictionary (Achsschlüssel fehlt): %s | %s | %s",
                    r[0],
                    r[1],
                    r[2],
                )
                continue
            if r[4] != None and r[5] != None and r[6] != None and r[7] != None and r[8] != None and r[9] != None:
                if r[3] == 'Rad-Laufkreisdurchmesser-1':
                    tVehicle.getmeterList1().getstrDates().append(r[4])
                    tVehicle.getmeterList1().getvalues().append(r[5])
                    tVehicle.getmeterList1().getkm().append(r[6])
                    tVehicle.getmeterList1().getmin().append(r[7])
                    tVehicle.getmeterList1().getmax().append(r[8])
                    tVehicle.getmeterList1().getgelb_min().append(r[9])
                    tVehicle.getmeterList1().setzaehlerartid(r[18])
                    tVehicle.getmeterList1().setzartbez(r[3])
                elif r[3] == 'Rad-Laufkreisdurchmesser-2':
                    tVehicle.getmeterList2().getstrDates().append(r[4])
                    tVehicle.getmeterList2().getvalues().append(r[5])
                    tVehicle.getmeterList2().getkm().append(r[6])
                    tVehicle.getmeterList2().getmin().append(r[7])
                    tVehicle.getmeterList2().getmax().append(r[8])
                    tVehicle.getmeterList2().getgelb_min().append(r[9])
                    tVehicle.getmeterList2().setzaehlerartid(r[18])
                    tVehicle.getmeterList2().setzartbez(r[3])
                tVehicle.settopeinheitid(r[10])
                tVehicle.setdgeinheitid(r[11])
                tVehicle.setdgbezeichnung(r[12])
                tVehicle.setrseinheitid(r[13])
                tVehicle.setrsbezeichnung(r[14])
                tVehicle.seteinbau(r[15])
                tVehicle.setausbau(r[16])
                tVehicle.setaktuell(r[17])

            else:
                print('Zählerdaten nicht vollständig für :' + r[0]+ ' ' + r[1] + ' ' + r[2])
                logging.warning('Zählerdaten nicht vollständig für :' + r[0]+ ' ' + r[1] + ' ' + r[2])
                    
        for key in dict_VehicleAxis:
            tmpVehicle = dict_VehicleAxis[key]
            m1 = tmpVehicle.getmeterList1()
            m2 = tmpVehicle.getmeterList2()
            dates1 = m1.getstrDates()
            dates2 = m2.getstrDates()

            if len(dates1) > 1:
                m1.setnDates([datetime2matlabdn(d) for d in dates1])
            if len(dates2) > 1:
                m2.setnDates([datetime2matlabdn(d) for d in dates2])

            # Prognose für beide LKD-Zähler: je mehr als ein Messpunkt (Zyklus-/Fit-Logik)
            if len(dates1) <= 1 or len(dates2) <= 1:
                logging.warning(
                    "Zu wenig Messdaten für Prognose (LKD1=%d, LKD2=%d Messpunkte): %s %s %s",
                    len(dates1),
                    len(dates2),
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
                n = getStartIndexLastCycle(
                    tmpVehicle.getmeterList1().getkm(),
                    tmpVehicle.getmeterList1().getvalues(),
                    diffLKD,
                )
                tmpVehicle.getmeterList1().setindexStartLastCycle(n)
                n = getStartIndexLastCycle(
                    tmpVehicle.getmeterList2().getkm(),
                    tmpVehicle.getmeterList2().getvalues(),
                    diffLKD,
                )
                tmpVehicle.getmeterList2().setindexStartLastCycle(n)

                tmpVehicle.calcDaysPerKm()
                tmpVehicle.CalcPrognostic(
                    1, defJumpRepro, defParamExp, nKm, nKmRepro, nValueRepro
                )
                tmpVehicle.CalcPrognostic(
                    2, defJumpRepro, defParamExp, nKm, nKmRepro, nValueRepro
                )
                tmpVehicle.calcnDatesProg()

                nIndex1 = tmpVehicle.getmeterList1().getindexStartLastCycle()
                nIndex2 = tmpVehicle.getmeterList2().getindexStartLastCycle()

                if showPlot:
                    fig = plt.figure(figsize=cfg.plot_figsize, dpi=cfg.plot_dpi)
                    plt.plot(
                        tmpVehicle.getmeterList1().getkm()[nIndex1:],
                        tmpVehicle.getmeterList1().getvalues()[nIndex1:],
                        color="blue",
                        linewidth=0.5,
                        linestyle="-",
                    )
                    plt.plot(
                        tmpVehicle.getmeterList2().getkm()[nIndex2:],
                        tmpVehicle.getmeterList2().getvalues()[nIndex2:],
                        color="green",
                        linewidth=0.5,
                        linestyle="-",
                    )

                    plt.plot(
                        tmpVehicle.getmeterList1().getkmProg(),
                        tmpVehicle.getmeterList1().getvaluesProg(),
                        color="blue",
                        linewidth=1.0,
                        linestyle=":",
                    )
                    plt.plot(
                        tmpVehicle.getmeterList2().getkmProg(),
                        tmpVehicle.getmeterList2().getvaluesProg(),
                        color="green",
                        linewidth=1.0,
                        linestyle=":",
                    )

                    plt.plot(
                        tmpVehicle.getmeterList1().getkm()[nIndex1:],
                        tmpVehicle.getmeterList1().getmin()[nIndex1:],
                        color="r",
                        linewidth=2.0,
                        linestyle="-",
                    )
                    plt.plot(
                        tmpVehicle.getmeterList1().getkm()[nIndex1:],
                        tmpVehicle.getmeterList1().getmax()[nIndex1:],
                        color="r",
                        linewidth=2.0,
                        linestyle="-",
                    )
                    plt.plot(
                        tmpVehicle.getmeterList1().getkm()[nIndex1:],
                        tmpVehicle.getmeterList1().getgelb_min()[nIndex1:],
                        color="yellow",
                        linewidth=2.0,
                        linestyle="-",
                    )

                    km_prog_1 = tmpVehicle.getmeterList1().getkmProg()
                    plt.plot(
                        km_prog_1,
                        [tmpVehicle.getmeterList1().getmin()[-1]] * len(km_prog_1),
                        color="r",
                        linewidth=2.0,
                        linestyle="-",
                    )
                    plt.plot(
                        km_prog_1,
                        [tmpVehicle.getmeterList1().getmax()[-1]] * len(km_prog_1),
                        color="r",
                        linewidth=2.0,
                        linestyle="-",
                    )
                    plt.plot(
                        km_prog_1,
                        [tmpVehicle.getmeterList1().getgelb_min()[-1]] * len(km_prog_1),
                        color="yellow",
                        linewidth=2.0,
                        linestyle="-",
                    )

                    ax = plt.gca()
                    ax.xaxis.set_ticks_position("bottom")
                    ax.yaxis.set_ticks_position("left")
                    plt.ylim(
                        tmpVehicle.getmeterList1().getmin()[-1] - 3,
                        tmpVehicle.getmeterList1().getmax()[-1] + 3,
                    )
                    plt.ylabel("Laufkreisdurchmesser [mm]", fontsize=12)
                    plt.xlabel("Laufleistung [km]", fontsize=12)
                    plt.annotate(
                        "D1",
                        xy=(
                            tmpVehicle.getmeterList1().getgelb_min_Prog_km(),
                            tmpVehicle.getmeterList1().getgelb_min()[-1],
                        ),
                        xytext=(
                            tmpVehicle.getmeterList1().getgelb_min_Prog_km(),
                            tmpVehicle.getmeterList1().getgelb_min()[-1] + 10,
                        ),
                        arrowprops=dict(facecolor="blue", width=1, shrink=0.05),
                    )
                    plt.annotate(
                        "D2",
                        xy=(
                            tmpVehicle.getmeterList2().getgelb_min_Prog_km(),
                            tmpVehicle.getmeterList2().getgelb_min()[-1],
                        ),
                        xytext=(
                            tmpVehicle.getmeterList2().getgelb_min_Prog_km(),
                            tmpVehicle.getmeterList2().getgelb_min()[-1] + 10,
                        ),
                        arrowprops=dict(facecolor="green", width=1, shrink=0.05),
                    )
                    plt.title(
                        "Prognose Fahrzeug: "
                        + tmpVehicle.getstrVDesc()
                        + " Drehgestell: "
                        + tmpVehicle.getstrBogie()
                        + " Achse: "
                        + tmpVehicle.getstrPosAxis()
                        + " Laufkreisdurchmesser 1 und 2"
                    )
                    if cfg.plot_output_dir:
                        os.makedirs(cfg.plot_output_dir, exist_ok=True)
                        safe = re.sub(r"[^\w\-.]+", "_", key, flags=re.UNICODE)[:180]
                        plot_path = os.path.join(
                            cfg.plot_output_dir, f"prognose_{safe}.png"
                        )
                        plt.savefig(plot_path, dpi=cfg.plot_dpi)
                        logging.info("Diagramm gespeichert: %s", plot_path)
                    if cfg.plot_show_window:
                        plt.show()
                    else:
                        plt.close(fig)
            except Exception:
                logging.exception(
                    "Prognose konnte nicht berechnet werden für: %s", key
                )
    except Exception:
        logging.exception(
            "Fehler beim Laden oder Aufbereiten der Messdaten (res2 / Achsen-Schleife)."
        )
         
    # Prognose speichern: DB oder CSV (wie useDatabase), nur wenn write_Prog_Data
    if write_Prog_Data:
        if useDatabase:
            con = oracledb.connect(str_connection)
            cur = con.cursor()
            date_N_days_ago = datetime.now() - timedelta(days=nDays2Delete)
            sql_delete_query = (
                "delete from BO_RADSATZDATEN_PROGNOSE where LETZTEAENDZEIT < :dtLAend"
            )
            cur.execute(sql_delete_query, {"dtLAend": date_N_days_ago})
            con.commit()
            for key in dict_VehicleAxis:
                tmpVehicle = dict_VehicleAxis[key]
                tmpVehicle.write_Prog_Data(cur, con)
            cur.close()
            con.close()
        else:
            with open(
                CSV_BO_PROGNOSE_OUT, "w", newline="", encoding="utf-8-sig"
            ) as csvfile:
                writer = csv.writer(csvfile, delimiter=";")
                writer.writerow(_PROGNOSE_CSV_HEADER)
                for key in dict_VehicleAxis:
                    for zeile in dict_VehicleAxis[key].iter_prognose_insert_tuples():
                        writer.writerow(
                            [
                                _prognose_csv_zelle(i, z)
                                for i, z in enumerate(zeile)
                            ]
                        )
            print(
                "Prognose-CSV geschrieben: "
                + CSV_BO_PROGNOSE_OUT
                + " (STAND=LKD [mm], LAUFLEISTUNG/KM_*=[km])"
            )
            logging.info(
                "Prognose-CSV geschrieben: %s — STAND=LKD [mm], "
                "LAUFLEISTUNG/KM_GRENZWERT/KM_WARNWERT=[km]",
                CSV_BO_PROGNOSE_OUT,
            )


else:
    print('Keine Elemente gefunden')
    logging.warning('Keine Elemente gefunden')
    
logging.info('Finished')