"""Gemeinsamer Aufbau fuer CSV und Oracle (structure, parsing, prognose_source)."""
import csv
from datetime import datetime, timedelta

import pytest

from tests.synth import make_rows, write_csv
from wheelset_dashboard.data.csv_source import load_prognose_csv, load_raw_csv
from wheelset_dashboard.data.models import Side
from wheelset_dashboard.data.oracle_source import parse_flotte_rows, parse_prognose_rows
from wheelset_dashboard.data.parsing import get_field, parse_datetime, parse_float, parse_int, stringify_row
from wheelset_dashboard.data.profile import load_profile_by_name
from wheelset_dashboard.data.prognose_source import dedupe_treppe
from wheelset_dashboard.data.models import PrognosePunkt
from wheelset_dashboard.data.structure import KIND_MESSPOSITION, KIND_RADSATZ, KIND_SAMMEL
from wheelset_dashboard.logic.aggregation import iter_messreihen


# ---------- Hilfen ----------

def fingerprint(flotte):
    """Struktur + Messpunkte der Flotte als vergleichbarer Text."""
    lines = []
    for en, e in sorted(flotte.einheiten.items()):
        for dk, dg in sorted(e.drehgestelle.items()):
            lines.append(f"DG {en}|{dk}|{dg.dg_id}|{dg.dg_bez}|{dg.synthetic}")
            for ak, a in sorted(dg.achsen.items()):
                lines.append(f" AX {ak}|{a.rs_id}|{a.kind}")
                for side, r in sorted(a.raeder.items(), key=lambda x: x[0].value):
                    for mg, mr in sorted(r.messreihen.items()):
                        pts = sorted((p.datum, p.stand, p.laufleistung, p.min_val, p.max_val) for p in mr.historie)
                        lines.append(f"  {side.value}|{mg}|{pts}|{mr.prognose}")
    for c in sorted(flotte.lager, key=lambda c: (c.kind, c.dg_bez, str(c.rs_id))):
        lines.append(f"LAGER {c.kind}|{c.dg_id}|{c.dg_bez}|{c.rs_id}|{c.ausbau}|{sorted(c.achsen)}")
        for ak, a in sorted(c.achsen.items()):
            lines.append(f" AX {ak}|{a.kind}|{sum(len(m.historie) for r in a.raeder.values() for m in r.messreihen.values())}")
    return "\n".join(lines)


def oracle_style_rows(name, csv_path):
    """Dieselben Zeilen wie in der CSV, aber als Datenbankwerte (datetime, float, None)."""
    profile = load_profile_by_name(name)
    with open(csv_path, encoding=profile.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=profile.delimiter)
        header = next(reader)
        kinds = {"datum": "dt", "einbau": "dt", "ausbau": "dt", "stand": "f", "min_val": "f", "max_val": "f",
                 "gelb_min": "f", "gelb_max": "f", "bereich_min": "f", "bereich_max": "f", "laufleistung": "f",
                 "topeinheit_id": "i", "dg_id": "i", "rs_id": "i", "aktuell": "i", "zaehlerart_id": "i"}
        out = []
        for row in reader:
            typed = []
            for col, val in zip(header, row):
                kind = kinds.get(profile.columns_raw[col])
                if val == "":
                    typed.append(None)
                elif kind == "dt":
                    typed.append(datetime.strptime(val, profile.date_format))
                elif kind == "f":
                    typed.append(float(val))
                elif kind == "i":
                    typed.append(int(val))
                else:
                    typed.append(val)
            out.append(tuple(typed))
    return header, out


# ---------- CSV und Oracle ergeben dieselbe Struktur ----------

def test_csv_und_oracle_weg_bauen_dieselbe_struktur(scenario, tmp_path):
    name, repo = scenario
    csv_path = repo.config.csv_raw_path
    profile = repo.profile
    aus_csv = load_raw_csv(csv_path, profile)
    header, rows = oracle_style_rows(name, csv_path)
    aus_oracle = parse_flotte_rows(rows, header, profile)
    assert fingerprint(aus_csv) == fingerprint(aus_oracle)
    assert len(list(iter_messreihen(aus_csv))) > 0


