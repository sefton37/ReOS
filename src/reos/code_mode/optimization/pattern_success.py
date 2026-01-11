"""Pattern success tracking for learned trust.

This module tracks the success/failure rate of execution patterns
over time. Patterns that consistently succeed can be trusted more.
Patterns that fail lose trust.

Important: We store success metrics, not code.
Learning without storing training data.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.intention import Action
    from reos.db import Database

logger = logging.getLogger(__name__)


@dataclass
class PatternStats:
    """Statistics for a pattern.

    Tracks success rate and recency to determine trust level.
    """

    pattern_hash: str
    description: str

    # Counts
    attempts: int = 0
    successes: int = 0
    failures: int = 0

    # Timestamps
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_success: datetime | None = None
    last_failure: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Raw success rate."""
        if self.attempts == 0:
            return 0.5  # Prior: assume 50%
        return self.successes / self.attempts

    @property
    def trust_level(self) -> float:
        """Trust level with recency decay.

        High success rate + recent success = high trust
        Old pattern without recent success = decayed trust
        Few attempts = reduced trust (not enough data)
        """
        base = self.success_rate

        # Decay for lack of recent success
        if self.last_success:
            days_since = (datetime.now(timezone.utc) - self.last_success).days
            decay = max(0.5, 1.0 - (days_since / 30) * 0.1)
            base *= decay

        # Require minimum attempts for high trust
        if self.attempts < 3:
            base *= 0.7
        elif self.attempts < 10:
            base *= 0.9

        # Cap at 0.95 - never fully trust
        return min(0.95, base)

    def record_success(self) -> None:
        """Record a successful execution."""
        self.attempts += 1
        self.successes += 1
        self.last_success = datetime.now(timezone.utc)

    def record_failure(self) -> None:
        """Record a failed execution."""
        self.attempts += 1
        self.failures += 1
        self.last_failure = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "pattern_hash": self.pattern_hash,
            "description": self.description,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "first_seen": self.first_seen.isoformat(),
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "success_rate": self.success_rate,
            "trust_level": self.trust_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PatternStats:
        """Deserialize from storage."""
        return cls(
            pattern_hash=data["pattern_hash"],
            description=data.get("description", ""),
            attempts=data.get("attempts", 0),
            successes=data.get("successes", 0),
            failures=data.get("failures", 0),
            first_seen=datetime.fromisoformat(data["first_seen"]) if data.get("first_seen") else datetime.now(timezone.utc),
            last_success=datetime.fromisoformat(data["last_success"]) if data.get("last_success") else None,
            last_failure=datetime.fromisoformat(data["last_failure"]) if data.get("last_failure") else None,
        )


