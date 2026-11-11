"""Matplotlib-Canvas (Qt-eingebettet) fuer das Dashboard."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter


from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..data.models import PrognosePunkt
from .time_axis import ShiftedDateFormatter, ShiftedDateLocator


# Farbkonventionen (aus PRD F-UI-2):
COL_LKD1 = "#1F5FA6"    # Blau (dunkler) = Rad 1 / links
COL_LKD2 = "#8BC447"    # Gruen (heller)  = Rad 2 / rechts
COL_UNSPEC = "#444441"
COL_WARN = "#F2B82B"   # synchron zu AMPEL_COLORS[YELLOW] in widgets.py
COL_GRENZ = "#E24B4A"
COL_TODAY = "#6B6F78"

# Zeitachse mit Sprung: erst wenn der letzte Messwert so viele Tage zurueckliegt
TIME_JUMP_MIN_DAYS = 90


SIDE_COLORS = {
    "left": COL_LKD1,
    "right": COL_LKD2,
    "unspecified": COL_UNSPEC,
}
SIDE_LABEL = {
    "left": "Rad links",
    "right": "Rad rechts",
    "unspecified": "Messung",
}


def _estimate_km_per_day(mr) -> Optional[float]:
    """Schaetzt km/Tag aus den juengsten Historie-Punkten (Median der Deltas)."""
    pts = [mp for mp in mr.historie
           if mp.laufleistung is not None and mp.datum is not None]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda mp: mp.datum)
    # Verwende die letzten 6 Punkte (oder alle, wenn weniger)
    recent = pts[-6:]
    rates = []
    for a, b in zip(recent, recent[1:]):
        dd = (b.datum - a.datum).days
        dkm = b.laufleistung - a.laufleistung
        if dd > 0 and dkm > 0:
            rates.append(dkm / dd)
    if not rates:
        return None
    rates.sort()
    return rates[len(rates) // 2]


def _km_formatter(v, _pos=None):
    """1 234 000 → '1 234 Tkm', 500 000 → '500 Tkm', < 1000 → als Zahl."""
    if v is None:
        return ""
    v = float(v)
    if abs(v) >= 1000:
        return f"{v/1000:,.0f} Tkm".replace(",", " ")
    return f"{v:.0f} km"


def _find_crossing(points, y_val, x_mode, get_x, get_y):
    """Findet den X-Wert, an dem eine Punktfolge absteigend den Y-Wert
    ``y_val`` erreicht bzw. unterschreitet.

    Allgemeine Suche in einer sortierten Punkt-Folge (Treppe oder
    Historie). Reprof-Spruenge (gleiches X, Y springt nach unten) werden
    beruecksichtigt. Gibt None zurueck, wenn die Linie den Y-Wert nicht
    (absteigend) kreuzt.
    """
    if y_val is None or not points:
        return None
    xs = [get_x(p) for p in points]
    ys = [get_y(p) for p in points]
    if any(x is None for x in xs) or any(y is None for y in ys):
        return None
    for i in range(1, len(xs)):
        y_a, y_b = ys[i - 1], ys[i]
        x_a, x_b = xs[i - 1], xs[i]
        if x_a == x_b:
            if y_a >= y_val >= y_b:
                return x_a
            continue
        if y_a >= y_val and y_b <= y_val:
            if y_a == y_b:
                return x_a
            frac = (y_a - y_val) / (y_a - y_b)
            return x_a + (x_b - x_a) * frac
    return None


def _trim_staircase(punkte, min_v):
    """Schneidet die Prognose-Treppe am ersten absteigenden Erreichen von ``min_v`` ab.

    Das Backend liefert die Treppe bis MIN (``_simulate_with_reprofilings`` in
    prognosis_new_core.py); das Trimmen dient nur als Sicherheitsnetz fuer evtl.
    alte Prognose-Zeilen, die noch ueber MIN hinauslaufen.
    """
    if not punkte or min_v is None:
        return punkte
    trimmed: List[PrognosePunkt] = []
    for p in punkte:
        if not trimmed:
            trimmed.append(p)
            continue
        prev = trimmed[-1]
        if prev.stand >= min_v and p.stand < min_v:
            if prev.datum == p.datum:
                trimmed.append(PrognosePunkt(datum=p.datum, stand=min_v,
                                             laufleistung=p.laufleistung))
            else:
                frac = (prev.stand - min_v) / (prev.stand - p.stand)
                new_datum = prev.datum + (p.datum - prev.datum) * frac
                new_lauf = None
                if prev.laufleistung is not None and p.laufleistung is not None:
                    new_lauf = prev.laufleistung + (p.laufleistung - prev.laufleistung) * frac
                trimmed.append(PrognosePunkt(datum=new_datum, stand=min_v,
                                             laufleistung=new_lauf))
            break
        trimmed.append(p)
    return trimmed


def _endpoint_polyline(letzt, prog, x_mode) -> List[Tuple[float, float]]:
    """Fallback-Linie letzter Messwert → Warn → Grenz aus den Prognose-Endpunkten."""
    y_warn, y_grenz = letzt.gelb_min, letzt.min_val
    if x_mode == "datum":
        x_start = letzt.datum
        ends = ((prog.datum_warnwert, y_warn), (prog.datum_grenzwert, y_grenz))
    elif x_mode == "km" and letzt.laufleistung is not None:
        x_start = letzt.laufleistung
        ends = ((prog.km_warnwert, y_warn), (prog.km_grenzwert, y_grenz))
    else:
        return []
    pts = [(x_start, letzt.stand)]
    for x_end, y_end in ends:
        if x_end is not None and y_end is not None and x_end > x_start:
            pts.append((x_end, y_end))
    return pts


def _crossing_x(punkte, historie, y_val, x_mode, fallback):
    """X-Wert, an dem die Prognose-Treppe ``y_val`` absteigend erreicht.

    - Reprof-Spruenge (gleiches X, Y springt nach unten) werden beruecksichtigt;
      ein Punkt GENAU auf ``y_val`` (z.B. letzter Punkt nach Trim bei MIN) zaehlt.
    - Fallback 1: Kreuzpunkt in der HISTORIE (typisch bei Lagerkomponenten, deren
      Treppe schon unter der Schwelle startet).
    - Fallback 2: ``fallback`` (Wert aus der Prognose-Tabelle).
    """
    if x_mode == "datum":
        get_p, get_h = (lambda p: p.datum), (lambda mp: mp.datum)
    else:
        get_p, get_h = (lambda p: p.laufleistung), (lambda mp: mp.laufleistung)
    x = _find_crossing(punkte, y_val, x_mode, get_x=get_p, get_y=lambda p: p.stand)
    if x is None:
        x = _find_crossing(historie, y_val, x_mode, get_x=get_h, get_y=lambda mp: mp.stand) or fallback
    return x


class PlotCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None):
        fig = Figure(figsize=(8, 4), tight_layout=True, facecolor="#FFFFFF")
        super().__init__(fig)
        self._ax = fig.add_subplot(111)
        self._style_axes()
        self.setMinimumHeight(320)
        self.setParent(parent)

    def _style_axes(self):
        ax = self._ax
        ax.set_facecolor("#FFFFFF")
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        for spine in ("left", "bottom"):
            ax.spines[spine].set_color("#D4D6DC")
        ax.tick_params(colors="#6B6F78", labelsize=9)
        ax.grid(True, color="#F0F2F6", linewidth=0.8)
        ax.yaxis.label.set_color("#6B6F78")
        ax.xaxis.label.set_color("#6B6F78")

    def clear(self):
        self._ax.clear()
        self._style_axes()

    def plot_messreihen(
        self,
        reihen: List[Tuple[str, object, Optional[object]]],   # (side, Messreihe, Prognose|None)
        y_label: str = "Wert",
        x_mode: str = "datum",       # "datum" | "km"
        today=None,
        prognose_config=None,         # PrognoseConfig (optional)
        flotte=None,                  # Flotte fuer Fleet-Fallback der Prognose-Parameter
        achse=None,                   # Achse fuer gemeinsames Reprof-Intervall beider Raeder
    ):
        """Zeichnet eine oder mehrere Messreihen (Rad links/rechts) mit optionaler Prognose.

        Reihenfolge (bestimmt Legende und Ueberlagerung): Messwerte, Prognose samt
        Markern, Grenzlinien, Heute-Linie, Achsenformat, Legende.
        """
        self.clear()

        # Sammel-Achse ("Radsatz-Zuordnung fehlt"): Werte mehrerer Raeder
        # stehen unter einem Zaehler. Eine Linie dazwischen wuerde einen Trend
        # vortaeuschen -> nur Punkte zeichnen.
        pooled = achse is not None and getattr(achse, "kind", None) == "sammel"

        plotted, limits = self._draw_series(reihen, x_mode, pooled)
        prognose_drawn = self._draw_prognosen(reihen, x_mode)
        self._draw_thresholds(limits)
        # Zeitachse mit Sprung zum aktuellen Datum (Einstellung "Darstellung"): ersetzt die Heute-Linie
        possible = None
        if x_mode == "datum" and prognose_drawn:
            possible = self._time_jump(reihen, today or datetime.now())
        jump = possible if getattr(prognose_config, "time_jump", False) else None
        self.time_jump_possible = possible is not None   # fuer den Schalter in der Achsen-Ansicht
        if today is not None and x_mode == "datum" and jump is None:
            self._draw_today(today)

        # Prognose-Parameter-Info und "Keine Prognose vorhanden"-Hinweis
        # werden NICHT im Plot gezeichnet, sondern von der View als
        # Kacheln unter dem Diagramm platziert (siehe self._prognose_info
        # und self._prognose_available).
        self._prognose_available = bool(self._prognose_info) or prognose_drawn

        self.time_jump_active = jump is not None      # fuer den Schalter in der Achsen-Ansicht
        self._format_axes(x_mode, y_label, jump)
        if jump is not None:
            self._draw_jump_marker(jump, today or datetime.now())
        self._draw_legend_or_hint(plotted, reihen, x_mode)
        self.draw_idle()

    # ---- Zeitachse mit Sprung -----------------------------------------

    @staticmethod
    def _time_jump(reihen, heute):
        """``(Uebergang als Datum, Verschiebung in Tagen)`` oder ``None``.

        Uebergang = letzter Messwert der Raeder mit Prognose (bei zwei Raedern der spaetere);
        die Verschiebung ist der Abstand bis heute. Liegt der Messwert nicht weit genug zurueck,
        bleibt die normale Achse.
        """
        lasts = [max(p.datum for p in mr.historie) for _, mr, prog in reihen
                 if prog is not None and mr.historie]
        if not lasts:
            return None
        x_j = max(lasts)
        delta = (heute - x_j).total_seconds() / 86400.0
        return (x_j, delta) if delta > TIME_JUMP_MIN_DAYS else None

    def _draw_jump_marker(self, jump, heute):
        """Senkrechte Linie am Uebergang; die Ueberschrift "heute (Datum)" steht ueber der Achse,
        damit die Legende sie nie verdeckt (bei weit rechts liegender Linie links davon)."""
        ax = self._ax
        x_j, _delta = jump
        ax.axvline(x_j, color=COL_TODAY, linestyle="--", linewidth=0.9, alpha=0.9)
        lo, hi = ax.get_xlim()
        right_side = (mdates.date2num(x_j) - lo) / (hi - lo) > 0.55
        ax.annotate(f"heute ({heute:%d.%m.%Y})", xy=(x_j, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(-4 if right_side else 4, 3), textcoords="offset points",
                    ha="right" if right_side else "left", va="bottom",
                    color=COL_TODAY, fontsize=8, annotation_clip=False)

    # ---- Messwerte ----------------------------------------------------

    def _draw_series(self, reihen, x_mode, pooled):
        """Zeichnet die Messwerte je Rad und sammelt die Schwellen aus den
        Messpunkten. Rueckgabe: ``(wurde_gezeichnet, schwellen)``."""
        ax = self._ax
        plotted = False
        limits = {"min": [], "max": [], "gelb_min": [], "gelb_max": []}
        for side, mr, _ in reihen:
            if not mr.historie:
                continue
            # Chronologisch sortieren, damit die Linie keine Ruecksprünge macht
            if x_mode == "km":
                pts = [mp for mp in mr.historie if mp.laufleistung is not None]
                pts.sort(key=lambda mp: mp.laufleistung)
                xs = [mp.laufleistung for mp in pts]
                ys = [mp.stand for mp in pts]
            else:
                pts = sorted(mr.historie, key=lambda mp: mp.datum)
                xs = [mp.datum for mp in pts]
                ys = [mp.stand for mp in pts]
            if not xs:
                continue
            col = SIDE_COLORS.get(side, COL_UNSPEC)
            # Linie + Punkte in einem Zug (gemeinsamer Legend-Eintrag)
            ax.plot(xs, ys, color=col, linewidth=1.2, marker="o", markersize=4,
                    linestyle="none" if pooled else "-",
                    zorder=3, label=SIDE_LABEL.get(side, side))
            plotted = True
            for mp in mr.historie:
                if mp.min_val is not None:
                    limits["min"].append(mp.min_val)
                if mp.max_val is not None:
                    limits["max"].append(mp.max_val)
                if mp.gelb_min is not None:
                    limits["gelb_min"].append(mp.gelb_min)
                if mp.gelb_max is not None:
                    limits["gelb_max"].append(mp.gelb_max)
        return plotted, limits

    # ---- Prognose -----------------------------------------------------

    def _draw_prognosen(self, reihen, x_mode) -> bool:
        """Prognose-Visualisierung: ausschliesslich aus ``mr.prognose``.

        Prognose-Darstellung ist nur fuer LKD definiert; fuer alle anderen
        Messgroessen (Sd, Sh, Spur, Stichmass ...) gibt es keine Prognose in
        der Tabelle. Fuellt ``self._prognose_info`` (Infotext-Daten je Rad:
        ``(label, prognose)``) und gibt zurueck, ob eine Prognose gezeichnet wurde.
        """
        self._prognose_info = []
        messgroesse = next((mr.messgroesse for _, mr, _ in reihen if mr), None)
        if messgroesse != "LKD":
            return False
        drawn = False
        for side, mr, prog in reihen:
            if prog is None or not mr.historie:
                continue
            drawn |= self._draw_prognose_row(side, mr, prog, x_mode)
            if drawn:
                self._prognose_info.append((SIDE_LABEL.get(side, side), prog))
        return drawn

    def _draw_prognose_row(self, side, mr, prog, x_mode) -> bool:
        """Prognose-Linie und Warn-/Grenz-Marker eines Rades. ``True``, wenn die
        Linie gezeichnet wurde.

        Die Prognose-Tabelle liefert die komplette Treppenkurve pro Rad
        (``prog.punkte``). Reprofilierungssprünge sind als zwei Punkte am selben
        Datum enthalten (erst "vor", dann "nach"), ein verbundener Linienzug
        erzeugt dadurch den senkrechten Sprung nach unten. Fehlen die
        Treppen-Punkte (z.B. nach einem Oracle-Lauf mit nur Endpunkten), wird die
        3-Punkt-Linie (letzter Messwert → Warn → Grenz) gezeichnet.
        """
        ax = self._ax
        letzt = max(mr.historie, key=lambda mp: mp.datum)
        col = SIDE_COLORS.get(side, COL_UNSPEC)
        label = f"Prognose {SIDE_LABEL.get(side, side).lower()}"
        punkte = _trim_staircase(list(getattr(prog, "punkte", []) or []), letzt.min_val)

        drawn = False
        if punkte:
            if x_mode == "km":
                xs_vals = [p.laufleistung for p in punkte]
                ys_vals = [p.stand for p in punkte]
                if any(v is None for v in xs_vals):
                    xs_vals = None
            else:
                xs_vals = [p.datum for p in punkte]
                ys_vals = [p.stand for p in punkte]
            if xs_vals is not None:
                ax.plot(xs_vals, ys_vals, color=col, linestyle="--", linewidth=1.3,
                        marker="", zorder=2, label=label)
                drawn = True
        else:
            pts = _endpoint_polyline(letzt, prog, x_mode)
            if len(pts) >= 2:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col,
                        linestyle="--", linewidth=1.3, marker="", zorder=2, label=label)
                drawn = True

        # Marker an den Prognose-Endpunkten (Warn: Kreis, Grenz: Raute) auf der
        # PROGNOSE-TREPPE, wo sie den Warn- bzw. Grenz-Y-Wert (gelb_min bzw.
        # min_val) absteigend kreuzt. So sitzt der Marker immer auf der Linie,
        # auch bei ruhenden Raedern. Fallbacks: Historie, dann Tabellenwerte.
        km = x_mode != "datum"
        y_warn, y_grenz = letzt.gelb_min, letzt.min_val
        x_warn = _crossing_x(punkte, mr.historie, y_warn, x_mode,
                             prog.km_warnwert if km else prog.datum_warnwert)
        x_grenz = _crossing_x(punkte, mr.historie, y_grenz, x_mode,
                              prog.km_grenzwert if km else prog.datum_grenzwert)
        self._draw_marker(x_warn, y_warn, col, COL_WARN, "o")
        self._draw_marker(x_grenz, y_grenz, col, COL_GRENZ, "D")
        return drawn

    def _draw_marker(self, x_val, y_val, face_col, edge_col, marker):
        if x_val is None or y_val is None:
            return
        self._ax.plot([x_val], [y_val], marker=marker, markersize=8,
                      markerfacecolor=face_col, markeredgecolor=edge_col,
                      markeredgewidth=1.5, zorder=4, linestyle="")

    # ---- Grenzlinien, Heute-Linie, Achsen -----------------------------

    def _draw_thresholds(self, limits):
        """Horizontale Schwellen — alle vier Werte zeichnen, soweit geliefert.

        Die ``direction`` steuert nur die Status-Berechnung, nicht die Darstellung.
        Gezeigte Werte muessen aber einen gueltigen Zwischenbereich bilden
        (schuetzt vor inkonsistenten Werten wie GELB_MAX = MIN).
        """
        ax = self._ax
        drawn_values = []   # fuer Y-Achsen-Erweiterung
        min_v = min(limits["min"]) if limits["min"] else None
        max_v = max(limits["max"]) if limits["max"] else None

        if min_v is not None:
            ax.axhline(min_v, color=COL_GRENZ, linestyle=":", linewidth=1.2, label=f"MIN {min_v:g}")
            drawn_values.append(min_v)
        if max_v is not None:
            ax.axhline(max_v, color=COL_GRENZ, linestyle=":", linewidth=1.2, label=f"MAX {max_v:g}")
            drawn_values.append(max_v)
        for key, pick, name in (("gelb_min", max, "GELB_MIN"), ("gelb_max", min, "GELB_MAX")):
            if limits[key]:
                v = pick(limits[key])
                # Warnlinie: muss echt zwischen MIN und MAX liegen
                if (min_v is None or v > min_v) and (max_v is None or v < max_v):
                    ax.axhline(v, color=COL_WARN, linestyle=":", linewidth=1.2, label=f"{name} {v:g}")
                    drawn_values.append(v)

        # Y-Achse so erweitern, dass alle gezeichneten Grenz-/Warnlinien sichtbar sind
        if drawn_values:
            ymin_cur, ymax_cur = ax.get_ylim()
            pad = (max(drawn_values) - min(drawn_values)) * 0.08 if len(drawn_values) > 1 else 1.0
            ax.set_ylim(min(ymin_cur, min(drawn_values) - pad),
                        max(ymax_cur, max(drawn_values) + pad))

    def _draw_today(self, today):
        """Heute-Linie — nur, wenn sie den Verlauf nicht zusammenstaucht.

        Bei historischen Daten (z.B. Abellio: Messungen enden Jahre vor heute)
        wuerde axvline() die Achse bis heute aufziehen und den eigentlichen
        Verlauf in eine Ecke druecken.
        """
        ax = self._ax
        x_lo, x_hi = ax.get_xlim()
        if mdates.date2num(today) <= x_hi + 0.5 * (x_hi - x_lo):
            ax.axvline(today, color=COL_TODAY, linestyle="--", linewidth=0.8, alpha=0.8)
            ax.text(today, ax.get_ylim()[1], "  heute", color=COL_TODAY, fontsize=8, va="top")

    def _format_axes(self, x_mode, y_label, jump=None):
        ax = self._ax
        if x_mode == "datum" and jump is not None:
            locator = ShiftedDateLocator(mdates.date2num(jump[0]), jump[1])
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(ShiftedDateFormatter(locator))
            ax.set_xlabel("Datum  (ab Prognosebeginn um den Abstand zu heute verschoben)")
        elif x_mode == "datum":
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            # Bei kurzen Zeitraeumen (z.B. alle Messwerte eines Tages) waere
            # "%Y-%m" an jeder Marke gleich -> feiner beschriften.
            x_lo, x_hi = ax.get_xlim()
            span_days = x_hi - x_lo
            if span_days < 3:
                fmt = "%d.%m.%Y %H:%M"
            elif span_days < 150:
                fmt = "%d.%m.%Y"
            else:
                fmt = "%Y-%m"
            ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
            ax.set_xlabel("Datum")
        else:
            # Grosse Werte in "Tkm" (Tausend Kilometer) statt 1.4e6
            ax.xaxis.get_offset_text().set_visible(False)
            ax.ticklabel_format(style="plain", axis="x", useOffset=False)
            ax.xaxis.set_major_formatter(FuncFormatter(_km_formatter))
            ax.set_xlabel("Laufleistung")
        ax.set_ylabel(y_label)

    def _draw_legend_or_hint(self, plotted, reihen, x_mode):
        ax = self._ax
        if plotted:
            ax.legend(loc="upper right", fontsize=8, frameon=False)
            return
        hint = ("Keine Laufleistung in den Daten"
                if x_mode == "km" and any(mr.historie for _, mr, _ in reihen)
                else "Keine Messwerte für diese Auswahl")
        ax.text(0.5, 0.5, hint, ha="center", va="center", transform=ax.transAxes,
                color="#8A8F99", fontsize=11)


class PlotPane(QWidget):
    """QWidget mit Canvas (ohne Toolbar — minimalistisch)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = PlotCanvas(self)
        lay.addWidget(self.canvas, 1)
