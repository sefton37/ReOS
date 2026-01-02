from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from .settings import settings


class Database:
    """Local SQLite database for ReOS events, sessions, and classifications."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.data_dir / "reos.db"
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        """Open or return an existing connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # Enable foreign key constraints for cascading deletes
        conn.execute("PRAGMA foreign_keys = ON")
        self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close the database connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _execute(self, query: str, params: tuple[object, ...] | None = None) -> sqlite3.Cursor:
        """Execute a query and return the cursor."""
        conn = self.connect()
        if params is None:
            return conn.execute(query)
        return conn.execute(query, params)

    def migrate(self) -> None:
        """Create tables if they don't exist."""
        conn = self.connect()

        # Events table: raw ingested metadata-only events (git snapshots, checkpoints, etc.)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                kind TEXT,
                ts TEXT NOT NULL,
                payload_metadata TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )

        # Sessions table: logical groupings of attention (by repo/folder + time window)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                workspace_folder TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                event_count INTEGER DEFAULT 0,
                switch_count INTEGER DEFAULT 0,
                coherence_score REAL,
                revolution_phase TEXT,
                evolution_phase TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        # Classifications table: explainable labels (fragmentation, frayed mind, etc.)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classifications (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                kind TEXT NOT NULL,
                severity TEXT,
                explanation TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )

        # Audit log: all mutations with context (for transparency + replay).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                before_state TEXT,
                after_state TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )

        # Discovered git repositories (metadata-only).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repos (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                remote_summary TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )

        # App state: small key/value store for local UI + tool coordination.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

        # Agent personas: saved system prompt/context + a few knobs.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_personas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                system_prompt TEXT NOT NULL,
                default_context TEXT NOT NULL,
                temperature REAL NOT NULL,
                top_p REAL NOT NULL,
                tool_call_limit INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )

        # ========================================================================
        # User Presence Tables
        # ========================================================================

        # Users table: core user identity (unencrypted metadata)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # User credentials: password hash and key derivation salt
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                key_salt TEXT NOT NULL,
                recovery_phrase_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        # User encrypted data: bio and other sensitive info (encrypted at rest)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_encrypted_data (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                data_type TEXT NOT NULL,
                encrypted_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, data_type)
            )
            """
        )

        # User sessions: active authentication sessions
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_valid INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        # Create indexes for performance
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_credentials_user_id ON user_credentials(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_encrypted_data_user_id ON user_encrypted_data(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at)"
        )

        conn.commit()

    def set_active_persona_id(self, *, persona_id: str | None) -> None:
        """Set the active agent persona id."""
        self.set_state(key="active_persona_id", value=persona_id)

    def get_active_persona_id(self) -> str | None:
        """Get the active agent persona id."""
        return self.get_state(key="active_persona_id")

    def upsert_agent_persona(
        self,
        *,
        persona_id: str,
        name: str,
        system_prompt: str,
        default_context: str,
        temperature: float,
        top_p: float,
        tool_call_limit: int,
    ) -> None:
        """Insert or update an agent persona by id.

        Name is unique; if a different persona already uses the name, SQLite will raise.
        """

        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO agent_personas
            (id, name, system_prompt, default_context, temperature, top_p, tool_call_limit,
             created_at, updated_at, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                system_prompt = excluded.system_prompt,
                default_context = excluded.default_context,
                temperature = excluded.temperature,
                top_p = excluded.top_p,
                tool_call_limit = excluded.tool_call_limit,
                updated_at = excluded.updated_at,
                ingested_at = excluded.ingested_at
            """,
            (
                persona_id,
                name,
                system_prompt,
                default_context,
                float(temperature),
                float(top_p),
                int(tool_call_limit),
                now,
                now,
                now,
            ),
        )
        self.connect().commit()

    def get_agent_persona(self, *, persona_id: str) -> dict[str, object] | None:
        row = self._execute(
            "SELECT * FROM agent_personas WHERE id = ?",
            (persona_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def iter_agent_personas(self) -> list[dict[str, object]]:
        rows = self._execute(
            "SELECT * FROM agent_personas ORDER BY name ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def set_state(self, *, key: str, value: str | None) -> None:
        """Set a small piece of app state."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO app_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self.connect().commit()

    def get_state(self, *, key: str) -> str | None:
        """Get a small piece of app state."""
        row = self._execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return row["value"]
        return str(row[0]) if row[0] is not None else None

    def upsert_repo(self, *, repo_id: str, path: str, remote_summary: str | None = None) -> None:
        """Insert or update a discovered repo by path."""
        now = datetime.now(UTC).isoformat()

        row = self._execute("SELECT id, first_seen_at FROM repos WHERE path = ?", (path,)).fetchone()
        if row is None:
            self._execute(
                """
                INSERT INTO repos
                (id, path, remote_summary, first_seen_at, last_seen_at, created_at, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (repo_id, path, remote_summary, now, now, now, now),
            )
        else:
            existing_id = str(row["id"]) if isinstance(row, sqlite3.Row) else str(row[0])
            self._execute(
                """
                UPDATE repos
                SET remote_summary = COALESCE(?, remote_summary),
                    last_seen_at = ?,
                    ingested_at = ?
                WHERE id = ?
                """,
                (remote_summary, now, now, existing_id),
            )

        self.connect().commit()

    def iter_repos(self) -> list[dict[str, object]]:
        """Return discovered repos (most recently seen first)."""
        rows = self._execute(
            "SELECT * FROM repos ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_repo_path(self, *, repo_id: str) -> str | None:
        """Resolve a discovered repo's path by id."""

        row = self._execute("SELECT path FROM repos WHERE id = ?", (repo_id,)).fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            val = row["path"]
            return str(val) if val is not None else None
        return str(row[0]) if row[0] is not None else None

    def insert_event(
        self,
        event_id: str,
        source: str,
        kind: str | None,
        ts: str,
        payload_metadata: str | None,
        note: str | None,
    ) -> None:
        """Insert an event into the database."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO events
            (id, source, kind, ts, payload_metadata, note, created_at, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, source, kind, ts, payload_metadata, note, now, now),
        )
        self.connect().commit()

    def iter_events_recent(self, limit: int | None = None) -> list[dict[str, object]]:
        """Retrieve recent events from the database."""
        if limit is None:
            limit = 1000

        rows = self._execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]

    def insert_session(
        self,
        session_id: str,
        workspace_folder: str | None,
        started_at: str,
        event_count: int = 0,
        switch_count: int = 0,
    ) -> None:
        """Insert a session."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO sessions
            (id, workspace_folder, started_at, event_count, switch_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, workspace_folder, started_at, event_count, switch_count, now),
        )
        self.connect().commit()

    def insert_classification(
        self,
        classification_id: str,
        session_id: str | None,
        kind: str,
        severity: str | None,
        explanation: str | None,
    ) -> None:
        """Insert a classification label."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO classifications
            (id, session_id, kind, severity, explanation, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (classification_id, session_id, kind, severity, explanation, now),
        )
        self.connect().commit()

    def iter_classifications_for_session(self, session_id: str) -> list[dict[str, object]]:
        """Get all classifications for a session."""
        rows = self._execute(
            "SELECT * FROM classifications WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ========================================================================
    # User Presence Methods
    # ========================================================================

    def create_user(
        self,
        *,
        user_id: str,
        display_name: str,
    ) -> None:
        """Create a new user record."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO users (id, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, display_name, now, now),
        )
        self.connect().commit()

    def get_user(self, *, user_id: str) -> dict[str, object] | None:
        """Get a user by ID."""
        row = self._execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_display_name(self, *, display_name: str) -> dict[str, object] | None:
        """Get a user by display name (case-insensitive)."""
        row = self._execute(
            "SELECT * FROM users WHERE LOWER(display_name) = LOWER(?)",
            (display_name,),
        ).fetchone()
        return dict(row) if row is not None else None

    def update_user(
        self,
        *,
        user_id: str,
        display_name: str | None = None,
    ) -> None:
        """Update user metadata."""
        now = datetime.now(UTC).isoformat()
        if display_name is not None:
            self._execute(
                """
                UPDATE users SET display_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (display_name, now, user_id),
            )
        self.connect().commit()

    def iter_users(self) -> list[dict[str, object]]:
        """List all users."""
        rows = self._execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def count_users(self) -> int:
        """Count total users."""
        row = self._execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0]) if row else 0

    def create_user_credentials(
        self,
        *,
        credential_id: str,
        user_id: str,
        password_hash: str,
        key_salt: str,
        recovery_phrase_hash: str | None = None,
    ) -> None:
        """Create user credentials."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO user_credentials
            (id, user_id, password_hash, key_salt, recovery_phrase_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (credential_id, user_id, password_hash, key_salt, recovery_phrase_hash, now, now),
        )
        self.connect().commit()

    def get_user_credentials(self, *, user_id: str) -> dict[str, object] | None:
        """Get credentials for a user."""
        row = self._execute(
            "SELECT * FROM user_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def update_user_credentials(
        self,
        *,
        user_id: str,
        password_hash: str | None = None,
        recovery_phrase_hash: str | None = None,
    ) -> None:
        """Update user credentials."""
        now = datetime.now(UTC).isoformat()
        if password_hash is not None:
            self._execute(
                """
                UPDATE user_credentials SET password_hash = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (password_hash, now, user_id),
            )
        if recovery_phrase_hash is not None:
            self._execute(
                """
                UPDATE user_credentials SET recovery_phrase_hash = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (recovery_phrase_hash, now, user_id),
            )
        self.connect().commit()

    def upsert_user_encrypted_data(
        self,
        *,
        data_id: str,
        user_id: str,
        data_type: str,
        encrypted_data: str,
    ) -> None:
        """Insert or update encrypted user data."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO user_encrypted_data
            (id, user_id, data_type, encrypted_data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, data_type) DO UPDATE SET
                encrypted_data = excluded.encrypted_data,
                updated_at = excluded.updated_at
            """,
            (data_id, user_id, data_type, encrypted_data, now, now),
        )
        self.connect().commit()

    def get_user_encrypted_data(
        self,
        *,
        user_id: str,
        data_type: str,
    ) -> dict[str, object] | None:
        """Get encrypted data for a user by type."""
        row = self._execute(
            "SELECT * FROM user_encrypted_data WHERE user_id = ? AND data_type = ?",
            (user_id, data_type),
        ).fetchone()
        return dict(row) if row is not None else None

    def create_user_session(
        self,
        *,
        session_id: str,
        user_id: str,
        expires_at: str,
    ) -> None:
        """Create a new user session."""
        now = datetime.now(UTC).isoformat()
        self._execute(
            """
            INSERT INTO user_sessions (id, user_id, created_at, expires_at, is_valid)
            VALUES (?, ?, ?, ?, 1)
            """,
            (session_id, user_id, now, expires_at),
        )
        self.connect().commit()

    def get_user_session(self, *, session_id: str) -> dict[str, object] | None:
        """Get a session by ID."""
        row = self._execute(
            "SELECT * FROM user_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def invalidate_user_session(self, *, session_id: str) -> None:
        """Invalidate a session."""
        self._execute(
            "UPDATE user_sessions SET is_valid = 0 WHERE id = ?",
            (session_id,),
        )
        self.connect().commit()

    def invalidate_all_user_sessions(self, *, user_id: str) -> None:
        """Invalidate all sessions for a user."""
        self._execute(
            "UPDATE user_sessions SET is_valid = 0 WHERE user_id = ?",
            (user_id,),
        )
        self.connect().commit()

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions. Returns count of deleted sessions."""
        now = datetime.now(UTC).isoformat()
        cursor = self._execute(
            "DELETE FROM user_sessions WHERE expires_at < ? OR is_valid = 0",
            (now,),
        )
        self.connect().commit()
        return cursor.rowcount

    def delete_user(self, *, user_id: str) -> None:
        """Delete a user and all associated data (cascades)."""
        # SQLite foreign key cascades handle the rest
        self._execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.connect().commit()


_db_instance: Database | None = None


def get_db() -> Database:
    """Get or create the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
        _db_instance.migrate()
    return _db_instance

