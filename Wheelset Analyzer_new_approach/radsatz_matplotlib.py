"""
Matplotlib-Backend setzen, bevor matplotlib.pyplot importiert wird.

PyQt5 allein reicht nicht: ohne matplotlib.use('Qt5Agg') VOR dem ersten pyplot-Import
bleibt unter Windows meist TkAgg aktiv.

Qt: Schließt man das Plotfenster, beendet QApplication standardmäßig den ganzen
Python-Prozess (quitOnLastWindowClosed). ensure_interactive_plot_session() verhindert das.
"""

from __future__ import annotations

import logging
import os

_interactive_session_ready = False


def configure_matplotlib_backend(
    backend_preference: str = "",
    plot_show_window: bool = True,
) -> str:
    import matplotlib

    env = os.environ.get("MPLBACKEND", "").strip()
    if env:
        candidates = [env]
    elif backend_preference.strip():
        candidates = [b.strip() for b in backend_preference.split(",") if b.strip()]
    elif plot_show_window:
        candidates = ["Qt5Agg", "QtAgg", "TkAgg"]
    else:
        candidates = ["Agg"]

    last_err: Exception | None = None
    for name in candidates:
        try:
            matplotlib.use(name, force=True)
            backend = matplotlib.get_backend()
            logging.info("Matplotlib-Backend: %s (gewünscht: %s)", backend, name)
            return backend
        except Exception as exc:
            last_err = exc
            logging.debug("Backend %s nicht nutzbar: %s", name, exc)

    backend = matplotlib.get_backend()
    logging.warning(
        "Matplotlib-Backend-Fallback auf %s (letzter Fehler: %s)",
        backend,
        last_err,
    )
    return backend


def _get_or_create_qt_app():
    """QApplication holen oder anlegen (matplotlib legt sie oft erst beim ersten Figure an)."""
    app = None
    try:
        from matplotlib.backends.backend_qt import QtCore  # type: ignore

        app = QtCore.QCoreApplication.instance()
    except Exception:
        pass
    if app is not None:
        return app
    try:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            import sys

            app = QApplication(sys.argv)
        return app
    except Exception:
        return None


def ensure_interactive_plot_session() -> None:
    """
    Qt: Prozess nicht beenden, wenn das Plotfenster geschlossen wird.
    Erst wirksam, wenn eine QApplication existiert (nach erstem Figure oder hier angelegt).
    """
    global _interactive_session_ready
    if _interactive_session_ready:
        return

    import matplotlib

    backend = matplotlib.get_backend().lower()
    if "qt" not in backend:
        _interactive_session_ready = True
        return

    app = _get_or_create_qt_app()
    if app is None:
        return
    if hasattr(app, "setQuitOnLastWindowClosed"):
        app.setQuitOnLastWindowClosed(False)
        logging.info("Qt: quitOnLastWindowClosed=False (Folge-Plots möglich)")
    _interactive_session_ready = True


def block_until_figure_closed(fig, title: str = "") -> None:
    """Fenster anzeigen und warten, bis der Nutzer es schließt — ohne Prozessende (Qt)."""
    import matplotlib.pyplot as plt

    ensure_interactive_plot_session()

    try:
        manager = fig.canvas.manager
        if manager is not None and hasattr(manager, "set_window_title"):
            manager.set_window_title(str(title)[:120])
    except Exception:
        pass

    backend = plt.get_backend().lower()

    if "qt" in backend:
        plt.show(block=False)
        try:
            fig.canvas.draw()
            fig.canvas.flush_events()
            win = fig.canvas.manager.window
            if win is not None:
                win.show()
                win.raise_()
                win.activateWindow()
        except Exception:
            pass
        app = _get_or_create_qt_app()
        while plt.fignum_exists(fig.number):
            try:
                if app is not None:
                    app.processEvents()
            except Exception:
                break
            plt.pause(0.05)
        return

    if "tk" in backend:
        plt.show(block=False)
        try:
            fig.canvas.draw()
            root = fig.canvas.manager.window
            if root is not None and hasattr(root, "winfo_exists"):
                while root.winfo_exists():
                    root.update()
                    plt.pause(0.05)
                return
        except Exception:
            pass

    plt.show(block=True)