def test_synthetische_strukturen_sind_markiert(scenario):
    name, repo = scenario
    f = repo.load()
    kinds = {a.kind for e in f.einheiten.values() for dg in e.drehgestelle.values() for a in dg.achsen.values()}
    if name == "mob":
        assert kinds == {KIND_MESSPOSITION}
    else:
        assert kinds == {KIND_RADSATZ}
    assert not any(dg.synthetic for e in f.einheiten.values() for dg in e.drehgestelle.values())


def test_zeilen_ohne_zuordnung_landen_in_markierten_sammelobjekten():
    abellio = load_profile_by_name("abellio")
    header = list(abellio.columns_raw)
    base = {"TOPEINHEITID": 1, "TOPEINHEITBEZEICHNUNG": "E1", "AKTUELL": 1, "ZAEHLERARTID": 1,
            "ZARTBEZ": "Laufkreisdurchmesser Dlk", "STAND": 700.0, "DATUM": datetime(2020, 1, 1)}
    f = parse_flotte_rows([tuple(base.get(c) for c in header)], header, abellio)
    (dg,) = f.einheiten["E1"].drehgestelle.values()
    (achse,) = dg.achsen.values()
    assert dg.synthetic and achse.kind == KIND_SAMMEL and achse.synthetic


# ---------- Prognose-Anreicherung: CSV und Oracle ----------

def _prognose_csv(profile, path, einheit_id, dg_id, rs_id):
    """Treppe fuer das linke Rad der Szenario-Achse (mit einem Reprof-Paar am selben Datum)."""
    cols = list(profile.columns_prognose.items())
    d0 = datetime(2024, 1, 10, 8, 0)
    zeilen = [
        (d0, 800.0, 100000.0), (d0 + timedelta(days=100), 790.0, 120000.0),
        (d0 + timedelta(days=200), 780.0, 140000.0), (d0 + timedelta(days=200), 790.0, 140000.0),  # Reprof-Paar
        (d0 + timedelta(days=400), 770.0, 160000.0),
    ]
    with open(path, "w", encoding=profile.encoding, newline="") as fh:
        w = csv.writer(fh, delimiter=profile.delimiter)
        w.writerow([c for c, _ in cols])
        for datum, stand, km in zeilen:
            rec = {"topeinheit_id": einheit_id, "dg_id": dg_id, "rs_id": rs_id,
                   "zartbez": "Rad-Laufkreisdurchmesser-1", "stand": stand, "datum": datum, "laufleistung": km,
                   "letzteaendzeit": d0, "km_warnwert": 150000.0, "datum_warnwert": d0 + timedelta(days=300),
                   "km_grenzwert": 180000.0, "datum_grenzwert": d0 + timedelta(days=500), "aktuell": 1, "ausbau": None}
            w.writerow(["" if rec.get(i) is None else (rec[i].strftime(profile.date_format)
                        if isinstance(rec[i], datetime) else rec[i]) for _, i in cols])


def test_prognose_aus_csv_und_oracle_ist_gleich(tmp_path):
    vgf = load_profile_by_name("vgf")
    csv_path = write_csv("vgf", tmp_path / "roh.csv")
    prog_csv = tmp_path / "prognose.csv"
    _prognose_csv(vgf, prog_csv, 1, 10, 100)

    # Weg 1: CSV
    f1 = load_raw_csv(csv_path, vgf)
    assert load_prognose_csv(prog_csv, vgf, f1) == 1
    # Weg 2: Datenbankwerte
    f2 = load_raw_csv(csv_path, vgf)
    with open(prog_csv, encoding=vgf.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=vgf.delimiter)
        header = next(reader)
        typed = []
        for row in reader:
            rec = dict(zip(header, row))
            typed.append(tuple(
                None if rec[h] == "" else
                datetime.strptime(rec[h], vgf.date_format) if "DATUM" in h or h == "LETZTEAENDZEIT" else
                float(rec[h]) if h in ("STAND", "LAUFLEISTUNG", "KM_WARNWERT", "KM_GRENZWERT") else
                int(rec[h]) if h in ("TOPEINHEITID", "DGEINHEITID", "RSEINHEITID", "AKTUELL") else rec[h]
                for h in header))
    assert parse_prognose_rows(typed, header, vgf, f2) == 1

    def prog_of(f):
        a = f.einheiten["U1"].drehgestelle["Drehgestell 1"].achsen["Achse 1"]
        return a.raeder[Side.LEFT].messreihen["LKD"].prognose

    p1, p2 = prog_of(f1), prog_of(f2)
    assert p1 is not None and p1 == p2
    assert (p1.km_warnwert, p1.km_grenzwert) == (150000.0, 180000.0)
    # Reprof-Paar: am selben Datum erst der hoehere, dann der niedrigere Wert
    paar = [p.stand for p in p1.punkte if p.datum == datetime(2024, 1, 10, 8, 0) + timedelta(days=200)]
    assert paar == [790.0, 780.0]


