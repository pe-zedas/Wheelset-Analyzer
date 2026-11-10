"""Start des Prognose-Backends aus dem Dashboard: INI-Werte werden per Kommandozeile
ueberschrieben, die INI-Datei selbst bleibt unveraendert; Plot-Fenster sind aus."""
import importlib.util
import subprocess
import sys

import pytest

from wheelset_dashboard.logic import backend_runner
from wheelset_dashboard.logic.backend_runner import backend_overrides, run_backend_prognose

INI = "[pipeline]\nuse_database = true\nwrite_prog_data = false\n\n[plot]\nshow_plot = true\nplot_show_window = true\n"


@pytest.fixture
def backend_dir(tmp_path):
    (tmp_path / "Radsatz_Bahn_DB_new_Approach.py").write_text("# Platzhalter", encoding="utf-8")
    (tmp_path / "radsatz_config.ini").write_text(INI, encoding="utf-8")
    return tmp_path


@pytest.fixture
def captured(monkeypatch):
    """Ersetzt subprocess.run und merkt sich den Aufruf."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(backend_runner.subprocess, "run", fake_run)
    return seen


def _werte(cmd):
    """{'abschnitt.schluessel': 'wert'} aus den --set-Argumenten."""
    out = {}
    for i, a in enumerate(cmd):
        if a == "--set":
            k, _, v = cmd[i + 1].partition("=")
            out[k] = v
    return out


@pytest.mark.parametrize("use_db", [True, False])
def test_aufruf_ueberschreibt_datenquelle_und_schaltet_plots_aus(backend_dir, captured, use_db):
    result = run_backend_prognose(use_database=use_db, backend_dir=backend_dir)
    assert result.ok
    cmd = captured["cmd"]
    assert cmd[:3] == [sys.executable, "-u", "Radsatz_Bahn_DB_new_Approach.py"]
    assert _werte(cmd) == {
        "pipeline.use_database": "true" if use_db else "false",
        "pipeline.write_prog_data": "true",
        "plot.show_plot": "false",
        "plot.plot_show_window": "false",
    }
    assert captured["kwargs"]["cwd"] == str(backend_dir)


def test_ini_datei_wird_nicht_veraendert(backend_dir, captured):
    ini = backend_dir / "radsatz_config.ini"
    vorher = ini.read_bytes()
    run_backend_prognose(use_database=False, backend_dir=backend_dir)
    assert ini.read_bytes() == vorher
    assert not (backend_dir / "radsatz_config.ini.bak").exists()


def test_fehlende_ini_ist_ein_fehler(tmp_path, captured):
    (tmp_path / "Radsatz_Bahn_DB_new_Approach.py").write_text("", encoding="utf-8")
    result = run_backend_prognose(use_database=False, backend_dir=tmp_path)
    assert not result.ok and "INI-Datei fehlt" in result.message
    assert "cmd" not in captured                      # nichts gestartet


def test_traceback_in_stderr_gilt_als_fehler_auch_bei_exit_0(backend_dir, monkeypatch):
    monkeypatch.setattr(backend_runner.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(
        cmd, 0, stdout="", stderr="Traceback (most recent call last):\n  ..."))
    result = run_backend_prognose(use_database=False, backend_dir=backend_dir)
    assert not result.ok and "Traceback" in result.message


def test_zeitueberschreitung_wird_gemeldet(backend_dir, monkeypatch):
    def timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(backend_runner.subprocess, "run", timeout)
    result = run_backend_prognose(use_database=False, timeout_s=5, backend_dir=backend_dir)
    assert not result.ok and "Timeout" in result.message


# ---------- Backend: --set schlaegt die INI (nur wenn das Backend-Verzeichnis vorhanden ist) ----------

BACKEND = backend_runner._BACKEND_DIR_DEFAULT


@pytest.mark.skipif(not (BACKEND / "radsatz_settings.py").exists(), reason="Backend-Verzeichnis nicht vorhanden")
class TestBackendOverrides:
    @pytest.fixture(scope="class")
    def settings(self):
        spec = importlib.util.spec_from_file_location("radsatz_settings_backend", BACKEND / "radsatz_settings.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod            # Dataclasses suchen ihr Modul hier
        try:
            spec.loader.exec_module(mod)
            yield mod
        finally:
            sys.modules.pop(spec.name, None)

    def test_ueberschreibung_hat_vorrang_vor_der_ini(self, settings, tmp_path):
        (tmp_path / "radsatz_config.ini").write_text(INI, encoding="utf-8")
        ohne = settings.load_radsatz_config(str(tmp_path))
        assert (ohne.show_plot, ohne.plot_show_window, ohne.use_database, ohne.write_prog_data) == (True, True, True, False)
        mit = settings.load_radsatz_config(
            str(tmp_path), settings.overrides_from_argv(backend_overrides(use_database=False)))
        assert (mit.show_plot, mit.plot_show_window, mit.use_database, mit.write_prog_data) == (False, False, False, True)

    def test_nicht_genannte_werte_bleiben_aus_der_ini(self, settings, tmp_path):
        (tmp_path / "radsatz_config.ini").write_text(INI + "\n[prognose]\nn_km = 12345\n", encoding="utf-8")
        cfg = settings.load_radsatz_config(str(tmp_path), {"plot.show_plot": "false"})
        assert cfg.n_km == 12345 and cfg.use_database is True

    def test_fremde_argumente_werden_ignoriert(self, settings):
        assert settings.overrides_from_argv(["--irgendwas", "x", "--set", "plot.show_plot=false"]) == {
            "plot.show_plot": "false"}

    def test_ohne_ueberschreibung_nichts(self, settings):
        assert settings.overrides_from_argv([]) == {}

    @pytest.mark.parametrize("kaputt", ["kaputt", "plot.show_plot", "=false", "plot=false", ".x=1"])
    def test_ungueltige_ueberschreibung_bricht_ab(self, settings, kaputt):
        with pytest.raises(SystemExit):
            settings.overrides_from_argv(["--set", kaputt])
