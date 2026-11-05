"""Matplotlib-Canvas (Qt-eingebettet) fuer das Dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from PySide6.QtWidgets import QVBoxLayout, QWidget


# Farbkonventionen (aus PRD F-UI-2):
COL_LKD1 = "#1F5FA6"    # Blau (dunkler) = Rad 1 / links
COL_LKD2 = "#8BC447"    # Gruen (heller)  = Rad 2 / rechts
COL_UNSPEC = "#444441"
COL_WARN = "#F2B82B"   # synchron zu AMPEL_COLORS[YELLOW] in widgets.py
COL_GRENZ = "#E24B4A"
COL_TODAY = "#6B6F78"


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
        """Zeichnet eine oder mehrere Messreihen (Rad links/rechts) mit optionaler Prognose."""
        self.clear()
        ax = self._ax

        all_min = []
        all_max = []
        all_gelb_min = []
        all_gelb_max = []

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
                    zorder=3, label=SIDE_LABEL.get(side, side))
            # Schwellen sammeln
            for mp in mr.historie:
                if mp.min_val is not None: all_min.append(mp.min_val)
                if mp.max_val is not None: all_max.append(mp.max_val)
                if mp.gelb_min is not None: all_gelb_min.append(mp.gelb_min)
                if mp.gelb_max is not None: all_gelb_max.append(mp.gelb_max)

        # Prognose-Visualisierung: ausschliesslich aus mr.prognose.
        # Die Prognose-Tabelle liefert die komplette Treppenkurve pro Rad
        # (prog.punkte = Liste von PrognosePunkt(datum, stand, laufleistung)).
        # Reprofilierungssprünge sind in der Liste als zwei Punkte am
        # selben Datum enthalten (erst "vor-Reprof", dann "nach-Reprof"),
        # ein verbundener Linienzug erzeugt dadurch automatisch den
        # senkrechten Sprung nach unten.
        #
        # Als Fallback — wenn die Treppen-Punkte fehlen (z.B. nach einem
        # Oracle-Lauf mit nur Endpunkten) — wird die klassische 3-Punkt-
        # Linie (letzter Messwert → Warn → Grenz) gezeichnet.
        #
        # Prognose-Darstellung ist nur fuer LKD definiert; fuer alle anderen
        # Messgroessen (Sd, Sh, Spur, Stichmass …) gibt es keine Prognose
        # in der Tabelle.
        messgroesse = next((mr.messgroesse for _, mr, _ in reihen if mr), None)
        prognose_supported = (messgroesse == "LKD")
        prognose_drawn = False
        self._prognose_info = []   # Infotext-Daten je Rad: (label, prognose)

        for side, mr, prog in reihen:
            if not prognose_supported:
                break
            if prog is None or not mr.historie:
                continue
            letzt = max(mr.historie, key=lambda mp: mp.datum)
            col = SIDE_COLORS.get(side, COL_UNSPEC)

            punkte = list(getattr(prog, "punkte", []) or [])

            # Treppe am ersten absteigenden Erreichen von MIN abschneiden.
            # Das Backend liefert die Treppe bis MIN (siehe
            # ``_simulate_with_reprofilings`` in prognosis_new_core.py);
            # das Trimmen hier dient nur als Sicherheitsnetz fuer evtl.
            # alte Prognose-Zeilen, die noch ueber MIN hinauslaufen.
            if punkte and letzt.min_val is not None:
                from ..data.models import PrognosePunkt as _PP
                trimmed: List[_PP] = []
                min_v = letzt.min_val
                for i, p in enumerate(punkte):
                    if not trimmed:
                        trimmed.append(p)
                        continue
                    prev = trimmed[-1]
                    if prev.stand >= min_v and p.stand < min_v:
                        if prev.datum == p.datum:
                            trimmed.append(_PP(datum=p.datum, stand=min_v,
                                                laufleistung=p.laufleistung))
                        else:
                            frac = (prev.stand - min_v) / (prev.stand - p.stand)
                            new_datum = prev.datum + (p.datum - prev.datum) * frac
                            new_lauf = None
                            if prev.laufleistung is not None and p.laufleistung is not None:
                                new_lauf = prev.laufleistung + (p.laufleistung - prev.laufleistung) * frac
                            trimmed.append(_PP(datum=new_datum, stand=min_v, laufleistung=new_lauf))
                        break
                    trimmed.append(p)
                punkte = trimmed

            # Linie bauen. Primaerer Weg: die aus der Prognose-Tabelle
            # geladene Treppe. Beginnend bei dem Punkt, der direkt vor dem
            # letzten echten Messwert liegt — so laeuft die Treppe nahtlos
            # aus der Historie heraus.
            if punkte:
                if x_mode == "km":
                    xs_vals = [p.laufleistung for p in punkte]
                    if any(v is None for v in xs_vals):
                        xs_vals = None
                    else:
                        ys_vals = [p.stand for p in punkte]
                else:   # datum
                    xs_vals = [p.datum for p in punkte]
                    ys_vals = [p.stand for p in punkte]
                if xs_vals is not None:
                    ax.plot(xs_vals, ys_vals, color=col, linestyle="--",
                            linewidth=1.3, marker="", zorder=2,
                            label=f"Prognose {SIDE_LABEL.get(side, side).lower()}")
                    prognose_drawn = True
            else:
                # Fallback: 3-Punkt-Linie aus Endpunkten.
                y_warn = letzt.gelb_min
                y_grenz = letzt.min_val
                if x_mode == "datum":
                    x_start, y_start = letzt.datum, letzt.stand
                    dw, dg = prog.datum_warnwert, prog.datum_grenzwert
                    pts: List[Tuple[datetime, float]] = [(x_start, y_start)]
                    if dw is not None and y_warn is not None and dw > x_start:
                        pts.append((dw, y_warn))
                    if dg is not None and y_grenz is not None and dg > x_start:
                        pts.append((dg, y_grenz))
                elif x_mode == "km" and letzt.laufleistung is not None:
                    x_start, y_start = letzt.laufleistung, letzt.stand
                    kw, kg = prog.km_warnwert, prog.km_grenzwert
                    pts = [(x_start, y_start)]
                    if kw is not None and y_warn is not None and kw > x_start:
                        pts.append((kw, y_warn))
                    if kg is not None and y_grenz is not None and kg > x_start:
                        pts.append((kg, y_grenz))
                else:
                    pts = []
                if len(pts) >= 2:
                    ax.plot([p[0] for p in pts], [p[1] for p in pts],
                            color=col, linestyle="--", linewidth=1.3,
                            marker="", zorder=2,
                            label=f"Prognose {SIDE_LABEL.get(side, side).lower()}")
                    prognose_drawn = True

            # Marker an den Prognose-Endpunkten (Warn: Kreis, Grenz: Raute).
            # Sie werden auf der PROGNOSE-TREPPE platziert — an der Stelle,
            # wo die Treppe den Warn- bzw. Grenz-Y-Wert (gelb_min bzw.
            # min_val) absteigend kreuzt. So sitzt der Marker immer auf
            # der Linie, auch bei ruhenden Raedern (Treppe ab letztem
            # Messwert; prog.datum_warnwert/grenzwert liegen dagegen in
            # der Zukunft und werden daher NICHT fuer den Marker benutzt).
            # Fallback auf die Tabellenwerte, wenn keine Treppe vorhanden
            # ist (3-Punkt-Linie).
            def _x_at_y(y_val):
                """Findet den X-Wert, an dem die Treppe erstmals absteigend
                den Y-Wert ``y_val`` erreicht bzw. unterschreitet.

                - Reprof-Spruenge (gleiches X, Y springt nach unten) werden
                  uebersprungen; stattdessen wird der Punkt NACH dem Sprung
                  bewertet.
                - Ein Punkt der Treppe, der GENAU auf ``y_val`` liegt (z.B.
                  letzter Punkt nach Trim bei MIN), zaehlt als Erreichen.
                - Falls die Treppe erst innerhalb eines Reprof-Sprungs
                  (vertikal) durch y_val geht, wird das X des Sprungs
                  zurueckgegeben.
                """
                return _find_crossing(punkte, y_val, x_mode,
                                        get_x=(lambda p: p.datum) if x_mode == "datum"
                                              else (lambda p: p.laufleistung),
                                        get_y=lambda p: p.stand)

            def _x_at_y_history(y_val):
                """Fallback: Kreuzpunkt in der HISTORIE suchen (nur wenn
                die Prognose-Treppe keinen liefert — typisch bei
                Lagerkomponenten, deren Prognose-Treppe schon unter der
                Schwelle startet, die aber in der Historie durch die
                Schwelle gelaufen sind)."""
                return _find_crossing(mr.historie, y_val, x_mode,
                                        get_x=(lambda mp: mp.datum) if x_mode == "datum"
                                              else (lambda mp: mp.laufleistung),
                                        get_y=lambda mp: mp.stand)

            def _marker(x_val, y_val, m_col, m_marker):
                if x_val is None or y_val is None:
                    return
                ax.plot([x_val], [y_val], marker=m_marker, markersize=8,
                        markerfacecolor=col, markeredgecolor=m_col,
                        markeredgewidth=1.5, zorder=4, linestyle="")
            # Y-Werte der Marker = Schwellen aus dem letzten Messpunkt
            y_warn = letzt.gelb_min
            y_grenz = letzt.min_val
            # Erst in der Prognose-Treppe suchen; falls dort nichts (z.B.
            # Lagerkomponente mit Treppe die schon unter Schwelle startet),
            # in der Historie suchen; letzter Fallback: Prognose-Tabellen-km.
            if x_mode == "datum":
                x_warn = _x_at_y(y_warn)
                if x_warn is None:
                    x_warn = _x_at_y_history(y_warn) or prog.datum_warnwert
                x_grenz = _x_at_y(y_grenz)
                if x_grenz is None:
                    x_grenz = _x_at_y_history(y_grenz) or prog.datum_grenzwert
            else:
                x_warn = _x_at_y(y_warn)
                if x_warn is None:
                    x_warn = _x_at_y_history(y_warn) or prog.km_warnwert
                x_grenz = _x_at_y(y_grenz)
                if x_grenz is None:
                    x_grenz = _x_at_y_history(y_grenz) or prog.km_grenzwert
            _marker(x_warn, y_warn, COL_WARN, "o")
            _marker(x_grenz, y_grenz, COL_GRENZ, "D")

            if prognose_drawn:
                self._prognose_info.append((SIDE_LABEL.get(side, side), prog))

        # Horizontale Schwellen — alle vier Werte zeichnen, soweit die CSV
        # sie liefert. Die ``direction`` steuert nur die Status-Berechnung,
        # nicht die Darstellung. Gezeigte Werte muessen aber einen gueltigen
        # Zwischenbereich bilden (schuetzt vor inkonsistenten CSV-Werten
        # wie GELB_MAX = MIN).
        drawn_values = []   # fuer Y-Achsen-Erweiterung
        min_v = min(all_min) if all_min else None
        max_v = max(all_max) if all_max else None

        if min_v is not None:
            ax.axhline(min_v, color=COL_GRENZ, linestyle=":", linewidth=1.2,
                       label=f"MIN {min_v:g}")
            drawn_values.append(min_v)
        if max_v is not None:
            ax.axhline(max_v, color=COL_GRENZ, linestyle=":", linewidth=1.2,
                       label=f"MAX {max_v:g}")
            drawn_values.append(max_v)
        if all_gelb_min:
            v = max(all_gelb_min)
            # Warnlinie unten: muss echt zwischen MIN und MAX liegen
            if (min_v is None or v > min_v) and (max_v is None or v < max_v):
                ax.axhline(v, color=COL_WARN, linestyle=":", linewidth=1.2,
                           label=f"GELB_MIN {v:g}")
                drawn_values.append(v)
        if all_gelb_max:
            v = min(all_gelb_max)
            # Warnlinie oben: muss echt zwischen MIN und MAX liegen
            if (min_v is None or v > min_v) and (max_v is None or v < max_v):
                ax.axhline(v, color=COL_WARN, linestyle=":", linewidth=1.2,
                           label=f"GELB_MAX {v:g}")
                drawn_values.append(v)

        # Y-Achse so erweitern, dass alle gezeichneten Grenz-/Warnlinien sichtbar sind
        if drawn_values:
            ymin_cur, ymax_cur = ax.get_ylim()
            pad = (max(drawn_values) - min(drawn_values)) * 0.08 if len(drawn_values) > 1 else 1.0
            ax.set_ylim(min(ymin_cur, min(drawn_values) - pad),
                        max(ymax_cur, max(drawn_values) + pad))

        # Heute-Linie
        if today is not None and x_mode == "datum":
            ax.axvline(today, color=COL_TODAY, linestyle="--", linewidth=0.8, alpha=0.8)
            ax.text(today, ax.get_ylim()[1], "  heute",
                    color=COL_TODAY, fontsize=8, va="top")

        # (Vertikale Warn-/Grenz-Linien entfernt — die Schnittpunkte werden
        # jetzt direkt als Marker auf der Prognosekurve angezeigt.)

        # Prognose-Parameter-Info und "Keine Prognose vorhanden"-Hinweis
        # werden NICHT im Plot gezeichnet, sondern von der View als
        # Kacheln unter dem Diagramm platziert (siehe self._prognose_info
        # und self._prognose_available).
        info = getattr(self, "_prognose_info", []) or []
        self._prognose_available = bool(info) or prognose_drawn

        # Achsenformat
        if x_mode == "datum":
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            ax.set_xlabel("Datum")
        else:
            # Grosse Werte in "Tkm" (Tausend Kilometer) statt 1.4e6
            ax.xaxis.get_offset_text().set_visible(False)
            ax.ticklabel_format(style="plain", axis="x", useOffset=False)
            ax.xaxis.set_major_formatter(FuncFormatter(_km_formatter))
            ax.set_xlabel("Laufleistung")
        ax.set_ylabel(y_label)
        if reihen:
            ax.legend(loc="upper right", fontsize=8, frameon=False)
        self.draw_idle()


class PlotPane(QWidget):
    """QWidget mit Canvas (ohne Toolbar — minimalistisch)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = PlotCanvas(self)
        lay.addWidget(self.canvas, 1)
