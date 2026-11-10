"""Repository: Quellenwahl (CSV/Oracle) und Fehlerfaelle."""
import pytest

from tests.synth import write_csv
from wheelset_dashboard.data import oracle_source
from wheelset_dashboard.data.models import Flotte
from wheelset_dashboard.data.repository import Repository, RepositoryConfig


def test_csv_wird_geladen_und_profil_aufgeloest(tmp_path):
    csv_path = write_csv("vgf", tmp_path / "vgf.csv")
    repo = Repository(RepositoryConfig(profile_name="vgf", source="csv", csv_raw_path=csv_path))
    assert repo.profile.name == "vgf"
    assert list(repo.load().einheiten) == ["U1"]


def test_flotte_property_laedt_einmal_und_haelt_das_ergebnis(tmp_path):
    csv_path = write_csv("mob", tmp_path / "mob.csv")
    repo = Repository(RepositoryConfig(profile_name="mob", source="csv", csv_raw_path=csv_path))
    assert repo.flotte is repo.flotte


def test_csv_ohne_pfad_ist_ein_fehler():
    repo = Repository(RepositoryConfig(profile_name="vgf", source="csv"))
    with pytest.raises(ValueError, match="csv_raw_path"):
        repo.load()


def test_unbekannte_quelle_ist_ein_fehler():
    repo = Repository(RepositoryConfig(profile_name="vgf", source="ftp"))
    with pytest.raises(ValueError, match="Unbekannte Quelle"):
        repo.load()


def test_unbekanntes_profil_ist_ein_fehler():
    with pytest.raises(FileNotFoundError):
        Repository(RepositoryConfig(profile_name="gibtsnicht", source="csv"))


def test_oracle_mit_connect_string_nutzt_eine_gemeinsame_session(monkeypatch):
    gesehen = {}

    def fake(connect_string, profile, thick_mode_lib_dir=None):
        gesehen.update(cs=connect_string, profile=profile.name)
        return Flotte()

    monkeypatch.setattr(oracle_source, "load_flotte_and_prognose_from_connect_string", fake)
    repo = Repository(RepositoryConfig(profile_name="abellio", source="oracle",
                                       oracle_connect_string="u/p@dsn"))
    assert isinstance(repo.load(), Flotte)
    assert gesehen == {"cs": "u/p@dsn", "profile": "abellio"}


def test_oracle_ohne_connect_string_nutzt_einzelangaben(monkeypatch):
    gesehen = {}

    def fake(dsn, user, password, profile, thick_mode_lib_dir=None):
        gesehen.update(dsn=dsn, user=user, password=password, profile=profile.name)
        return Flotte()

    monkeypatch.setattr(oracle_source, "load_flotte_from_oracle", fake)
    repo = Repository(RepositoryConfig(profile_name="mob", source="oracle",
                                       oracle_dsn="pcs16", oracle_user="mob", oracle_password="x"))
    repo.load()
    assert gesehen == {"dsn": "pcs16", "user": "mob", "password": "x", "profile": "mob"}
