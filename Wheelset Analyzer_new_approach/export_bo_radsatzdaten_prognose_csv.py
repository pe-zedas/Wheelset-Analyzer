"""
Exportiert alle Zeilen aus bo_radsatzdaten_prognose nach CSV.

Verbindung: eine Zeile aus oracle_connect_string.txt (neben diesem Skript),
             optional überschreibbar mit Umgebungsvariable ORACLE_CONNECT_STRING.
Aufruf: python export_bo_radsatzdaten_prognose_csv.py [Ausgabedatei.csv]
"""
import csv
import os
import sys

try:
    import oracledb
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Oracle-Treiber fehlt: python -m pip install oracledb"
    ) from exc

oracledb.init_oracle_client()

_CONNECT_FILE = "oracle_connect_string.txt"


def _load_connect_string():
    env = os.environ.get("ORACLE_CONNECT_STRING", "").strip()
    if env:
        return env
    path = os.path.join(os.path.dirname(__file__), _CONNECT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError as exc:
        raise SystemExit(
            f"Connect-String-Datei fehlt oder nicht lesbar: {path}\n{exc}"
        ) from exc
    if not line or line.startswith("#"):
        raise SystemExit(
            f"In {_CONNECT_FILE} muss die Verbindungszeile (eine Zeile) stehen."
        )
    return line


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, oracledb.LOB):
        return v.read() if v.size() else ""
    return v


def main():
    conn_str = _load_connect_string()
    out_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(
            os.path.dirname(__file__), "bo_radsatzdaten_prognose_export.csv"
        )
    )

    with oracledb.connect(conn_str) as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM bo_radsatzdaten_prognose")
            cols = [d[0] for d in cur.description]
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(cols)
                for row in cur:
                    w.writerow([_cell(c) for c in row])

    print(out_path)


if __name__ == "__main__":
    main()
