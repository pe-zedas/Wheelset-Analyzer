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

        # Prognose-Visualisierung: entweder Treppen-Prognose aus der lokalen
        # Logik (wenn PrognoseConfig gegeben + Treppen/CI aktiv). Modus-
        # unabhaengig: im km-Modus direkt, im Datum-Modus ueber km->Datum.
        use_ci = (prognose_config is not None
                  and getattr(prognose_config, "show_ci_band", False))

        # Prognose-Algorithmus (project_with_reprofs + ci_band) ist nur fuer
        # LKD validiert — der Zyklus-Fit, die Reprof-Erkennung und das
        # Treppen-Modell beruhen auf dem Verschleissverhalten des
        # Laufkreisdurchmessers. Fuer andere Messgroessen (Sd, Sh, Spur,
        # Stichmass …) gibt es dafuer kein Modell → wir zeichnen keine
        # Prognose und zeigen stattdessen einen Hinweis.
        messgroesse = next((mr.messgroesse for _, mr, _ in reihen if mr), None)
        prognose_supported = (messgroesse == "LKD")
        prognose_drawn = False

        # Treppen-Prognose: im km-Modus direkt; im Datum-Modus ueber km->Datum-
        # Umrechnung (km/Tag aus der Historie geschaetzt).
        use_steps_any = (prognose_config is not None
                         and getattr(prognose_config, "show_reprof_steps", False)
                         and prognose_supported)
        self._prognose_info = []   # Infotext-Daten je Rad
        if use_steps_any:
            from ..logic.prognose import (
                project_with_reprofs, ci_band, effective_params, crossings,
                cycle_fit,
            )
            # Fuer Schwellen-Marker: GELB_MIN und MIN sammeln
            _gelb_min = max([mp.gelb_min for _, mr, _ in reihen
                             for mp in mr.historie if mp.gelb_min is not None], default=None)
            _min_v = max([mp.min_val for _, mr, _ in reihen
                          for mp in mr.historie if mp.min_val is not None], default=None)
            for side, mr, prog in reihen:
                if not mr.historie:
                    continue
                col = SIDE_COLORS.get(side, COL_UNSPEC)
                treppen = project_with_reprofs(mr, prognose_config, flotte=flotte, achse=achse)
                if not treppen:
                    continue
                prognose_drawn = True
                xs_km = [t[0] for t in treppen]
                ys = [t[1] for t in treppen]
                km_per_day = _estimate_km_per_day(mr)
                letzt_mp = max(mr.historie, key=lambda mp: mp.datum)
                def _km_to_x(km):
                    if x_mode == "km":
                        return km
                    if km_per_day is None or km_per_day <= 0 or letzt_mp.laufleistung is None:
                        return None
                    return letzt_mp.datum + timedelta(days=(km - letzt_mp.laufleistung) / km_per_day)
                if x_mode == "km":
                    xs = xs_km
                else:
                    if km_per_day is None or km_per_day <= 0 or letzt_mp.laufleistung is None:
                        continue
                    xs = [_km_to_x(k) for k in xs_km]
                ax.plot(xs, ys, color=col, linestyle="--", linewidth=1.5,
                        marker="", zorder=2,
                        label=f"Prognose {SIDE_LABEL.get(side, side).lower()} (mit Reprof.)")
                # Marker an Schnittpunkten mit Warn- und Grenzschwelle
                for y_lvl, m_col, m_marker in ((_gelb_min, COL_WARN, "o"),
                                                (_min_v, COL_GRENZ, "D")):
                    if y_lvl is None:
                        continue
                    for km_cross, y_cross in crossings(treppen, y_lvl):
                        x_c = _km_to_x(km_cross)
                        if x_c is None:
                            continue
                        ax.plot([x_c], [y_cross], marker=m_marker, markersize=7,
                                markerfacecolor=col, markeredgecolor=m_col,
                                markeredgewidth=1.5, zorder=4)
                # Prognose-Parameter fuer Infotext sammeln
                params = effective_params(mr, prognose_config, flotte=flotte, achse=achse)
                self._prognose_info.append(
                    (SIDE_LABEL.get(side, side),
                     params.typical_interval_km, params.typical_magnitude_mm)
                )
                # KI-Band parallel zur Treppen-Prognose:
                # Breite waechst linear mit (km - km_start), aber bei jedem
                # Reprof-Sprung verschiebt sich das Band gemeinsam mit der
                # Treppenprognose nach unten. Pro Treppen-Punkt wird der
                # Offset (slope_low/high − slope) × dkm auf die Treppen-y
                # addiert → Band folgt den Stufen.
                if use_ci:
                    fit = cycle_fit(mr, prognose_config, flotte=flotte, achse=achse)
                    cb = ci_band(mr, prognose_config,
                                 [letzt_mp.laufleistung, letzt_mp.laufleistung + 1.0],
                                 flotte=flotte, achse=achse)
                    min_v = letzt_mp.min_val
                    if fit is not None and cb is not None and min_v is not None:
                        slope = fit[0]
                        lower_pair, upper_pair = cb
                        slope_hi_band = (lower_pair[1] - lower_pair[0]) / 1.0   # faellt staerker
                        slope_lo_band = (upper_pair[1] - upper_pair[0]) / 1.0   # faellt schwaecher
                        km_start = letzt_mp.laufleistung

                        # Pro Treppen-Punkt: oberer/unterer Rand als Offset
                        # auf die Treppen-y. Dadurch folgen BEIDE Raender
                        # den Reprof-Stufen gemeinsam nach unten.
                        band_km = list(xs_km)
                        band_y = list(ys)
                        band_lower, band_upper = [], []
                        for km_i, lkd_i in zip(band_km, band_y):
                            dkm = km_i - km_start
                            delta_lo = (slope_hi_band - slope) * dkm
                            delta_hi = (slope_lo_band - slope) * dkm
                            band_lower.append(lkd_i + delta_lo)
                            band_upper.append(lkd_i + delta_hi)

                        # Band bis zur MIN-Linie fuehren: wenn die OBERE
                        # Kurve am letzten Treppen-Punkt noch ueber MIN liegt,
                        # ergaenzen wir einen Tail-Punkt rechts, bei dem der
                        # obere Rand genau auf MIN liegt. Unterer Rand wird
                        # dort und ueberall auf MIN gecappt.
                        if band_upper[-1] > min_v and slope_lo_band < 0:
                            km_tail = band_km[-1] + (min_v - band_upper[-1]) / slope_lo_band
                            if km_tail > band_km[-1]:
                                dkm_tail = km_tail - km_start
                                y_tail = band_y[-1] + slope * (km_tail - band_km[-1])
                                band_km.append(km_tail)
                                band_y.append(y_tail)
                                band_lower.append(y_tail + (slope_hi_band - slope) * dkm_tail)
                                band_upper.append(y_tail + (slope_lo_band - slope) * dkm_tail)
                        # Unterer Rand bei MIN cappen (nie unter MIN)
                        band_lower = [max(v, min_v) for v in band_lower]
                        band_upper = [max(v, min_v) for v in band_upper]

                        if x_mode == "km":
                            band_x = band_km
                        else:
                            band_x = [_km_to_x(k) for k in band_km]
                        ax.fill_between(band_x, band_lower, band_upper,
                                        color=col, alpha=0.12, zorder=1,
                                        label=f"KI-Band {int(prognose_config.ci_level*100)} % "
                                              f"{SIDE_LABEL.get(side, side).lower()}")

        # Fallback / zusaetzliche einfache Prognose-Linie
        # (nur fuer prognose-faehige Reihen, aktuell nur LKD).
        # Linie durch die beiden Prognose-Anker (Warn-Punkt bei GELB_MIN, Grenz-Punkt bei MIN),
        # verlaengert bis zum letzten Messpunkt. So entspricht die Linie der tatsaechlichen
        # Trend-Vorhersage und trifft die horizontalen Schwellen genau an den Prognose-Datumsmarken.
        _skip_linear = use_steps_any or not prognose_supported
        for side, mr, prog in reihen:
            if _skip_linear:
                break
            if prog is None or not mr.historie:
                continue
            letzt = max(mr.historie, key=lambda mp: mp.datum)
            col = SIDE_COLORS.get(side, COL_UNSPEC)

            # Steigung aus den beiden Prognose-Ankern (Warn-Punkt bei GELB_MIN,
            # Grenz-Punkt bei MIN). Linie startet am LETZTEN REALEN MESSWERT
            # und laeuft mit dieser Steigung weiter bis zum Grenzpunkt.
            if x_mode == "datum":
                dg_x = prog.datum_grenzwert
                dw_x = prog.datum_warnwert
                if dg_x is None:
                    continue
                y_grenz = letzt.min_val if letzt.min_val is not None else letzt.stand - 15
                y_warn = letzt.gelb_min
                if dw_x is not None and y_warn is not None and dw_x != dg_x:
                    span_days = (dg_x - dw_x).days or 1
                    slope = (y_grenz - y_warn) / span_days   # mm pro Tag
                    # Linie beginnt am letzten Messwert; errechne, wo sie die Grenze erreicht
                    if slope != 0:
                        days_to_grenz = (y_grenz - letzt.stand) / slope
                        x_grenz_reached = letzt.datum + timedelta(days=days_to_grenz)
                    else:
                        x_grenz_reached = dg_x
                    y_at_warn = (letzt.stand + slope * (dw_x - letzt.datum).days
                                 if dw_x > letzt.datum else None)
                    xs = [letzt.datum]
                    ys = [letzt.stand]
                    if y_at_warn is not None:
                        xs.append(dw_x); ys.append(y_at_warn)
                    xs.append(x_grenz_reached)
                    ys.append(y_grenz)
                else:
                    xs = [letzt.datum, dg_x]
                    ys = [letzt.stand, y_grenz]
                ax.plot(xs, ys, color=col, linestyle="--", linewidth=1.3,
                        marker="x", markersize=5, zorder=2,
                        label=f"Prognose {SIDE_LABEL.get(side, side).lower()}")
            elif x_mode == "km" and letzt.laufleistung is not None:
                kg = prog.km_grenzwert
                kw = prog.km_warnwert
                if kg is None:
                    continue
                y_grenz = letzt.min_val if letzt.min_val is not None else letzt.stand - 15
                y_warn = letzt.gelb_min
                if kw is not None and y_warn is not None and kw != kg:
                    slope = (y_grenz - y_warn) / (kg - kw)
                    # Linie beginnt am letzten Messwert; errechne, wo sie die
                    # Grenze erreicht (= wo die Linie y_grenz schneidet)
                    x_grenz_reached = letzt.laufleistung + (y_grenz - letzt.stand) / slope if slope != 0 else kg
                    y_at_warn = letzt.stand + slope * (kw - letzt.laufleistung) if kw > letzt.laufleistung else None
                    xs = [letzt.laufleistung]
                    ys = [letzt.stand]
                    if y_at_warn is not None:
                        xs.append(kw); ys.append(y_at_warn)
                    xs.append(x_grenz_reached)
                    ys.append(y_grenz)
                else:
                    xs = [letzt.laufleistung, kg]
                    ys = [letzt.stand, y_grenz]
                ax.plot(xs, ys, color=col, linestyle="--", linewidth=1.3,
                        marker="x", markersize=5, zorder=2,
                        label=f"Prognose {SIDE_LABEL.get(side, side).lower()}")

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
