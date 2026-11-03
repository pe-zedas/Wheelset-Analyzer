"""Oracle-Loader (Skelett) fuer BO_RADSATZDATEN / BO_RADSATZDATEN_PROGNOSE.

In P1 nur Grundgeruest: Verbindung oeffnen, SELECT auslesen, in dieselbe
Flotten-Struktur ueberfuehren wie der CSV-Loader. Die eigentliche Oracle-
Abfrage bleibt kundenprofilabhaengig (Spaltennamen).
"""
from __future__ import annotations

import logging
from typing import Optional

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

    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception as exc:
            log.warning("init_oracle_client: %s", exc)
    else:
        try:
            oracledb.init_oracle_client()
        except Exception:
            pass  # thin-mode faellt zurueck

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


def load_prognose_from_connect_string(connect_string: str, profile, flotte,
                                       thick_mode_lib_dir: Optional[str] = None) -> int:
    """Liest BO_RADSATZDATEN_PROGNOSE und reichert die Messreihen der Flotte an.

    Pro Messreihe wird die juengste Prognose uebernommen (bevorzugt AKTUELL=1,
    sonst spaetestes LETZTEAENDZEIT, sonst spaetestes DATUM). Analog zum
    CSV-Loader load_prognose_csv.
    """
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc
    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception:
            pass
    else:
        try:
            oracledb.init_oracle_client()
        except Exception:
            pass

    try:
        conn = oracledb.connect(connect_string)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc

    db_cols = list(profile.columns_prognose.keys())
    sql = f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN_PROGNOSE"
    cur = conn.cursor()
    try:
        cur.execute(sql)
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN_PROGNOSE geladen", len(rows))

    from .csv_source import _parse_float, _parse_int, _get
    from .models import Prognose, Quality
    from datetime import datetime as _dt

    idx = {profile.columns_prognose[name]: i
           for i, name in enumerate(header) if name in profile.columns_prognose}

    axis_by_ids = {}
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            for a in dg.achsen.values():
                axis_by_ids[(e.topeinheit_id, dg.dg_id, a.rs_id)] = (e, dg, a)

    best = {}  # (axle_key, side, mg_name) -> (score, Prognose)
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
        datum = _dt_or_none(_get(row_s, idx, "datum"))
        score = (aktuell,
                 laend.timestamp() if laend else 0,
                 datum.timestamp() if datum else 0)
        key_full = (key_axis, side, mdef.name)
        prev = best.get(key_full)
        if prev is None or score > prev[0]:
            best[key_full] = (score, prog)

    attached = 0
    for (key_axis, side, mg_name), (_s, prog) in best.items():
        _, _, achse = axis_by_ids[key_axis]
        rad = achse.raeder.get(side)
        if rad is None:
            continue
        mr = rad.messreihen.get(mg_name)
        if mr is None:
            continue
        mr.prognose = prog
        attached += 1

    log.info("Oracle-Prognose: %d Messreihen angereichert (aus %d Zeilen)",
             attached, len(rows))
    return attached


