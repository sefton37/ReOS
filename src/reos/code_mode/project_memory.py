"""Project Memory - Long-term memory for Code Mode.

Provides persistent memory that learns project-specific decisions, patterns,
and corrections across coding sessions. The system remembers "We use
dataclasses, not TypedDict" and applies it to future work.

Memory Types:
- Decisions: Project-level choices that guide future work
- Patterns: Recurring code patterns to follow
- Corrections: User modifications to AI-generated code (learning opportunities)
- Sessions: History of coding sessions
- Changes: Record of what was modified when
"""

from __future__ import annotations

import fnmatch
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.db import Database

logger = logging.getLogger(__name__)


def _generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class ProjectDecision:
    """A project-level decision that should guide future work.

    Examples:
    - "We use dataclasses, not TypedDict"
    - "All API endpoints return JSON with snake_case keys"
    - "Prefer composition over inheritance"
    """

    id: str
    repo_path: str
    decision: str
    rationale: str
    scope: str  # "global", "module:foo", "file:bar.py"
    keywords: list[str]
    source: str  # "user_explicit", "inferred", "correction"
    confidence: float
    created_at: datetime
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "decision": self.decision,
            "rationale": self.rationale,
            "scope": self.scope,
            "keywords": self.keywords,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectDecision:
        """Deserialize from dictionary."""
        keywords = data.get("keywords", [])
        if isinstance(keywords, str):
            keywords = json.loads(keywords)
        created_at = data.get("created_at", "")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            id=data["id"],
            repo_path=data["repo_path"],
            decision=data["decision"],
            rationale=data.get("rationale", ""),
            scope=data.get("scope", "global"),
            keywords=keywords,
            source=data.get("source", "inferred"),
            confidence=float(data.get("confidence", 1.0)),
            created_at=created_at,
            superseded_by=data.get("superseded_by"),
        )


@dataclass
class ProjectPattern:
    """A recurring pattern in the codebase to follow.

    Examples:
    - "Tests go in tests/, named test_*.py"
    - "Use pytest fixtures for shared setup"
    - "Import typing at top, stdlib second, local third"
    """

    id: str
    repo_path: str
    pattern_type: str  # "file_structure", "naming", "testing", "import", "style"
    description: str
    applies_to: str  # Glob pattern: "*.py", "tests/*"
    example_code: str | None
    source: str  # "detected", "user_explicit", "inferred"
    occurrence_count: int
    created_at: datetime
    last_seen_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "pattern_type": self.pattern_type,
            "description": self.description,
            "applies_to": self.applies_to,
            "example_code": self.example_code,
            "source": self.source,
            "occurrence_count": self.occurrence_count,
            "created_at": self.created_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectPattern:
        """Deserialize from dictionary."""
        created_at = data.get("created_at", "")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        last_seen_at = data.get("last_seen_at", "")
        if isinstance(last_seen_at, str):
            last_seen_at = datetime.fromisoformat(last_seen_at)
        return cls(
            id=data["id"],
            repo_path=data["repo_path"],
            pattern_type=data.get("pattern_type", "style"),
            description=data["description"],
            applies_to=data.get("applies_to", "*"),
            example_code=data.get("example_code"),
            source=data.get("source", "detected"),
            occurrence_count=int(data.get("occurrence_count", 1)),
            created_at=created_at,
            last_seen_at=last_seen_at,
        )


