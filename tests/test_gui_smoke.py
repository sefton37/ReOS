from __future__ import annotations

import os

import pytest


@pytest.fixture
def qapp():
    # Ensure headless operation.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_constructs(
    isolated_db_singleton,  # noqa: ANN001
    qapp,
) -> None:
    from reos.gui.main_window import MainWindow

    w = MainWindow()
    w.close()


def test_projects_window_constructs(
    isolated_db_singleton,  # noqa: ANN001
    qapp,
) -> None:
    from reos.db import get_db
    from reos.gui.projects_window import ProjectsWindow

    w = ProjectsWindow(db=get_db())
    w.close()


def test_settings_window_constructs(
    isolated_db_singleton,  # noqa: ANN001
    qapp,
) -> None:
    from reos.db import get_db
    from reos.gui.settings_window import SettingsWindow

    w = SettingsWindow(db=get_db())
    w.close()
