# Document Knowledge Base

> **"Your documents, searchable by meaning. Local extraction, semantic retrieval, zero cloud dependencies."**

The document system extends the block architecture with document ingestion, enabling CAIRN to retrieve relevant information from your PDFs, Word documents, spreadsheets, and text files.

---

## Overview

The document system provides:

1. **Document Ingestion**: Extract text from various file formats
2. **Semantic Chunking**: Split documents into ~500 token segments
3. **RAG Integration**: Index chunks for retrieval during conversations
4. **Visual Cards**: Display documents in the block editor

```
User types /document
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ FILE PICKER                                              │
│ Select: PDF, DOCX, TXT, MD, CSV, XLSX                   │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ BACKEND PROCESSING                                       │
│                                                          │
│ 1. Copy file to ~/.reos-data/play/documents/{id}/       │
│ 2. Extract text (pypdf, python-docx, openpyxl)          │
│ 3. Chunk into ~500 token segments                       │
│ 4. Create document_chunk blocks                         │
│ 5. Index blocks via memory system                       │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ EDITOR                                                   │
│                                                          │
│ Document card inserted showing:                          │
│ [📕] resume.pdf                                         │
│      245 KB • 12 chunks indexed                          │
└─────────────────────────────────────────────────────────┘
```

---

## Core Principles

### Local-First

All document processing runs locally:
- **Extraction**: pypdf, python-docx, openpyxl (no cloud APIs)
- **Storage**: Files copied to `~/.reos-data/play/documents/`
- **Indexing**: Embeddings via local `all-MiniLM-L6-v2`

### Block-Native

Documents integrate with the existing block system:
- Each chunk becomes a `document_chunk` block
- Chunks are indexed via the memory system
- Retrieved alongside other memory sources during conversation

### Privacy by Architecture

Your documents never leave your machine:
- Original files stored locally
- Text extraction happens locally
- Embeddings generated locally
- No cloud processing or storage

---

## Supported Formats

| Format | Extensions | Extraction Library | Notes |
|--------|------------|-------------------|-------|
| **PDF** | `.pdf` | pypdf | Page boundaries preserved |
| **Word** | `.docx`, `.doc` | python-docx | Includes tables |
| **Excel** | `.xlsx`, `.xls` | openpyxl | Multi-sheet support |
| **Text** | `.txt` | Built-in | UTF-8, Latin-1 fallback |
| **Markdown** | `.md` | Built-in | Preserved as-is |
| **CSV** | `.csv` | Built-in | Converted to markdown table |

### Installation

Document extraction requires optional dependencies:

```bash
pip install -e ".[documents]"
```

This installs:
- `pypdf>=4.0` - PDF extraction
- `python-docx>=1.1` - Word document extraction
- `openpyxl>=3.1` - Excel extraction

---

## Usage

### Via Slash Command

1. Type `/document` in the block editor
2. Select a file from the picker
3. Wait for extraction and indexing
4. Document card appears in editor

### Via RPC

```json
// Insert document
{
  "method": "documents/insert",
  "params": {
    "file_path": "/home/user/documents/resume.pdf",
    "act_id": "act-career"
  }
}

// Response
{
  "documentId": "doc-abc123",
  "fileName": "resume.pdf",
  "fileType": "pdf",
  "fileSize": 245760,
  "chunkCount": 12
}
```

---

## Architecture

### Text Extraction

Each format has a dedicated extractor:

```python
from reos.documents import extract_text

text, metadata = extract_text(Path("/path/to/document.pdf"))

# metadata includes:
# - file_type: "pdf"
# - page_count: 15
# - page_boundaries: [0, 1234, 2456, ...]  # Character offsets
# - title: "Document Title" (if available)
# - author: "Author Name" (if available)
```

### Chunking Strategy

Text is split into semantic chunks:

1. **Paragraph Splitting**: Split on double newlines
2. **Size Targeting**: ~500 tokens per chunk
3. **Overlap**: 50 token overlap between chunks for context continuity
4. **Boundary Respect**: Prefer paragraph/sentence boundaries over hard cuts

```python
from reos.documents import chunk_text

chunks = chunk_text(
    text,
    max_tokens=500,
    overlap_tokens=50,
    metadata=extraction_metadata,  # For page boundaries
)

# Each chunk has:
# - content: str
# - chunk_index: int
# - start_char: int
# - end_char: int
# - page_number: int | None (for PDFs)
# - section_title: str | None
```

### Storage Structure

```
~/.reos-data/play/
├── documents/                    # Managed document storage
│   ├── {doc_id}/
│   │   ├── original.pdf         # Original file (extension preserved)
│   │   ├── extracted.txt        # Plain text extraction
│   │   └── metadata.json        # Extraction metadata
│   └── ...
└── acts/{act_id}/
    └── documents/               # Act-scoped document references
        └── {doc_id}.json        # Reference to main storage
```

### Block Creation

Each chunk becomes a `document_chunk` block:

```json
{
  "id": "block-chunk-001",
  "type": "document_chunk",
  "act_id": "act-career",
  "rich_text": [{"content": "Extracted text content..."}],
  "properties": {
    "source_document_id": "doc-abc123",
    "chunk_index": 0,
    "page_number": 1,
    "section_title": "Experience",
    "total_chunks": 12
  }
}
```

### Memory Integration

Chunks are automatically indexed via `memory/index/batch`:

1. Embedding generated for each chunk
2. Stored in `block_embeddings` table
3. Retrieved via `memory/search` during conversation
4. Included in CAIRN's context as memory matches

---

## RPC API

### `documents/insert`

Insert a document into the knowledge base.

**Request:**
```json
{
  "file_path": "/absolute/path/to/document.pdf",
  "act_id": "act-abc123"  // Optional, scopes to act
}
```

