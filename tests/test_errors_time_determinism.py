from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reos.db import get_db
from reos.errors import record_error


def test_record_error_dedupe_boundary_is_deterministic(
    isolated_db_singleton,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import reos.errors as errors_mod

    # Avoid cross-test interference.
    errors_mod._RECENT_SIGNATURES.clear()

    t0 = datetime(2025, 12, 19, 0, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(errors_mod, "_utcnow", lambda: t0)

    db = get_db()
    first = record_error(
        source="reos",
        operation="determinism",
        exc=ValueError("same"),
        db=db,
        dedupe_window_seconds=60,
        include_traceback=False,
    )
    assert first is not None

    # Within dedupe window (t0 + 59s) => suppressed.
    t1 = t0 + timedelta(seconds=59)
    monkeypatch.setattr(errors_mod, "_utcnow", lambda: t1)
    second = record_error(
        source="reos",
        operation="determinism",
        exc=ValueError("same"),
        db=db,
        dedupe_window_seconds=60,
        include_traceback=False,
    )
    assert second is None

    # After window (t0 + 61s) => stored.
    t2 = t0 + timedelta(seconds=61)
    monkeypatch.setattr(errors_mod, "_utcnow", lambda: t2)
    third = record_error(
        source="reos",
        operation="determinism",
        exc=ValueError("same"),
        db=db,
        dedupe_window_seconds=60,
        include_traceback=False,
    )
    assert third is not None

    rows = db.iter_events_recent(limit=10)
    assert sum(1 for r in rows if r.get("kind") == "error") == 2
