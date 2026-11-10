import os

# qtpy (von qtawesome benutzt) waehlt sonst PyQt5, sobald das installiert ist.
# Zwei Qt-Bindings in einem Prozess stuerzen ab (Access Violation).
os.environ.setdefault("QT_API", "pyside6")
