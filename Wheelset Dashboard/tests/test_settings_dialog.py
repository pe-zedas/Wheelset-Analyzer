"""Einstellungsdialog: Aufbau, Konfiguration, und dass die wirkungslosen Prognose-Einstellungen
(Konfidenzband, Reprofilierungs-Erkennung, Standard-Werte, Treppen) nicht zurueckkehren."""
import pytest
from PySide6.QtWidgets import QLabel, QTreeWidgetItem

from wheelset_dashboard.ui.settings_dialog import SettingsDialog

pytestmark = pytest.mark.usefixtures("qapp")

CONFIG = {"profile": "vgf", "source": "csv", "csv_raw": "", "csv_prognose": "", "oracle_dsn": "",
          "oracle_user": "", "oracle_password": "", "refresh_min": "15"}


def _baum(dlg):
    """Alle Baumtexte (flach)."""
    out = []

    def walk(item: QTreeWidgetItem):
        out.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(dlg._tree.topLevelItemCount()):
        walk(dlg._tree.topLevelItem(i))
    return out


def test_baum_enthaelt_nur_noch_wirksame_abschnitte():
    dlg = SettingsDialog(dict(CONFIG))
    assert _baum(dlg) == ["Allgemein", "Datenquelle", "CSV", "Oracle", "Prognose", "Neuberechnung"]


def test_keine_wirkungslosen_prognose_einstellungen():
    dlg = SettingsDialog(dict(CONFIG))
    texte = " ".join(l.text() for l in dlg.findChildren(QLabel))
    for wort in ("KI-Band", "Konfidenz", "Auto-Erkennung", "Sprung-Schwelle", "Reprofilierungs-Sprung",
                 "Reprofilierungs-Intervall", "Treppen-Prognose"):
        assert wort not in texte
    for attr in ("p_show_ci", "p_ci_level", "p_auto", "p_min_jump", "p_delta", "p_interval", "p_show_steps"):
        assert not hasattr(dlg, attr)


def test_get_config_liefert_genau_die_felder_des_hauptfensters():
    assert set(SettingsDialog(dict(CONFIG)).get_config()) == {
        "profile", "source", "csv_raw", "csv_prognose", "oracle_dsn", "oracle_user", "oracle_password",
        "refresh_min"}


def test_alte_konfiguration_mit_entfernten_schluesseln_stoert_nicht():
    SettingsDialog({**CONFIG, "p_show_ci": True, "p_ci_level": 0.95, "p_auto": True, "p_delta": 5.0,
                    "p_interval": 1.0, "p_min_jump": 1.0, "p_show_steps": False})


def test_prognose_knoten_zeigt_die_neuberechnung():
    dlg = SettingsDialog(dict(CONFIG))
    assert dlg._pages["prognose_overview"] == dlg._pages["prognose_recalc"]
    dlg._tree.setCurrentItem(dlg._tree.topLevelItem(2))              # "Prognose"
    assert dlg._stack.currentIndex() == dlg._pages["prognose_recalc"]
    assert dlg._page_header.text() == "Prognose"


def test_neuberechnung_setzt_flag_und_nimmt_den_dialog_an():
    dlg = SettingsDialog(dict(CONFIG))
    dlg._on_recalc_clicked()
    assert dlg.recalc_requested and dlg.result() == dlg.DialogCode.Accepted
