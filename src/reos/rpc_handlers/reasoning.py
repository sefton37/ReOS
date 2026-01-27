"""Reasoning chain RPC handlers for RLHF feedback system.

These handlers manage reasoning chains and user feedback for training data collection.
Feedback triggers memory learning to strengthen/weaken relationships.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from reos.db import Database
from reos.play import blocks_db
from reos.play.blocks_models import BlockType

from . import RpcError

logger = logging.getLogger(__name__)


def handle_reasoning_feedback(
    _db: Database,
    *,
    chain_block_id: str,
    rating: int,
    comment: str | None = None,
) -> dict[str, Any]:
    """Submit feedback on a reasoning chain.

    Args:
        chain_block_id: ID of the reasoning_chain block
        rating: 1=thumbs down, 5=thumbs up
        comment: Optional qualitative feedback

    Returns:
        Dict with success status
    """
    # Validate rating
    if rating not in (1, 5):
        raise RpcError(code=-32602, message="rating must be 1 (thumbs down) or 5 (thumbs up)")

    # Get the block to verify it exists and is a reasoning_chain
    block = blocks_db.get_block(chain_block_id, include_rich_text=False)
    if not block:
        raise RpcError(code=-32602, message=f"Block not found: {chain_block_id}")

    if block.type != BlockType.REASONING_CHAIN:
        raise RpcError(code=-32602, message=f"Block is not a reasoning_chain: {block.type}")

    # Update block properties with feedback
    feedback_status = "positive" if rating == 5 else "negative"
    feedback_timestamp = datetime.now(timezone.utc).isoformat()

    blocks_db.set_block_property(chain_block_id, "feedback_status", feedback_status)
    blocks_db.set_block_property(chain_block_id, "feedback_rating", rating)
    blocks_db.set_block_property(chain_block_id, "feedback_timestamp", feedback_timestamp)

    if comment:
        blocks_db.set_block_property(chain_block_id, "feedback_comment", comment)

    # Trigger memory learning from feedback
    # This strengthens relationships for positive feedback, weakens for negative
    memory_changes: list[dict[str, Any]] = []
    try:
        from reos.memory import MemoryGraphStore
        from reos.memory.extractor import RelationshipExtractor

        graph_store = MemoryGraphStore()
        extractor = RelationshipExtractor(graph_store=graph_store)
        memory_changes = extractor.extract_from_feedback(
            chain_block_id,
            rating,
            corrected_block_id=None,  # No correction provided via simple UI
        )
        logger.info(
            "Memory learning from feedback: chain=%s rating=%d changes=%d",
            chain_block_id,
            rating,
            len(memory_changes),
        )
    except Exception as e:
        # Don't fail the feedback if memory learning has issues
        logger.warning("Memory learning failed for feedback: %s", e)

    return {
        "ok": True,
        "chain_block_id": chain_block_id,
        "feedback_status": feedback_status,
        "feedback_timestamp": feedback_timestamp,
        "memory_changes": len(memory_changes),
    }


def handle_reasoning_chain_get(
    _db: Database,
    *,
    chain_block_id: str,
) -> dict[str, Any]:
    """Get full reasoning chain with all events for diagnosis.

    Args:
        chain_block_id: ID of the reasoning_chain block

    Returns:
        Dict with full chain data including all events
    """
    # Get the chain block
    block = blocks_db.get_block(chain_block_id, include_rich_text=True)
    if not block:
        raise RpcError(code=-32602, message=f"Block not found: {chain_block_id}")

    if block.type != BlockType.REASONING_CHAIN:
        raise RpcError(code=-32602, message=f"Block is not a reasoning_chain: {block.type}")

    # Load children (the events)
    blocks_db._load_children_recursive(block)

    # Organize children by type
    user_prompt = None
    consciousness_events = []
    llm_response = None

    for child in block.children:
        if child.type == BlockType.USER_PROMPT:
            user_prompt = {
                "block_id": child.id,
                "message_id": child.properties.get("message_id"),
            }
        elif child.type == BlockType.CONSCIOUSNESS_EVENT:
            # Parse metadata if it's a JSON string
            metadata = child.properties.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    pass

            consciousness_events.append({
                "block_id": child.id,
                "position": child.position,
                "event_type": child.properties.get("event_type"),
                "timestamp": child.properties.get("timestamp"),
                "title": child.properties.get("title"),
                "content": child.properties.get("content"),
                "metadata": metadata,
            })
        elif child.type == BlockType.LLM_RESPONSE:
            llm_response = {
                "block_id": child.id,
                "message_id": child.properties.get("message_id"),
            }

    # Sort consciousness events by position
    consciousness_events.sort(key=lambda e: e["position"])

    return {
        "chain_block_id": chain_block_id,
        "conversation_id": block.properties.get("conversation_id"),
        "feedback_status": block.properties.get("feedback_status"),
        "feedback_rating": block.properties.get("feedback_rating"),
        "feedback_comment": block.properties.get("feedback_comment"),
        "feedback_timestamp": block.properties.get("feedback_timestamp"),
        "created_at": block.created_at,
        "user_prompt": user_prompt,
        "consciousness_events": consciousness_events,
        "llm_response": llm_response,
        "event_count": len(consciousness_events),
    }


def handle_reasoning_chains_list(
    _db: Database,
    *,
    act_id: str | None = None,
    feedback_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List reasoning chains with optional filtering.

    Args:
        act_id: Filter by act ID
        feedback_status: Filter by feedback status (pending, positive, negative)
        limit: Maximum number of chains to return
        offset: Offset for pagination

    Returns:
        Dict with list of reasoning chains
    """
    from reos.play_db import _get_connection, init_db

    init_db()
    conn = _get_connection()

    # Build query
    conditions = ["b.type = ?"]
    params: list[Any] = [BlockType.REASONING_CHAIN.value]

    if act_id:
        conditions.append("b.act_id = ?")
        params.append(act_id)

    if feedback_status:
        # We need to join with block_properties to filter by feedback_status
        conditions.append("""
            EXISTS (
                SELECT 1 FROM block_properties bp
                WHERE bp.block_id = b.id
                AND bp.key = 'feedback_status'
                AND bp.value = ?
            )
        """)
        params.append(f'"{feedback_status}"' if feedback_status else feedback_status)

    where_clause = " AND ".join(conditions)

    # Query for chains
    query = f"""
        SELECT b.id, b.act_id, b.created_at, b.updated_at,
               (SELECT bp.value FROM block_properties bp WHERE bp.block_id = b.id AND bp.key = 'conversation_id') as conversation_id,
               (SELECT bp.value FROM block_properties bp WHERE bp.block_id = b.id AND bp.key = 'feedback_status') as feedback_status,
               (SELECT bp.value FROM block_properties bp WHERE bp.block_id = b.id AND bp.key = 'feedback_rating') as feedback_rating,
               (SELECT COUNT(*) FROM blocks c WHERE c.parent_id = b.id AND c.type = 'consciousness_event') as event_count
        FROM blocks b
        WHERE {where_clause}
        ORDER BY b.created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    cursor = conn.execute(query, params)
    chains = []

    for row in cursor:
        # Parse JSON values
        conversation_id = row["conversation_id"]
        if isinstance(conversation_id, str):
            try:
                conversation_id = json.loads(conversation_id)
            except json.JSONDecodeError:
                pass

        feedback_status_val = row["feedback_status"]
        if isinstance(feedback_status_val, str):
            try:
                feedback_status_val = json.loads(feedback_status_val)
            except json.JSONDecodeError:
                pass

        chains.append({
            "chain_block_id": row["id"],
            "act_id": row["act_id"],
            "conversation_id": conversation_id,
            "feedback_status": feedback_status_val,
            "feedback_rating": row["feedback_rating"],
            "event_count": row["event_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    # Get total count for pagination
    count_query = f"""
        SELECT COUNT(*) as total
        FROM blocks b
        WHERE {where_clause}
    """
    count_cursor = conn.execute(count_query, params[:-2])  # Remove limit and offset
    total = count_cursor.fetchone()["total"]

    return {
        "chains": chains,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
