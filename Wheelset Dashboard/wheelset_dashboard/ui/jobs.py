"""Hintergrund-Aufgaben fuer langlaufende Aktionen (Laden, Backend-Prognose).

Die Oberflaeche darf waehrend einer Oracle-Abfrage (Sekunden) oder des
Backend-Laufs (Minuten) nicht einfrieren. ``BackgroundJob`` fuehrt eine
Funktion in einem eigenen Thread aus und meldet das Ergebnis per Signal im
GUI-Thread zurueck. Qt-Objekte duerfen **nicht** in ``fn`` angefasst werden.

Der Thread ist ein Daemon-Thread: Beendet der Nutzer die Anwendung waehrend
einer Abfrage, wartet der Prozess nicht darauf.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from ..perf import Timer

log = logging.getLogger(__name__)


class BackgroundJob(QObject):
    """Fuehrt ``fn()`` im Hintergrund aus.

    ``done(result)`` bzw. ``failed(message)`` kommen im Thread des
    Empfaengers an (GUI-Thread), sofern der Empfaenger ein QObject ist
    (z.B. eine ``@Slot``-Methode des Hauptfensters).
    """

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], name: str = "job", parent=None):
        super().__init__(parent)
        self._fn = fn
        self._name = name
        self._thread = threading.Thread(target=self._run, name=f"job-{name}", daemon=True)
        self.seconds = 0.0

    def start(self) -> "BackgroundJob":
        self._thread.start()
        return self

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        timer = Timer()
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - jede Ursache soll im GUI landen
            self.seconds = timer.stop()
            log.exception("Hintergrundaufgabe '%s' fehlgeschlagen", self._name)
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.seconds = timer.stop()
        log.debug("Hintergrundaufgabe '%s' fertig nach %.2fs", self._name, self.seconds)
        self.done.emit(result)
