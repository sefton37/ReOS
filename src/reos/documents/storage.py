"""Document storage management.

Handles copying files to managed storage and tracking document metadata.
Storage location: ~/.reos-data/play/documents/{doc_id}/
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_documents_base_path() -> Path:
    """Get the base path for document storage."""
    base = Path(os.path.expanduser("~/.reos-data/play/documents"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _get_act_documents_path(act_id: str) -> Path:
    """Get the path for act-scoped document references."""
    base = Path(os.path.expanduser(f"~/.reos-data/play/acts/{act_id}/documents"))
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class DocumentMetadata:
    """Metadata for a stored document."""

    document_id: str
    file_name: str
    file_type: str
    file_size: int
    chunk_count: int
    storage_path: str
    extracted_at: str
    act_id: str | None = None
    title: str | None = None
    author: str | None = None
    page_count: int | None = None
    extraction_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentMetadata":
        """Create from dictionary."""
        return cls(**data)


def store_document(
    source_path: Path,
    act_id: str | None = None,
    document_id: str | None = None,
) -> tuple[str, Path]:
    """Copy a document to managed storage.

    Args:
        source_path: Path to the source document.
        act_id: Optional act ID to scope the document.
        document_id: Optional document ID (generated if not provided).

    Returns:
        Tuple of (document_id, storage_path).

    Raises:
        FileNotFoundError: If source file doesn't exist.
        ValueError: If file is too large (>50MB).
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Check file size (max 50MB)
    file_size = source_path.stat().st_size
    max_size = 50 * 1024 * 1024  # 50MB
    if file_size > max_size:
        raise ValueError(f"File too large: {file_size / 1024 / 1024:.1f}MB (max: 50MB)")

    # Generate document ID if not provided
    if document_id is None:
        document_id = str(uuid.uuid4())

    # Create document directory
    doc_dir = _get_documents_base_path() / document_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    # Copy original file with preserved extension
    original_ext = source_path.suffix.lower()
    dest_path = doc_dir / f"original{original_ext}"
    shutil.copy2(source_path, dest_path)

    logger.info(
        "Stored document %s: %s -> %s",
        document_id,
        source_path,
        dest_path,
    )

    return document_id, dest_path


def save_extracted_text(document_id: str, text: str) -> Path:
    """Save extracted text to document directory.

    Args:
        document_id: The document ID.
        text: Extracted text content.

    Returns:
        Path to the saved text file.
    """
    doc_dir = _get_documents_base_path() / document_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    text_path = doc_dir / "extracted.txt"
    text_path.write_text(text, encoding="utf-8")

    return text_path


def save_metadata(metadata: DocumentMetadata) -> Path:
    """Save document metadata.

    Args:
        metadata: Document metadata to save.

    Returns:
        Path to the saved metadata file.
    """
    doc_dir = _get_documents_base_path() / metadata.document_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    meta_path = doc_dir / "metadata.json"
    meta_path.write_text(
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Also create act-scoped reference if act_id is provided
    if metadata.act_id:
        act_docs_path = _get_act_documents_path(metadata.act_id)
        ref_path = act_docs_path / f"{metadata.document_id}.json"
        ref_path.write_text(
            json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return meta_path


def get_document_path(document_id: str) -> Path | None:
    """Get the storage path for a document.

    Args:
        document_id: The document ID.

    Returns:
        Path to the document directory, or None if not found.
    """
    doc_dir = _get_documents_base_path() / document_id
    if doc_dir.exists():
        return doc_dir
    return None


def get_document_metadata(document_id: str) -> DocumentMetadata | None:
    """Get metadata for a document.

    Args:
        document_id: The document ID.

    Returns:
        DocumentMetadata or None if not found.
    """
    doc_dir = _get_documents_base_path() / document_id
    meta_path = doc_dir / "metadata.json"

    if not meta_path.exists():
        return None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return DocumentMetadata.from_dict(data)
    except Exception as exc:
        logger.warning("Failed to read metadata for %s: %s", document_id, exc)
        return None


def delete_document(document_id: str, act_id: str | None = None) -> bool:
    """Delete a document and its associated data.

    Args:
        document_id: The document ID.
        act_id: Optional act ID to also remove act-scoped reference.

    Returns:
        True if deleted, False if not found.
    """
    doc_dir = _get_documents_base_path() / document_id

    if not doc_dir.exists():
        return False

    # Get metadata to find act_id if not provided
    if not act_id:
        metadata = get_document_metadata(document_id)
        if metadata and metadata.act_id:
            act_id = metadata.act_id

    # Delete document directory
    shutil.rmtree(doc_dir)
    logger.info("Deleted document: %s", document_id)

    # Remove act-scoped reference
    if act_id:
        ref_path = _get_act_documents_path(act_id) / f"{document_id}.json"
        if ref_path.exists():
            ref_path.unlink()

    return True


def list_documents(act_id: str | None = None) -> list[DocumentMetadata]:
    """List all documents, optionally filtered by act.

    Args:
        act_id: Optional act ID to filter by.

    Returns:
        List of DocumentMetadata.
    """
    if act_id:
        # List from act-scoped directory
        act_docs_path = _get_act_documents_path(act_id)
        if not act_docs_path.exists():
            return []

        documents: list[DocumentMetadata] = []
        for ref_path in act_docs_path.glob("*.json"):
            try:
                data = json.loads(ref_path.read_text(encoding="utf-8"))
                documents.append(DocumentMetadata.from_dict(data))
            except Exception as exc:
                logger.warning("Failed to read document ref %s: %s", ref_path, exc)

        return documents

    # List all documents
    base_path = _get_documents_base_path()
    documents: list[DocumentMetadata] = []

    for doc_dir in base_path.iterdir():
        if doc_dir.is_dir():
            meta_path = doc_dir / "metadata.json"
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    documents.append(DocumentMetadata.from_dict(data))
                except Exception as exc:
                    logger.warning("Failed to read metadata for %s: %s", doc_dir.name, exc)

    return documents


def get_original_file(document_id: str) -> Path | None:
    """Get the path to the original file.

    Args:
        document_id: The document ID.

    Returns:
        Path to original file or None if not found.
    """
    doc_dir = _get_documents_base_path() / document_id
    if not doc_dir.exists():
        return None

    # Find the original file (has 'original' prefix with extension)
    for f in doc_dir.iterdir():
        if f.stem == "original":
            return f

    return None


def get_extracted_text(document_id: str) -> str | None:
    """Get the extracted text for a document.

    Args:
        document_id: The document ID.

    Returns:
        Extracted text or None if not found.
    """
    doc_dir = _get_documents_base_path() / document_id
    text_path = doc_dir / "extracted.txt"

    if not text_path.exists():
        return None

    return text_path.read_text(encoding="utf-8")