class PatternSuccessTracker:
    """Track and learn from pattern success/failure.

    Stores pattern statistics in the database for persistence
    across sessions.
    """

    def __init__(self, db: "Database", repo_path: str):
        """Initialize tracker.

        Args:
            db: Database connection
            repo_path: Repository path (patterns are per-repo)
        """
        self.db = db
        self.repo_path = repo_path
        self._cache: dict[str, PatternStats] = {}
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Ensure the pattern_success table exists."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS pattern_success (
                pattern_hash TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                description TEXT,
                attempts INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_success TEXT,
                last_failure TEXT,
                UNIQUE(pattern_hash, repo_path)
            )
        """)

    def record_outcome(
        self,
        action: "Action",
        success: bool,
        description: str | None = None,
    ) -> None:
        """Record the outcome of an action.

        Args:
            action: The action that was executed
            success: Whether it succeeded
            description: Optional human description of the pattern
        """
        pattern_hash = self._hash_pattern(action)
        stats = self._get_or_create(pattern_hash, description or str(action.type.value))

        if success:
            stats.record_success()
        else:
            stats.record_failure()

        self._save(stats)
        logger.debug(
            "Pattern %s: %s (trust: %.2f)",
            pattern_hash[:8],
            "success" if success else "failure",
            stats.trust_level,
        )

    def get_trust_level(self, action: "Action") -> float:
        """Get trust level for an action based on history.

        Args:
            action: The action to check

        Returns:
            Trust level from 0.0 to 1.0
        """
        pattern_hash = self._hash_pattern(action)
        stats = self._get(pattern_hash)

        if stats:
            return stats.trust_level

        return 0.5  # Default: moderate trust

    def should_skip_verification(self, action: "Action") -> bool:
        """Should we skip verification for this action?

        Only skip if we have high confidence from history.

        Args:
            action: The action to check

        Returns:
            True if verification can be skipped
        """
        trust = self.get_trust_level(action)
        return trust > 0.9

    def _hash_pattern(self, action: "Action") -> str:
        """Create a hash for the action pattern.

        We hash based on:
        - Action type (command, edit, create, etc.)
        - Target file pattern (e.g., "*.py" for Python files)
        - Content pattern (normalized)
        """
        # Normalize target to pattern
        target_pattern = ""
        if action.target:
            # Use file extension as pattern
            if "." in action.target:
                ext = action.target.rsplit(".", 1)[-1]
                target_pattern = f"*.{ext}"
            else:
                target_pattern = action.target

        # Normalize content - just first 50 chars of type signature
        content_sig = self._normalize_content(action.content)[:50]

        pattern_str = f"{action.type.value}:{target_pattern}:{content_sig}"
        return hashlib.sha256(pattern_str.encode()).hexdigest()[:16]

    def _normalize_content(self, content: str) -> str:
        """Normalize content for pattern matching.

        Strip variable names, keep structure.
        """
        import re

        # Remove string literals
        normalized = re.sub(r'"[^"]*"', '""', content)
        normalized = re.sub(r"'[^']*'", "''", normalized)

        # Remove numbers
        normalized = re.sub(r"\d+", "N", normalized)

        # Collapse whitespace
        normalized = " ".join(normalized.split())

        return normalized

    def _get(self, pattern_hash: str) -> PatternStats | None:
        """Get pattern stats from cache or database."""
        if pattern_hash in self._cache:
            return self._cache[pattern_hash]

        row = self.db.fetchone(
            """
            SELECT * FROM pattern_success
            WHERE pattern_hash = ? AND repo_path = ?
            """,
            (pattern_hash, self.repo_path),
        )

        if row:
            stats = PatternStats.from_dict(dict(row))
            self._cache[pattern_hash] = stats
            return stats

        return None

    def _get_or_create(
        self,
        pattern_hash: str,
        description: str,
    ) -> PatternStats:
        """Get existing or create new pattern stats."""
        stats = self._get(pattern_hash)
        if stats:
            return stats

        stats = PatternStats(
            pattern_hash=pattern_hash,
            description=description,
        )
        self._cache[pattern_hash] = stats
        return stats

    def _save(self, stats: PatternStats) -> None:
        """Save pattern stats to database."""
        self.db.execute(
            """
            INSERT OR REPLACE INTO pattern_success (
                pattern_hash, repo_path, description,
                attempts, successes, failures,
                first_seen, last_success, last_failure
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stats.pattern_hash,
                self.repo_path,
                stats.description,
                stats.attempts,
                stats.successes,
                stats.failures,
                stats.first_seen.isoformat(),
                stats.last_success.isoformat() if stats.last_success else None,
                stats.last_failure.isoformat() if stats.last_failure else None,
            ),
        )

    def get_top_patterns(self, limit: int = 10) -> list[PatternStats]:
        """Get the most trusted patterns.

        Useful for debugging and analysis.
        """
        rows = self.db.fetchall(
            """
            SELECT * FROM pattern_success
            WHERE repo_path = ?
            ORDER BY (successes * 1.0 / MAX(attempts, 1)) DESC
            LIMIT ?
            """,
            (self.repo_path, limit),
        )

        return [PatternStats.from_dict(dict(row)) for row in rows]
