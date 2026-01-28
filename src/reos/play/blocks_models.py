"""Data models for the block-based content system.

This module defines the core data structures for Notion-style blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BlockType(str, Enum):
    """Supported block types for Phase 1."""

    # Page-level
    PAGE = "page"

    # Text blocks
    PARAGRAPH = "paragraph"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"

    # List blocks (nestable)
    BULLETED_LIST = "bulleted_list"
    NUMBERED_LIST = "numbered_list"
    TO_DO = "to_do"

    # Special blocks
    CODE = "code"
    DIVIDER = "divider"
    CALLOUT = "callout"

    # Scene embed (links to existing scene)
    SCENE = "scene"

    # Reasoning chain blocks (RLHF feedback system)
    REASONING_CHAIN = "reasoning_chain"      # Container for entire reasoning chain
    USER_PROMPT = "user_prompt"              # User's input message
    CONSCIOUSNESS_EVENT = "consciousness_event"  # Individual thinking step
    LLM_RESPONSE = "llm_response"            # Final LLM response

    # Document knowledge base blocks
    DOCUMENT_CHUNK = "document_chunk"        # Chunk of extracted document text for RAG


# Block types that support nesting children
NESTABLE_TYPES = frozenset({
    BlockType.PAGE,
    BlockType.BULLETED_LIST,
    BlockType.NUMBERED_LIST,
    BlockType.TO_DO,
    BlockType.CALLOUT,
    BlockType.REASONING_CHAIN,  # Contains user_prompt, consciousness_events, llm_response
})


@dataclass
class RichTextSpan:
    """A span of formatted text within a block.

    Rich text is stored as a sequence of spans, each with its own
    formatting. This allows for inline bold, italic, links, etc.
    """

    id: str
    block_id: str
    position: int
    content: str

    # Formatting flags
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False
    code: bool = False
    underline: bool = False

    # Colors (optional)
    color: str | None = None
    background_color: str | None = None

    # Link (optional)
    link_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "block_id": self.block_id,
            "position": self.position,
            "content": self.content,
            "bold": self.bold,
            "italic": self.italic,
            "strikethrough": self.strikethrough,
            "code": self.code,
            "underline": self.underline,
            "color": self.color,
            "background_color": self.background_color,
            "link_url": self.link_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RichTextSpan:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            block_id=data["block_id"],
            position=data.get("position", 0),
            content=data["content"],
            bold=bool(data.get("bold", False)),
            italic=bool(data.get("italic", False)),
            strikethrough=bool(data.get("strikethrough", False)),
            code=bool(data.get("code", False)),
            underline=bool(data.get("underline", False)),
            color=data.get("color"),
            background_color=data.get("background_color"),
            link_url=data.get("link_url"),
        )

    def plain_text(self) -> str:
        """Get plain text content without formatting."""
        return self.content


@dataclass
class Block:
    """A content block in the Notion-style editor.

    Blocks form a tree structure where each block can have children.
    The content of text-based blocks is stored as rich_text spans.
    Type-specific data is stored in properties.
    """

    id: str
    type: BlockType
    act_id: str

    # Hierarchy
    parent_id: str | None = None
    page_id: str | None = None
    scene_id: str | None = None
    position: int = 0

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    # Content (loaded separately)
    rich_text: list[RichTextSpan] = field(default_factory=list)

    # Type-specific properties (e.g., checked for to_do, language for code)
    properties: dict[str, Any] = field(default_factory=dict)

    # Children (loaded separately for tree operations)
    children: list[Block] = field(default_factory=list)

    def to_dict(self, include_children: bool = False) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, BlockType) else self.type,
            "act_id": self.act_id,
            "parent_id": self.parent_id,
            "page_id": self.page_id,
            "scene_id": self.scene_id,
            "position": self.position,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rich_text": [span.to_dict() for span in self.rich_text],
            "properties": self.properties,
        }
        if include_children:
            result["children"] = [child.to_dict(include_children=True) for child in self.children]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Block:
        """Create from dictionary."""
        block_type = data["type"]
        if isinstance(block_type, str):
            block_type = BlockType(block_type)

        return cls(
            id=data["id"],
            type=block_type,
            act_id=data["act_id"],
            parent_id=data.get("parent_id"),
            page_id=data.get("page_id"),
            scene_id=data.get("scene_id"),
            position=data.get("position", 0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            rich_text=[
                RichTextSpan.from_dict(span)
                for span in data.get("rich_text", [])
            ],
            properties=data.get("properties", {}),
            children=[
                Block.from_dict(child)
                for child in data.get("children", [])
            ],
        )

    def plain_text(self) -> str:
        """Get concatenated plain text from all rich_text spans."""
        return "".join(span.plain_text() for span in self.rich_text)

    def is_nestable(self) -> bool:
        """Check if this block type supports children."""
        return self.type in NESTABLE_TYPES

    def has_children(self) -> bool:
        """Check if this block has any children loaded."""
        return len(self.children) > 0
