"""Kleiner Zeitmesser fuer die DEBUG-Zeitangaben (Start, Laden, Abfragen).

Ersetzt die verstreuten ``t0 = time.monotonic() ... log.debug(...)``-Paare::

    with timed("repo.load", log) as t:
        flotte = repo.load()
    ...
    t.seconds        # gemessene Dauer, auch nach dem Block lesbar
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator, Optional


class Timer:
    """Stoppuhr; ``seconds`` ist waehrend des Blocks die bisherige Dauer."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._final: Optional[float] = None

    def stop(self) -> float:
        if self._final is None:
            self._final = time.monotonic() - self._t0
        return self._final

    @property
    def seconds(self) -> float:
        return self._final if self._final is not None else time.monotonic() - self._t0


@contextmanager
def timed(label: str, logger: Optional[logging.Logger] = None,
          level: int = logging.DEBUG) -> Iterator[Timer]:
    """Misst den Block und loggt ``"<label>=<s>s"``. Bei ``logger=None`` nur messen."""
    timer = Timer()
    try:
        yield timer
    finally:
        secs = timer.stop()
        if logger is not None:
            logger.log(level, "%s=%.2fs", label, secs)