@dataclass
class UserCorrection:
    """A correction the user made to AI-generated code.

    These are gold: they show exactly where AI went wrong and what the
    user prefers. Repeated corrections can be promoted to decisions.
    """

    id: str
    repo_path: str
    session_id: str
    original_code: str
    corrected_code: str
    file_path: str
    correction_type: str  # "style", "logic", "naming", "structure", "missing"
    inferred_rule: str
    created_at: datetime
    promoted_to_decision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "session_id": self.session_id,
            "original_code": self.original_code,
            "corrected_code": self.corrected_code,
            "file_path": self.file_path,
            "correction_type": self.correction_type,
            "inferred_rule": self.inferred_rule,
            "created_at": self.created_at.isoformat(),
            "promoted_to_decision": self.promoted_to_decision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserCorrection:
        """Deserialize from dictionary."""
        created_at = data.get("created_at", "")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            id=data["id"],
            repo_path=data["repo_path"],
            session_id=data["session_id"],
            original_code=data["original_code"],
            corrected_code=data["corrected_code"],
            file_path=data["file_path"],
            correction_type=data.get("correction_type", "unknown"),
            inferred_rule=data.get("inferred_rule", ""),
            created_at=created_at,
            promoted_to_decision=data.get("promoted_to_decision"),
        )


@dataclass
class CodingSession:
    """Summary of a past coding session.

    Provides context for "what were we working on?" and helps track
    the history of work on a repository.
    """

    id: str
    repo_path: str
    started_at: datetime
    ended_at: datetime | None
    prompt_summary: str
    outcome: str  # "completed", "partial", "failed", "abandoned"
    files_changed: list[str]
    intent_summary: str
    lessons_learned: list[str]
    contract_fulfilled: bool
    iteration_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "prompt_summary": self.prompt_summary,
            "outcome": self.outcome,
            "files_changed": self.files_changed,
            "intent_summary": self.intent_summary,
            "lessons_learned": self.lessons_learned,
            "contract_fulfilled": self.contract_fulfilled,
            "iteration_count": self.iteration_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodingSession:
        """Deserialize from dictionary."""
        started_at = data.get("started_at", "")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        ended_at = data.get("ended_at")
        if isinstance(ended_at, str):
            ended_at = datetime.fromisoformat(ended_at)
        files_changed = data.get("files_changed", [])
        if isinstance(files_changed, str):
            files_changed = json.loads(files_changed)
        lessons_learned = data.get("lessons_learned", [])
        if isinstance(lessons_learned, str):
            lessons_learned = json.loads(lessons_learned)
        return cls(
            id=data["id"],
            repo_path=data["repo_path"],
            started_at=started_at,
            ended_at=ended_at,
            prompt_summary=data.get("prompt_summary", ""),
            outcome=data.get("outcome", "unknown"),
            files_changed=files_changed,
            intent_summary=data.get("intent_summary", ""),
            lessons_learned=lessons_learned,
            contract_fulfilled=bool(data.get("contract_fulfilled", False)),
            iteration_count=int(data.get("iteration_count", 0)),
        )


@dataclass
class CodeChange:
    """Record of what was modified and when.

    Granular history for "what did we change in file X?"
    """

    id: str
    repo_path: str
    session_id: str
    file_path: str
    change_type: str  # "create", "edit", "delete"
    diff_summary: str
    old_content_hash: str | None
    new_content_hash: str
    changed_at: datetime
    contract_step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "repo_path": self.repo_path,
            "session_id": self.session_id,
            "file_path": self.file_path,
            "change_type": self.change_type,
            "diff_summary": self.diff_summary,
            "old_content_hash": self.old_content_hash,
            "new_content_hash": self.new_content_hash,
            "changed_at": self.changed_at.isoformat(),
            "contract_step_id": self.contract_step_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeChange:
        """Deserialize from dictionary."""
        changed_at = data.get("changed_at", "")
        if isinstance(changed_at, str):
            changed_at = datetime.fromisoformat(changed_at)
        return cls(
            id=data["id"],
            repo_path=data["repo_path"],
            session_id=data["session_id"],
            file_path=data["file_path"],
            change_type=data.get("change_type", "edit"),
            diff_summary=data.get("diff_summary", ""),
            old_content_hash=data.get("old_content_hash"),
            new_content_hash=data["new_content_hash"],
            changed_at=changed_at,
            contract_step_id=data.get("contract_step_id"),
        )


