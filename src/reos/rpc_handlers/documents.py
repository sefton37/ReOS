"""Documents RPC handlers - Knowledge base document management.

These handlers manage document ingestion, chunking, and indexing for RAG.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from reos.db import Database
from reos.documents import (
    extract_text,
    chunk_text,
    store_document,
    save_extracted_text,
    save_metadata,
    get_document_metadata,
    get_document_path,
    delete_document,
    list_documents,
    DocumentMetadata,
    DocumentExtractionError,
)
from reos.play import blocks_db
from reos.play.blocks_models import BlockType

from . import RpcError

logger = logging.getLogger(__name__)

# Maximum chunks per document to prevent memory issues
MAX_CHUNKS_PER_DOCUMENT = 100


def handle_documents_insert(
    _db: Database,
    *,
    file_path: str,
    act_id: str | None = None,
) -> dict[str, Any]:
    """Insert a document into the knowledge base.

    1. Copies the file to managed storage
    2. Extracts text content
    3. Chunks text for RAG
    4. Creates blocks for each chunk
    5. Indexes blocks via memory system

    Args:
        file_path: Absolute path to the document file.
        act_id: Optional act ID to scope the document.

    Returns:
        Document metadata including chunk count.
    """
    source_path = Path(file_path)

    if not source_path.exists():
        raise RpcError(code=-32602, message=f"File not found: {file_path}")

    if not source_path.is_file():
        raise RpcError(code=-32602, message=f"Not a file: {file_path}")

    # Store document
    try:
        document_id, storage_path = store_document(source_path, act_id=act_id)
    except ValueError as exc:
        raise RpcError(code=-32602, message=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to store document: %s", file_path)
        raise RpcError(code=-32000, message=f"Failed to store document: {exc}") from exc

    # Extract text
    try:
        text, extraction_metadata = extract_text(source_path)
    except DocumentExtractionError as exc:
        # Clean up stored document on extraction failure
        delete_document(document_id)
        raise RpcError(code=-32000, message=str(exc)) from exc
    except Exception as exc:
        delete_document(document_id)
        logger.exception("Failed to extract text from document: %s", file_path)
        raise RpcError(code=-32000, message=f"Text extraction failed: {exc}") from exc

    # Save extracted text
    try:
        save_extracted_text(document_id, text)
    except Exception as exc:
        logger.warning("Failed to save extracted text: %s", exc)

    # Chunk text
    chunks = chunk_text(text, max_tokens=500, overlap_tokens=50, metadata=extraction_metadata)

    # Limit chunks
    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        logger.warning(
            "Document %s has %d chunks, limiting to %d",
            document_id,
            len(chunks),
            MAX_CHUNKS_PER_DOCUMENT,
        )
        chunks = chunks[:MAX_CHUNKS_PER_DOCUMENT]

    # Create blocks for chunks and index them
    chunk_block_ids: list[str] = []

    for chunk in chunks:
        try:
            # Create a block for this chunk
            block = blocks_db.create_block(
                type="document_chunk",
                act_id=act_id or "global",
                properties={
                    "source_document_id": document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "section_title": chunk.section_title,
                    "total_chunks": len(chunks),
                },
                rich_text=[
                    {
                        "content": chunk.content,
                        "bold": False,
                        "italic": False,
                        "strikethrough": False,
                        "code": False,
                        "underline": False,
                        "color": None,
                        "background_color": None,
                        "link_url": None,
                    }
                ],
            )
            chunk_block_ids.append(block.id)
        except Exception as exc:
            logger.warning("Failed to create block for chunk %d: %s", chunk.chunk_index, exc)

    # Index blocks for semantic search
    if chunk_block_ids:
        try:
            from reos.rpc_handlers.memory import handle_memory_index_batch
            handle_memory_index_batch(_db, block_ids=chunk_block_ids)
        except Exception as exc:
            logger.warning("Failed to index document chunks: %s", exc)

    # Get file info
    file_size = source_path.stat().st_size
    file_type = source_path.suffix.lower().lstrip(".")

    # Save metadata
    metadata = DocumentMetadata(
        document_id=document_id,
        file_name=source_path.name,
        file_type=file_type,
        file_size=file_size,
        chunk_count=len(chunks),
        storage_path=str(storage_path.parent.relative_to(Path.home())),
        extracted_at=datetime.utcnow().isoformat() + "Z",
        act_id=act_id,
        title=extraction_metadata.get("title"),
        author=extraction_metadata.get("author"),
        page_count=extraction_metadata.get("page_count"),
        extraction_metadata=extraction_metadata,
    )

    try:
        save_metadata(metadata)
    except Exception as exc:
        logger.warning("Failed to save document metadata: %s", exc)

    logger.info(
        "Inserted document %s: %s (%d chunks)",
        document_id,
        source_path.name,
        len(chunks),
    )

    return {
        "documentId": document_id,
        "fileName": source_path.name,
        "fileType": file_type,
        "fileSize": file_size,
        "chunkCount": len(chunks),
        "storagePath": str(storage_path.parent),
    }


def handle_documents_list(
    _db: Database,
    *,
    act_id: str | None = None,
) -> dict[str, Any]:
    """List documents in the knowledge base.

    Args:
        act_id: Optional act ID to filter by.

    Returns:
        List of document metadata.
    """
    documents = list_documents(act_id=act_id)

    return {
        "documents": [
            {
                "documentId": doc.document_id,
                "fileName": doc.file_name,
                "fileType": doc.file_type,
                "fileSize": doc.file_size,
                "chunkCount": doc.chunk_count,
                "extractedAt": doc.extracted_at,
                "title": doc.title,
                "author": doc.author,
                "pageCount": doc.page_count,
            }
            for doc in documents
        ],
        "count": len(documents),
    }


def handle_documents_get(
    _db: Database,
    *,
    document_id: str,
) -> dict[str, Any]:
    """Get document metadata and details.

    Args:
        document_id: The document ID.

    Returns:
        Document metadata.
    """
    metadata = get_document_metadata(document_id)

    if not metadata:
        raise RpcError(code=-32602, message=f"Document not found: {document_id}")

    return {
        "documentId": metadata.document_id,
        "fileName": metadata.file_name,
        "fileType": metadata.file_type,
        "fileSize": metadata.file_size,
        "chunkCount": metadata.chunk_count,
        "storagePath": metadata.storage_path,
        "extractedAt": metadata.extracted_at,
        "actId": metadata.act_id,
        "title": metadata.title,
        "author": metadata.author,
        "pageCount": metadata.page_count,
        "extractionMetadata": metadata.extraction_metadata,
    }


def handle_documents_delete(
    _db: Database,
    *,
    document_id: str,
) -> dict[str, Any]:
    """Delete a document from the knowledge base.

    Also removes associated chunk blocks and their embeddings.

    Args:
        document_id: The document ID.

    Returns:
        Deletion status.
    """
    # Get metadata to find act_id
    metadata = get_document_metadata(document_id)
    if not metadata:
        raise RpcError(code=-32602, message=f"Document not found: {document_id}")

    # Find and delete chunk blocks
    try:
        from reos import play_db
        # Find blocks with this source_document_id
        conn = play_db._get_connection()
        cursor = conn.execute(
            """
            SELECT b.id FROM blocks b
            JOIN block_properties bp ON b.id = bp.block_id
            WHERE bp.key = 'source_document_id' AND bp.value = ?
            """,
            (f'"{document_id}"',),  # JSON encoded string
        )
        block_ids = [row["id"] for row in cursor]

        # Delete blocks and their embeddings
        for block_id in block_ids:
            try:
                blocks_db.delete_block(block_id, recursive=False)
            except Exception as exc:
                logger.warning("Failed to delete chunk block %s: %s", block_id, exc)

            # Remove from embedding index
            try:
                from reos.rpc_handlers.memory import handle_memory_remove_index
                handle_memory_remove_index(_db, block_id=block_id)
            except Exception as exc:
                logger.warning("Failed to remove embedding for block %s: %s", block_id, exc)

        logger.info("Deleted %d chunk blocks for document %s", len(block_ids), document_id)
    except Exception as exc:
        logger.warning("Failed to clean up chunk blocks: %s", exc)

    # Delete document storage
    deleted = delete_document(document_id, act_id=metadata.act_id)

    if not deleted:
        raise RpcError(code=-32602, message=f"Failed to delete document: {document_id}")

    return {
        "deleted": True,
        "documentId": document_id,
    }


def handle_documents_get_chunks(
    _db: Database,
    *,
    document_id: str,
) -> dict[str, Any]:
    """Get all chunks for a document.

    Args:
        document_id: The document ID.

    Returns:
        List of chunks with their content and metadata.
    """
    metadata = get_document_metadata(document_id)
    if not metadata:
        raise RpcError(code=-32602, message=f"Document not found: {document_id}")

    # Find chunk blocks
    try:
        from reos import play_db
        conn = play_db._get_connection()
        cursor = conn.execute(
            """
            SELECT b.id, b.created_at
            FROM blocks b
            JOIN block_properties bp ON b.id = bp.block_id
            WHERE bp.key = 'source_document_id' AND bp.value = ?
            ORDER BY b.position
            """,
            (f'"{document_id}"',),
        )
        block_rows = list(cursor)
    except Exception as exc:
        logger.exception("Failed to find chunk blocks")
        raise RpcError(code=-32000, message=f"Failed to find chunks: {exc}") from exc

    chunks: list[dict[str, Any]] = []
    for row in block_rows:
        block = blocks_db.get_block(row["id"])
        if block:
            # Get text content
            text_content = "".join(span.content for span in block.rich_text)

            chunks.append({
                "blockId": block.id,
                "chunkIndex": block.properties.get("chunk_index", 0),
                "pageNumber": block.properties.get("page_number"),
                "sectionTitle": block.properties.get("section_title"),
                "content": text_content,
            })

    # Sort by chunk index
    chunks.sort(key=lambda c: c.get("chunkIndex", 0))

    return {
        "documentId": document_id,
        "fileName": metadata.file_name,
        "chunks": chunks,
        "count": len(chunks),
    }
