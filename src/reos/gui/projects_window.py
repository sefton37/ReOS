"""Projects window.

UX principle:
- Middle pane of ReOS is always Chat.
- Projects open in a separate window launched from the left navigation.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow

from ..db import Database
from ..errors import record_error
from ..repo_discovery import discover_git_repos
from .projects_widget import ProjectsWidget

logger = logging.getLogger(__name__)


class ProjectsWindow(QMainWindow):
    """Standalone window for managing Projects."""

    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db
        self.setWindowTitle("ReOS - Projects")
        self.resize(QSize(1100, 800))

        self._widget = ProjectsWidget(db=self._db)
        self.setCentralWidget(self._widget)

    def refresh(self) -> None:
        """Run repo discovery and refresh the Projects UI."""

        try:
            repos = discover_git_repos()
            import uuid

            for repo_path in repos:
                self._db.upsert_repo(repo_id=str(uuid.uuid4()), path=str(repo_path))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Repo discovery failed")
            record_error(source="reos", operation="repo_discovery", exc=exc)

        self._widget.refresh()
