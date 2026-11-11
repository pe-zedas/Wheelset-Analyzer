"""Zeitachse mit Sprung zum aktuellen Datum.

Das Backend verankert die Prognose am letzten Messwert. Liegt der Jahre zurueck,
steht die Prognose im Diagramm in der Vergangenheit (und widerspricht den Kacheln,
die die Termine auf "heute" verschieben). In dieser Darstellung bleibt die Achse
**durchgehend und im gleichen Massstab**; nur die Beschriftung aendert sich:

* links vom Uebergang (letzter Messwert) stehen die echten Daten,
* rechts davon das um ``delta`` Tage verschobene Datum (Uebergang = heute).

Die Marken liegen auf runden Zeitpunkten (Jahresmarken am 1. Januar, Monatsmarken
an Vielfachen des Intervalls). Nur wenn sich die letzte linke und die erste rechte
Marke beruehren wuerden, entfaellt die linke.
"""
from __future__ import annotations

from typing import List

import matplotlib.dates as mdates
from matplotlib.ticker import Formatter, Locator

MONTH_STEPS = (1, 2, 3, 6, 12, 24, 60)
PX_PER_TICK = 70.0        # Zielabstand der Marken in Pixeln (bestimmt das Intervall)
LABEL_PX = 56.0           # Breite einer Beschriftung: naeher duerfen sich zwei Marken nicht kommen
RIGHT_EDGE_PX = 18.0      # Marken naeher am rechten Rand werden abgeschnitten -> weglassen
FALLBACK_WIDTH_PX = 700.0


def month_step(total_days: float, width_px: float) -> int:
    """Kleinstes Monatsintervall aus ``MONTH_STEPS``, bei dem die Marken genug Platz haben."""
    months = total_days / 30.4
    return next((m for m in MONTH_STEPS if months / m <= width_px / PX_PER_TICK), MONTH_STEPS[-1])


class ShiftedDateLocator(Locator):
    """Marken links vom Uebergang in echten Daten, rechts in verschobenen Daten.

    ``junction``: Position des Uebergangs (Datumszahl von matplotlib),
    ``delta_days``: Verschiebung der Beschriftung rechts davon in Tagen.
    Die Marken werden bei jedem Zeichnen neu berechnet (Fensterbreite, Zoom).
    """

    def __init__(self, junction: float, delta_days: float):
        self.junction = float(junction)
        self.delta = float(delta_days)
        self.fmt = "%Y-%m"            # vom Formatter gelesen, wird in tick_values gesetzt

    def __call__(self):
        vmin, vmax = self.axis.get_view_interval()
        return self.tick_values(vmin, vmax)

    def _width_px(self) -> float:
        try:
            w = float(self.axis.axes.bbox.width)
        except Exception:
            w = 0.0
        return w if w > 50 else FALLBACK_WIDTH_PX

    def tick_values(self, vmin: float, vmax: float) -> List[float]:
        lo, hi = (vmin, vmax) if vmin <= vmax else (vmax, vmin)
        if hi - lo <= 0:
            return []
        j, delta = self.junction, self.delta
        per_px = (hi - lo) / self._width_px()
        k = month_step(hi - lo, self._width_px())
        self.fmt = "%Y" if k >= 12 else "%Y-%m"
        # runde Zeitpunkte: Jahresmarken am 1. Januar, Monatsmarken an Vielfachen des Intervalls
        loc = mdates.YearLocator(base=k // 12) if k >= 12 else mdates.MonthLocator(bymonth=range(1, 13, k))

        left: List[float] = []
        if lo < j:
            left = [t for t in loc.tick_values(mdates.num2date(lo), mdates.num2date(min(j, hi)))
                    if lo <= t < j]
        right: List[float] = []
        if hi > j:
            right = [t - delta for t in loc.tick_values(mdates.num2date(max(lo, j) + delta),
                                                         mdates.num2date(hi + delta))]
            right = [t for t in right if j < t <= hi - RIGHT_EDGE_PX * per_px and t >= lo]
        if left and right and (right[0] - left[-1]) / per_px < LABEL_PX:
            left = left[:-1]
        return left + right


class ShiftedDateFormatter(Formatter):
    """Beschriftung passend zu :class:`ShiftedDateLocator`: links echtes, rechts verschobenes Datum."""

    def __init__(self, locator: ShiftedDateLocator):
        self.locator = locator

    def __call__(self, x, pos=None):
        loc = self.locator
        d = mdates.num2date(x if x <= loc.junction else x + loc.delta)
        return d.strftime(loc.fmt)
