"""Oracle-Loader (Skelett) fuer BO_RADSATZDATEN / BO_RADSATZDATEN_PROGNOSE.

In P1 nur Grundgeruest: Verbindung oeffnen, SELECT auslesen, in dieselbe
Flotten-Struktur ueberfuehren wie der CSV-Loader. Die eigentliche Oracle-
Abfrage bleibt kundenprofilabhaengig (Spaltennamen).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from .models import Flotte
from .profile import Profile

log = logging.getLogger(__name__)


class OracleConnectionError(Exception):
    pass


def test_connection(dsn: Optional[str] = None, user: Optional[str] = None,
                    password: Optional[str] = None,
                    thick_mode_lib_dir: Optional[str] = None,
                    connect_string: Optional[str] = None) -> str:
    """Prueft die DB-Verbindung.

    Entweder (dsn/user/password) oder (connect_string) muessen gegeben sein.
    `connect_string` entspricht dem Format, das das Backend nutzt:
    ``user/password@dsn`` in einer Zeile.
    """
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc

    # Thick-Mode versuchen (noetig fuer manche Oracle-Server-Setups).
    # Erfolg → Thick-Mode; Exception → Thin-Mode-Fallback. Beides ist
    # ok — wir unterdruecken nur die Konsolen-Warnung, der Rueckfall
    # bleibt wie vor der Umstellung aktiv.
    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception as exc:
            log.debug("init_oracle_client (thick dir): %s", exc)
    else:
        try:
            oracledb.init_oracle_client()
        except Exception as exc:
            log.debug("init_oracle_client (auto): %s", exc)

    try:
        if connect_string:
            conn = oracledb.connect(connect_string)
        else:
            conn = oracledb.connect(user=user, password=password, dsn=dsn)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM BO_RADSATZDATEN")
        row = cur.fetchone()
        cur.close()
        return f"OK — DB erreichbar, BO_RADSATZDATEN hat {row[0] if row else 0} Zeilen"
    finally:
        conn.close()


def _ensure_oracle_client(oracledb, thick_mode_lib_dir: Optional[str]):
    """Thick-Mode-Initialisierung versuchen.

    Mit ``thick_mode_lib_dir`` wird der Oracle Instant Client aus dem
    angegebenen Verzeichnis geladen; ohne wird der automatische Lookup
    probiert. Fehler sind ok — ``oracledb`` faellt dann auf Thin-Mode
    zurueck. Wichtig: der Aufruf selbst darf NICHT entfallen, weil
    manche Oracle-Server-Setups zwingend Thick-Mode brauchen.
    """
    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception as exc:
            log.debug("init_oracle_client (thick dir): %s", exc)
    else:
        try:
            oracledb.init_oracle_client()
        except Exception as exc:
            log.debug("init_oracle_client (auto): %s", exc)


def _run_sql(conn, sql: str) -> Tuple[List[str], list]:
    """Fuehrt SQL auf der ``conn`` aus und liefert ``(header, rows)`` zurueck.
    Schliesst den Cursor, laesst die Connection unberuehrt.

    ``arraysize``/``prefetchrows`` werden erhoeht, damit grosse Ergebnismengen
    (BO_RADSATZDATEN: 12k Zeilen, BO_RADSATZDATEN_PROGNOSE: 5k Zeilen) in
    wenigen Netzwerk-Runden statt in Hunderten gefetcht werden.
    """
    cur = conn.cursor()
    cur.arraysize = 5000
    cur.prefetchrows = 5000
    try:
        cur.execute(sql)
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()
    return header, rows


def _parse_prognose_rows(rows, header, profile, flotte) -> int:
    """Parst BO_RADSATZDATEN_PROGNOSE-Zeilen und reichert ``flotte``.

    Jede Zeile der Prognose-Tabelle gehoert zu einem Punkt der Treppen-
    Prognose eines Rades: STAND/DATUM/LAUFLEISTUNG sind die Y/X-Werte.
    Reprofilierungen erscheinen als zwei Zeilen am selben Datum (zuerst
    der hoehere "vor"-Wert, dann der niedrigere "nach"-Wert). Zusaetzlich
    enthaelt jede Zeile dieselben Endpunkt-Spalten KM_/DATUM_WARNWERT und
    KM_/DATUM_GRENZWERT. Wir sammeln beides pro Rad und heften sie an
    ``mr.prognose``.
    """
    from .csv_source import _parse_float, _parse_int, _get, _dedupe_treppe
    from .models import Prognose, PrognosePunkt, Quality
    from datetime import datetime as _dt

    idx = {profile.columns_prognose[name]: i
           for i, name in enumerate(header) if name in profile.columns_prognose}

    # Lookup fuer EINGEBAUTE Achsen (Match ueber Position topeinheit/dg/rs).
    axis_by_ids = {}
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            for a in dg.achsen.values():
                axis_by_ids[(e.topeinheit_id, dg.dg_id, a.rs_id)] = (e, dg, a)

    # Lookup fuer LAGERKOMPONENTEN: pro physischer Achse rs_id -> (Achse im
    # Lager, dg_komponente_falls_dg).
    # Backend identifiziert Lagerachsen eindeutig ueber RSEINHEITID.
    lager_axle_by_rsid = {}   # rs_id -> (LagerKomponente, "achse")
    lager_dg_axle_by_rsid = {}  # rs_id -> (LagerKomponente, inner_Achse)
    for comp in flotte.lager:
        if comp.kind == "achse" and comp.rs_id is not None:
            lager_axle_by_rsid[comp.rs_id] = comp
        elif comp.kind == "drehgestell":
            for inner_axle in comp.achsen.values():
                if inner_axle.rs_id is not None:
                    lager_dg_axle_by_rsid[inner_axle.rs_id] = (comp, inner_axle)

    best = {}            # (axle_key, side, mg_name) -> (score, Prognose-Endpunkte)
    punkte: Dict[tuple, List[PrognosePunkt]] = {}
    # lager_best / lager_punkte verwenden rs_id als Teil des Keys
    lager_best = {}      # (rs_id, side, mg_name) -> (score, Prognose-Endpunkte)
    lager_punkte: Dict[tuple, List[PrognosePunkt]] = {}
    for row in rows:
        row_s = [
            ("" if v is None else
             (v.strftime(profile.date_format) if hasattr(v, "strftime") else str(v)))
            for v in row
        ]
        zartbez = _get(row_s, idx, "zartbez")
        cls = profile.classify_zartbez(zartbez)
        if cls is None:
            continue
        mdef, side = cls
        if not mdef.prognosis:
            continue

        key_axis = (
            _parse_int(_get(row_s, idx, "topeinheit_id")),
            _parse_int(_get(row_s, idx, "dg_id")),
            _parse_int(_get(row_s, idx, "rs_id")),
        )
        ausbau_str = _get(row_s, idx, "ausbau")
        is_lager = bool(ausbau_str and ausbau_str.strip())

        if is_lager:
            # Lagerpfad: Zuordnung ueber rs_id (physische Achse).
            rs_id = key_axis[2]
            if rs_id is None:
                continue
            if rs_id not in lager_axle_by_rsid and rs_id not in lager_dg_axle_by_rsid:
                continue
        else:
            if axis_by_ids.get(key_axis) is None:
                continue

        def _dt_or_none(s):
            if not s: return None
            for fmt in (profile.date_format, "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
                try:
                    return _dt.strptime(s, fmt)
                except ValueError:
                    continue
            return None

        datum = _dt_or_none(_get(row_s, idx, "datum"))
        stand = _parse_float(_get(row_s, idx, "stand"), profile.decimal)
        lauf = _parse_float(_get(row_s, idx, "laufleistung"), profile.decimal)
        if is_lager:
            key_full = (key_axis[2], side, mdef.name)   # rs_id im Schluessel
        else:
            key_full = (key_axis, side, mdef.name)

        if datum is not None and stand is not None:
            pp = PrognosePunkt(datum=datum, stand=stand, laufleistung=lauf)
            if is_lager:
                lager_punkte.setdefault(key_full, []).append(pp)
            else:
                punkte.setdefault(key_full, []).append(pp)

        prog = Prognose(
            km_warnwert=_parse_float(_get(row_s, idx, "km_warnwert"), profile.decimal),
            datum_warnwert=_dt_or_none(_get(row_s, idx, "datum_warnwert")),
            km_grenzwert=_parse_float(_get(row_s, idx, "km_grenzwert"), profile.decimal),
            datum_grenzwert=_dt_or_none(_get(row_s, idx, "datum_grenzwert")),
            methode="theil_sen",
            qualitaet=Quality.OK,
        )
        aktuell = _parse_int(_get(row_s, idx, "aktuell")) or 0
        laend = _dt_or_none(_get(row_s, idx, "letzteaendzeit"))
        score = (aktuell,
                 laend.timestamp() if laend else 0,
                 datum.timestamp() if datum else 0)
        store = lager_best if is_lager else best
        prev = store.get(key_full)
        if prev is None or score > prev[0]:
            store[key_full] = (score, prog)

    attached = 0
    # Eingebaute Raeder: Prognose an deren Messreihen anhaengen.
    for (key_axis, side, mg_name), (_s, prog) in best.items():
        _, _, achse = axis_by_ids[key_axis]
        rad = achse.raeder.get(side)
        if rad is None:
            continue
        mr = rad.messreihen.get(mg_name)
        if mr is None:
            continue
        prog.punkte = _dedupe_treppe(punkte.get((key_axis, side, mg_name), []))
        mr.prognose = prog
        attached += 1

    # Lagerkomponenten: Prognose an deren Messreihen anhaengen.
    attached_lager = 0
    for (rs_id, side, mg_name), (_s, prog) in lager_best.items():
        rad = None
        if rs_id in lager_axle_by_rsid:
            comp = lager_axle_by_rsid[rs_id]
            rad = comp.raeder.get(side)
        elif rs_id in lager_dg_axle_by_rsid:
            _comp, inner_axle = lager_dg_axle_by_rsid[rs_id]
            rad = inner_axle.raeder.get(side)
        if rad is None:
            continue
        mr = rad.messreihen.get(mg_name)
        if mr is None:
            continue
        prog.punkte = _dedupe_treppe(lager_punkte.get((rs_id, side, mg_name), []))
        mr.prognose = prog
        attached_lager += 1

    log.info(
        "Oracle-Prognose: %d eingebaute + %d Lager-Messreihen angereichert (aus %d Zeilen)",
        attached, attached_lager, len(rows),
    )
    return attached + attached_lager


def _flotte_raw_sql(profile, limit: Optional[int]) -> str:
    db_cols = list(profile.columns_raw.keys())
    sql = f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN"
    if limit:
        sql += f" FETCH FIRST {int(limit)} ROWS ONLY"
    return sql


def _prognose_sql(profile) -> str:
    db_cols = list(profile.columns_prognose.keys())
    return f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN_PROGNOSE"


def _parse_flotte_rows(rows, header, profile) -> Flotte:
    """Parst BO_RADSATZDATEN-Zeilen in eine ``Flotte``."""
    from datetime import datetime

    from .csv_source import (
        _add_installed, _add_lager, _get, _make_messpunkt, _parse_float,
        finalize_structure,
    )

    flotte = Flotte()
    lager_map = {}
    idx = {profile.columns_raw[name]: i for i, name in enumerate(header) if name in profile.columns_raw}
    zi = idx.get("zartbez", -1)
    stats = dict(rows=len(rows), unknown_zartbez=0, invalid_value=0, dropped=0,
                 lager_unassigned=0)

    for row in rows:
        # Messgroesse zuerst klassifizieren: unbekannte Zeilen (z.B.
        # Bremsscheiben) werden verworfen, bevor die teure Textkonvertierung
        # aller Spalten laeuft.
        cls = profile.classify_zartbez(row[zi] if zi >= 0 and row[zi] is not None else "")
        if cls is None:
            stats["unknown_zartbez"] += 1
            continue
        mdef, side = cls
        row_s = [
            ("" if v is None else
             (v.strftime(profile.date_format) if hasattr(v, "strftime") else str(v)))
            for v in row
        ]
        datum_s = _get(row_s, idx, "datum")
        stand = _parse_float(_get(row_s, idx, "stand"), profile.decimal)
        if not datum_s or stand is None:
            stats["dropped"] += 1
            continue
        try:
            datum = datetime.strptime(datum_s, profile.date_format)
        except ValueError:
            stats["dropped"] += 1
            continue
        mp = _make_messpunkt(lambda k: _get(row_s, idx, k), profile, mdef, datum, stand)
        if mp is None:
            stats["invalid_value"] += 1
            continue
        ausbau_s = _get(row_s, idx, "ausbau")
        try:
            ausbau = datetime.strptime(ausbau_s, profile.date_format) if ausbau_s else None
        except ValueError:
            ausbau = None
        aktuell_s = _get(row_s, idx, "aktuell")
        aktuell = int(float(aktuell_s)) if aktuell_s else 0
        if ausbau is None and aktuell == 1:
            _add_installed(flotte, row_s, idx, profile, mdef, side, mp)
        elif not _add_lager(lager_map, row_s, idx, profile, mdef, side, mp, ausbau):
            stats["lager_unassigned"] += 1
    flotte.lager = list(lager_map.values())
    finalize_structure(flotte, profile)
    log.info("Oracle-Rohdaten verarbeitet (%s): %s", profile.name, stats)
    return flotte


def load_flotte_from_connect_string(connect_string: str, profile,
                                     thick_mode_lib_dir: Optional[str] = None,
                                     limit: Optional[int] = None) -> Flotte:
    """Laedt BO_RADSATZDATEN ueber einen fertigen Connect-String."""
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc
    _ensure_oracle_client(oracledb, thick_mode_lib_dir)
    try:
        conn = oracledb.connect(connect_string)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc
    try:
        header, rows = _run_sql(conn, _flotte_raw_sql(profile, limit))
    finally:
        conn.close()
    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN geladen", len(rows))
    return _parse_flotte_rows(rows, header, profile)


def load_prognose_from_connect_string(connect_string: str, profile, flotte,
                                       thick_mode_lib_dir: Optional[str] = None) -> int:
    """Liest BO_RADSATZDATEN_PROGNOSE und reichert die Messreihen der Flotte an.

    Pro Messreihe wird die juengste Prognose uebernommen (bevorzugt
    AKTUELL=1, sonst spaetestes LETZTEAENDZEIT, sonst spaetestes DATUM)."""
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc
    _ensure_oracle_client(oracledb, thick_mode_lib_dir)
    try:
        conn = oracledb.connect(connect_string)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc
    try:
        header, rows = _run_sql(conn, _prognose_sql(profile))
    finally:
        conn.close()
    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN_PROGNOSE geladen", len(rows))
    return _parse_prognose_rows(rows, header, profile, flotte)


def load_flotte_and_prognose_from_connect_string(
        connect_string: str,
        profile,
        thick_mode_lib_dir: Optional[str] = None,
        limit: Optional[int] = None) -> Flotte:
    """Laedt BO_RADSATZDATEN und BO_RADSATZDATEN_PROGNOSE in EINER
    Oracle-Session und reichert die Flotte direkt mit den Prognosen an.

    Spart gegenueber dem getrennten Aufruf einen zweiten Verbindungs-
    aufbau (TCP/TLS-Handshake, Oracle-Session). Fehler beim Lesen der
    Prognose-Tabelle blockieren die Rohdaten nicht — sie werden geloggt
    und die Flotte wird ohne Prognosen zurueckgegeben.
    """
    import time as _time
    import threading as _th
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc
    t0 = _time.monotonic()
    _ensure_oracle_client(oracledb, thick_mode_lib_dir)
    t1 = _time.monotonic()

    # Zwei parallele Oracle-Sessions: die Rohdaten-Query (~12k Zeilen,
    # dominiert die Gesamtzeit) laeuft gleichzeitig mit der Prognose-
    # Query (~5k Zeilen). Verbindungsaufbau selbst passiert ebenfalls
    # parallel, so dass die Netzwerk-Latenz nur einmal in die
    # Gesamtzeit eingeht.
    raw_result: dict = {}
    prog_result: dict = {}

    def _worker_raw():
        try:
            tc0 = _time.monotonic()
            conn = oracledb.connect(connect_string)
            tc1 = _time.monotonic()
            try:
                header, rows = _run_sql(conn, _flotte_raw_sql(profile, limit))
                tc2 = _time.monotonic()
                raw_result["header"] = header
                raw_result["rows"] = rows
                raw_result["t_connect"] = tc1 - tc0
                raw_result["t_sql"] = tc2 - tc1
            finally:
                conn.close()
        except Exception as exc:
            raw_result["error"] = exc

    def _worker_prog():
        try:
            tc0 = _time.monotonic()
            conn = oracledb.connect(connect_string)
            tc1 = _time.monotonic()
            try:
                header, rows = _run_sql(conn, _prognose_sql(profile))
                tc2 = _time.monotonic()
                prog_result["header"] = header
                prog_result["rows"] = rows
                prog_result["t_connect"] = tc1 - tc0
                prog_result["t_sql"] = tc2 - tc1
            finally:
                conn.close()
        except Exception as exc:
            prog_result["error"] = exc

    th_raw = _th.Thread(target=_worker_raw, name="oracle-raw", daemon=True)
    th_prog = _th.Thread(target=_worker_prog, name="oracle-prognose", daemon=True)
    th_raw.start()
    th_prog.start()
    th_raw.join()
    th_prog.join()
    t2 = _time.monotonic()

    if "error" in raw_result:
        raise OracleConnectionError(
            f"Verbindung/Abfrage BO_RADSATZDATEN fehlgeschlagen: {raw_result['error']}"
        ) from raw_result["error"]

    log.debug(
        "Oracle (parallel) — init_client=%.2fs, parallel-block=%.2fs "
        "[raw: connect=%.2fs SQL+fetch=%.2fs | prog: connect=%.2fs SQL+fetch=%.2fs]",
        t1 - t0, t2 - t1,
        raw_result.get("t_connect", 0.0), raw_result.get("t_sql", 0.0),
        prog_result.get("t_connect", 0.0), prog_result.get("t_sql", 0.0),
    )
    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN geladen", len(raw_result["rows"]))

    t3 = _time.monotonic()
    flotte = _parse_flotte_rows(raw_result["rows"], raw_result["header"], profile)
    t4 = _time.monotonic()
    log.debug("Oracle: parse_flotte_rows=%.2fs", t4 - t3)

    if "error" in prog_result:
        log.warning("Prognose-Tabelle konnte nicht gelesen werden: %s", prog_result["error"])
    else:
        log.info(
            "Oracle: %d Zeilen aus BO_RADSATZDATEN_PROGNOSE geladen",
            len(prog_result["rows"]),
        )
        _parse_prognose_rows(prog_result["rows"], prog_result["header"], profile, flotte)
        t5 = _time.monotonic()
        log.debug("Oracle: parse_prognose_rows=%.2fs", t5 - t4)
    return flotte


def load_flotte_from_oracle(
    dsn: str,
    user: str,
    password: str,
    profile: Profile,
    thick_mode_lib_dir: Optional[str] = None,
) -> Flotte:
    """Baut die Flotte aus der Oracle-DB auf.

    Erwartet denselben Spaltensatz wie das Kundenprofil (``profile.columns_raw``).
    Bei fehlender ``oracledb``-Installation oder DB-Verbindung wird
    ``OracleConnectionError`` ausgeloest.
    """
    try:
        import oracledb  # lazy import
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc

    import time as _time
    t_init0 = _time.monotonic()
    # Thick-Mode versuchen; Fehler → Thin-Mode-Fallback.
    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception as exc:
            log.debug("init_oracle_client (thick dir): %s", exc)
    else:
        try:
            oracledb.init_oracle_client()
        except Exception as exc:
            log.debug("init_oracle_client (auto): %s", exc)
    t_init1 = _time.monotonic()

    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc
    t_conn = _time.monotonic()

    # Spalten aus Profil ableiten (DB-Spaltenname -> intern)
    db_cols = list(profile.columns_raw.keys())
    sql = f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN"

    cur = conn.cursor()
    try:
        cur.execute(sql)
        t_exec = _time.monotonic()
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
        t_fetch = _time.monotonic()
    finally:
        cur.close()
        conn.close()

    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN geladen (Profil %s)",
             len(rows), profile.name)
    log.debug(
        "Oracle timings: init_client=%.2fs, connect=%.2fs, execute=%.2fs, fetch=%.2fs",
        t_init1 - t_init0, t_conn - t_init1, t_exec - t_conn, t_fetch - t_exec,
    )

    return _parse_flotte_rows(rows, header, profile)
