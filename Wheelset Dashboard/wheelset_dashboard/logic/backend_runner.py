"""Stoesst den Backend-Prognoselauf an.

Das eigentliche Rechnen liegt im Nachbar-Projekt
``Wheelset Analyzer_new_approach/Radsatz_Bahn_DB_new_Approach.py``.
Dieses Modul startet das Skript als Subprozess mit demselben Python-Interpreter
und uebergibt die Werte, die fuer den Dashboard-Lauf gelten, per Kommandozeile
(``--set abschnitt.schluessel=wert``). Sie haben Vorrang vor
``radsatz_config.ini``; die Datei selbst wird **nicht** veraendert:

* ``pipeline.use_database``: ``true`` fuer Oracle, ``false`` fuer CSV
* ``pipeline.write_prog_data``: immer ``true``
* ``plot.show_plot`` / ``plot.plot_show_window``: immer ``false`` — der Lauf hat
  keine Oberflaeche, ein Plotfenster wuerde ihn bis zum Zeitlimit blockieren
"""
from __future__ import annotations

import logging
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


def backend_overrides(use_database: bool) -> list:
    """Kommandozeilen-Argumente, die die INI-Werte fuer einen Dashboard-Lauf ueberschreiben."""
    values = {
        "pipeline.use_database": "true" if use_database else "false",
        "pipeline.write_prog_data": "true",
        "plot.show_plot": "false",
        "plot.plot_show_window": "false",
    }
    args: list = []
    for dotted, value in values.items():
        args += ["--set", f"{dotted}={value}"]
    return args


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
    cmd = [sys.executable, "-u", _SCRIPT_NAME, *backend_overrides(use_database)]
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
