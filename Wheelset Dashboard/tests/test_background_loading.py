"""Laden und Backend-Lauf im Hintergrund: Die Oberflaeche darf nicht einfrieren,
Fehler muessen gemeldet werden, Mehrfachausloeser werden zusammengefasst."""
import threading

import pytest
from PySide6.QtWidgets import QMessageBox

from tests.synth import write_csv
from wheelset_dashboard.data.repository import Repository, RepositoryConfig
from wheelset_dashboard.logic import backend_runner
from wheelset_dashboard.ui.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")
WAIT = 20.0


def _repo(name, tmp_path):
    csv_path = write_csv(name, tmp_path / f"{name}.csv")
    return Repository(RepositoryConfig(profile_name=name, source="csv", csv_raw_path=csv_path))


class Gate:
    """Haelt ``repo.load()`` an, bis es freigegeben wird, und zaehlt die Aufrufe."""

    def __init__(self, repo, open_=False, error=None):
        self.event = threading.Event()
        if open_:
            self.event.set()
        self.error = error
        self.calls = 0
        self.threads = []
        real = repo.load

        def load():
            self.calls += 1
            self.threads.append(threading.current_thread())
            assert self.event.wait(WAIT), "Gate wurde nicht freigegeben"
            if self.error is not None:
                raise self.error
            return real()

        repo.load = load


@pytest.fixture
def vgf_repo(tmp_path):
    return _repo("vgf", tmp_path)


@pytest.fixture
def mob_repo(tmp_path):
    return _repo("mob", tmp_path)


@pytest.fixture
def boxes(monkeypatch):
    """Faengt Meldungsfenster ab (kein modaler Dialog im Test)."""
    seen = {"critical": [], "information": [], "question": []}
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(
        lambda parent, title, text, *a, **k: seen["critical"].append(text)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda parent, title, text, *a, **k: seen["information"].append(text)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda parent, title, text, *a, **k: (seen["question"].append(text), QMessageBox.Yes)[1]))
    return seen


def test_fenster_erscheint_sofort_waehrend_im_hintergrund_geladen_wird(vgf_repo, qapp):
    gate = Gate(vgf_repo)                      # load() blockiert
    win = MainWindow(vgf_repo)                 # kehrt trotzdem sofort zurueck
    assert win._flotte is None and win.is_busy()
    assert not win._busy_bar.isHidden()
    assert not win._reload_btn.isEnabled()
    assert win._status_lbl.text().startswith("Lade")
    for _ in range(20):                        # Ereignisschleife laeuft weiter
        qapp.processEvents()
    assert win.is_busy()

    gate.event.set()
    assert win.wait_for_load(WAIT)
    assert win._flotte is not None and not win.is_busy()
    assert win._busy_bar.isHidden() and win._reload_btn.isEnabled()
    assert win._status_lbl.text().startswith("Stand")
    assert gate.threads[0] is not threading.main_thread()


def test_ergebnis_wird_im_gui_thread_angewendet(vgf_repo, monkeypatch):
    Gate(vgf_repo, open_=True)
    seen = []
    orig = MainWindow.navigate

    def navigate(self, path):
        seen.append(threading.current_thread())
        return orig(self, path)

    monkeypatch.setattr(MainWindow, "navigate", navigate)
    win = MainWindow(vgf_repo)
    assert win.wait_for_load(WAIT)
    assert len(seen) >= 2                      # Start + nach dem Laden
    assert all(t is threading.main_thread() for t in seen)


def test_ladefehler_wird_gemeldet_und_blockiert_nicht(vgf_repo, boxes):
    gate = Gate(vgf_repo, open_=True, error=RuntimeError("DB nicht erreichbar"))
    win = MainWindow(vgf_repo)
    assert win.wait_for_load(WAIT)
    assert len(boxes["critical"]) == 1 and "DB nicht erreichbar" in boxes["critical"][0]
    assert win._flotte is None and not win.is_busy()
    assert win._reload_btn.isEnabled() and win._busy_bar.isHidden()
    assert win._status_lbl.text() == "Laden fehlgeschlagen"

    gate.error = None                          # danach funktioniert Neu laden wieder
    win.reload_data()
    assert win.wait_for_load(WAIT)
    assert win._flotte is not None


