"""Gemeinsame Fixtures: Qt ohne Bildschirm, synthetische Szenarien je Profil."""
import os

# Muss vor dem ersten QApplication gesetzt sein (kein Fenster auf dem Desktop).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from tests.synth import PROFILES, write_csv


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(params=PROFILES)
def scenario(request, tmp_path):
    """(profilname, Repository auf einer synthetischen CSV dieses Profils)."""
    from wheelset_dashboard.data.repository import Repository, RepositoryConfig
    name = request.param
    csv_path = write_csv(name, tmp_path / f"bo_radsatzdaten_{name}.csv")
    repo = Repository(RepositoryConfig(profile_name=name, source="csv", csv_raw_path=csv_path))
    return name, repo
