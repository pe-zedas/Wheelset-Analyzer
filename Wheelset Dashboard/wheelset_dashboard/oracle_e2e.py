"""End-to-End-Test gegen die Oracle-DB.

Liest den Connect-String aus (in dieser Reihenfolge):
  1. ``--connect-file <pfad>``
  2. Umgebungsvariable ``ORACLE_CONNECT_STRING``
  3. Dashboard-eigenes Config-Verzeichnis:
     ``<App-Root>/config/oracle_connect_string.txt``

Fuehrt der Reihe nach aus:
  * DB-Verbindung testen
  * BO_RADSATZDATEN laden (optional per --limit begrenzt)
  * Status- und Lager-Logik anwenden
  * Zusammenfassung drucken

Credentials werden NICHT geloggt oder ausgegeben.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config.app_paths import ORACLE_CONNECT_FILE, read_oracle_connect_string
from .config.logging_setup import setup_logging
from .data.oracle_source import (
    OracleConnectionError, load_flotte_from_connect_string, test_connection,
)
from .data.profile import load_profile_by_name
from .logic.lager_state import recompute_all as recompute_lager
from .logic.status import recompute_all as recompute_status


DEFAULT_CONNECT_FILE = ORACLE_CONNECT_FILE


def _load_connect_string(explicit: str | None, profile: str = "vgf") -> str:
    if explicit:
        p = Path(explicit)
        line = p.read_text(encoding="utf-8").splitlines()[0].strip()
        if not line:
            raise SystemExit(f"Connect-String-Datei leer: {p}")
        return line

    env = os.environ.get("ORACLE_CONNECT_STRING", "").strip()
    if env:
        return env

    line = read_oracle_connect_string(profile)
    if not line:
        raise SystemExit(
            f"Kein Connect-String gefunden. Erwartet via --connect-file, "
            f"ORACLE_CONNECT_STRING oder Zeile '{profile} = user/pw@dsn' in "
            f"{ORACLE_CONNECT_FILE}"
        )
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="vgf")
    ap.add_argument("--connect-file", default=None,
                    help="Pfad zur Datei mit dem Connect-String (eine Zeile)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Zeilen-Limit (fuer schnellen Test)")
    ap.add_argument("--thick-lib-dir", default=None,
                    help="Pfad zum Oracle Instant Client (optional)")
    args = ap.parse_args()

    setup_logging(level="INFO", log_file="oracle_e2e.log")
    log = logging.getLogger(__name__)

    conn_str = _load_connect_string(args.connect_file, args.profile)
    log.info("Connect-String geladen (Laenge %d Zeichen, Inhalt nicht geloggt)", len(conn_str))

    print("1) Testverbindung...")
    try:
        msg = test_connection(connect_string=conn_str, thick_mode_lib_dir=args.thick_lib_dir)
        print(f"   {msg}")
    except OracleConnectionError as exc:
        print(f"   FEHLER: {exc}")
        return 2

    print(f"2) Lade Daten (Profil: {args.profile}" + (f", Limit {args.limit}" if args.limit else "") + ")...")
    profile = load_profile_by_name(args.profile)
    try:
        flotte = load_flotte_from_connect_string(
            conn_str, profile,
            thick_mode_lib_dir=args.thick_lib_dir, limit=args.limit,
        )
    except OracleConnectionError as exc:
        print(f"   FEHLER: {exc}")
        return 2

    print(f"   {len(flotte.einheiten)} Einheiten, {len(flotte.lager)} Lager-Komponenten")

    print("3) Berechne Status und Lager-Zustand...")
    recompute_status(flotte)
    counts = recompute_lager(flotte)
    print(f"   Lager: ready={counts['ready']}, to_overhaul={counts['to_overhaul']}")
    print(f"   Flotten-Status: {flotte.status().value}")

    print("4) Top-5 Einheiten:")
    for i, (bez, e) in enumerate(sorted(flotte.einheiten.items())):
        if i >= 5:
            break
        n_dg = len(e.drehgestelle)
        n_a = sum(len(dg.achsen) for dg in e.drehgestelle.values())
        print(f"   [{e.status().value:6s}] {bez:30s}  DGs={n_dg}  Achsen={n_a}")

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