def test_mehrfaches_neu_laden_wird_zusammengefasst(vgf_repo):
    gate = Gate(vgf_repo)
    win = MainWindow(vgf_repo)
    for _ in range(3):
        win.reload_data()                      # waehrend des Ladens: nur vormerken
    gate.event.set()
    assert win.wait_for_load(WAIT)
    assert gate.calls == 2                     # der laufende + genau ein nachgeholter


def test_auto_refresh_stapelt_keine_laeufe(vgf_repo):
    gate = Gate(vgf_repo)
    win = MainWindow(vgf_repo)
    win._auto_reload()
    win._auto_reload()
    gate.event.set()
    assert win.wait_for_load(WAIT)
    assert gate.calls == 1


def test_ergebnis_fuer_altes_profil_wird_verworfen(vgf_repo, mob_repo):
    alt = Gate(vgf_repo)                       # laeuft noch, wenn das Profil wechselt
    neu = Gate(mob_repo, open_=True)
    win = MainWindow(vgf_repo)
    win._repo = mob_repo                       # wie nach dem Einstellungsdialog
    win.reload_data()                          # vorgemerkt
    alt.event.set()
    assert win.wait_for_load(WAIT)
    assert win._flotte_repo is mob_repo
    assert win._flotte_repo.profile.name == "mob"
    assert "MOB" in win._schema_lbl.text()
    assert (alt.calls, neu.calls) == (1, 1)


def _fake_backend(monkeypatch, release=None, ok=True):
    calls = []

    def fake(use_database, **kw):
        calls.append(use_database)
        if release is not None:
            assert release.wait(WAIT)
        return backend_runner.BackendResult(
            ok, 0 if ok else 1, "", "" if ok else "boom", None,
            "Prognose-Lauf erfolgreich." if ok else "Backend-Lauf gab Exit 1 zurueck")

    monkeypatch.setattr(backend_runner, "run_backend_prognose", fake)
    return calls


def test_backend_lauf_blockiert_die_oberflaeche_nicht(vgf_repo, qapp, boxes, monkeypatch):
    gate = Gate(vgf_repo, open_=True)
    win = MainWindow(vgf_repo)
    assert win.wait_for_load(WAIT)
    release = threading.Event()
    calls = _fake_backend(monkeypatch, release)

    win.recalc_prognose()
    assert win.is_busy() and win._status_lbl.text().startswith("Prognose wird neu")
    win.reload_data()                          # waehrend des Backend-Laufs: vormerken
    for _ in range(20):
        qapp.processEvents()
    assert gate.calls == 1                     # noch kein zweites Laden

    release.set()
    assert win.wait_for_load(WAIT)
    assert calls == [False]                    # CSV-Quelle -> use_database=False
    assert gate.calls == 2                     # danach genau ein Neu-Laden
    assert boxes["information"] and "erfolgreich" in boxes["information"][0]


def test_backend_fehler_wird_gemeldet(vgf_repo, boxes, monkeypatch):
    Gate(vgf_repo, open_=True)
    win = MainWindow(vgf_repo)
    assert win.wait_for_load(WAIT)
    _fake_backend(monkeypatch, ok=False)
    win.recalc_prognose()
    assert win.wait_for_load(WAIT)
    assert len(boxes["critical"]) == 1 and "boom" in boxes["critical"][0]
    assert not win.is_busy() and win._reload_btn.isEnabled()


def test_neuberechnung_nur_fuer_vgf(mob_repo, boxes, monkeypatch):
    Gate(mob_repo, open_=True)
    win = MainWindow(mob_repo)
    assert win.wait_for_load(WAIT)
    calls = _fake_backend(monkeypatch)
    win.recalc_prognose()
    assert calls == [] and boxes["question"] == []
    assert boxes["information"] and "nur für das Profil" in boxes["information"][0]
    assert not win.is_busy()
