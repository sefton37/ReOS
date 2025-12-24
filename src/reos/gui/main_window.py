"""Main window: 2-pane layout (nav | chat)."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..agent import ChatAgent
from ..db import get_db
from .projects_window import ProjectsWindow
from .settings_window import SettingsWindow

logger = logging.getLogger(__name__)


class _ChatAgentThread(QThread):
    def __init__(self, *, agent: ChatAgent, user_text: str) -> None:
        super().__init__()
        self._agent = agent
        self._user_text = user_text
        self.answer: str | None = None
        self.error: str | None = None

    def run(self) -> None:  # noqa: D401
        try:
            self.answer = self._agent.respond(self._user_text)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)


class MainWindow(QMainWindow):
    """ReOS desktop app: chat-first companion in a 1080p window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ReOS - Attention Kernel")
        self.resize(QSize(1920, 1080))  # 1080p-ish (width for 3 panes)

        # Glass-pane feel: allow the desktop to show through.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

        self._db = get_db()
        self._agent = ChatAgent(db=self._db)
        self._projects_window: ProjectsWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._chat_thread: _ChatAgentThread | None = None
        self._typing_timer: QTimer | None = None
        self._typing_step: int = 0
        self._typing_row: QWidget | None = None
        self._typing_label: QLabel | None = None
        self._bubble_max_width_ratio: float = 0.78
        self._last_assistant_text: str | None = None

        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        central.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        central.setAutoFillBackground(False)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Left pane: Navigation
        left_pane = self._create_nav_pane()

        # Center pane: Chat (always)
        center_pane = self._create_chat_pane()

        # Use splitters for resizable panes
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        main_split.setAutoFillBackground(False)
        main_split.addWidget(left_pane)
        main_split.addWidget(center_pane)

        # Default proportions: nav (15%), chat (85%)
        main_split.setSizes([288, 1632])
        layout.addWidget(main_split)

        # No background polling: Git observation happens only via explicit tool calls.

    def _create_nav_pane(self) -> QWidget:
        """Left navigation pane."""
        widget = QWidget()
        widget.setObjectName("reosNavPane")
        layout = QVBoxLayout(widget)

        title = QLabel("Navigation")
        title.setProperty("reosTitle", True)
        layout.addWidget(title)

        projects_btn = QPushButton("Projects")
        projects_btn.clicked.connect(self._open_projects_window)
        layout.addWidget(projects_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings_window)
        layout.addWidget(settings_btn)

        layout.addStretch()
        return widget

    def _apply_chat_bubble_shadow(self, bubble: QFrame) -> None:
        shadow = QGraphicsDropShadowEffect(bubble)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 55))
        bubble.setGraphicsEffect(shadow)

    def _append_chat(self, *, role: str, text: str) -> None:
        if not hasattr(self, "_chat_layout"):
            return

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        bubble = QFrame()
        bubble.setFrameShape(QFrame.Shape.NoFrame)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        bubble.setProperty("reosChatBubble", True)
        bubble.setProperty("reosRole", "user" if role == "user" else "reos")
        self._apply_chat_bubble_shadow(bubble)

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(0)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_layout.addWidget(label)

        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)

        # Insert above the stretch spacer.
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, row)
        self._refresh_bubble_widths()
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _refresh_bubble_widths(self) -> None:
        if not hasattr(self, "_chat_scroll"):
            return
        viewport_width = self._chat_scroll.viewport().width()
        if viewport_width <= 0:
            return

        # Chat layout has left/right margins of 12px each; keep a little slack.
        available = max(0, viewport_width - 24)
        max_width = int(available * self._bubble_max_width_ratio)
        if max_width <= 0:
            return

        if not hasattr(self, "_chat_container"):
            return

        for bubble in self._chat_container.findChildren(QFrame):
            if bubble.property("reosChatBubble") is True:
                bubble.setMaximumWidth(max_width)

    def _scroll_chat_to_bottom(self) -> None:
        if not hasattr(self, "_chat_scroll"):
            return
        bar = self._chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _start_typing_indicator(self) -> None:
        self._stop_typing_indicator()

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        bubble = QFrame()
        bubble.setFrameShape(QFrame.Shape.NoFrame)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        bubble.setProperty("reosChatBubble", True)
        bubble.setProperty("reosRole", "reos")
        self._apply_chat_bubble_shadow(bubble)

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(0)

        label = QLabel("")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        bubble_layout.addWidget(label)

        row_layout.addWidget(bubble)
        row_layout.addStretch(1)

        self._typing_row = row
        self._typing_label = label
        self._typing_step = 0
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, row)
        self._refresh_bubble_widths()
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

        timer = QTimer(self)
        timer.timeout.connect(self._advance_typing_indicator)
        timer.start(350)
        self._typing_timer = timer

    def _advance_typing_indicator(self) -> None:
        if self._typing_label is None:
            return
        self._typing_step = (self._typing_step + 1) % 4
        dots = "." * self._typing_step
        self._typing_label.setText(dots if dots else "…")

    def _stop_typing_indicator(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer.deleteLater()
            self._typing_timer = None

        if self._typing_row is not None:
            self._typing_row.setParent(None)
            self._typing_row.deleteLater()
            self._typing_row = None
            self._typing_label = None

    def eventFilter(self, obj: object, event: object) -> bool:  # noqa: N802
        if hasattr(self, "_chat_scroll") and obj is self._chat_scroll.viewport():
            if isinstance(event, QEvent) and event.type() == QEvent.Type.Resize:
                self._refresh_bubble_widths()
        return super().eventFilter(obj, event)

    def _open_projects_window(self) -> None:
        if self._projects_window is None:
            self._projects_window = ProjectsWindow(db=self._db)

        self._projects_window.refresh()
        self._projects_window.show()
        self._projects_window.raise_()
        self._projects_window.activateWindow()

    def _open_settings_window(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(db=self._db)

        self._settings_window.refresh()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()


    def _create_chat_pane(self) -> QWidget:
        """Center chat pane."""
        widget = QWidget()
        widget.setObjectName("reosChatPane")
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        widget.setAutoFillBackground(False)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)

        # Chat history display (bubble list)
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setObjectName("reosChatScroll")
        self._chat_scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._chat_scroll.setAutoFillBackground(False)
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setFrameShape(QFrame.Shape.NoFrame)

        viewport = self._chat_scroll.viewport()
        viewport.setObjectName("reosChatViewport")
        viewport.installEventFilter(self)
        viewport.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        viewport.setAutoFillBackground(False)

        self._chat_container = QWidget()
        self._chat_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._chat_container.setAutoFillBackground(False)
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(0, 0, 0, 0)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch(1)
        self._chat_scroll.setWidget(self._chat_container)
        layout.addWidget(self._chat_scroll, stretch=1)

        self._append_chat(
            role="reos",
            text=(
                "Hello! I'm here to help you understand your attention patterns.\n\n"
                "Tell me about your work."
            ),
        )

        # Input bar (sleek + minimal)
        input_bar = QFrame()
        input_bar.setObjectName("reosChatInputBar")
        input_bar_layout = QHBoxLayout(input_bar)
        input_bar_layout.setContentsMargins(10, 10, 10, 10)
        input_bar_layout.setSpacing(10)

        self.chat_input = QLineEdit()
        self.chat_input.setObjectName("reosChatInput")
        self.chat_input.setPlaceholderText("Type a message…")
        self.chat_input.returnPressed.connect(self._on_send_message)
        input_bar_layout.addWidget(self.chat_input, stretch=1)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("reosChatSend")
        send_btn.clicked.connect(self._on_send_message)
        input_bar_layout.addWidget(send_btn)

        # Subtle shadow so the input bar stands out.
        shadow = QGraphicsDropShadowEffect(input_bar)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, -1)
        shadow.setColor(QColor(0, 0, 0, 35))
        input_bar.setGraphicsEffect(shadow)

        layout.addWidget(input_bar)

        return widget

    def _on_send_message(self) -> None:
        """Handle user message."""
        text = self.chat_input.text().strip()
        if not text:
            return

        self._append_chat(role="user", text=text)
        self.chat_input.clear()

        if self._chat_thread is not None and self._chat_thread.isRunning():
            self._append_chat(role="reos", text="One moment — still thinking on the last message.")
            return

        self._start_typing_indicator()

        thread = _ChatAgentThread(agent=self._agent, user_text=text)
        thread.finished.connect(self._on_agent_finished)
        self._chat_thread = thread
        thread.start()

    def _on_agent_finished(self) -> None:
        thread = self._chat_thread
        self._chat_thread = None
        if thread is None:
            return

        self._stop_typing_indicator()

        if thread.error:
            msg = thread.error
            if "Ollama" in msg or "11434" in msg:
                msg = (
                    msg
                    + "\n\nHint: start Ollama and set REOS_OLLAMA_MODEL, e.g. "
                    "`export REOS_OLLAMA_MODEL=llama3.2`."
                )
            self._append_chat(role="reos", text=msg)
            return

        answer = thread.answer or "(no response)"
        self._append_chat(role="reos", text=answer)
        self._last_assistant_text = answer

    def _extract_unified_diff(self, text: str) -> str | None:
        """Extract a unified diff from assistant text.

        Supports:
        - fenced codeblocks: ```diff ... ```
        - raw patches starting with 'diff --git'
        """

        if not text.strip():
            return None

        fence = re.search(r"```(?:diff|patch)\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
        if fence:
            payload = fence.group(1).strip("\n")
            return payload or None

        raw = re.search(r"(diff --git[\s\S]+)", text)
        if raw:
            payload = raw.group(1).strip("\n")
            return payload or None

        return None

    def _patch_targets_are_kb_only(self, patch_text: str) -> bool:
        """Return True iff all changed paths are under projects/<id>/kb/."""

        # Extract paths from +++/--- lines; accept both a/ and b/ prefixes.
        paths: set[str] = set()
        for line in patch_text.splitlines():
            if line.startswith("+++ ") or line.startswith("--- "):
                _, p = line.split(" ", 1)
                p = p.strip()
                if p in {"/dev/null"}:
                    continue
                if p.startswith("a/") or p.startswith("b/"):
                    p = p[2:]
                paths.add(p)

        if not paths:
            # If we can't determine targets safely, deny.
            return False

        for p in paths:
            if not p.startswith("projects/"):
                return False
            if "/kb/" not in p:
                return False
        return True

    def _on_preview_apply_patch(self) -> None:
        patch = self._extract_unified_diff(self._last_assistant_text or "")
        if not patch:
            return

        if not self._patch_targets_are_kb_only(patch):
            self._append_chat(
                role="reos",
                text=(
                    "I found a patch, but it targets files outside `projects/<id>/kb/`, "
                    "so I won't apply it automatically."
                ),
            )
            return

        # Preview in a dialog and apply via `git apply` only on explicit confirmation.
        from PySide6.QtWidgets import QDialog  # local import to avoid GUI cycles

        dlg = QDialog(self)
        dlg.setWindowTitle("Preview/Apply Patch")
        root = QVBoxLayout(dlg)

        info = QLabel("This will apply the patch to your ReOS workspace (ready to commit).")
        info.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(info)

        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(patch)
        box.setMinimumSize(900, 520)
        root.addWidget(box, stretch=1)

        buttons = QHBoxLayout()
        root.addLayout(buttons)
        buttons.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        buttons.addWidget(cancel)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(dlg.accept)
        buttons.addWidget(apply_btn)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        repo_root = Path(__file__).resolve().parents[3]
        try:
            check = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=patch,
                text=True,
                cwd=repo_root,
                capture_output=True,
                check=False,
            )
            if check.returncode != 0:
                self._append_chat(role="reos", text=f"Patch check failed:\n{check.stderr or check.stdout}")
                return

            res = subprocess.run(
                ["git", "apply", "-"],
                input=patch,
                text=True,
                cwd=repo_root,
                capture_output=True,
                check=False,
            )
            if res.returncode != 0:
                self._append_chat(role="reos", text=f"Patch apply failed:\n{res.stderr or res.stdout}")
                return

        except Exception as exc:  # noqa: BLE001
            self._append_chat(role="reos", text=f"Patch apply error: {exc}")
            return

        self._append_chat(role="reos", text="Patch applied to KB files (ready to commit).")
