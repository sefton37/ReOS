"""RPC handlers for ReOS telemetry — event writes and named analysis queries.

Two handlers:

  handle_reos_telemetry_event  — write a single event (fire-and-forget)
  handle_reos_telemetry_query  — run a named read-only analysis query

The query handler uses a registry of pre-approved SELECT statements. It never
executes raw SQL from the frontend. The ``params`` dict provides safe binding
values for parameterised queries (e.g., ``{"days": 7}``).

The ``db`` parameter is the Cairn Database object passed by the dispatch
framework. Telemetry uses its own separate SQLite connection via
``reos.telemetry.get_connection()``, so ``db`` is unused but must be accepted
for dispatch compatibility — identical pattern to ``handle_reos_vitals``.

Note on __session: the dispatch framework injects ``__session`` into params.
Both handlers accept ``**params`` and simply ignore unknown keys.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Named query registry — never raw SQL from the frontend.
# ---------------------------------------------------------------------------

_QUERIES: dict[str, str] = {
    # Success rate, retry rate, and average latency per model.
    "model_comparison": """
        SELECT
            json_extract(payload_json, '$.model_name')     AS model,
            COUNT(*)                                        AS total_proposals,
            SUM(json_extract(payload_json, '$.success'))   AS successes,
            ROUND(
                100.0 * SUM(json_extract(payload_json, '$.success')) / COUNT(*), 1
            )                                               AS success_pct,
            SUM(
                CASE WHEN json_extract(payload_json, '$.attempt_count') = 2
                     THEN 1 ELSE 0 END
            )                                               AS retries,
            ROUND(AVG(json_extract(payload_json, '$.latency_ms')), 0) AS avg_latency_ms
        FROM reos_events
        WHERE event_type = 'proposal_generated'
          AND ts > (strftime('%s','now') - :days * 86400) * 1000
        GROUP BY model
        ORDER BY success_pct DESC, avg_latency_ms ASC
    """,

    # p50 / p95 / max latency per model for successful proposals.
    "latency_percentiles": """
        WITH ranked AS (
            SELECT
                json_extract(payload_json, '$.model_name') AS model,
                json_extract(payload_json, '$.latency_ms') AS latency_ms,
                ROW_NUMBER() OVER (
                    PARTITION BY json_extract(payload_json, '$.model_name')
                    ORDER BY json_extract(payload_json, '$.latency_ms')
                ) AS rn,
                COUNT(*) OVER (
                    PARTITION BY json_extract(payload_json, '$.model_name')
                ) AS total
            FROM reos_events
            WHERE event_type = 'proposal_generated'
              AND json_extract(payload_json, '$.success') = 1
              AND ts > (strftime('%s','now') - :days * 86400) * 1000
        )
        SELECT
            model,
            MAX(CASE WHEN rn <= total * 0.50 THEN latency_ms END) AS p50_ms,
            MAX(CASE WHEN rn <= total * 0.95 THEN latency_ms END) AS p95_ms,
            MAX(latency_ms)                                        AS max_ms
        FROM ranked
        GROUP BY model
        ORDER BY p50_ms
    """,

    # Sessions where error_detected fired but no proposal_generated followed
    # within 10 seconds on the same trace_id.
    "false_negative_rate": """
        WITH detections AS (
            SELECT session_id, trace_id, ts AS detected_at
            FROM reos_events WHERE event_type = 'error_detected'
        ),
        proposals AS (
            SELECT session_id, trace_id, ts AS proposed_at
            FROM reos_events WHERE event_type = 'proposal_generated'
        )
        SELECT
            d.session_id,
            d.trace_id,
            d.detected_at,
            p.proposed_at,
            (p.proposed_at - d.detected_at) AS pipeline_ms
        FROM detections d
        LEFT JOIN proposals p
            ON d.session_id = p.session_id AND d.trace_id = p.trace_id
        WHERE p.proposed_at IS NULL
           OR (p.proposed_at - d.detected_at) > 10000
    """,

    # Run / Edit / Dismiss breakdown with average card display duration.
    "user_action_distribution": """
        SELECT
            json_extract(payload_json, '$.action')          AS action,
            COUNT(*)                                        AS count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct,
            ROUND(AVG(json_extract(payload_json, '$.card_display_duration_ms')), 0)
                                                            AS avg_display_ms
        FROM reos_events
        WHERE event_type = 'user_action'
          AND ts > (strftime('%s','now') - :days * 86400) * 1000
        GROUP BY action
    """,

    # Most recent N sessions with event counts.
    "recent_sessions": """
        SELECT
            session_id,
            MIN(ts)     AS started_at,
            MAX(ts)     AS ended_at,
            COUNT(*)    AS event_count
        FROM reos_events
        WHERE session_id != 'backend'
        GROUP BY session_id
        ORDER BY started_at DESC
        LIMIT :limit
    """,

    # Full pipeline history for one trace_id (primary debugging query).
    "trace_replay": """
        SELECT ts, event_type, payload_json
        FROM reos_events
        WHERE trace_id = :trace_id
        ORDER BY ts ASC
    """,
}

# Default parameter values for queries that need them.
_QUERY_DEFAULTS: dict[str, dict[str, Any]] = {
    "model_comparison": {"days": 30},
    "latency_percentiles": {"days": 30},
    "false_negative_rate": {},
    "user_action_distribution": {"days": 30},
    "recent_sessions": {"limit": 20},
    "trace_replay": {"trace_id": ""},
}


def handle_reos_telemetry_event(db: Any = None, **params: Any) -> dict[str, Any]:
    """Write a single telemetry event. Fire-and-forget — always returns success.

    Parameters (all extracted from ``params``):
        session_id : str  — session UUID
        trace_id   : str  — proposal-pipeline UUID
        ts         : int  — epoch milliseconds (set by frontend for accuracy)
        event_type : str  — event taxonomy discriminator
        payload    : dict — type-specific fields
    """
    from reos.telemetry import record_event

    # Silently ignore __session and other dispatch-injected keys.
    session_id: str = params.get("session_id", "")
    trace_id: str = params.get("trace_id", "")
    ts: int = params.get("ts", 0)
    event_type: str = params.get("event_type", "")
    payload: dict = params.get("payload", {})

    record_event(
        session_id=session_id,
        trace_id=trace_id,
        ts=ts,
        event_type=event_type,
        payload=payload if isinstance(payload, dict) else {},
    )
    return {"success": True}


def handle_reos_telemetry_query(db: Any = None, **params: Any) -> dict[str, Any]:
    """Run a named analysis query and return rows.

    Parameters (all extracted from ``params``):
        query  : str  — name from the ``_QUERIES`` registry
        params : dict — binding values for the SQL (e.g., ``{"days": 7}``)

    Returns:
        {"rows": [...], "columns": [...]}  on success
        {"rows": [], "columns": [], "error": "..."} on failure

    Raises ValueError for unknown query names (not raw SQL execution).
    """
    import json as _json

    from reos.telemetry import get_connection

    query_name: str = params.get("query", "")
    query_params: dict = params.get("params", {})

    if query_name not in _QUERIES:
        known = sorted(_QUERIES.keys())
        raise ValueError(f"Unknown telemetry query '{query_name}'. Known: {known}")

    sql = _QUERIES[query_name]

    # Merge caller params over defaults so callers can omit optional params.
    defaults = _QUERY_DEFAULTS.get(query_name, {})
    merged_params: dict[str, Any] = {**defaults, **(query_params if isinstance(query_params, dict) else {})}

    try:
        conn = get_connection()
        cursor = conn.execute(sql, merged_params)
        columns = [description[0] for description in cursor.description]
        rows = []
        for row in cursor.fetchall():
            row_dict: dict[str, Any] = {}
            for col, val in zip(columns, row):
                # Attempt to parse payload_json fields for easier consumption.
                if col == "payload_json" and isinstance(val, str):
                    try:
                        val = _json.loads(val)
                    except Exception:
                        pass
                row_dict[col] = val
            rows.append(row_dict)
        return {"rows": rows, "columns": columns}
    except Exception as exc:
        logger.warning("Telemetry query '%s' failed: %s", query_name, exc)
        return {"rows": [], "columns": [], "error": str(exc)}
