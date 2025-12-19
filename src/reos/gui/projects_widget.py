"""Projects screen.

A Project Charter is the authoritative source of truth for a project.
All fields live in SQLite (slow-changing, human-authored).

UX principle: this widget is intended to be used in a separate Projects window,
not in the main chat pane.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..db import Database


@dataclass(frozen=True)
class RepoChoice:
    repo_id: str
    path: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProjectsWidget(QWidget):
    """Projects screen for managing `project_charter`."""

    # Keep the SQLite schema as-is (ground truth), but simplify the editor UX.
    # Hidden fields are stored as empty strings when creating a new charter and
    # are left untouched on updates.

    _OPTIONAL_FIELDS = {"origin_story", "current_state_summary"}

    _VISIBLE_FIELDS: list[tuple[str, str, str, bool]] = [
        (
            "project_name",
            "Project name",
            "Short name, e.g. 'ReOS'.",
            True,
        ),
        (
            "project_owner",
            "Project owner",
            "Who holds the intent + can say 'no'.",
            True,
        ),
        (
            "core_intent",
            "Core intent",
            "Why this exists (one sentence).",
            True,
        ),
        (
            "problem_statement",
            "Problem statement",
            "The pain or gap you're resolving.",
            True,
        ),
        (
            "non_goals",
            "Non-goals",
            "Explicitly out of scope (bullets).",
            True,
        ),
        (
            "definition_of_done",
            "Definition of done",
            "Concrete exit criteria; measurable.",
            True,
        ),
        (
            "success_signals",
            "Success signals",
            "Signals you're on track (bullets).",
            True,
        ),
        (
            "time_horizon",
            "Time horizon",
            "Timebox, e.g. '2 weeks' or 'M1B'.",
            True,
        ),
        (
            "allowed_scope",
            "Allowed scope",
            "What is allowed to change.",
            True,
        ),
        (
            "forbidden_scope",
            "Forbidden scope",
            "Hard boundaries; no exceptions.",
            True,
        ),
        (
            "primary_values",
            "Primary values",
            "Values to optimize for, e.g. 'local-first, transparency'.",
            True,
        ),
        (
            "attention_budget",
            "Attention budget",
            "How much attention this deserves, e.g. '3 hrs/week'.",
            True,
        ),
        (
            "intervention_style",
            "Intervention style",
            "How ReOS should nudge: gentle, direct, quiet, etc.",
            True,
        ),
    ]

    _HIDDEN_REQUIRED_DB_FIELDS: set[str] = {
        # These remain in the DB schema but aren't in the simplified editor.
        "failure_conditions",
        "sunset_criteria",
        "energy_profile",
        "acceptable_tradeoffs",
        "unacceptable_tradeoffs",
        "distraction_tolerance",
    }

    _ALL_DB_TEXT_FIELDS: set[str] = {
        "core_intent",
        "problem_statement",
        "non_goals",
        "definition_of_done",
        "success_signals",
        "failure_conditions",
        "sunset_criteria",
        "time_horizon",
        "energy_profile",
        "allowed_scope",
        "forbidden_scope",
        "primary_values",
        "acceptable_tradeoffs",
        "unacceptable_tradeoffs",
        "attention_budget",
        "distraction_tolerance",
        "intervention_style",
        "origin_story",
        "current_state_summary",
    }

    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db
        self._selected_project_id: str | None = None

        root = QHBoxLayout(self)

        # Left: project list
        left = QVBoxLayout()
        root.addLayout(left, stretch=1)

        header = QLabel("Projects")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        left.addWidget(header)

        self.project_list = QListWidget()
        self.project_list.itemClicked.connect(self._on_project_clicked)
        left.addWidget(self.project_list, stretch=1)

        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self._on_new)
        left.addWidget(self.new_btn)

        # Right: charter form (scrollable)
        right = QVBoxLayout()
        root.addLayout(right, stretch=2)

        meta_row = QHBoxLayout()
        right.addLayout(meta_row)

        self.created_at_label = QLabel("Created: —")
        self.last_reaffirmed_label = QLabel("Last reaffirmed: —")
        self.created_at_label.setStyleSheet("color: #666; font-size: 11px;")
        self.last_reaffirmed_label.setStyleSheet("color: #666; font-size: 11px;")
        meta_row.addWidget(self.created_at_label)
        meta_row.addWidget(self.last_reaffirmed_label)
        meta_row.addStretch()

        self.reaffirm_btn = QPushButton("Reaffirm")
        self.reaffirm_btn.clicked.connect(self._on_reaffirm)
        meta_row.addWidget(self.reaffirm_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        right.addWidget(scroll, stretch=1)

        form_container = QWidget()
        scroll.setWidget(form_container)
        form = QFormLayout(form_container)

        self.repo_combo = QComboBox()
        form.addRow("Linked repo", self.repo_combo)

        self._text_fields: dict[str, QTextEdit] = {}
        self._line_fields: dict[str, QLineEdit] = {}

        def label_with_help(*, title: str, help_text: str) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)

            t = QLabel(title)
            t.setStyleSheet("font-weight: 600;")
            v.addWidget(t)

            h = QLabel(help_text)
            h.setWordWrap(True)
            h.setStyleSheet("color: #666; font-size: 11px;")
            v.addWidget(h)
            return w

        # Build simplified field set.
        for field, title, help_text, _required in self._VISIBLE_FIELDS:
            if field in {"project_name", "project_owner"}:
                box = QLineEdit()
                self._line_fields[field] = box
                form.addRow(label_with_help(title=title, help_text=help_text), box)
                continue

            box = QTextEdit()
            box.setMinimumHeight(70)
            self._text_fields[field] = box
            form.addRow(label_with_help(title=title, help_text=help_text), box)

        buttons = QHBoxLayout()
        right.addLayout(buttons)

        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._on_save)
        buttons.addWidget(self.save_btn)

        buttons.addStretch()

        self.status = QLabel("")
        self.status.setStyleSheet("color: #666; font-size: 11px;")
        right.addWidget(self.status)

        self.refresh()

    def refresh(self) -> None:
        self._load_repos()
        self._load_projects()

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _load_repos(self) -> None:
        self.repo_combo.clear()
        repos = self._db.iter_repos()
        for row in repos:
            repo_id = str(row.get("id"))
            path = str(row.get("path"))
            self.repo_combo.addItem(path, RepoChoice(repo_id=repo_id, path=path))
        if not repos:
            self.repo_combo.addItem("(no repos detected yet)", None)

    def _load_projects(self) -> None:
        self.project_list.clear()
        for row in self._db.iter_project_charters():
            project_id = str(row.get("project_id"))
            name = str(row.get("project_name"))
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, project_id)
            self.project_list.addItem(item)

    def _clear_form(self) -> None:
        self._selected_project_id = None
        self.created_at_label.setText("Created: —")
        self.last_reaffirmed_label.setText("Last reaffirmed: —")

        for field in self._line_fields.values():
            field.setText("")
        for field in self._text_fields.values():
            field.setPlainText("")

        self.repo_combo.setCurrentIndex(0)

    def _on_new(self) -> None:
        self._clear_form()
        self._set_status("Ready.")

    def _on_project_clicked(self, item: QListWidgetItem) -> None:
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(project_id, str) or not project_id:
            return

        row = self._db.get_project_charter(project_id=project_id)
        if row is None:
            return

        # Selecting a project makes it the active project for tools/Chat/MCP.
        self._db.set_active_project_id(project_id=project_id)

        self._selected_project_id = project_id

        self.created_at_label.setText(f"Created: {row.get('created_at', '—')}")
        self.last_reaffirmed_label.setText(
            f"Last reaffirmed: {row.get('last_reaffirmed_at', '—')}"
        )

        self._line_fields["project_name"].setText(str(row.get("project_name", "")))
        self._line_fields["project_owner"].setText(str(row.get("project_owner", "")))

        for field in self._text_fields:
            self._text_fields[field].setPlainText(str(row.get(field, "") or ""))

        repo_id = str(row.get("repo_id"))
        for idx in range(self.repo_combo.count()):
            choice = self.repo_combo.itemData(idx)
            if isinstance(choice, RepoChoice) and choice.repo_id == repo_id:
                self.repo_combo.setCurrentIndex(idx)
                break

        self._set_status("Loaded project charter.")

    def _collect(self) -> tuple[dict[str, str] | None, str | None]:
        choice = self.repo_combo.currentData()
        if not isinstance(choice, RepoChoice):
            return None, "Select a detected repo first."

        record: dict[str, str] = {"repo_id": choice.repo_id}

        # Collect only visible fields.
        for field, _title, _help, required in self._VISIBLE_FIELDS:
            if field in self._line_fields:
                record[field] = self._line_fields[field].text().strip()
            else:
                record[field] = self._text_fields[field].toPlainText().strip()

            if required and not record[field]:
                return None, f"Missing required field: {field}"

        return record, None

    def _on_save(self) -> None:
        record, err = self._collect()
        if err is not None or record is None:
            self._set_status(err or "Invalid charter.")
            return

        now = _now_iso()
        if self._selected_project_id is None:
            project_id = str(uuid.uuid4())
            # On create, we must satisfy the full DB schema. Keep hidden fields
            # empty by default; users can always extend later if we add an
            # advanced editor.
            full: dict[str, str] = {
                "project_id": project_id,
                "created_at": now,
                "last_reaffirmed_at": now,
                "updated_at": now,
                "ingested_at": now,
                **record,
            }
            for field in self._ALL_DB_TEXT_FIELDS:
                if field not in full:
                    full[field] = ""
            self._db.insert_project_charter(record=full)
            self._selected_project_id = project_id
            self._set_status("Project charter created.")
        else:
            self._db.update_project_charter(project_id=self._selected_project_id, updates=record)
            self._set_status("Project charter updated.")

        self.refresh()
        if self._selected_project_id is not None:
            row = self._db.get_project_charter(project_id=self._selected_project_id)
            if row is not None:
                self.created_at_label.setText(f"Created: {row.get('created_at', '—')}")
                self.last_reaffirmed_label.setText(
                    f"Last reaffirmed: {row.get('last_reaffirmed_at', '—')}"
                )

    def _on_reaffirm(self) -> None:
        if self._selected_project_id is None:
            self._set_status("Select a project first.")
            return

        confirm = QMessageBox.question(
            self,
            "Reaffirm charter",
            "Reaffirming is an explicit human confirmation that this project is still worth attention.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._db.reaffirm_project_charter(project_id=self._selected_project_id)
        row = self._db.get_project_charter(project_id=self._selected_project_id)
        if row is not None:
            self.last_reaffirmed_label.setText(
                f"Last reaffirmed: {row.get('last_reaffirmed_at', '—')}"
            )
        self._set_status("Charter reaffirmed.")
