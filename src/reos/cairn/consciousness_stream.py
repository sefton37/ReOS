"""CAIRN Consciousness Stream - Real-time visibility into CAIRN's thinking process.

Philosophy: Full transparency as our open-source competitive advantage.
Users see everything in real-time.

This module provides an observer pattern for capturing consciousness events
during CAIRN's processing pipeline:
- Intent extraction
- Extended thinking phases
- Tool calls
- Response generation

Events are collected and made available for frontend polling.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class ConsciousnessEventType(Enum):
    """Types of consciousness events that CAIRN can emit."""

    # High-level phases
    PHASE_START = auto()      # "Starting Intent Extraction"
    PHASE_COMPLETE = auto()   # "Intent Extraction Complete"

    # Intent engine events
    INTENT_EXTRACTED = auto()     # Category, action, confidence
    INTENT_VERIFIED = auto()      # Tool resolution
    PATTERN_MATCHED = auto()      # Which patterns triggered

    # Extended thinking events
    COMPREHENSION_START = auto()
    COMPREHENSION_RESULT = auto()
    DECOMPOSITION_START = auto()
    DECOMPOSITION_RESULT = auto()
    REASONING_START = auto()
    REASONING_ITERATION = auto()  # Each pass in iterative reasoning
    REASONING_RESULT = auto()
    COHERENCE_START = auto()
    COHERENCE_RESULT = auto()
    DECISION_START = auto()
    DECISION_RESULT = auto()

    # Conversational reasoning
    EXPLORE_PASS = auto()    # 3-pass conversational
    IDEATE_PASS = auto()
    SYNTHESIZE_PASS = auto()

    # LLM interaction
    LLM_CALL_START = auto()   # About to call LLM
    LLM_CALL_COMPLETE = auto() # Got response

    # Tool execution
    TOOL_CALL_START = auto()
    TOOL_CALL_COMPLETE = auto()

    # Final
    RESPONSE_READY = auto()


@dataclass
class ConsciousnessEvent:
    """A single consciousness event with full content."""

    event_type: ConsciousnessEventType
    timestamp: datetime
    title: str              # Human-readable title
    content: str            # Full content (not truncated!)
    metadata: dict[str, Any] = field(default_factory=dict)  # Extra structured data


class ConsciousnessObserver:
    """Captures consciousness events during processing.

    Singleton pattern ensures all components emit to the same observer.
    Thread-safe for concurrent access.

    Usage:
        observer = ConsciousnessObserver.get_instance()
        observer.start_session()
        observer.emit(ConsciousnessEventType.PHASE_START, "Starting", "Content...")
        events = observer.poll(since_index=0)
        observer.end_session()
    """

    _instance: ConsciousnessObserver | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.events: list[ConsciousnessEvent] = []
        self.active = False
        self._event_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> ConsciousnessObserver:
        """Get the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def start_session(self) -> None:
        """Start a new consciousness streaming session.

        Clears previous events and activates event collection.
        """
        with self._event_lock:
            self.events.clear()
            self.active = True

    def emit(
        self,
        event_type: ConsciousnessEventType,
        title: str,
        content: str,
        **metadata: Any,
    ) -> None:
        """Emit a consciousness event.

        Args:
            event_type: The type of event
            title: Human-readable title (e.g., "Intent Extraction")
            content: Full content - never truncated
            **metadata: Additional structured data
        """
        if not self.active:
            return

        event = ConsciousnessEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            title=title,
            content=content,
            metadata=dict(metadata),
        )
        with self._event_lock:
            self.events.append(event)

        # Debug logging to file
        with open("/tmp/consciousness_debug.log", "a") as f:
            f.write(f"[EMIT] {title} (total events: {len(self.events)})\n")

    def poll(self, since_index: int = 0) -> list[ConsciousnessEvent]:
        """Poll for new events since the given index.

        Args:
            since_index: Return events starting from this index

        Returns:
            List of events since the given index
        """
        with self._event_lock:
            return list(self.events[since_index:])

    def get_all(self) -> list[ConsciousnessEvent]:
        """Get all events from the current session."""
        with self._event_lock:
            return list(self.events)

    def end_session(self) -> None:
        """End the current consciousness streaming session."""
        self.active = False

    def is_active(self) -> bool:
        """Check if a session is currently active."""
        return self.active
