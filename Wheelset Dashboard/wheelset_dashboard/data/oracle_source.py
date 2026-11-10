"""Oracle-Loader fuer BO_RADSATZDATEN / BO_RADSATZDATEN_PROGNOSE.

Ein Weg: ``user/passwort@dsn`` als Connect-String; die Rohdaten- und die
Prognose-Abfrage laufen in zwei parallelen Sessions. Aufbau der Struktur steht
in ``structure.build_flotte``, die Anreicherung um Prognosen in
``prognose_source.attach_prognose`` (beides gemeinsam mit dem CSV-Loader).
Die Abfrage selbst bleibt kundenprofilabhaengig (Spaltennamen).
"""
from __future__ import annotations

import logging
import threading
from typing import List, Optional, Tuple

from ..perf import timed
from .models import Flotte
from .profile import Profile
from .prognose_source import attach_prognose
from .structure import build_flotte

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

    _ensure_oracle_client(oracledb, thick_mode_lib_dir)

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


def _flotte_raw_sql(profile, limit: Optional[int]) -> str:
    db_cols = list(profile.columns_raw.keys())
    sql = f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN"
    if limit:
        sql += f" FETCH FIRST {int(limit)} ROWS ONLY"
    return sql


def _prognose_sql(profile) -> str:
    db_cols = list(profile.columns_prognose.keys())
    return f"SELECT {', '.join(db_cols)} FROM BO_RADSATZDATEN_PROGNOSE"


def parse_flotte_rows(rows, header, profile: Profile) -> Flotte:
    """Baut die Flotte aus BO_RADSATZDATEN-Zeilen (Datenbankwerte)."""
    return build_flotte(rows, profile.map_raw_header(list(header)), profile,
                        stringify=True, label="Oracle-Rohdaten")


def parse_prognose_rows(rows, header, profile: Profile, flotte: Flotte) -> int:
    """Reichert ``flotte`` um BO_RADSATZDATEN_PROGNOSE-Zeilen an.

    Jede Zeile gehoert zu einem Punkt der Treppen-Prognose eines Rades; siehe
    ``prognose_source.attach_prognose``. Rueckgabe: angereicherte Messreihen."""
    return attach_prognose(flotte, profile, rows, profile.map_prognose_header(list(header)),
                           stringify=True, label="Oracle-Prognose")


def _fetch(oracledb, connect_string: str, sql: str, out: dict) -> None:
    """Eigene Session: verbinden, Abfrage ausfuehren, Ergebnis in ``out`` ablegen.

    Laeuft in einem Thread; Fehler landen unter ``out["error"]`` statt zu werfen.
    """
    try:
        with timed("connect", None) as t_connect:
            conn = oracledb.connect(connect_string)
        try:
            with timed("sql", None) as t_sql:
                header, rows = _run_sql(conn, sql)
            out.update(header=header, rows=rows,
                       t_connect=t_connect.seconds, t_sql=t_sql.seconds)
        finally:
            conn.close()
    except Exception as exc:
        out["error"] = exc


def load_flotte_and_prognose_from_connect_string(
        connect_string: str,
        profile,
        thick_mode_lib_dir: Optional[str] = None,
        limit: Optional[int] = None) -> Flotte:
    """Laedt BO_RADSATZDATEN und BO_RADSATZDATEN_PROGNOSE ueber zwei PARALLELE
    Oracle-Sessions und reichert die Flotte direkt mit den Prognosen an.

    Die Rohdaten-Query (~12k Zeilen, dominiert die Gesamtzeit) laeuft gleichzeitig
    mit der Prognose-Query (~5k Zeilen); auch der Verbindungsaufbau passiert
    parallel, so dass die Netzwerk-Latenz nur einmal in die Gesamtzeit eingeht.
    Fehler beim Lesen der Prognose-Tabelle blockieren die Rohdaten nicht — sie
    werden geloggt und die Flotte wird ohne Prognosen zurueckgegeben.
    """
    try:
        import oracledb
    except ImportError as exc:
        raise OracleConnectionError(f"oracledb nicht installiert: {exc}") from exc
    with timed("init_client", None) as t_init:
        _ensure_oracle_client(oracledb, thick_mode_lib_dir)

    raw: dict = {}
    prog: dict = {}
    threads = [
        threading.Thread(target=_fetch, name="oracle-raw", daemon=True,
                         args=(oracledb, connect_string, _flotte_raw_sql(profile, limit), raw)),
        threading.Thread(target=_fetch, name="oracle-prognose", daemon=True,
                         args=(oracledb, connect_string, _prognose_sql(profile), prog)),
    ]
    with timed("parallel", None) as t_parallel:
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    if "error" in raw:
        raise OracleConnectionError(
            f"Verbindung/Abfrage BO_RADSATZDATEN fehlgeschlagen: {raw['error']}"
        ) from raw["error"]

    log.debug(
        "Oracle (parallel) — init_client=%.2fs, parallel-block=%.2fs "
        "[raw: connect=%.2fs SQL+fetch=%.2fs | prog: connect=%.2fs SQL+fetch=%.2fs]",
        t_init.seconds, t_parallel.seconds,
        raw.get("t_connect", 0.0), raw.get("t_sql", 0.0),
        prog.get("t_connect", 0.0), prog.get("t_sql", 0.0),
    )
    log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN geladen", len(raw["rows"]))

    with timed("Oracle: parse_flotte_rows", log):
        flotte = parse_flotte_rows(raw["rows"], raw["header"], profile)

    if "error" in prog:
        log.warning("Prognose-Tabelle konnte nicht gelesen werden: %s", prog["error"])
    else:
        log.info("Oracle: %d Zeilen aus BO_RADSATZDATEN_PROGNOSE geladen", len(prog["rows"]))
        with timed("Oracle: parse_prognose_rows", log):
            parse_prognose_rows(prog["rows"], prog["header"], profile, flotte)
    return flotte