@dataclass
class ProjectMemoryContext:
    """Aggregated memory context for prompt injection."""

    relevant_decisions: list[ProjectDecision] = field(default_factory=list)
    applicable_patterns: list[ProjectPattern] = field(default_factory=list)
    recent_corrections: list[UserCorrection] = field(default_factory=list)
    recent_sessions: list[CodingSession] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render as markdown for context injection."""
        sections = []

        if self.relevant_decisions:
            lines = ["## Project Decisions", ""]
            for d in self.relevant_decisions:
                lines.append(f"- **{d.decision}** ({d.scope})")
                if d.rationale:
                    lines.append(f"  _Rationale: {d.rationale}_")
            sections.append("\n".join(lines))

        if self.applicable_patterns:
            lines = ["## Code Patterns", ""]
            for p in self.applicable_patterns:
                lines.append(f"- {p.description} (applies to: {p.applies_to})")
                if p.example_code:
                    lines.append(f"  ```\n  {p.example_code[:200]}\n  ```")
            sections.append("\n".join(lines))

        if self.recent_corrections:
            lines = ["## Learned from Corrections", ""]
            for c in self.recent_corrections[:5]:
                lines.append(f"- {c.inferred_rule} (from {c.file_path})")
            sections.append("\n".join(lines))

        if self.recent_sessions:
            lines = ["## Recent Work", ""]
            for s in self.recent_sessions[:3]:
                status = "completed" if s.contract_fulfilled else s.outcome
                lines.append(f"- {s.prompt_summary[:80]}... ({status})")
            sections.append("\n".join(lines))

        return "\n\n".join(sections) if sections else ""

    def is_empty(self) -> bool:
        """Check if context has any content."""
        return not (
            self.relevant_decisions
            or self.applicable_patterns
            or self.recent_corrections
            or self.recent_sessions
        )


# =============================================================================
# ProjectMemoryStore
# =============================================================================


class ProjectMemoryStore:
    """Manages long-term project memory for Code Mode.

    Provides:
    - Storage of decisions, patterns, corrections, sessions, changes
    - Retrieval of relevant context for prompts
    - Learning from user corrections
    """

    # Stopwords for keyword extraction
    STOPWORDS = frozenset({
        "the", "a", "an", "is", "are", "to", "for", "in", "on", "with",
        "and", "or", "of", "that", "this", "it", "be", "as", "at", "by",
        "from", "has", "have", "had", "not", "but", "what", "all", "were",
        "we", "when", "your", "can", "said", "there", "use", "each", "which",
        "she", "he", "do", "how", "their", "if", "will", "up", "other", "about",
    })

    def __init__(self, db: Database) -> None:
        """Initialize the memory store.

        Args:
            db: Database instance for storage
        """
        self.db = db

    # -------------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------------

    def get_relevant_context(
        self,
        repo_path: str,
        prompt: str,
        file_paths: list[str] | None = None,
        max_decisions: int = 5,
        max_patterns: int = 5,
        max_corrections: int = 3,
        max_sessions: int = 3,
    ) -> ProjectMemoryContext:
        """Retrieve relevant memory context for a prompt.

        This is the main entry point for Code Mode integration.

        Args:
            repo_path: Repository path to search
            prompt: User's prompt for keyword extraction
            file_paths: Optional file paths for pattern matching
            max_decisions: Maximum decisions to return
            max_patterns: Maximum patterns to return
            max_corrections: Maximum corrections to return
            max_sessions: Maximum sessions to return

        Returns:
            ProjectMemoryContext with relevant memories
        """
        keywords = self._extract_keywords(prompt)

        decisions = self._find_decisions(repo_path, keywords, file_paths, max_decisions)
        patterns = self._find_patterns(repo_path, file_paths, max_patterns)
        corrections = self._find_corrections(repo_path, file_paths, max_corrections)
        sessions = self._find_recent_sessions(repo_path, max_sessions)

        return ProjectMemoryContext(
            relevant_decisions=decisions,
            applicable_patterns=patterns,
            recent_corrections=corrections,
            recent_sessions=sessions,
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract searchable keywords from text."""
        words = text.lower().split()
        keywords = []
        for word in words:
            # Clean punctuation
            clean = "".join(c for c in word if c.isalnum())
            if len(clean) > 2 and clean not in self.STOPWORDS:
                keywords.append(clean)
        return keywords[:20]

    def _find_decisions(
        self,
        repo_path: str,
        keywords: list[str],
        file_paths: list[str] | None,
        limit: int,
    ) -> list[ProjectDecision]:
        """Find decisions relevant to the current context."""
        conn = self.db.connect()

        query = """
            SELECT * FROM project_decisions
            WHERE repo_path = ?
              AND superseded_by IS NULL
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """

        rows = conn.execute(query, (repo_path, limit * 3)).fetchall()

        # Score and filter by keyword relevance
        scored = []
        for row in rows:
            row_dict = dict(row)
            keywords_json = row_dict.get("keywords", "[]")
            try:
                row_keywords = json.loads(keywords_json) if keywords_json else []
            except json.JSONDecodeError:
                row_keywords = []

            # Score by keyword overlap
            overlap = len(set(keywords) & {k.lower() for k in row_keywords})
            if overlap > 0 or not keywords:
                scored.append((overlap, ProjectDecision.from_dict(row_dict)))

        scored.sort(key=lambda x: (-x[0], -x[1].confidence))
        return [d for _, d in scored[:limit]]

    def _find_patterns(
        self,
        repo_path: str,
        file_paths: list[str] | None,
        limit: int,
    ) -> list[ProjectPattern]:
        """Find patterns applicable to the file paths."""
        conn = self.db.connect()

        query = """
            SELECT * FROM project_patterns
            WHERE repo_path = ?
            ORDER BY occurrence_count DESC, last_seen_at DESC
            LIMIT ?
        """
        rows = conn.execute(query, (repo_path, limit * 3)).fetchall()

        if not file_paths:
            return [ProjectPattern.from_dict(dict(r)) for r in rows[:limit]]

        # Filter by glob pattern match
        results = []
        for row in rows:
            pattern = ProjectPattern.from_dict(dict(row))
            if any(fnmatch.fnmatch(fp, pattern.applies_to) for fp in file_paths):
                results.append(pattern)
            if len(results) >= limit:
                break

        return results

    def _find_corrections(
        self,
        repo_path: str,
        file_paths: list[str] | None,
        limit: int,
    ) -> list[UserCorrection]:
        """Find corrections relevant to file paths or recent."""
        conn = self.db.connect()

        if file_paths:
            placeholders = ",".join("?" * len(file_paths))
            query = f"""
                SELECT * FROM user_corrections
                WHERE repo_path = ?
                  AND file_path IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = conn.execute(query, (repo_path, *file_paths, limit)).fetchall()
        else:
            query = """
                SELECT * FROM user_corrections
                WHERE repo_path = ?
                ORDER BY created_at DESC
                LIMIT ?
            """
            rows = conn.execute(query, (repo_path, limit)).fetchall()

        return [UserCorrection.from_dict(dict(r)) for r in rows]

    def _find_recent_sessions(
        self,
        repo_path: str,
        limit: int,
    ) -> list[CodingSession]:
        """Get recent coding sessions for context."""
        conn = self.db.connect()

        query = """
            SELECT * FROM coding_sessions
            WHERE repo_path = ?
            ORDER BY started_at DESC
            LIMIT ?
        """
        rows = conn.execute(query, (repo_path, limit)).fetchall()
        return [CodingSession.from_dict(dict(r)) for r in rows]

    # -------------------------------------------------------------------------
    # Recording
    # -------------------------------------------------------------------------

    def add_decision(
        self,
        repo_path: str,
        decision: str,
        rationale: str = "",
        scope: str = "global",
        keywords: list[str] | None = None,
        source: str = "user_explicit",
        confidence: float = 1.0,
    ) -> ProjectDecision:
        """Add a project decision.

        Args:
            repo_path: Repository this applies to
            decision: The decision text
            rationale: Why this decision was made
            scope: Scope of the decision
            keywords: Keywords for retrieval (extracted if not provided)
            source: How this decision was created
            confidence: Confidence level (0-1)

        Returns:
            The created ProjectDecision
        """
        if keywords is None:
            keywords = self._extract_keywords(decision)

        d = ProjectDecision(
            id=_generate_id("decision"),
            repo_path=repo_path,
            decision=decision,
            rationale=rationale,
            scope=scope,
            keywords=keywords,
            source=source,
            confidence=confidence,
            created_at=datetime.now(timezone.utc),
        )

        conn = self.db.connect()
        conn.execute(
            """
            INSERT INTO project_decisions
            (id, repo_path, decision, rationale, scope, keywords, source, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d.id,
                d.repo_path,
                d.decision,
                d.rationale,
                d.scope,
                json.dumps(d.keywords),
                d.source,
                d.confidence,
                d.created_at.isoformat(),
            ),
        )
        conn.commit()

        logger.info("Added decision: %s", d.decision[:50])
        return d

    def add_pattern(
        self,
        repo_path: str,
        pattern_type: str,
        description: str,
        applies_to: str = "*",
        example_code: str | None = None,
        source: str = "detected",
    ) -> ProjectPattern:
        """Add a project pattern.

        Args:
            repo_path: Repository this applies to
            pattern_type: Type of pattern
            description: Description of the pattern
            applies_to: Glob pattern for file matching
            example_code: Optional code example
            source: How this pattern was discovered

        Returns:
            The created ProjectPattern
        """
        now = datetime.now(timezone.utc)
        p = ProjectPattern(
            id=_generate_id("pattern"),
            repo_path=repo_path,
            pattern_type=pattern_type,
            description=description,
            applies_to=applies_to,
            example_code=example_code,
            source=source,
            occurrence_count=1,
            created_at=now,
            last_seen_at=now,
        )

        conn = self.db.connect()
        conn.execute(
            """
            INSERT INTO project_patterns
            (id, repo_path, pattern_type, description, applies_to, example_code,
             source, occurrence_count, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p.id,
                p.repo_path,
                p.pattern_type,
                p.description,
                p.applies_to,
                p.example_code,
                p.source,
                p.occurrence_count,
                p.created_at.isoformat(),
                p.last_seen_at.isoformat(),
            ),
        )
        conn.commit()

        logger.info("Added pattern: %s", p.description[:50])
        return p

    def record_correction(
        self,
        repo_path: str,
        session_id: str,
        file_path: str,
        original_code: str,
        corrected_code: str,
        correction_type: str = "unknown",
        inferred_rule: str = "",
    ) -> UserCorrection:
        """Record a user correction.

        Args:
            repo_path: Repository path
            session_id: Coding session ID
            file_path: File that was corrected
            original_code: What AI generated
            corrected_code: What user changed it to
            correction_type: Type of correction
            inferred_rule: Rule inferred from correction

        Returns:
            The created UserCorrection
        """
        c = UserCorrection(
            id=_generate_id("correction"),
            repo_path=repo_path,
            session_id=session_id,
            original_code=original_code[:2000],  # Truncate
            corrected_code=corrected_code[:2000],
            file_path=file_path,
            correction_type=correction_type,
            inferred_rule=inferred_rule,
            created_at=datetime.now(timezone.utc),
        )

        conn = self.db.connect()
        conn.execute(
            """
            INSERT INTO user_corrections
            (id, repo_path, session_id, original_code, corrected_code, file_path,
             correction_type, inferred_rule, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.id,
                c.repo_path,
                c.session_id,
                c.original_code,
                c.corrected_code,
                c.file_path,
                c.correction_type,
                c.inferred_rule,
                c.created_at.isoformat(),
            ),
        )
        conn.commit()

        logger.info("Recorded correction in %s: %s", c.file_path, c.inferred_rule[:50])
        return c

    def record_session(
        self,
        session_id: str,
        repo_path: str,
        prompt_summary: str,
        started_at: datetime,
        ended_at: datetime | None = None,
        outcome: str = "completed",
        files_changed: list[str] | None = None,
        intent_summary: str = "",
        lessons_learned: list[str] | None = None,
        contract_fulfilled: bool = False,
        iteration_count: int = 0,
    ) -> CodingSession:
        """Record a coding session.

        Args:
            session_id: Session ID
            repo_path: Repository path
            prompt_summary: Summary of user's request
            started_at: When session started
            ended_at: When session ended
            outcome: Session outcome
            files_changed: List of changed files
            intent_summary: Summary of discovered intent
            lessons_learned: Lessons from this session
            contract_fulfilled: Whether contract was met
            iteration_count: Number of loop iterations

        Returns:
            The created CodingSession
        """
        s = CodingSession(
            id=session_id,
            repo_path=repo_path,
            started_at=started_at,
            ended_at=ended_at,
            prompt_summary=prompt_summary[:200],
            outcome=outcome,
            files_changed=files_changed or [],
            intent_summary=intent_summary,
            lessons_learned=lessons_learned or [],
            contract_fulfilled=contract_fulfilled,
            iteration_count=iteration_count,
        )

        conn = self.db.connect()
        conn.execute(
            """
            INSERT INTO coding_sessions
            (id, repo_path, started_at, ended_at, prompt_summary, outcome,
             files_changed, intent_summary, lessons_learned, contract_fulfilled, iteration_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.id,
                s.repo_path,
                s.started_at.isoformat(),
                s.ended_at.isoformat() if s.ended_at else None,
                s.prompt_summary,
                s.outcome,
                json.dumps(s.files_changed),
                s.intent_summary,
                json.dumps(s.lessons_learned),
                1 if s.contract_fulfilled else 0,
                s.iteration_count,
            ),
        )
        conn.commit()

        logger.info("Recorded session: %s", s.prompt_summary[:50])
        return s

    def record_change(
        self,
        repo_path: str,
        session_id: str,
        file_path: str,
        change_type: str,
        diff_summary: str,
        new_content_hash: str,
        old_content_hash: str | None = None,
        contract_step_id: str | None = None,
    ) -> CodeChange:
        """Record a code change.

        Args:
            repo_path: Repository path
            session_id: Coding session ID
            file_path: File that was changed
            change_type: Type of change ("create", "edit", "delete")
            diff_summary: Summary of the change
            new_content_hash: Hash of new content
            old_content_hash: Hash of old content (if edit)
            contract_step_id: Contract step that caused this

        Returns:
            The created CodeChange
        """
        c = CodeChange(
            id=_generate_id("change"),
            repo_path=repo_path,
            session_id=session_id,
            file_path=file_path,
            change_type=change_type,
            diff_summary=diff_summary[:500],
            old_content_hash=old_content_hash,
            new_content_hash=new_content_hash,
            changed_at=datetime.now(timezone.utc),
            contract_step_id=contract_step_id,
        )

        conn = self.db.connect()
        conn.execute(
            """
            INSERT INTO code_changes
            (id, repo_path, session_id, file_path, change_type, diff_summary,
             old_content_hash, new_content_hash, changed_at, contract_step_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c.id,
                c.repo_path,
                c.session_id,
                c.file_path,
                c.change_type,
                c.diff_summary,
                c.old_content_hash,
                c.new_content_hash,
                c.changed_at.isoformat(),
                c.contract_step_id,
            ),
        )
        conn.commit()

        return c

    # -------------------------------------------------------------------------
    # Learning
    # -------------------------------------------------------------------------

    def promote_correction_to_decision(
        self,
        correction_id: str,
    ) -> ProjectDecision:
        """Promote a user correction to a project decision.

        Called when the same correction appears multiple times
        or when user explicitly confirms a rule.

        Args:
            correction_id: ID of the correction to promote

        Returns:
            The created ProjectDecision
        """
        conn = self.db.connect()

        row = conn.execute(
            "SELECT * FROM user_corrections WHERE id = ?",
            (correction_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"Correction not found: {correction_id}")

        correction = UserCorrection.from_dict(dict(row))

        decision = self.add_decision(
            repo_path=correction.repo_path,
            decision=correction.inferred_rule,
            rationale=f"Learned from user correction on {correction.file_path}",
            scope="global",
            source="correction",
            confidence=0.8,
        )

        # Mark correction as promoted
        conn.execute(
            "UPDATE user_corrections SET promoted_to_decision = ? WHERE id = ?",
            (decision.id, correction_id),
        )
        conn.commit()

        logger.info("Promoted correction %s to decision %s", correction_id, decision.id)
        return decision

    def supersede_decision(
        self,
        old_decision_id: str,
        new_decision_id: str,
    ) -> None:
        """Mark a decision as superseded by a newer one.

        Args:
            old_decision_id: ID of the old decision
            new_decision_id: ID of the new decision that replaces it
        """
        conn = self.db.connect()
        conn.execute(
            "UPDATE project_decisions SET superseded_by = ? WHERE id = ?",
            (new_decision_id, old_decision_id),
        )
        conn.commit()

    def increment_pattern_count(self, pattern_id: str) -> None:
        """Increment occurrence count for a pattern.

        Args:
            pattern_id: ID of the pattern
        """
        conn = self.db.connect()
        conn.execute(
            """
            UPDATE project_patterns
            SET occurrence_count = occurrence_count + 1,
                last_seen_at = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), pattern_id),
        )
        conn.commit()

    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------

    def get_decision(self, decision_id: str) -> ProjectDecision | None:
        """Get a decision by ID."""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM project_decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        return ProjectDecision.from_dict(dict(row)) if row else None

    def get_pattern(self, pattern_id: str) -> ProjectPattern | None:
        """Get a pattern by ID."""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM project_patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()
        return ProjectPattern.from_dict(dict(row)) if row else None

    def get_session(self, session_id: str) -> CodingSession | None:
        """Get a session by ID."""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM coding_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return CodingSession.from_dict(dict(row)) if row else None

    def list_decisions(
        self,
        repo_path: str,
        include_superseded: bool = False,
    ) -> list[ProjectDecision]:
        """List all decisions for a repository."""
        conn = self.db.connect()
        if include_superseded:
            query = "SELECT * FROM project_decisions WHERE repo_path = ? ORDER BY created_at DESC"
            rows = conn.execute(query, (repo_path,)).fetchall()
        else:
            query = "SELECT * FROM project_decisions WHERE repo_path = ? AND superseded_by IS NULL ORDER BY created_at DESC"
            rows = conn.execute(query, (repo_path,)).fetchall()
        return [ProjectDecision.from_dict(dict(r)) for r in rows]

    def list_patterns(self, repo_path: str) -> list[ProjectPattern]:
        """List all patterns for a repository."""
        conn = self.db.connect()
        query = "SELECT * FROM project_patterns WHERE repo_path = ? ORDER BY occurrence_count DESC"
        rows = conn.execute(query, (repo_path,)).fetchall()
        return [ProjectPattern.from_dict(dict(r)) for r in rows]

    def list_sessions(
        self,
        repo_path: str,
        limit: int = 20,
    ) -> list[CodingSession]:
        """List recent sessions for a repository."""
        conn = self.db.connect()
        query = "SELECT * FROM coding_sessions WHERE repo_path = ? ORDER BY started_at DESC LIMIT ?"
        rows = conn.execute(query, (repo_path, limit)).fetchall()
        return [CodingSession.from_dict(dict(r)) for r in rows]

    def get_file_history(
        self,
        repo_path: str,
        file_path: str,
        limit: int = 20,
    ) -> list[CodeChange]:
        """Get change history for a file."""
        conn = self.db.connect()
        query = """
            SELECT * FROM code_changes
            WHERE repo_path = ? AND file_path = ?
            ORDER BY changed_at DESC
            LIMIT ?
        """
        rows = conn.execute(query, (repo_path, file_path, limit)).fetchall()
        return [CodeChange.from_dict(dict(r)) for r in rows]
