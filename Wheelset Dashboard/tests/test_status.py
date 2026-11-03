"""Unit-Tests fuer logic.status."""
from datetime import datetime

from wheelset_dashboard.data.models import (
    Messpunkt, Messreihe, StatusAmpel,
)
from wheelset_dashboard.logic.status import (
    classify_messpunkt_ist, classify_messreihe,
)


NOW = datetime(2026, 11, 1)


def mp(stand, min_val=520, max_val=600, gelb_min=531, gelb_max=None):
    return Messpunkt(datum=NOW, stand=stand, min_val=min_val, max_val=max_val,
                    gelb_min=gelb_min, gelb_max=gelb_max)


def test_ist_green():
    assert classify_messpunkt_ist(mp(540)) == StatusAmpel.GREEN


def test_ist_yellow_untere_warnschwelle():
    assert classify_messpunkt_ist(mp(530)) == StatusAmpel.YELLOW


def test_ist_red_grenzwert():
    assert classify_messpunkt_ist(mp(520)) == StatusAmpel.RED
    assert classify_messpunkt_ist(mp(510)) == StatusAmpel.RED


def test_ist_gray_ohne_schwellen():
    assert classify_messpunkt_ist(
        Messpunkt(datum=NOW, stand=540)) == StatusAmpel.GRAY


def test_messreihe_nutzt_letzten_messwert():
    mr = Messreihe(messgroesse="LKD", historie=[mp(540)])
    assert classify_messreihe(mr) == StatusAmpel.GREEN
    mr2 = Messreihe(messgroesse="LKD", historie=[mp(518)])
    assert classify_messreihe(mr2) == StatusAmpel.RED
