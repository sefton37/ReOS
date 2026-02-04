from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from .alignment import get_default_repo_path, get_review_context_budget, is_git_repo
from .db import Database, get_db
from .models import Event
from .settings import settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def append_event(event: Event) -> str:
    """Store an event to SQLite; fallback to JSONL for debugging."""
    db = get_db()
    event_id = str(uuid.uuid4())

    # Try SQLite first
    try:
        db.insert_event(
            event_id=event_id,
            source=event.source,
            kind=event.payload_metadata.get("kind") if event.payload_metadata else None,
            ts=event.ts.isoformat(),
            payload_metadata=json.dumps(event.payload_metadata) if event.payload_metadata else None,
            note=event.note,
        )
        return event_id
    except Exception as exc:
        # Fallback to JSONL for debugging/recovery
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "id": event_id,
            "source": event.source,
            "ts": event.ts.isoformat(),
            "payload_metadata": event.payload_metadata,
            "note": event.note,
            "error": f"SQLite failed, fell back to JSONL: {str(exc)}",
        }
        with settings.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")
        return event_id


def _maybe_emit_review_trigger(
    *,
    db: Database,
    recent_event_payload: dict[str, object] | None,
) -> None:
    """Insert a review-trigger event if context budget is nearing capacity.

    This runs during ingestion so triggers can happen in the background.
    The trigger is throttled by a cooldown to avoid spamming.
    """

    try:
        repo_path = get_default_repo_path()
        if repo_path is None:
            return

        if not is_git_repo(repo_path):
            return

        roadmap_path = repo_path / "docs" / "tech-roadmap.md"
        charter_path = repo_path / "ReOS_charter.md"

        budget = get_review_context_budget(
            repo_path=repo_path,
            roadmap_path=roadmap_path,
            charter_path=charter_path,
        )

        if not budget.should_trigger:
            return

        # Throttle based on most recent triggers in DB.
        cooldown = timedelta(minutes=max(1, settings.review_trigger_cooldown_minutes))
        now = _utcnow()
        for evt in db.iter_events_recent(limit=200):
            if evt.get("kind") != "review_trigger":
                continue
            try:
                ts = datetime.fromisoformat(str(evt.get("ts")))
            except Exception as e:
                logger.debug(
                    "Failed to parse timestamp for event %s: %s",
                    evt.get("id", "unknown"),
                    e,
                )
                continue
            if now - ts < cooldown:
                return

        trigger_id = str(uuid.uuid4())
        trigger_ts = now.isoformat()
        payload = {
            "kind": "review_trigger",
            "repo": str(repo_path),
            "context_limit_tokens": budget.context_limit_tokens,
            "estimated_total_tokens": budget.total_tokens,
            "utilization": budget.utilization,
            "trigger_ratio": budget.trigger_ratio,
            "breakdown": {
                "roadmap_tokens": budget.roadmap_tokens,
                "charter_tokens": budget.charter_tokens,
                "changes_tokens": budget.changes_tokens,
                "overhead_tokens": budget.overhead_tokens,
            },
            "note": (
                "Estimated review context is nearing the configured limit. "
                "Consider running an alignment review to checkpoint before adding more context."
            ),
        }

        # Insert directly to avoid recursive trigger loops.
        db.insert_event(
            event_id=trigger_id,
            source="reos",
            kind="review_trigger",
            ts=trigger_ts,
            payload_metadata=json.dumps(payload),
            note="Review checkpoint suggested (context budget nearing limit)",
        )
    except Exception as e:
        # Best-effort only; ingestion should not fail if budgeting fails.
        logger.debug("Review trigger emission failed (non-critical): %s", e)
        return


def iter_events(limit: int | None = None) -> Iterable[tuple[str, Event]]:
    """Yield events from SQLite storage (newest first)."""
    db = get_db()
    rows = db.iter_events_recent(limit=limit or 1000)

    for row in rows:
        try:
            payload = None
            payload_metadata = row["payload_metadata"]
            if payload_metadata:
                payload = json.loads(str(payload_metadata))

            ts_str = row["ts"]
            # Parse the ISO format timestamp back to datetime
            from datetime import datetime

            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))

            evt = Event(
                source=str(row["source"]),
                ts=ts,
                payload_metadata=payload,
                note=str(row["note"]) if row["note"] else None,
            )
            event_id = str(row["id"])
            yield event_id, evt
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(
                "Skipping malformed event (id=%s): %s",
                row.get("id", "unknown"),
                e,
            )
            continue
