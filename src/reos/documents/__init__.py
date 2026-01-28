"""Document processing module for knowledge base integration.

This module provides functionality for:
- Extracting text from various document formats (PDF, DOCX, TXT, MD, CSV)
- Chunking text into semantic segments for RAG
- Managing document storage in the knowledge base
"""

from .extractor import extract_text, DocumentExtractionError
from .chunker import chunk_text, Chunk
from .storage import (
    store_document,
    save_extracted_text,
    save_metadata,
    get_document_path,
    get_document_metadata,
    delete_document,
    list_documents,
    get_original_file,
    get_extracted_text,
    DocumentMetadata,
)

__all__ = [
    "extract_text",
    "DocumentExtractionError",
    "chunk_text",
    "Chunk",
    "store_document",
    "save_extracted_text",
    "save_metadata",
    "get_document_path",
    "get_document_metadata",
    "delete_document",
    "list_documents",
    "get_original_file",
    "get_extracted_text",
    "DocumentMetadata",
]
