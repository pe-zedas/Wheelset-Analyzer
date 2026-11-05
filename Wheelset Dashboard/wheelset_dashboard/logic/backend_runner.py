"""Stoesst den Backend-Prognoselauf an.

Das eigentliche Rechnen liegt im Nachbar-Projekt
``Wheelset Analyzer_new_approach/Radsatz_Bahn_DB_new_Approach.py``.
Dieses Modul passt dessen INI-Datei an den aktuellen Dashboard-Modus an
(``[pipeline] use_database`` wird auf ``true`` fuer Oracle und ``false``
fuer CSV gesetzt; ``write_prog_data`` wird auf ``true`` gezwungen) und
startet das Skript als Subprozess mit demselben Python-Interpreter.
"""
from __future__ import annotations

import configparser
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Backend-Projekt liegt neben dem Dashboard-Projekt.
_BACKEND_DIR_DEFAULT = (
    Path(__file__).resolve().parents[2].parent
    / "Wheelset Analyzer_new_approach"
)
_SCRIPT_NAME = "Radsatz_Bahn_DB_new_Approach.py"
_INI_NAME = "radsatz_config.ini"
_LOG_NAME = "Prog_Radsatzdaten.log"


@dataclass
class BackendResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    log_path: Optional[Path]
    message: str


def _resolve_backend_dir() -> Path:
    """Backend-Verzeichnis ermitteln; wirft FileNotFoundError, wenn das
    Skript nicht gefunden wird."""
    d = _BACKEND_DIR_DEFAULT
    if (d / _SCRIPT_NAME).exists():
        return d
    raise FileNotFoundError(
        f"Backend-Skript nicht gefunden: {d / _SCRIPT_NAME}"
    )


def _patch_ini(ini_path: Path, use_database: bool) -> None:
    """Setzt [pipeline] use_database und write_prog_data passend.

    Die INI wird nur geaendert, wenn noetig (idempotent). Eine
    Backup-Datei ``radsatz_config.ini.bak`` wird einmal angelegt, falls
    noch keine existiert."""
    cp = configparser.ConfigParser()
    cp.read(ini_path, encoding="utf-8")
    if "pipeline" not in cp:
        cp["pipeline"] = {}
    desired_use_db = "true" if use_database else "false"
    changed = False
    if cp["pipeline"].get("use_database", "").strip().lower() != desired_use_db:
        cp["pipeline"]["use_database"] = desired_use_db
        changed = True
    if cp["pipeline"].get("write_prog_data", "").strip().lower() != "true":
        cp["pipeline"]["write_prog_data"] = "true"
        changed = True
    if not changed:
        return
    backup = ini_path.with_suffix(".ini.bak")
    if not backup.exists():
        shutil.copy2(ini_path, backup)
    with ini_path.open("w", encoding="utf-8") as f:
        cp.write(f)


def run_backend_prognose(
    use_database: bool,
    timeout_s: int = 1800,
    backend_dir: Optional[Path] = None,
) -> BackendResult:
    """Fuehrt das Backend synchron aus. Gibt BackendResult zurueck.

    ``use_database=True``  → schreibt in Oracle ``BO_RADSATZDATEN_PROGNOSE``.
    ``use_database=False`` → schreibt CSV ``bo_radsatzdaten_prognose_recalc.csv``.
    """
    bdir = backend_dir or _resolve_backend_dir()
    ini = bdir / _INI_NAME
    if not ini.exists():
        return BackendResult(False, -1, "", "",
                             None, f"INI-Datei fehlt: {ini}")
    try:
        _patch_ini(ini, use_database=use_database)
    except Exception as exc:
        return BackendResult(False, -1, "", str(exc),
                             None, f"INI konnte nicht angepasst werden: {exc}")

    cmd = [sys.executable, "-u", _SCRIPT_NAME]
    log.info("Backend-Prognose-Lauf: %s (cwd=%s, use_db=%s)",
             " ".join(cmd), bdir, use_database)
    try:
        proc = subprocess.run(
            cmd, cwd=str(bdir),
            capture_output=True, text=True,
            timeout=timeout_s,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        return BackendResult(False, -1, exc.stdout or "", exc.stderr or "",
                             bdir / _LOG_NAME,
                             f"Backend-Lauf hat Timeout {timeout_s}s ueberschritten")
    except Exception as exc:
        return BackendResult(False, -1, "", str(exc),
                             bdir / _LOG_NAME,
                             f"Backend-Aufruf fehlgeschlagen: {exc}")

    log_path = bdir / _LOG_NAME if (bdir / _LOG_NAME).exists() else None
    # Das Backend faengt viele Fehler mit logging.exception ab und
    # beendet dann mit Exit 0. Deshalb reicht der Exit-Code allein nicht
    # als Erfolgsindikator — wir pruefen zusaetzlich den stderr auf
    # Traceback-Signatur. Ausserdem muss der Backend-Log existieren.
    tb_in_stderr = "Traceback (most recent call last)" in (proc.stderr or "")
    ok = (proc.returncode == 0) and not tb_in_stderr
    msg = ("Prognose-Lauf erfolgreich." if ok
           else f"Backend-Lauf gab Exit {proc.returncode} zurueck"
                + (" (Traceback in stderr)" if tb_in_stderr else ""))
    return BackendResult(ok, proc.returncode, proc.stdout, proc.stderr,
                         log_path, msg)