def load_flotte_from_connect_string(connect_string: str, profile,
                                     thick_mode_lib_dir: Optional[str] = None,
                                     limit: Optional[int] = None):
    """Variante von load_flotte_from_oracle, die einen fertigen connect_string nimmt."""
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc
    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception:
            pass
    else:
        try:
            oracledb.init_oracle_client()
        except Exception:
            pass

    try:
        conn = oracledb.connect(connect_string)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc

    db_cols = list(profile.columns_raw.keys())
    sql = f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN"
    if limit:
        sql += f" FETCH FIRST {int(limit)} ROWS ONLY"

    cur = conn.cursor()
    try:
        cur.execute(sql)
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN geladen", len(rows))

    from .csv_source import _add_installed, _add_lager, _parse_float, _get
    from .models import Flotte, Messpunkt

    flotte = Flotte()
    lager_map = {}
    idx = {profile.columns_raw[name]: i for i, name in enumerate(header) if name in profile.columns_raw}

    from datetime import datetime
    for row in rows:
        row_s = [
            ("" if v is None else
             (v.strftime(profile.date_format) if hasattr(v, "strftime") else str(v)))
            for v in row
        ]
        zartbez = row_s[idx.get("zartbez", -1)] if "zartbez" in idx else ""
        cls = profile.classify_zartbez(zartbez)
        if cls is None:
            continue
        mdef, side = cls
        datum_s = _get(row_s, idx, "datum")
        stand = _parse_float(_get(row_s, idx, "stand"), profile.decimal)
        if not datum_s or stand is None:
            continue
        try:
            datum = datetime.strptime(datum_s, profile.date_format)
        except ValueError:
            continue
        mp = Messpunkt(
            datum=datum, stand=stand,
            laufleistung=_parse_float(_get(row_s, idx, "laufleistung"), profile.decimal),
            min_val=_parse_float(_get(row_s, idx, "min_val"), profile.decimal),
            max_val=_parse_float(_get(row_s, idx, "max_val"), profile.decimal),
            gelb_min=_parse_float(_get(row_s, idx, "gelb_min"), profile.decimal),
            gelb_max=_parse_float(_get(row_s, idx, "gelb_max"), profile.decimal),
        )
        ausbau_s = _get(row_s, idx, "ausbau")
        try:
            ausbau = datetime.strptime(ausbau_s, profile.date_format) if ausbau_s else None
        except ValueError:
            ausbau = None
        aktuell_s = _get(row_s, idx, "aktuell")
        aktuell = int(float(aktuell_s)) if aktuell_s else 0
        if ausbau is None and aktuell == 1:
            _add_installed(flotte, row_s, idx, profile, mdef, side, mp)
        else:
            _add_lager(lager_map, row_s, idx, profile, mdef, side, mp, ausbau)
    flotte.lager = list(lager_map.values())
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

    if thick_mode_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=thick_mode_lib_dir)
        except Exception as exc:
            log.warning("init_oracle_client fehlgeschlagen (ggf. bereits initialisiert): %s", exc)

    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
    except Exception as exc:
        raise OracleConnectionError(f"Verbindung fehlgeschlagen: {exc}") from exc

    # Spalten aus Profil ableiten (DB-Spaltenname -> intern)
    db_cols = list(profile.columns_raw.keys())
    sql = f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN"

    cur = conn.cursor()
    try:
        cur.execute(sql)
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN geladen (Profil %s)", len(rows), profile.name)

    # Delegiere Row-Verarbeitung an denselben Pfad wie CSV
    from .csv_source import _add_installed, _add_lager, _parse_datetime, _parse_int
    from .models import Flotte, Messpunkt, Side

    flotte = Flotte()
    lager_map = {}
    idx = {profile.columns_raw[name]: i for i, name in enumerate(header) if name in profile.columns_raw}

    for row in rows:
        row_s = [("" if v is None else (v.strftime(profile.date_format) if hasattr(v, "strftime") else str(v))) for v in row]
        zartbez = row_s[idx.get("zartbez", -1)] if "zartbez" in idx else ""
        cls = profile.classify_zartbez(zartbez)
        if cls is None:
            continue
        mdef, side = cls
        # Reuse der CSV-Hilfsroutinen:
        from .csv_source import load_raw_csv  # noqa (zur Dokumentation)
        # Konstruktion eines Messpunkts direkt aus den Row-Strings:
        from .csv_source import _parse_float, _get
        datum = _parse_datetime(_get(row_s, idx, "datum"), profile.date_format)
        stand = _parse_float(_get(row_s, idx, "stand"), profile.decimal)
        if datum is None or stand is None:
            continue
        mp = Messpunkt(
            datum=datum,
            stand=stand,
            laufleistung=_parse_float(_get(row_s, idx, "laufleistung"), profile.decimal),
            min_val=_parse_float(_get(row_s, idx, "min_val"), profile.decimal),
            max_val=_parse_float(_get(row_s, idx, "max_val"), profile.decimal),
            gelb_min=_parse_float(_get(row_s, idx, "gelb_min"), profile.decimal),
            gelb_max=_parse_float(_get(row_s, idx, "gelb_max"), profile.decimal),
        )
        ausbau = _parse_datetime(_get(row_s, idx, "ausbau"), profile.date_format)
        aktuell = _parse_int(_get(row_s, idx, "aktuell")) or 0
        if ausbau is None and aktuell == 1:
            _add_installed(flotte, row_s, idx, profile, mdef, side, mp)
        else:
            _add_lager(lager_map, row_s, idx, profile, mdef, side, mp, ausbau)

    flotte.lager = list(lager_map.values())
    return flotte
