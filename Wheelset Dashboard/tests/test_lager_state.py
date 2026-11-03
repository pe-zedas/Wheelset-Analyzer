from datetime import datetime

from wheelset_dashboard.data.models import ComponentState, LagerKomponente, Messpunkt, Messreihe
from wheelset_dashboard.logic.lager_state import LagerParams, classify_komponente


def _komp(ausbau, historie):
    lkd = Messreihe(messgroesse="LKD", historie=historie)
    return LagerKomponente(
        rs_id=1, rs_bez="X", letzte_einheit="Zug 1", ausbau=ausbau,
        messreihen={"LKD": lkd},
    )


def test_ready_wenn_sprung_nach_ausbau():
    ausbau = datetime(2026, 1, 1)
    hist = [
        Messpunkt(datetime(2025, 12, 1), stand=530.0),
        Messpunkt(datetime(2026, 2, 1), stand=540.0),  # Sprung +10 mm
    ]
    comp = _komp(ausbau, hist)
    assert classify_komponente(comp, LagerParams()) == ComponentState.STORED_READY


def test_to_overhaul_wenn_keine_messung_nach_ausbau():
    ausbau = datetime(2026, 1, 1)
    hist = [Messpunkt(datetime(2025, 12, 1), stand=530.0)]
    comp = _komp(ausbau, hist)
    assert classify_komponente(comp, LagerParams()) == ComponentState.STORED_TO_OVERHAUL


def test_to_overhaul_wenn_kein_sprung():
    ausbau = datetime(2026, 1, 1)
    hist = [
        Messpunkt(datetime(2025, 12, 1), stand=530.0),
        Messpunkt(datetime(2026, 2, 1), stand=530.3),
    ]
    comp = _komp(ausbau, hist)
    assert classify_komponente(comp, LagerParams()) == ComponentState.STORED_TO_OVERHAUL
