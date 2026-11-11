"""Startpunkt fuer PyInstaller (und fuer ``python run_dashboard.py``).

``wheelset_dashboard/main.py`` darf nicht direkt als Skript gestartet werden:
Es benutzt relative Imports (``from .config... import ...``), die nur
funktionieren, wenn Python die Datei als Teil des Pakets ``wheelset_dashboard``
importiert — nicht, wenn sie als eigenstaendiges Skript laeuft (dann fehlt das
"known parent package", siehe ``ImportError: attempted relative import with no
known parent package``). Das passiert sowohl bei ``python wheelset_dashboard\\main.py``
als auch, wenn man PyInstaller direkt auf diese Datei ansetzt.

Dieses Skript liegt deshalb bewusst EINE Ebene hoeher, ausserhalb des Pakets,
und importiert ``wheelset_dashboard`` ganz normal als Paket. Mit PyInstaller
baut man darauf (nicht auf ``wheelset_dashboard/main.py``), siehe README.md.
"""
from wheelset_dashboard.main import main

if __name__ == "__main__":
    main()