def test_prognose_fuer_unbekannte_achse_wird_uebersprungen(tmp_path):
    vgf = load_profile_by_name("vgf")
    f = load_raw_csv(write_csv("vgf", tmp_path / "roh.csv"), vgf)
    _prognose_csv(vgf, tmp_path / "p.csv", 1, 10, 99999)         # Achse gibt es nicht
    assert load_prognose_csv(tmp_path / "p.csv", vgf, f) == 0


def test_dedupe_treppe_entfernt_duplikate_und_ordnet_reprof_paare():
    d = datetime(2024, 1, 1)
    p = lambda days, stand: PrognosePunkt(datum=d + timedelta(days=days), stand=stand, laufleistung=None)
    ergebnis = dedupe_treppe([p(5, 780), p(0, 800), p(5, 790), p(0, 800)])
    assert [(x.datum.day, x.stand) for x in ergebnis] == [(1, 800), (6, 790), (6, 780)]


# ---------- Text -> Wert ----------

@pytest.mark.parametrize("text, dec, erwartet", [
    ("1234.5", ".", 1234.5), ("1.234,5", ",", 1234.5), (" 7 ", ".", 7.0),
    ("", ".", None), (None, ".", None), ("abc", ".", None),
])
def test_parse_float(text, dec, erwartet):
    assert parse_float(text, dec) == erwartet


def test_parse_int_und_datum():
    assert parse_int("42") == 42 and parse_int("42.0") == 42 and parse_int("") is None and parse_int("x") is None
    fmt = "%d.%m.%Y"
    assert parse_datetime("05.03.2024", fmt) == datetime(2024, 3, 5)
    assert parse_datetime("2024-03-05 10:11:12", fmt) == datetime(2024, 3, 5, 10, 11, 12)   # Ausweichformate
    assert parse_datetime("2024-03-05", fmt) == datetime(2024, 3, 5)
    assert parse_datetime("kein datum", fmt) is None and parse_datetime(None, fmt) is None


def test_get_field_und_stringify_row():
    idx = {"a": 0, "b": 1, "c": 5}
    assert get_field(["x", "y"], idx, "a") == "x"
    assert get_field(["x", "y"], idx, "c") == ""            # Spalte jenseits der Zeile
    assert get_field(["x", "y"], idx, "fehlt") == ""
    assert stringify_row((None, datetime(2024, 1, 2, 3, 4, 5), 1.5, "t"), "%Y-%m-%d %H:%M:%S") == \
        ["", "2024-01-02 03:04:05", "1.5", "t"]


def test_bezeichnung_mit_leerzeichen_wird_auch_im_oracle_weg_erkannt():
    # Die CSV strippte die Bezeichnung schon immer; der Oracle-Weg frueher nicht.
    vgf = load_profile_by_name("vgf")
    header = list(vgf.columns_raw)
    zeile = dict(make_rows("vgf")[0])
    zeile["zartbez"] = zeile["zartbez"] + "  "
    row = tuple(zeile.get(vgf.columns_raw[c]) for c in header)
    f = parse_flotte_rows([row], header, vgf)
    assert len(list(iter_messreihen(f))) == 1
