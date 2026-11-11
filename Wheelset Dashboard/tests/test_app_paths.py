"""Connect-String-Datei und -Zerlegung (dort stehen Zugangsdaten: Zuordnung je
Kunde darf nie vermischt werden); App-Root im Entwicklungsbetrieb und als PyInstaller-EXE."""
import importlib
import sys

import pytest

from wheelset_dashboard.config import app_paths
from wheelset_dashboard.config.app_paths import (
    build_connect_string, parse_connect_string, read_oracle_connect_string,
)


def test_app_root_liegt_im_entwicklungsbetrieb_ueber_dem_paket():
    """Normaler Lauf (python -m / Tests): App-Root ist der Projektordner, eine Ebene ueber
    wheelset_dashboard/ — dort legt die App ihr config/-Verzeichnis an (Connect-String, Log)."""
    assert app_paths.APP_ROOT == app_paths._PACKAGE_DIR.parent
    assert app_paths.CONFIG_DIR == app_paths.APP_ROOT / "config"


def test_app_root_liegt_bei_pyinstaller_neben_der_exe(monkeypatch, tmp_path):
    """Als PyInstaller-EXE zeigt __file__ auf das Temp-Extraktionsverzeichnis (_MEIPASS), das bei
    --onefile nach jedem Lauf verworfen wird. Die Betriebs-Konfiguration (Oracle-Connect-String,
    Logdatei) muss trotzdem dauerhaft neben der .exe liegen bleiben, sonst ist sie beim naechsten
    Start weg -> APP_ROOT muss dort aus sys.executable berechnet werden, nicht aus __file__."""
    exe = tmp_path / "Wheelset-Dashboard.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    importlib.reload(app_paths)
    try:
        assert app_paths.APP_ROOT == tmp_path
        assert app_paths.CONFIG_DIR == tmp_path / "config"
    finally:
        # Vor dem Zurueckladen explizit entfrosten: sys.frozen bliebe sonst bis zum Ende der
        # Testfunktion True (monkeypatch macht erst danach rueckgaengig) und der Reload wuerde
        # erneut den PyInstaller-Zweig nehmen.
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        importlib.reload(app_paths)


@pytest.fixture
def connect_file(tmp_path, monkeypatch):
    path = tmp_path / "oracle_connect_string.txt"
    monkeypatch.setattr(app_paths, "ORACLE_CONNECT_FILE", path)
    return path


def test_eintrag_je_kunde_wird_getrennt_gelesen(connect_file):
    connect_file.write_text(
        "# Kommentar\n\nvgf = flotte/pw1@host1/db1\nAbellio = ab/pw2@pcs15\nmob = mob/pw3@pcs16\n",
        encoding="utf-8")
    assert read_oracle_connect_string("vgf") == "flotte/pw1@host1/db1"
    assert read_oracle_connect_string("abellio") == "ab/pw2@pcs15"      # Gross-/Kleinschreibung egal
    assert read_oracle_connect_string("MOB") == "mob/pw3@pcs16"


def test_unbekanntes_profil_bekommt_nie_fremde_zugangsdaten(connect_file):
    connect_file.write_text("vgf = flotte/pw@host/db\n", encoding="utf-8")
    assert read_oracle_connect_string("abellio") is None
    assert read_oracle_connect_string("mob") is None


def test_alte_unbeschriftete_zeile_gilt_nur_fuer_vgf(connect_file):
    connect_file.write_text("flotte/pw@host/db\n", encoding="utf-8")
    assert read_oracle_connect_string("vgf") == "flotte/pw@host/db"
    assert read_oracle_connect_string(None) == "flotte/pw@host/db"      # Standardprofil
    assert read_oracle_connect_string("abellio") is None
    assert read_oracle_connect_string("mob") is None


def test_passwort_mit_gleichheitszeichen_wird_nicht_als_beschriftung_gelesen(connect_file):
    connect_file.write_text("flotte/pa=ss@host/db\n", encoding="utf-8")
    assert read_oracle_connect_string("vgf") == "flotte/pa=ss@host/db"


def test_erster_beschrifteter_eintrag_gewinnt(connect_file):
    connect_file.write_text("mob = a/1@x\nmob = b/2@y\n", encoding="utf-8")
    assert read_oracle_connect_string("mob") == "a/1@x"


def test_fehlende_datei_ergibt_none(connect_file):
    assert not connect_file.exists()
    assert read_oracle_connect_string("vgf") is None


@pytest.mark.parametrize("text, erwartet", [
    ("flotte/pw@10.0.0.1/asset_pdb1", ("flotte", "pw", "10.0.0.1/asset_pdb1")),
    ("u/p@ss/w@host:1521/svc", ("u", "p@ss/w", "host:1521/svc")),   # Sonderzeichen im Passwort
    ("nur_user", ("nur_user", "", "")),
    ("u/pw", ("u", "pw", "")),
    ("", ("", "", "")),
    (None, ("", "", "")),
])
def test_connect_string_zerlegen(text, erwartet):
    assert parse_connect_string(text) == erwartet


def test_zerlegen_und_zusammenbauen_ergeben_denselben_string():
    cs = "flotte/pw@10.0.0.1/asset_pdb1"
    assert build_connect_string(*parse_connect_string(cs)) == cs


@pytest.mark.parametrize("user, pw, dsn", [("", "p", "d"), ("u", "", "d"), ("u", "p", "")])
def test_unvollstaendige_angaben_ergeben_keinen_connect_string(user, pw, dsn):
    assert build_connect_string(user, pw, dsn) is None
