"""semantic_rag.py — Core RAG module for ReOS semantic layer integration.

Handles:
  - Indexing YAML intent definitions into ChromaDB
  - Retrieving matching semantic entries at query time
  - Loading and checking blocked command patterns
  - CLI entry point for building/rebuilding the index
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

try:
    import chromadb
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# src/reos/semantic_rag.py → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SEMANTIC_DIR = _PROJECT_ROOT / "semantic-layer"
_DOMAINS_DIR = _SEMANTIC_DIR / "domains"
_INTENT_INDEX = _SEMANTIC_DIR / "intent-index.yaml"
_BLOCKED_PATTERNS = _SEMANTIC_DIR / "blocked-patterns.yaml"

_CHROMADB_DIR = Path.home() / ".reos-data" / "chromadb"
_MANIFEST_PATH = Path.home() / ".reos-data" / "semantic_index_manifest.json"
_COLLECTION_NAME = "reos_intents"

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class SemanticEntry:
    """A single retrieved semantic layer entry."""

    phrase: str           # The matched intent phrase
    domain: str           # e.g. "file-operations"
    command: str          # e.g. "ls"
    pattern: str          # e.g. "ls -lh {directory}"
    safety_level: str     # "safe" | "moderate" | "dangerous" | "blocked"
    requires_sudo: bool
    undo: dict[str, str] | None  # e.g. {"copy": "rm {destination}"}
    distance: float       # cosine distance from query (lower = better match)
    is_alternate: bool    # True if this was an alternate_phrasing, not primary intent


# ---------------------------------------------------------------------------
# SemanticRetriever
# ---------------------------------------------------------------------------


class SemanticRetriever:
    """Retrieves semantic layer entries from ChromaDB."""

    def __init__(self) -> None:
        self._collection = _open_collection()

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.65,
    ) -> list[SemanticEntry]:
        """Embed query via nomic-embed-text, search ChromaDB, return entries above threshold.

        ChromaDB uses cosine distance where 0 = identical and 2 = opposite.
        The threshold conversion: distance <= 1 - min_similarity.
        """
        if self._collection is None:
            return []

        try:
            count = self._collection.count()
        except Exception as exc:
            logger.warning("ChromaDB count check failed: %s", exc)
            return []

        if count == 0:
            return []

        distance_threshold = 1.0 - min_similarity

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, count),
                include=["metadatas", "distances", "documents"],
            )
        except Exception as exc:
            logger.warning("ChromaDB query failed: %s", exc)
            return []

        entries: list[SemanticEntry] = []
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        documents = results.get("documents", [[]])[0]

        for meta, dist, doc in zip(metadatas, distances, documents):
            if dist > distance_threshold:
                continue

            undo: dict[str, str] | None = None
            raw_undo = meta.get("undo_json")
            if raw_undo:
                try:
                    undo = json.loads(raw_undo)
                except json.JSONDecodeError:
                    pass

            entries.append(
                SemanticEntry(
                    phrase=doc or meta.get("phrase", ""),
                    domain=meta.get("domain", ""),
                    command=meta.get("command", ""),
                    pattern=meta.get("pattern", ""),
                    safety_level=meta.get("safety_level", "safe"),
                    requires_sudo=bool(meta.get("requires_sudo", False)),
                    undo=undo,
                    distance=dist,
                    is_alternate=bool(meta.get("is_alternate", False)),
                )
            )

        entries.sort(key=lambda e: e.distance)
        return entries

    def format_for_prompt(self, entries: list[SemanticEntry]) -> str:
        """Format retrieved entries as a prompt block for LLM injection.

        Deduplicates on pattern field — shows at most 3 unique patterns.
        """
        if not entries:
            return ""

        seen_patterns: set[str] = set()
        unique: list[SemanticEntry] = []
        for entry in entries:
            if entry.pattern not in seen_patterns:
                seen_patterns.add(entry.pattern)
                unique.append(entry)
            if len(unique) >= 3:
                break

        lines = ["Relevant patterns from the semantic layer (use these if they match):"]
        for i, entry in enumerate(unique, start=1):
            sudo_note = " (requires sudo)" if entry.requires_sudo else ""
            if entry.undo:
                # Show first undo value
                undo_value = next(iter(entry.undo.values()))
            else:
                undo_value = "none"

            lines.append(f"\nPattern {i} ({entry.domain} / {entry.command}):")
            lines.append(f'  User intent: "{entry.phrase}"')
            lines.append(f"  Command pattern: {entry.pattern}")
            lines.append(f"  Safety: {entry.safety_level}{sudo_note}")
            lines.append(f"  Undo: {undo_value}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SemanticBlockedPatternLoader
# ---------------------------------------------------------------------------


class SemanticBlockedPatternLoader:
    """Loads and compiles blocked-patterns.yaml into a fast-reject filter."""

    def __init__(self) -> None:
        self._rules: list[tuple[re.Pattern[str], str, str]] = []
        self._load()

    def _load(self) -> None:
        if not _BLOCKED_PATTERNS.exists():
            logger.warning("blocked-patterns.yaml not found at %s", _BLOCKED_PATTERNS)
            return

        try:
            with open(_BLOCKED_PATTERNS) as f:
                data = yaml.safe_load(f)
        except Exception as exc:
            logger.error("Failed to load blocked-patterns.yaml: %s", exc)
            return

        categories = data.get("categories", [])
        for category in categories:
            cat_name = category.get("name", "unknown")
            for entry in category.get("patterns", []):
                raw_pattern = entry.get("pattern", "")
                why = entry.get("why", "blocked pattern")
                if not raw_pattern:
                    continue
                try:
                    # Compile as a substring match after escaping literals.
                    # Many blocked patterns are literal strings (e.g. "rm -rf /"),
                    # so re.escape is appropriate. We wrap in a partial-line match.
                    compiled = re.compile(
                        re.escape(raw_pattern), re.IGNORECASE
                    )
                    self._rules.append((compiled, why, cat_name))
                except re.error as exc:
                    logger.warning(
                        "Failed to compile blocked pattern %r: %s", raw_pattern, exc
                    )

    def check(self, command: str) -> tuple[bool, str]:
        """Returns (is_safe, reason). Checks command against all blocked patterns.

        Returns (True, "") if the command is safe.
        Returns (False, reason) on the first match.
        """
        for compiled, why, cat_name in self._rules:
            if compiled.search(command):
                return False, f"[{cat_name}] {why}"
        return True, ""


# ---------------------------------------------------------------------------
# SemanticLayerIndexer
# ---------------------------------------------------------------------------


class SemanticLayerIndexer:
    """Builds ChromaDB collection from semantic layer YAML files."""

    def __init__(self) -> None:
        self._manifest: dict[str, str] = {}

    def build(self, force: bool = False) -> None:
        """Parse intent-index.yaml + domain YAMLs, embed phrases, store in ChromaDB.

        Uses a hash manifest for incremental re-indexing — only domains whose
        YAML file hash has changed (or all domains if force=True) are reprocessed.
        """
        if not HAS_CHROMADB:
            print("chromadb is not installed — cannot build index.")
            return

        if not _INTENT_INDEX.exists():
            print(f"intent-index.yaml not found at {_INTENT_INDEX}")
            return

        collection = _open_or_create_collection()
        if collection is None:
            print("Failed to open/create ChromaDB collection.")
            return

        if not force:
            self._manifest = _load_manifest()
        else:
            self._manifest = {}

        # Load intent index
        print("Loading intent-index.yaml …")
        try:
            with open(_INTENT_INDEX) as f:
                index_data = yaml.safe_load(f)
        except Exception as exc:
            print(f"Failed to load intent-index.yaml: {exc}")
            return

        intents: list[dict[str, Any]] = index_data.get("intents", [])
        if not intents:
            print("No intents found in intent-index.yaml.")
            return

        # Group intents by domain
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for entry in intents:
            domain = entry.get("domain", "unknown")
            by_domain.setdefault(domain, []).append(entry)

        print(f"Found {len(intents)} intent phrases across {len(by_domain)} domains.")

        # Load domain metadata (safety, undo) keyed by (domain, command)
        domain_meta = _load_domain_metadata()

        total_upserted = 0
        total_skipped = 0

        for domain, domain_intents in sorted(by_domain.items()):
            domain_yaml = _DOMAINS_DIR / f"{domain}.yaml"
            domain_hash = _file_hash(domain_yaml) if domain_yaml.exists() else "missing"
            cached_hash = self._manifest.get(domain)

            if not force and cached_hash == domain_hash:
                print(f"  {domain}: unchanged, skipping ({len(domain_intents)} phrases)")
                total_skipped += len(domain_intents)
                continue

            print(f"  {domain}: indexing {len(domain_intents)} phrases …", end="", flush=True)

            # Delete stale docs for this domain
            try:
                existing = collection.get(where={"domain": domain})
                if existing and existing.get("ids"):
                    collection.delete(ids=existing["ids"])
            except Exception as exc:
                logger.warning("Failed to delete stale docs for domain %s: %s", domain, exc)

            # Build batch
            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict[str, Any]] = []

            for intent_entry in domain_intents:
                phrase = intent_entry.get("phrase", "").strip()
                if not phrase:
                    logger.warning("Empty phrase in domain %s, skipping", domain)
                    continue

                command = intent_entry.get("command", "")
                pattern = intent_entry.get("pattern", "")
                is_alternate = bool(intent_entry.get("is_alternate", False))

                # Look up safety/undo from domain YAML
                meta_key = (domain, command)
                cmd_meta = domain_meta.get(meta_key, {})
                safety_level = cmd_meta.get("safety_level", "safe")
                requires_sudo = cmd_meta.get("requires_sudo", False)
                undo_dict = cmd_meta.get("undo", {})
                undo_json = json.dumps(undo_dict) if undo_dict else ""

                doc_id = f"{domain}_{command}_{hashlib.sha256(phrase.encode()).hexdigest()[:8]}"

                ids.append(doc_id)
                documents.append(phrase)
                metadatas.append(
                    {
                        "domain": domain,
                        "command": command,
                        "pattern": pattern,
                        "safety_level": safety_level,
                        "requires_sudo": requires_sudo,
                        "undo_json": undo_json,
                        "is_alternate": is_alternate,
                    }
                )

            # Upsert in batches of 64
            batch_size = 64
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i : i + batch_size]
                batch_docs = documents[i : i + batch_size]
                batch_metas = metadatas[i : i + batch_size]
                try:
                    collection.upsert(
                        ids=batch_ids,
                        documents=batch_docs,
                        metadatas=batch_metas,
                    )
                except Exception as exc:
                    print(f"\n    ERROR upserting batch {i//batch_size + 1}: {exc}")
                    logger.error("Upsert failed for domain %s batch %d: %s", domain, i, exc)

            upserted = len(ids)
            total_upserted += upserted
            print(f" done ({upserted} phrases)")

            self._manifest[domain] = domain_hash

        # Write updated manifest
        _save_manifest(self._manifest)

        total = total_upserted + total_skipped
        print(
            f"\nIndex complete: {total_upserted} phrases indexed, "
            f"{total_skipped} skipped (unchanged). "
            f"Total in index: {collection.count()}."
        )


# ---------------------------------------------------------------------------
# Domain metadata loader
# ---------------------------------------------------------------------------


def _load_domain_metadata() -> dict[tuple[str, str], dict[str, Any]]:
    """Load safety/undo metadata from all domain YAML files.

    Returns a dict keyed by (domain_name, command_name).
    """
    result: dict[tuple[str, str], dict[str, Any]] = {}

    if not _DOMAINS_DIR.exists():
        logger.warning("Domains directory not found: %s", _DOMAINS_DIR)
        return result

    for yaml_file in sorted(_DOMAINS_DIR.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
        except Exception as exc:
            logger.warning("Failed to load domain YAML %s: %s", yaml_file, exc)
            continue

        domain_name = data.get("domain", yaml_file.stem)
        commands = data.get("commands", [])

        for cmd in commands:
            cmd_name = cmd.get("name", "")
            if not cmd_name:
                continue

            safety_block = cmd.get("safety", {})
            safety_level = safety_block.get("level", "safe")
            requires_sudo = bool(safety_block.get("requires_sudo", False))
            undo = cmd.get("undo", {})

            # Normalize undo: strip no-op strings (they're informational, not actionable)
            if isinstance(undo, dict):
                undo_clean = {
                    k: v
                    for k, v in undo.items()
                    if v and "no-op" not in v.lower()
                }
            else:
                undo_clean = {}

            result[(domain_name, cmd_name)] = {
                "safety_level": safety_level,
                "requires_sudo": requires_sudo,
                "undo": undo_clean,
            }

    return result


# ---------------------------------------------------------------------------
# ChromaDB helpers
# ---------------------------------------------------------------------------


def _make_embedding_function() -> Any:
    return OllamaEmbeddingFunction(
        url="http://localhost:11434/api/embeddings",
        model_name="nomic-embed-text",
    )


def _open_collection() -> Any | None:
    """Open existing ChromaDB collection. Returns None if unavailable."""
    if not HAS_CHROMADB:
        return None
    try:
        client = chromadb.PersistentClient(path=str(_CHROMADB_DIR))
        return client.get_collection(
            name=_COLLECTION_NAME,
            embedding_function=_make_embedding_function(),
        )
    except Exception as exc:
        logger.debug("Could not open ChromaDB collection: %s", exc)
        return None


def _open_or_create_collection() -> Any | None:
    """Open or create ChromaDB collection for indexing."""
    if not HAS_CHROMADB:
        return None
    try:
        _CHROMADB_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(_CHROMADB_DIR))
        return client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=_make_embedding_function(),
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as exc:
        logger.error("Failed to open/create ChromaDB collection: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _load_manifest() -> dict[str, str]:
    if not _MANIFEST_PATH.exists():
        return {}
    try:
        with open(_MANIFEST_PATH) as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load manifest: %s", exc)
        return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    try:
        _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
    except Exception as exc:
        logger.warning("Failed to save manifest: %s", exc)


def _file_hash(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "error"
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Module-level singleton factories
# ---------------------------------------------------------------------------

_retriever_instance: SemanticRetriever | None = None
_retriever_initialized = False

_blocked_loader_instance: SemanticBlockedPatternLoader | None = None


def get_retriever() -> SemanticRetriever | None:
    """Singleton factory. Returns None if ChromaDB is not available or not indexed."""
    global _retriever_instance, _retriever_initialized

    if _retriever_initialized:
        return _retriever_instance

    _retriever_initialized = True

    if not HAS_CHROMADB:
        return None

    try:
        retriever = SemanticRetriever()
        # Verify the collection is usable
        if retriever._collection is None:
            return None
        _retriever_instance = retriever
    except Exception as exc:
        logger.debug("SemanticRetriever init failed: %s", exc)
        _retriever_instance = None

    return _retriever_instance


def get_blocked_pattern_loader() -> SemanticBlockedPatternLoader:
    """Singleton factory for blocked pattern loader."""
    global _blocked_loader_instance
    if _blocked_loader_instance is None:
        _blocked_loader_instance = SemanticBlockedPatternLoader()
    return _blocked_loader_instance


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ReOS semantic layer index management")
    parser.add_argument("action", choices=["index"], help="Action to perform")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full rebuild, ignoring the hash manifest",
    )
    args = parser.parse_args()

    if args.action == "index":
        indexer = SemanticLayerIndexer()
        indexer.build(force=args.force)
