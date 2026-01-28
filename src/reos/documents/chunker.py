"""Text chunking for RAG (Retrieval-Augmented Generation).

Splits text into semantic chunks suitable for embedding and retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Chunk:
    """A chunk of text from a document."""

    content: str
    chunk_index: int
    start_char: int
    end_char: int
    page_number: int | None = None  # For PDFs
    section_title: str | None = None  # For documents with headers

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "content": self.content,
            "chunk_index": self.chunk_index,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "page_number": self.page_number,
            "section_title": self.section_title,
        }


def chunk_text(
    text: str,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Split text into semantic chunks.

    Tries to preserve:
    - Paragraph boundaries
    - Sentence boundaries
    - Section headers

    Args:
        text: The text to chunk.
        max_tokens: Maximum tokens per chunk (approximate, using word count).
        overlap_tokens: Token overlap between chunks for context continuity.
        metadata: Optional extraction metadata (e.g., page_boundaries for PDFs).

    Returns:
        List of Chunk objects.
    """
    if not text.strip():
        return []

    # Get page boundaries if available (for PDFs)
    page_boundaries: list[int] = []
    if metadata and "page_boundaries" in metadata:
        page_boundaries = metadata["page_boundaries"]

    # Split into paragraphs first
    paragraphs = _split_into_paragraphs(text)

    # Group paragraphs into chunks respecting max_tokens
    chunks: list[Chunk] = []
    current_content: list[str] = []
    current_token_count = 0
    current_start_char = 0
    current_section_title: str | None = None
    char_position = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        # Check if this is a section header
        if _is_section_header(para):
            current_section_title = para.strip("#").strip()

        # If single paragraph exceeds max_tokens, split it
        if para_tokens > max_tokens:
            # Flush current content first
            if current_content:
                chunk_text_content = "\n\n".join(current_content)
                page_num = _get_page_number(current_start_char, page_boundaries)
                chunks.append(Chunk(
                    content=chunk_text_content,
                    chunk_index=len(chunks),
                    start_char=current_start_char,
                    end_char=current_start_char + len(chunk_text_content),
                    page_number=page_num,
                    section_title=current_section_title,
                ))
                current_content = []
                current_token_count = 0

            # Split long paragraph into sentences
            sentence_chunks = _split_long_paragraph(para, max_tokens, overlap_tokens)
            for sentence_chunk in sentence_chunks:
                page_num = _get_page_number(char_position, page_boundaries)
                chunks.append(Chunk(
                    content=sentence_chunk,
                    chunk_index=len(chunks),
                    start_char=char_position,
                    end_char=char_position + len(sentence_chunk),
                    page_number=page_num,
                    section_title=current_section_title,
                ))
            char_position += len(para) + 2  # +2 for paragraph separator
            current_start_char = char_position
            continue

        # Check if adding this paragraph would exceed limit
        if current_token_count + para_tokens > max_tokens and current_content:
            # Flush current chunk
            chunk_text_content = "\n\n".join(current_content)
            page_num = _get_page_number(current_start_char, page_boundaries)
            chunks.append(Chunk(
                content=chunk_text_content,
                chunk_index=len(chunks),
                start_char=current_start_char,
                end_char=current_start_char + len(chunk_text_content),
                page_number=page_num,
                section_title=current_section_title,
            ))

            # Start new chunk with overlap (include last paragraph if under overlap limit)
            if current_content and _estimate_tokens(current_content[-1]) <= overlap_tokens:
                current_content = [current_content[-1]]
                current_token_count = _estimate_tokens(current_content[-1])
            else:
                current_content = []
                current_token_count = 0
            current_start_char = char_position

        current_content.append(para)
        current_token_count += para_tokens
        char_position += len(para) + 2

    # Flush remaining content
    if current_content:
        chunk_text_content = "\n\n".join(current_content)
        page_num = _get_page_number(current_start_char, page_boundaries)
        chunks.append(Chunk(
            content=chunk_text_content,
            chunk_index=len(chunks),
            start_char=current_start_char,
            end_char=current_start_char + len(chunk_text_content),
            page_number=page_num,
            section_title=current_section_title,
        ))

    return chunks


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    # Split on double newlines or single newlines followed by whitespace
    paragraphs = re.split(r"\n\s*\n", text)
    # Filter empty paragraphs and strip whitespace
    return [p.strip() for p in paragraphs if p.strip()]


def _estimate_tokens(text: str) -> int:
    """Estimate token count (roughly 1 token per 4 characters or word)."""
    # Simple heuristic: count words as a reasonable proxy
    return len(text.split())


def _is_section_header(text: str) -> bool:
    """Check if text looks like a section header."""
    text = text.strip()
    # Markdown headers
    if text.startswith("#"):
        return True
    # All caps short line
    if text.isupper() and len(text.split()) <= 8 and len(text) < 100:
        return True
    # Numbered section
    if re.match(r"^\d+\.?\s+[A-Z]", text) and len(text.split()) <= 10:
        return True
    return False


def _split_long_paragraph(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split a long paragraph into sentence-based chunks."""
    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not sentences:
        return [text]

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = _estimate_tokens(sentence)

        if current_tokens + sentence_tokens > max_tokens and current_sentences:
            # Flush current
            chunks.append(" ".join(current_sentences))

            # Keep overlap
            overlap_sentences: list[str] = []
            overlap_count = 0
            for s in reversed(current_sentences):
                s_tokens = _estimate_tokens(s)
                if overlap_count + s_tokens <= overlap_tokens:
                    overlap_sentences.insert(0, s)
                    overlap_count += s_tokens
                else:
                    break

            current_sentences = overlap_sentences
            current_tokens = overlap_count

        current_sentences.append(sentence)
        current_tokens += sentence_tokens

    if current_sentences:
        chunks.append(" ".join(current_sentences))

    return chunks


def _get_page_number(char_offset: int, page_boundaries: list[int]) -> int | None:
    """Get page number from character offset using page boundaries."""
    if not page_boundaries:
        return None

    for i, boundary in enumerate(page_boundaries):
        if i + 1 < len(page_boundaries):
            if boundary <= char_offset < page_boundaries[i + 1]:
                return i + 1  # 1-indexed page numbers
        else:
            # Last page
            if char_offset >= boundary:
                return i + 1

    return 1  # Default to page 1
