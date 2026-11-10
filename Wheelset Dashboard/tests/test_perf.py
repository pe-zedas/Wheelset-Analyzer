"""Zeitmesser fuer die DEBUG-Logs."""
import logging
import time

import pytest

from wheelset_dashboard.perf import Timer, timed


def test_timed_misst_und_haelt_die_dauer_nach_dem_block():
    with timed("x") as t:
        time.sleep(0.02)
    assert t.seconds >= 0.02
    fertig = t.seconds
    time.sleep(0.02)
    assert t.seconds == fertig                    # nach dem Block eingefroren


def test_timed_loggt_label_und_sekunden(caplog):
    log = logging.getLogger("test.perf")
    with caplog.at_level(logging.DEBUG, logger="test.perf"):
        with timed("Laden", log):
            pass
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.DEBUG
    assert caplog.records[0].getMessage().startswith("Laden=") and caplog.records[0].getMessage().endswith("s")


def test_timed_ohne_logger_loggt_nichts(caplog):
    with caplog.at_level(logging.DEBUG):
        with timed("still"):
            pass
    assert not [r for r in caplog.records if "still=" in r.getMessage()]


def test_timed_loggt_auch_bei_ausnahme(caplog):
    log = logging.getLogger("test.perf2")
    with caplog.at_level(logging.DEBUG, logger="test.perf2"):
        with pytest.raises(ValueError):
            with timed("kaputt", log):
                raise ValueError("x")
    assert any(r.getMessage().startswith("kaputt=") for r in caplog.records)


def test_timer_laeuft_waehrend_des_blocks_und_stop_ist_idempotent():
    t = Timer()
    time.sleep(0.01)
    zwischen = t.seconds
    assert zwischen > 0
    erste = t.stop()
    assert t.stop() == erste and t.seconds == erste
