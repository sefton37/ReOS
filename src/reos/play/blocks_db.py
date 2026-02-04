"""Database operations for blocks and rich text.

This module provides CRUD operations for the block-based content system,
following the patterns established in play_db.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..play_db import _get_connection, _transaction, init_db

from .blocks_models import Block, BlockType, RichTextSpan

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    """Generate a new unique ID with prefix."""
    return f"{prefix}-{uuid4().hex[:12]}"


# =============================================================================
# Block CRUD Operations
# =============================================================================


def create_block(
    *,
    type: BlockType | str,
    act_id: str,
    parent_id: str | None = None,
    page_id: str | None = None,
    scene_id: str | None = None,
    position: int | None = None,
    rich_text: list[dict[str, Any]] | None = None,
    properties: dict[str, Any] | None = None,
) -> Block:
    """Create a new block.

    Args:
        type: Block type (e.g., 'paragraph', 'heading_1').
        act_id: Act this block belongs to.
        parent_id: Parent block ID for nesting.
        page_id: Page ID if this is a page-level block.
        scene_id: Scene ID for scene embed blocks.
        position: Position among siblings (auto-calculated if None).
        rich_text: Initial rich text content as list of span dicts.
        properties: Type-specific properties.

    Returns:
        The created Block with its ID.
    """
    init_db()

    block_id = _new_id("block")
    now = _now_iso()

    # Convert string type to enum
    if isinstance(type, str):
        type = BlockType(type)

    with _transaction() as conn:
        # Auto-calculate position if not provided
        if position is None:
            if parent_id:
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocks WHERE parent_id = ?",
                    (parent_id,)
                )
            elif page_id:
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocks WHERE page_id = ? AND parent_id IS NULL",
                    (page_id,)
                )
            else:
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM blocks WHERE act_id = ? AND parent_id IS NULL AND page_id IS NULL",
                    (act_id,)
                )
            position = cursor.fetchone()[0]

        # Insert block
        conn.execute("""
            INSERT INTO blocks (id, type, act_id, parent_id, page_id, scene_id, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (block_id, type.value, act_id, parent_id, page_id, scene_id, position, now, now))

        # Insert properties
        if properties:
            for key, value in properties.items():
                json_value = json.dumps(value) if not isinstance(value, str) else value
                conn.execute(
                    "INSERT INTO block_properties (block_id, key, value) VALUES (?, ?, ?)",
                    (block_id, key, json_value)
                )

        # Insert rich text spans
        spans = []
        if rich_text:
            for i, span_data in enumerate(rich_text):
                span_id = _new_id("span")
                conn.execute("""
                    INSERT INTO rich_text
                    (id, block_id, position, content, bold, italic, strikethrough, code, underline, color, background_color, link_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    span_id,
                    block_id,
                    span_data.get("position", i),
                    span_data.get("content", ""),
                    1 if span_data.get("bold") else 0,
                    1 if span_data.get("italic") else 0,
                    1 if span_data.get("strikethrough") else 0,
                    1 if span_data.get("code") else 0,
                    1 if span_data.get("underline") else 0,
                    span_data.get("color"),
                    span_data.get("background_color"),
                    span_data.get("link_url"),
                ))
                spans.append(RichTextSpan(
                    id=span_id,
                    block_id=block_id,
                    position=span_data.get("position", i),
                    content=span_data.get("content", ""),
                    bold=bool(span_data.get("bold")),
                    italic=bool(span_data.get("italic")),
                    strikethrough=bool(span_data.get("strikethrough")),
                    code=bool(span_data.get("code")),
                    underline=bool(span_data.get("underline")),
                    color=span_data.get("color"),
                    background_color=span_data.get("background_color"),
                    link_url=span_data.get("link_url"),
                ))

    return Block(
        id=block_id,
        type=type,
        act_id=act_id,
        parent_id=parent_id,
        page_id=page_id,
        scene_id=scene_id,
        position=position,
        created_at=now,
        updated_at=now,
        rich_text=spans,
        properties=properties or {},
    )


def get_block(block_id: str, include_rich_text: bool = True) -> Block | None:
    """Get a block by ID.

    Args:
        block_id: The block ID.
        include_rich_text: Whether to load rich text spans.

    Returns:
        The Block or None if not found.
    """
    init_db()
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT id, type, act_id, parent_id, page_id, scene_id, position, created_at, updated_at
        FROM blocks WHERE id = ?
    """, (block_id,))

    row = cursor.fetchone()
    if not row:
        return None

    # Load properties
    props_cursor = conn.execute(
        "SELECT key, value FROM block_properties WHERE block_id = ?",
        (block_id,)
    )
    properties = {}
    for prop_row in props_cursor:
        try:
            properties[prop_row["key"]] = json.loads(prop_row["value"])
        except (json.JSONDecodeError, TypeError):
            properties[prop_row["key"]] = prop_row["value"]

    # Load rich text if requested
    rich_text = []
    if include_rich_text:
        rt_cursor = conn.execute("""
            SELECT id, block_id, position, content, bold, italic, strikethrough, code, underline, color, background_color, link_url
            FROM rich_text WHERE block_id = ? ORDER BY position
        """, (block_id,))
        for rt_row in rt_cursor:
            rich_text.append(RichTextSpan(
                id=rt_row["id"],
                block_id=rt_row["block_id"],
                position=rt_row["position"],
                content=rt_row["content"],
                bold=bool(rt_row["bold"]),
                italic=bool(rt_row["italic"]),
                strikethrough=bool(rt_row["strikethrough"]),
                code=bool(rt_row["code"]),
                underline=bool(rt_row["underline"]),
                color=rt_row["color"],
                background_color=rt_row["background_color"],
                link_url=rt_row["link_url"],
            ))

    return Block(
        id=row["id"],
        type=BlockType(row["type"]),
        act_id=row["act_id"],
        parent_id=row["parent_id"],
        page_id=row["page_id"],
        scene_id=row["scene_id"],
        position=row["position"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        rich_text=rich_text,
        properties=properties,
    )


def list_blocks(
    *,
    page_id: str | None = None,
    parent_id: str | None = None,
    act_id: str | None = None,
    include_rich_text: bool = True,
) -> list[Block]:
    """List blocks with optional filtering.

    Args:
        page_id: Filter by page ID (root blocks of a page).
        parent_id: Filter by parent block ID (children of a block).
        act_id: Filter by act ID.
        include_rich_text: Whether to load rich text spans.

    Returns:
        List of matching blocks ordered by position.
    """
    init_db()
    conn = _get_connection()

    # Build query based on filters
    conditions = []
    params: list[Any] = []

    if parent_id is not None:
        conditions.append("parent_id = ?")
        params.append(parent_id)
    elif page_id is not None:
        conditions.append("page_id = ? AND parent_id IS NULL")
        params.append(page_id)
    elif act_id is not None:
        conditions.append("act_id = ?")
        params.append(act_id)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    cursor = conn.execute(f"""
        SELECT id, type, act_id, parent_id, page_id, scene_id, position, created_at, updated_at
        FROM blocks WHERE {where_clause}
        ORDER BY position
    """, params)

    blocks = []
    for row in cursor:
        block_id = row["id"]

        # Load properties
        props_cursor = conn.execute(
            "SELECT key, value FROM block_properties WHERE block_id = ?",
            (block_id,)
        )
        properties = {}
        for prop_row in props_cursor:
            try:
                properties[prop_row["key"]] = json.loads(prop_row["value"])
            except (json.JSONDecodeError, TypeError):
                properties[prop_row["key"]] = prop_row["value"]

        # Load rich text if requested
        rich_text = []
        if include_rich_text:
            rt_cursor = conn.execute("""
                SELECT id, block_id, position, content, bold, italic, strikethrough, code, underline, color, background_color, link_url
                FROM rich_text WHERE block_id = ? ORDER BY position
            """, (block_id,))
            for rt_row in rt_cursor:
                rich_text.append(RichTextSpan(
                    id=rt_row["id"],
                    block_id=rt_row["block_id"],
                    position=rt_row["position"],
                    content=rt_row["content"],
                    bold=bool(rt_row["bold"]),
                    italic=bool(rt_row["italic"]),
                    strikethrough=bool(rt_row["strikethrough"]),
                    code=bool(rt_row["code"]),
                    underline=bool(rt_row["underline"]),
                    color=rt_row["color"],
                    background_color=rt_row["background_color"],
                    link_url=rt_row["link_url"],
                ))

        blocks.append(Block(
            id=row["id"],
            type=BlockType(row["type"]),
            act_id=row["act_id"],
            parent_id=row["parent_id"],
            page_id=row["page_id"],
            scene_id=row["scene_id"],
            position=row["position"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            rich_text=rich_text,
            properties=properties,
        ))

    return blocks


def update_block(
    block_id: str,
    *,
    rich_text: list[dict[str, Any]] | None = None,
    properties: dict[str, Any] | None = None,
    position: int | None = None,
) -> Block | None:
    """Update a block.

    Args:
        block_id: The block to update.
        rich_text: New rich text content (replaces existing).
        properties: Properties to update (merged with existing).
        position: New position among siblings.

    Returns:
        Updated Block or None if not found.
    """
    init_db()

    block = get_block(block_id, include_rich_text=False)
    if not block:
        return None

    now = _now_iso()

    with _transaction() as conn:
        # SAFETY: updates list MUST only contain hardcoded "column = ?" strings.
        # Never add user-controlled column names here.
        updates = ["updated_at = ?"]
        params: list[Any] = [now]

        if position is not None:
            updates.append("position = ?")
            params.append(position)

        _ALLOWED_COLUMNS = {"updated_at", "position"}
        assert all(u.split(" = ?")[0] in _ALLOWED_COLUMNS for u in updates), (
            f"SQL injection guard: unexpected column in updates: {updates}"
        )

        params.append(block_id)
        conn.execute(f"UPDATE blocks SET {', '.join(updates)} WHERE id = ?", params)

        # Update properties (merge)
        if properties is not None:
            for key, value in properties.items():
                json_value = json.dumps(value) if not isinstance(value, str) else value
                conn.execute("""
                    INSERT INTO block_properties (block_id, key, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT (block_id, key) DO UPDATE SET value = excluded.value
                """, (block_id, key, json_value))

        # Replace rich text if provided
        if rich_text is not None:
            conn.execute("DELETE FROM rich_text WHERE block_id = ?", (block_id,))
            for i, span_data in enumerate(rich_text):
                span_id = _new_id("span")
                conn.execute("""
                    INSERT INTO rich_text
                    (id, block_id, position, content, bold, italic, strikethrough, code, underline, color, background_color, link_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    span_id,
                    block_id,
                    span_data.get("position", i),
                    span_data.get("content", ""),
                    1 if span_data.get("bold") else 0,
                    1 if span_data.get("italic") else 0,
                    1 if span_data.get("strikethrough") else 0,
                    1 if span_data.get("code") else 0,
                    1 if span_data.get("underline") else 0,
                    span_data.get("color"),
                    span_data.get("background_color"),
                    span_data.get("link_url"),
                ))

    return get_block(block_id)


def delete_block(block_id: str, recursive: bool = True) -> bool:
    """Delete a block.

    Args:
        block_id: The block to delete.
        recursive: If True, also delete all descendants.

    Returns:
        True if deleted, False if not found.
    """
    init_db()

    with _transaction() as conn:
        # Check if block exists
        cursor = conn.execute("SELECT id FROM blocks WHERE id = ?", (block_id,))
        if not cursor.fetchone():
            return False

        if recursive:
            # Delete descendants first (depth-first)
            _delete_descendants(conn, block_id)

        # Delete the block (CASCADE handles properties and rich_text)
        conn.execute("DELETE FROM blocks WHERE id = ?", (block_id,))

    return True


def _delete_descendants(conn, parent_id: str) -> None:
    """Recursively delete all descendants of a block."""
    cursor = conn.execute("SELECT id FROM blocks WHERE parent_id = ?", (parent_id,))
    children = [row[0] for row in cursor.fetchall()]

    for child_id in children:
        _delete_descendants(conn, child_id)
        conn.execute("DELETE FROM blocks WHERE id = ?", (child_id,))


# =============================================================================
# Rich Text Operations
# =============================================================================


def get_rich_text(block_id: str) -> list[RichTextSpan]:
    """Get rich text spans for a block.

    Args:
        block_id: The block ID.

    Returns:
        List of RichTextSpan objects ordered by position.
    """
    init_db()
    conn = _get_connection()

    cursor = conn.execute("""
        SELECT id, block_id, position, content, bold, italic, strikethrough, code, underline, color, background_color, link_url
        FROM rich_text WHERE block_id = ? ORDER BY position
    """, (block_id,))

    return [
        RichTextSpan(
            id=row["id"],
            block_id=row["block_id"],
            position=row["position"],
            content=row["content"],
            bold=bool(row["bold"]),
            italic=bool(row["italic"]),
            strikethrough=bool(row["strikethrough"]),
            code=bool(row["code"]),
            underline=bool(row["underline"]),
            color=row["color"],
            background_color=row["background_color"],
            link_url=row["link_url"],
        )
        for row in cursor
    ]


def set_rich_text(block_id: str, spans: list[dict[str, Any]]) -> list[RichTextSpan]:
    """Replace all rich text for a block.

    Args:
        block_id: The block ID.
        spans: List of span dictionaries.

    Returns:
        Created RichTextSpan objects.
    """
    init_db()
    now = _now_iso()

    with _transaction() as conn:
        # Delete existing spans
        conn.execute("DELETE FROM rich_text WHERE block_id = ?", (block_id,))

        # Update block timestamp
        conn.execute("UPDATE blocks SET updated_at = ? WHERE id = ?", (now, block_id))

        # Insert new spans
        result = []
        for i, span_data in enumerate(spans):
            span_id = _new_id("span")
            conn.execute("""
                INSERT INTO rich_text
                (id, block_id, position, content, bold, italic, strikethrough, code, underline, color, background_color, link_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                span_id,
                block_id,
                span_data.get("position", i),
                span_data.get("content", ""),
                1 if span_data.get("bold") else 0,
                1 if span_data.get("italic") else 0,
                1 if span_data.get("strikethrough") else 0,
                1 if span_data.get("code") else 0,
                1 if span_data.get("underline") else 0,
                span_data.get("color"),
                span_data.get("background_color"),
                span_data.get("link_url"),
            ))
            result.append(RichTextSpan(
                id=span_id,
                block_id=block_id,
                position=span_data.get("position", i),
                content=span_data.get("content", ""),
                bold=bool(span_data.get("bold")),
                italic=bool(span_data.get("italic")),
                strikethrough=bool(span_data.get("strikethrough")),
                code=bool(span_data.get("code")),
                underline=bool(span_data.get("underline")),
                color=span_data.get("color"),
                background_color=span_data.get("background_color"),
                link_url=span_data.get("link_url"),
            ))

    return result


# =============================================================================
# Block Properties Operations
# =============================================================================


def get_block_property(block_id: str, key: str) -> Any | None:
    """Get a single block property.

    Args:
        block_id: The block ID.
        key: Property key.

    Returns:
        Property value or None.
    """
    init_db()
    conn = _get_connection()

    cursor = conn.execute(
        "SELECT value FROM block_properties WHERE block_id = ? AND key = ?",
        (block_id, key)
    )
    row = cursor.fetchone()
    if not row:
        return None

    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_block_property(block_id: str, key: str, value: Any) -> None:
    """Set a block property.

    Args:
        block_id: The block ID.
        key: Property key.
        value: Property value (will be JSON-encoded if not a string).
    """
    init_db()
    now = _now_iso()
    json_value = json.dumps(value) if not isinstance(value, str) else value

    with _transaction() as conn:
        conn.execute("""
            INSERT INTO block_properties (block_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT (block_id, key) DO UPDATE SET value = excluded.value
        """, (block_id, key, json_value))

        # Update block timestamp
        conn.execute("UPDATE blocks SET updated_at = ? WHERE id = ?", (now, block_id))


def delete_block_property(block_id: str, key: str) -> bool:
    """Delete a block property.

    Args:
        block_id: The block ID.
        key: Property key.

    Returns:
        True if deleted, False if not found.
    """
    init_db()
    now = _now_iso()

    with _transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM block_properties WHERE block_id = ? AND key = ?",
            (block_id, key)
        )

        if cursor.rowcount > 0:
            conn.execute("UPDATE blocks SET updated_at = ? WHERE id = ?", (now, block_id))
            return True

    return False


# =============================================================================
# Convenience Functions
# =============================================================================


def create_text_block(
    *,
    type: BlockType | str,
    act_id: str,
    text: str,
    parent_id: str | None = None,
    page_id: str | None = None,
    position: int | None = None,
    **properties: Any,
) -> Block:
    """Create a text block with plain text content.

    This is a convenience function for creating common text blocks
    (paragraph, headings) with simple unformatted text.

    Args:
        type: Block type.
        act_id: Act ID.
        text: Plain text content.
        parent_id: Parent block ID.
        page_id: Page ID.
        position: Position among siblings.
        **properties: Additional type-specific properties.

    Returns:
        Created Block.
    """
    return create_block(
        type=type,
        act_id=act_id,
        parent_id=parent_id,
        page_id=page_id,
        position=position,
        rich_text=[{"content": text}] if text else None,
        properties=properties if properties else None,
    )


def get_page_blocks(page_id: str, recursive: bool = False) -> list[Block]:
    """Get all blocks for a page.

    Args:
        page_id: The page ID.
        recursive: If True, also load children recursively.

    Returns:
        List of root-level blocks for the page.
    """
    blocks = list_blocks(page_id=page_id)

    if recursive:
        for block in blocks:
            _load_children_recursive(block)

    return blocks


def _load_children_recursive(block: Block) -> None:
    """Recursively load children for a block."""
    if not block.is_nestable():
        return

    children = list_blocks(parent_id=block.id)
    block.children = children

    for child in children:
        _load_children_recursive(child)
