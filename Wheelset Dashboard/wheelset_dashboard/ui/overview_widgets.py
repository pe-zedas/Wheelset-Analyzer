"""Donut-Chart und Gantt-Zeitachse fuer die Uebersichts-Ansichten (L1-L3)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QScrollArea, QSlider, QToolTip, QVBoxLayout, QWidget,
)

from ..data.models import StatusAmpel
from .widgets import AMPEL_COLORS, AMPEL_LABEL


class DonutCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None):
        fig = Figure(figsize=(3.5, 3.5), facecolor="#FFFFFF")
        super().__init__(fig)
        self._ax = fig.add_subplot(111)
        self.setMinimumSize(180, 140)
        self.setMaximumHeight(220)
        self.setParent(parent)

    def set_counts(self, counts: Dict[StatusAmpel, int], center_label: str = "Räder"):
        order = [StatusAmpel.GREEN, StatusAmpel.YELLOW, StatusAmpel.RED, StatusAmpel.GRAY]
        values = [counts.get(s, 0) for s in order]
        total = sum(values)
        colors = [AMPEL_COLORS[s] for s in order]
        labels = [AMPEL_LABEL[s] for s in order]

        ax = self._ax
        ax.clear()
        ax.set_aspect("equal")
        if total == 0:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "keine Daten", ha="center", va="center",
                    transform=ax.transAxes, color="#8A8F99", fontsize=11)
            self.draw_idle()
            return

        wedges, _ = ax.pie(
            values, colors=colors, startangle=90, counterclock=False,
            wedgeprops=dict(width=0.32, edgecolor="#FFFFFF", linewidth=1.5),
        )
        ax.text(0, 0.08, str(total), ha="center", va="center",
                fontsize=18, fontweight="500", color="#1A1C20")
        # Center-Label ggf. auf zwei Zeilen umbrechen, wenn > 12 Zeichen
        label_disp = center_label
        if len(center_label) > 12 and " " in center_label:
            # an mittlerstem Leerzeichen trennen
            mid = len(center_label) // 2
            left_sp = center_label.rfind(" ", 0, mid)
            right_sp = center_label.find(" ", mid)
            if left_sp == -1: cut = right_sp
            elif right_sp == -1: cut = left_sp
            else: cut = left_sp if (mid - left_sp) <= (right_sp - mid) else right_sp
            if cut > 0:
                label_disp = center_label[:cut] + "\n" + center_label[cut + 1:]
        elif len(center_label) > 14:
            mid = len(center_label) // 2
            label_disp = center_label[:mid] + "\n" + center_label[mid:]
        ax.text(0, -0.18, label_disp, ha="center", va="center",
                fontsize=9, color="#8A8F99", linespacing=1.1)
        # kleine Legende rechts
        legend_labels = [f"{lab}  {v}" for lab, v in zip(labels, values)]
        ax.legend(wedges, legend_labels, loc="center left",
                  bbox_to_anchor=(1.05, 0.5), fontsize=9, frameon=False)
        ax.set_axis_off()
        self.figure.subplots_adjust(left=0.02, right=0.60, top=0.95, bottom=0.05)
        self.draw_idle()


def _normalize_entries(entries):
    """Bringt die erlaubten Eintragsformate (siehe ``set_entries``) auf
    ``(label, reprofs, warns, grenze, note)`` mit Terminlisten."""
    norm = []
    for e in entries:
        note: Optional[str] = None
        if len(e) == 3:
            label, warns_raw, grenze_raw = e
            reprofs_raw = []
        elif len(e) == 4:
            label, reprofs_raw, warns_raw, grenze_raw = e
        else:
            label, reprofs_raw, warns_raw, grenze_raw, note = e
        norm.append((label, _as_date_list(reprofs_raw), _as_date_list(warns_raw),
                     _as_date_list(grenze_raw), note))
    return norm


class GanttCanvas(FigureCanvasQTAgg):
    """Horizontaler Gantt mit einer Zeile pro Entitaet und Markern fuer
    Reprofilierung/Warn/Grenz. Jeder Marker merkt sich seine Achse fuer
    den Hover-Tooltip; das letzte Grenz-Datum liefert die Scroll-Reichweite.
    """
    # Feste Pixel-Margins der Plot-Area innerhalb der Figure. Werden in
    # ``_apply_margins`` relativ zur aktuellen Figurehoehe umgerechnet,
    # damit der obere/untere Rand unabhaengig von der Zeilenzahl immer
    # gleich hoch wirkt — sonst skaliert ``tight_layout`` die Raender
    # proportional und bei vielen Zeilen entsteht viel Leerflaeche oben.
    _MARGIN_TOP_PX = 14
    _MARGIN_BOTTOM_PX = 40   # Platz fuer Monatslabel + Jahr-Doppelzeile
    _MARGIN_LEFT_FRAC = 0.14
    _MARGIN_RIGHT_FRAC = 0.98

    # Fest gepinnte Logical-DPI fuer die Umrechnung Pixel ↔ Inches.
    # matplotlib wuerde sonst beim Verschieben auf einen Monitor mit
    # anderem Skalierungsfaktor automatisch die figure.dpi anheben
    # (z.B. 100 → 125 bei 125%-DPI-Scaling), und unsere Resize-Formel
    # ``w / dpi`` wuerde dadurch zu kleinere Inches-Werten rechnen →
    # Backbuffer schrumpft, waehrend das Widget seine logischen Pixel
    # behaelt → Fehldarstellung. Device-Pixel-Ratio handled matplotlib
    # intern korrekt, solange die figure-DPI konstant bleibt.
    _LOGICAL_DPI = 100.0

    def __init__(self, parent=None):
        # tight_layout: False — wir setzen die Margins selbst (siehe
        # ``_apply_margins``). tight_layout wuerde sonst den oberen Rand
        # mit der Figurehoehe mitwachsen lassen.
        fig = Figure(figsize=(6.5, 3.5), facecolor="#FFFFFF",
                     tight_layout=False, dpi=self._LOGICAL_DPI)
        super().__init__(fig)
        self._ax = fig.add_subplot(111)
        self.setMinimumHeight(140)
        self.setParent(parent)
        self.setMouseTracking(True)
        self._markers: List[Tuple[datetime, int, float, float, str]] = []
        self.mpl_connect("motion_notify_event", self._on_mouse_move)

    def _resize_for_rows(self, n_rows: int):
        """Hoehe an die Zeilenzahl anpassen: ca. 22 px pro Zeile + Rand.
        Keine obere Deckelung — der Scrollbalken im GanttPane uebernimmt
        die sichtbare Begrenzung.

        Die BREITE kommt aus dem umgebenden QScrollArea-Viewport (nicht
        aus ``self.width()``), damit nach einem View-Wechsel die Canvas
        sich an die aktuelle Fensterbreite anpasst — sonst zeichnet
        matplotlib in der alten (kleineren) Breite und rechts bleibt ein
        leerer Bereich.
        """
        n = max(1, n_rows)
        px = max(140, 60 + n * 22)
        self.setMinimumHeight(px)
        self.setMaximumHeight(px)
        # Verfuegbare Breite aus dem Scrollviewport des Panes ermitteln.
        pane = getattr(self, "_pane", None)
        scroll = getattr(pane, "_scroll", None) if pane is not None else None
        if scroll is not None:
            vp_w = scroll.viewport().width()
            # Bei aktivem vertikalen Scrollbar die Scrollbar-Breite abziehen
            sb = scroll.verticalScrollBar()
            if sb is not None and sb.isVisible():
                vp_w -= sb.sizeHint().width()
            w = max(vp_w, max(self.width(), 100))
        else:
            w = max(self.width(), 100)
        self.resize(w, px)
        # DPI festhalten (siehe _LOGICAL_DPI-Kommentar oben) und nur dann
        # ueberschreiben, falls matplotlib sie veraendert hat.
        if abs(self.figure.dpi - self._LOGICAL_DPI) > 0.1:
            self.figure.set_dpi(self._LOGICAL_DPI)
        dpi = self._LOGICAL_DPI
        dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else 1.0
        self.figure.set_size_inches(w / dpi, px / dpi, forward=False)
        self._apply_margins()
        try:
            import logging as _l
            scr = self.screen() if hasattr(self, "screen") else None
            scr_name = scr.name() if scr is not None else "?"
            vp = scroll.viewport().width() if scroll is not None else -1
            fig_in = self.figure.get_size_inches()
            _l.getLogger(__name__).debug(
                "GanttCanvas._resize_for_rows: n_rows=%d vp_w=%d self.width=%d "
                "-> target_px=(%d,%d) dpi=%.1f dpr=%.2f fig_inches=(%.3f,%.3f) screen=%s",
                n_rows, vp, self.width(), w, px, dpi, dpr,
                float(fig_in[0]), float(fig_in[1]), scr_name,
            )
        except Exception:
            pass

    # resizeEvent wird NICHT ueberschrieben: matplotlib's eigener
    # Standard-resizeEvent in FigureCanvasQTAgg handhabt Device-Pixel-
    # Ratio korrekt (skaliert die Figure intern mit dem dpr des
    # aktuellen Bildschirms). Ein manuelles set_size_inches(w/dpi, h/dpi)
    # interferiert mit dieser Automatik und verursacht einen Dauer-Flip
    # zwischen ×dpr und ÷dpr (siehe Analyse der Debug-Logs vom 2026-11-05
    # bei Wechsel zwischen PL2492H (dpr=1.0) und DISPLAY1 (dpr=1.25)).

    def _apply_margins(self):
        """Setzt die Plot-Area-Raender fest in Pixel (umgerechnet in
        Figur-Fraktion). Damit bleibt der Abstand von Figurkante zur
        obersten Zeile unabhaengig von der Zeilenzahl konstant."""
        h_px = max(self.figure.get_size_inches()[1] * (self.figure.dpi or 100), 1)
        top = max(0.5, 1.0 - self._MARGIN_TOP_PX / h_px)
        bot = min(0.5, self._MARGIN_BOTTOM_PX / h_px)
        self.figure.subplots_adjust(
            top=top, bottom=bot,
            left=self._MARGIN_LEFT_FRAC, right=self._MARGIN_RIGHT_FRAC,
        )

    def set_entries(self, entries, horizon_months: int = 12,
                    base_date: Optional[datetime] = None):
        """Zeichnet pro Entitaet eine Zeile mit Markern fuer anstehende Termine.

        Akzeptierte Eintrags-Formate (rueckwaertskompatibel):

        1. ``(label, warn_date, grenz_date)``.
        2. ``(label, reprof_dates, warn_date, grenz_date)``.
        3. ``(label, reprof_tuples, warns, grenze)`` — Listen von Tuples
           ``(datum, achsen_label)``, Einzel-Tuples oder None.
        4. ``(label, reprof_tuples, warns, grenze, note)`` — zusaetzlich
           ein ``note``-Text, der in der Zeile als Platzhalter erscheint,
           wenn fuer die Gruppe kein Marker erzeugt werden konnte.

        Jede Zeile des Rueckgabedatensatzes erzeugt eine Gantt-Zeile;
        Eintraege ohne Marker und ohne Note werden ebenfalls geschrieben,
        damit die Reihenfolge der Tabelle oben erhalten bleibt.
        """
        self._last_entries = entries
        self._last_horizon_months = horizon_months
        self._latest_grenz_date = _extract_latest_grenz(entries)
        ax = self._ax
        ax.clear()
        self._markers.clear()

        # KEINE Umsortierung — die Reihenfolge entspricht 1:1 der vom Aufrufer
        # uebergebenen ``entries``-Liste. Damit folgt die Kachel der Sortierung
        # der darueberliegenden Tabelle.
        norm = _normalize_entries(entries)
        self._resize_for_rows(len(norm))

        if not norm:
            ax.text(0.5, 0.5, "keine Einträge",
                    ha="center", va="center", transform=ax.transAxes,
                    color="#8A8F99", fontsize=11)
            ax.set_axis_off()
            self.draw_idle()
            return

        # "heute" fuer die Darstellung = Basis-Zeitpunkt. Default: jetzt;
        # wird aber vom Aufrufer typischerweise auf den jueng­sten Messwert
        # der Flotte gesetzt, denn die Prognose rechnet ab dort und das ist
        # fachlich der Nullpunkt der Faelligkeiten.
        now = base_date or datetime.now()
        horizon_end = now + timedelta(days=horizon_months * 30)

        labels = [x[0] for x in norm]
        ax.set_yticks(list(range(len(norm))))
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(now, horizon_end)
        # Oberen/unteren y-Rand fest an die Zeilenzahl koppeln, damit
        # matplotlib keinen Auto-Padding einfuegt und die erste Zeile
        # immer direkt unter dem oberen Rand liegt.
        ax.set_ylim(len(norm) - 0.5, -0.8)

        self._draw_rows(norm, now, horizon_end)
        ax.axvline(now, color="#378ADD", linestyle="--", linewidth=1, alpha=0.7)
        ax.text(now, -0.6, " heute", color="#378ADD", fontsize=8, va="bottom")
        self._format_time_axis()
        self.draw_idle()
        # Slider-Range an das spaeteste Grenzdatum anpassen
        pane = getattr(self, "_pane", None)
        if pane is not None:
            pane.refresh_slider()

    # Marker je Terminart: (Titel im Tooltip, scatter-Argumente).
    # Reprofilierung → hellblau (geplante Werkstattaktion),
    # Warn (GELB_MIN) → orange (naechste Unterschreitung der Warngrenze),
    # Grenz (MIN) → rot (naechste Unterschreitung des Grenzwerts).
    _MARKER_STYLES = (
        ("Reprofilierung", dict(marker="s", color="#8FC7F0", s=60, zorder=3)),
        ("Warnschwelle unterschritten",
         dict(marker="o", color=AMPEL_COLORS[StatusAmpel.YELLOW], s=70, zorder=4)),
        ("Grenzwert unterschritten",
         dict(marker="D", color=AMPEL_COLORS[StatusAmpel.RED], s=70, zorder=5)),
    )

    def _draw_rows(self, norm, now, horizon_end):
        """Eine Gantt-Zeile je Eintrag: Hintergrundband, Marker, Platzhaltertext."""
        ax = self._ax
        # Marker-Treffer-Toleranz: 1 % des sichtbaren Zeitbereichs in Tagen
        span_days = max((horizon_end - now).days, 1)
        hit_radius_days = max(span_days * 0.01, 1.5)

        for i, (label, reprofs, warns, grenze, note) in enumerate(norm):
            ax.hlines(i, now, horizon_end, color="#F0F2F6", linewidth=10, zorder=1)
            for (title, style), termine in zip(self._MARKER_STYLES, (reprofs, warns, grenze)):
                for d, achs in termine:
                    if d is None or not (now <= d <= horizon_end):
                        continue
                    ax.scatter([d], [i], edgecolor="#FFFFFF", linewidths=1, **style)
                    tip = f"{title}\n{d.strftime('%Y-%m-%d')}" + (f"\n{achs}" if achs else "")
                    self._markers.append((d, i, hit_radius_days, 0.35, tip))
            # Platzhaltertext fuer Zeilen ohne Prognose
            if note:
                ax.text(now, i, " " + note, color="#8A8F99", fontsize=8,
                        style="italic", va="center", ha="left", zorder=6)

    def _format_time_axis(self):
        """X-Achse: Monatsraster. Zweizeiliges Label: oben der Monat, bei
        Januar und am linken Rand zusaetzlich das Jahr darunter — so ist auf
        einen Blick klar, in welchem Kalenderjahr der Marker liegt."""
        ax = self._ax
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))

        def month_year(x, pos):
            d = mdates.num2date(x)
            # pos == 0 ist das linke-Rand-Tick; Januar bringt den Jahreswechsel ins Bild.
            if pos == 0 or d.month == 1:
                return f"{d.strftime('%b')}\n{d.year}"
            return d.strftime("%b")

        ax.xaxis.set_major_formatter(mticker.FuncFormatter(month_year))
        ax.tick_params(colors="#6B6F78", labelsize=9)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color("#D4D6DC")
        ax.grid(False)

    def _on_mouse_move(self, event):
        """Zeigt QToolTip, wenn der Cursor nahe an einem Marker ist."""
        if event.inaxes is not self._ax or not self._markers:
            QToolTip.hideText()
            return
        if event.xdata is None or event.ydata is None:
            return
        # event.xdata ist in matplotlib-Date-Zahlen (Tage seit epoch)
        best = None
        best_dist = None
        for d, row, rx_days, ry, tip in self._markers:
            dx = abs(event.xdata - mdates.date2num(d))   # Tage
            dy = abs(event.ydata - row)
            if dx <= rx_days and dy <= ry:
                dist = dx / rx_days + dy / ry
                if best is None or dist < best_dist:
                    best = tip
                    best_dist = dist
        if best:
            QToolTip.showText(QCursor.pos(), best, self)
        else:
            QToolTip.hideText()


class DonutPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = DonutCanvas(self)
        lay.addWidget(self.canvas)


def _as_date_tuple(x):
    """Normalisiert einen Eintrag auf ``(datum, achse_label|None)`` oder None."""
    if x is None:
        return None
    if isinstance(x, tuple):
        if len(x) == 2:
            return (x[0], x[1])
        if len(x) == 1:
            return (x[0], None)
    return (x, None)


def _as_date_list(x):
    """Normalisiert auf eine Liste von ``(datum, achse_label|None)``.

    Akzeptiert: None, einzelnes datum, einzelnes Tuple, Liste gemischt.
    """
    if x is None:
        return []
    # Einzelnes Tuple (datum, label) vs. Liste von Tuples auseinanderhalten:
    # ein 2-Tuple, dessen erstes Element ein datetime ist, zaehlt als Tuple.
    if isinstance(x, tuple) and len(x) in (1, 2):
        if len(x) == 2 and isinstance(x[0], datetime):
            t = _as_date_tuple(x)
            return [t] if t and t[0] is not None else []
    if isinstance(x, datetime):
        return [(x, None)]
    out = []
    for item in x:
        t = _as_date_tuple(item)
        if t and t[0] is not None:
            out.append(t)
    return out


def _extract_latest_grenz(entries) -> Optional[datetime]:
    """Spaetestes Grenz-Datum ueber alle Entries — fuer Scroll-Reichweite."""
    latest = None
    for e in entries:
        if len(e) == 3:
            _, _, grenz = e
        elif len(e) == 4:
            _, _, _, grenz = e
        else:
            _, _, _, grenz, _note = e
        for d, _achs in _as_date_list(grenz):
            if latest is None or d > latest:
                latest = d
    return latest


class GanttPane(QWidget):
    """GanttCanvas in einem vertikalen Scrollbereich fester Hoehe, plus
    horizontaler Zeitachsen-Slider darunter.

    - Die Kachel bleibt kompakt (max. 220 px sichtbar wie frueher).
    - Bei vielen Zeilen waechst die Canvas nach unten; der vertikale
      Scrollbalken des QScrollArea bringt die unteren Zeilen in Sicht.
    - Der horizontale Slider unten schiebt die Zeitachse weiter in die
      Zukunft.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self.canvas = GanttCanvas(self)
        self._scroll = QScrollArea(self)
        self._scroll.setWidget(self.canvas)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        # Sichtbare Hoehe des Scrollbereichs (entspricht der frueheren
        # Kachelhoehe).
        self._scroll.setMinimumHeight(180)
        self._scroll.setMaximumHeight(220)
        lay.addWidget(self._scroll)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.setSingleStep(7)   # 1 Woche
        self._slider.setPageStep(30)    # 1 Monat
        self._slider.setTickPosition(QSlider.NoTicks)
        self._slider.valueChanged.connect(self._on_scroll)
        self._slider.hide()             # erst zeigen wenn ueberhaupt scrollbar
        lay.addWidget(self._slider)
        # Nach jedem set_entries: Slider-Range nachstellen
        self.canvas._pane = self

    def _on_scroll(self, days: int):
        if not getattr(self.canvas, "_last_entries", None):
            return
        from datetime import datetime, timedelta
        new_base = datetime.now() + timedelta(days=days)
        self.canvas.set_entries(
            self.canvas._last_entries,
            horizon_months=self.canvas._last_horizon_months,
            base_date=new_base,
        )

    def refresh_slider(self):
        """Nach set_entries von aussen aufrufen, damit der Slider seine
        Reichweite an das spaeteste Grenzdatum anpasst."""
        latest = getattr(self.canvas, "_latest_grenz_date", None)
        if latest is None:
            self._slider.hide()
            return
        from datetime import datetime
        max_days = max(0, (latest - datetime.now()).days)
        if max_days <= 30:
            self._slider.hide()
        else:
            self._slider.setRange(0, max_days)
            self._slider.show()