**Response:**
```json
{
  "documentId": "doc-xyz789",
  "fileName": "document.pdf",
  "fileType": "pdf",
  "fileSize": 245760,
  "chunkCount": 12,
  "storagePath": "/home/user/.reos-data/play/documents/doc-xyz789"
}
```

### `documents/list`

List documents in the knowledge base.

**Request:**
```json
{
  "act_id": "act-abc123"  // Optional, filter by act
}
```

**Response:**
```json
{
  "documents": [
    {
      "documentId": "doc-xyz789",
      "fileName": "resume.pdf",
      "fileType": "pdf",
      "fileSize": 245760,
      "chunkCount": 12,
      "extractedAt": "2026-01-28T10:30:00Z",
      "title": "John Doe Resume",
      "pageCount": 3
    }
  ],
  "count": 1
}
```

### `documents/get`

Get detailed metadata for a document.

**Request:**
```json
{
  "document_id": "doc-xyz789"
}
```

**Response:**
```json
{
  "documentId": "doc-xyz789",
  "fileName": "resume.pdf",
  "fileType": "pdf",
  "fileSize": 245760,
  "chunkCount": 12,
  "storagePath": ".reos-data/play/documents/doc-xyz789",
  "extractedAt": "2026-01-28T10:30:00Z",
  "actId": "act-career",
  "title": "John Doe Resume",
  "author": "John Doe",
  "pageCount": 3,
  "extractionMetadata": {
    "page_boundaries": [0, 1234, 2456, 3678]
  }
}
```

### `documents/delete`

Delete a document and all its chunks.

**Request:**
```json
{
  "document_id": "doc-xyz789"
}
```

**Response:**
```json
{
  "deleted": true,
  "documentId": "doc-xyz789"
}
```

This also:
- Deletes all `document_chunk` blocks
- Removes embeddings from the index
- Removes files from storage

### `documents/chunks`

Get all chunks for a document.

**Request:**
```json
{
  "document_id": "doc-xyz789"
}
```

**Response:**
```json
{
  "documentId": "doc-xyz789",
  "fileName": "resume.pdf",
  "chunks": [
    {
      "blockId": "block-chunk-001",
      "chunkIndex": 0,
      "pageNumber": 1,
      "sectionTitle": "Experience",
      "content": "Senior Software Engineer at..."
    },
    {
      "blockId": "block-chunk-002",
      "chunkIndex": 1,
      "pageNumber": 1,
      "sectionTitle": "Experience",
      "content": "Led team of 5 engineers..."
    }
  ],
  "count": 12
}
```

---

## RAG Integration

When you talk to CAIRN, document chunks are retrieved alongside other memories:

```
You: "What experience do I have with Python?"
        │
        ▼
┌────────────────────────────────────────────────────────┐
│ Memory Retrieval                                        │
│                                                         │
│ Semantic search finds relevant chunks:                  │
│ - resume.pdf chunk 3: "Python developer for 5 years..." │
│ - resume.pdf chunk 5: "Built Django applications..."    │
│ - notes.md chunk 2: "Completed Python certification..." │
└────────────────────────────────────────────────────────┘
        │
        ▼
CAIRN responds with context from your documents
```

The memory system treats document chunks like any other block:
- Same embedding model (`all-MiniLM-L6-v2`)
- Same retrieval pipeline (semantic + graph expansion)
- Same ranking and scoring

---

## Limits and Performance

| Limit | Value | Reason |
|-------|-------|--------|
| Max file size | 50 MB | Memory constraints |
| Max chunks per document | 100 | Context window limits |
| Chunk size | ~500 tokens | Optimal for retrieval |
| Overlap | 50 tokens | Context continuity |

### Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| PDF extraction (10 pages) | < 2s | pypdf |
| DOCX extraction | < 1s | python-docx |
| Chunking | < 100ms | In-memory |
| Indexing (per chunk) | < 50ms | After model loaded |

---

## Error Handling

### Unsupported Format

```json
{
  "error": {
    "code": -32602,
    "message": "Unsupported file type: .xyz. Supported: ['.pdf', '.docx', ...]"
  }
}
```

### Extraction Failure

```json
{
  "error": {
    "code": -32000,
    "message": "Extraction failed: Could not decode PDF"
  }
}
```

The system attempts graceful degradation:
- Corrupted PDFs: Fall back to filename-only
- Missing dependencies: Helpful error with install instructions
- Encoding issues: Try multiple encodings (UTF-8, Latin-1, CP1252)

---

## Frontend Integration

### Document Card Component

Documents appear in the editor as visual cards:

```
┌─────────────────────────────────────────┐
│ 📕  resume.pdf                          │
│     245 KB • 12 chunks indexed  [Remove]│
└─────────────────────────────────────────┘
```

The card shows:
- File type icon (PDF, Word, Excel, etc.)
- Filename
- File size
- Number of indexed chunks
- Remove button (removes from editor, keeps in knowledge base)

### Slash Command

The `/document` command:
1. Opens native file picker via Tauri dialog
2. Filters by supported extensions
3. Sends file path to backend
4. Inserts document card on success
5. Shows error alert on failure

---

## Future Extensions

- **OCR Support**: Extract text from scanned PDFs
- **Image Documents**: Extract text from images
- **Web Pages**: Save and index web content
- **Incremental Updates**: Re-index only changed sections
- **Document Links**: Link documents to specific blocks
- **Preview**: View extracted text before indexing

---

## Related Documentation

- [Memory System](./memory-system.md) - Semantic search and RAG
- [Blocks API](./blocks-api.md) - Block system documentation
- [The Play](./the-play.md) - Block editor and slash commands
- [CAIRN Architecture](./cairn_architecture.md) - How CAIRN uses document context
