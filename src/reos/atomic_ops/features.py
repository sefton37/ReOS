"""Feature extraction for atomic operation classification.

This module extracts features from user requests for ML classification.
Uses sentence-transformers for semantic embeddings and lightweight NLP
for lexical/syntactic features.

The 3x2x3 taxonomy requires understanding:
- Destination: Where does output go? (stream/file/process)
- Consumer: Who uses the result? (human/machine)
- Semantics: What action is taken? (read/interpret/execute)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .models import Features

if TYPE_CHECKING:
    pass

# Verb patterns for classification
IMPERATIVE_VERBS = {
    "show", "display", "print", "list", "get", "fetch", "find", "search",
    "create", "make", "add", "write", "save", "store",
    "run", "execute", "start", "stop", "kill", "restart",
    "delete", "remove", "clear", "clean",
    "update", "modify", "change", "edit", "rename", "move",
    "install", "uninstall", "download", "upload",
    "open", "close", "launch", "exit",
    "help", "explain", "describe", "tell", "what", "how", "why",
}

IMMEDIATE_VERBS = {
    "now", "immediately", "quick", "fast", "asap", "right away",
    "hurry", "urgent", "quickly",
}

# Domain keyword patterns
CODE_KEYWORDS = {
    "code", "function", "class", "method", "variable", "bug", "error",
    "test", "debug", "compile", "build", "deploy", "refactor",
    "import", "export", "module", "package", "library", "api",
    "python", "javascript", "typescript", "rust", "java", "go",
}

SYSTEM_KEYWORDS = {
    "memory", "cpu", "disk", "process", "service", "port", "network",
    "file", "folder", "directory", "permission", "user", "group",
    "install", "package", "apt", "dnf", "pacman", "systemctl",
    "docker", "container", "pod", "kubernetes",
}

GIT_KEYWORDS = {
    "git", "commit", "push", "pull", "merge", "branch", "checkout",
    "rebase", "stash", "diff", "log", "status", "clone", "remote",
}

TEST_KEYWORDS = {
    "test", "pytest", "unittest", "coverage", "assert", "mock",
    "fixture", "spec", "tdd", "bdd",
}

FILE_OPERATION_KEYWORDS = {
    "save", "write", "create", "delete", "remove", "move", "copy",
    "rename", "backup", "restore", "export", "import",
}

# File extension patterns
FILE_EXTENSION_PATTERN = re.compile(r'\.\w{1,10}(?:\s|$|[,\)\]\}])')
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".h"}
DOC_EXTENSIONS = {".md", ".txt", ".doc", ".docx", ".pdf", ".rst"}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".conf", ".env"}
DATA_EXTENSIONS = {".csv", ".xml", ".sql", ".db", ".sqlite"}


class FeatureExtractor:
    """Extract features from user requests for classification.

    Uses a combination of:
    - Lexical features (tokens, word counts, patterns)
    - Syntactic features (sentence structure, verb types)
    - Domain features (code, system, git, test keywords)
    - Semantic features (embeddings via sentence-transformers)
    """

    def __init__(self, embedding_model: Optional[object] = None):
        """Initialize feature extractor.

        Args:
            embedding_model: Optional sentence-transformers model.
                            If None, embeddings will be empty.
        """
        self._embedding_model = embedding_model
        self._model_loaded = embedding_model is not None

    def load_embedding_model(self, model_name: str = "all-MiniLM-L6-v2") -> bool:
        """Load sentence-transformers model for embeddings.

        Args:
            model_name: Model to load. Default is all-MiniLM-L6-v2 (22MB, 384-dim).

        Returns:
            True if model loaded successfully, False otherwise.
        """
        try:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(model_name)
            self._model_loaded = True
            return True
        except ImportError:
            # sentence-transformers not installed
            self._model_loaded = False
            return False
        except Exception:
            # Model download or load failed
            self._model_loaded = False
            return False

    def extract(
        self,
        request: str,
        context: Optional[dict] = None,
    ) -> tuple[Features, Optional[bytes]]:
        """Extract features from a user request.

        Args:
            request: The user's natural language request.
            context: Optional context dict with keys like:
                    - recent_operation_count: int
                    - recent_success_rate: float

        Returns:
            Tuple of (Features dataclass, embedding bytes or None)
        """
        context = context or {}

        # Tokenize
        tokens = self._tokenize(request)
        words = [t.lower() for t in tokens if t.isalpha()]

        # Extract lexical features
        verbs, nouns = self._extract_pos(words)
        file_ext = self._detect_file_extension(request)

        # Extract syntactic features
        has_imperative = bool(verbs & IMPERATIVE_VERBS)
        has_interrogative = self._has_interrogative(request)
        has_conditional = self._has_conditional(request)
        has_negation = self._has_negation(request)
        sentence_count = self._count_sentences(request)

        # Extract domain features
        word_set = set(words)
        mentions_code = bool(word_set & CODE_KEYWORDS)
        mentions_system = bool(word_set & SYSTEM_KEYWORDS)
        mentions_git = bool(word_set & GIT_KEYWORDS)
        mentions_testing = bool(word_set & TEST_KEYWORDS)
        has_file_op = bool(word_set & FILE_OPERATION_KEYWORDS)
        has_immediate = bool(word_set & IMMEDIATE_VERBS) or "!" in request

        # Detect programming languages mentioned
        detected_langs = self._detect_languages(request)

        # Context features
        now = datetime.now()

        # Create features object
        features = Features(
            # Lexical
            token_count=len(tokens),
            char_count=len(request),
            verb_count=len(verbs),
            noun_count=len(nouns),
            verbs=list(verbs),
            nouns=list(nouns),
            has_file_extension=file_ext is not None,
            file_extension_type=self._categorize_extension(file_ext),
            avg_word_length=sum(len(w) for w in words) / max(len(words), 1),
            # Syntactic
            has_imperative_verb=has_imperative,
            has_interrogative=has_interrogative,
            has_conditional=has_conditional,
            has_negation=has_negation,
            sentence_count=sentence_count,
            # Domain
            mentions_code=mentions_code,
            detected_languages=detected_langs,
            mentions_system_resource=mentions_system,
            has_file_operation=has_file_op,
            has_immediate_verb=has_immediate,
            mentions_testing=mentions_testing,
            mentions_git=mentions_git,
            # Context
            time_of_day=now.hour,
            day_of_week=now.weekday(),
            recent_operation_count=context.get("recent_operation_count", 0),
            recent_success_rate=context.get("recent_success_rate", 0.0),
            # Hash for deduplication
            request_hash=self._hash_request(request),
        )

        # Generate embeddings if model available
        embeddings = None
        if self._model_loaded and self._embedding_model is not None:
            embeddings = self._generate_embeddings(request)

        return features, embeddings

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization."""
        # Split on whitespace and punctuation
        return re.findall(r'\b\w+\b', text)

    def _extract_pos(self, words: list[str]) -> tuple[set[str], set[str]]:
        """Extract verbs and nouns (simplified POS tagging).

        Uses keyword lists rather than full POS tagging for speed.
        """
        verbs = set()
        nouns = set()

        for word in words:
            word_lower = word.lower()
            if word_lower in IMPERATIVE_VERBS:
                verbs.add(word_lower)
            elif word_lower in CODE_KEYWORDS | SYSTEM_KEYWORDS | GIT_KEYWORDS:
                nouns.add(word_lower)
            # Simple heuristic: words ending in common noun suffixes
            elif word_lower.endswith(("tion", "ment", "ness", "ity", "er", "or")):
                nouns.add(word_lower)

        return verbs, nouns

    def _detect_file_extension(self, text: str) -> Optional[str]:
        """Detect file extension in text."""
        match = FILE_EXTENSION_PATTERN.search(text)
        if match:
            ext = match.group().strip().rstrip(",)]}")
            return ext.lower()
        return None

    def _categorize_extension(self, ext: Optional[str]) -> Optional[str]:
        """Categorize file extension type."""
        if ext is None:
            return None
        if ext in CODE_EXTENSIONS:
            return "code"
        if ext in DOC_EXTENSIONS:
            return "document"
        if ext in CONFIG_EXTENSIONS:
            return "config"
        if ext in DATA_EXTENSIONS:
            return "data"
        return "other"

    def _has_interrogative(self, text: str) -> bool:
        """Check for question markers."""
        text_lower = text.lower()
        return (
            "?" in text or
            text_lower.startswith(("what", "how", "why", "when", "where", "who", "which", "is ", "are ", "can ", "do ", "does "))
        )

    def _has_conditional(self, text: str) -> bool:
        """Check for conditional markers."""
        text_lower = text.lower()
        return any(word in text_lower for word in ["if", "unless", "when", "while", "whether"])

    def _has_negation(self, text: str) -> bool:
        """Check for negation markers."""
        text_lower = text.lower()
        return any(word in text_lower for word in ["not", "don't", "doesn't", "won't", "can't", "never", "no "])

    def _count_sentences(self, text: str) -> int:
        """Count sentences in text."""
        # Simple heuristic: count sentence-ending punctuation
        return max(1, len(re.findall(r'[.!?]+', text)))

    def _detect_languages(self, text: str) -> list[str]:
        """Detect programming languages mentioned."""
        text_lower = text.lower()
        languages = []

        lang_patterns = {
            "python": ["python", "py ", ".py", "pytest", "pip"],
            "javascript": ["javascript", "js ", ".js", "node", "npm"],
            "typescript": ["typescript", "ts ", ".ts", ".tsx"],
            "rust": ["rust", ".rs", "cargo"],
            "go": [" go ", "golang", ".go"],
            "java": ["java ", ".java", "maven", "gradle"],
        }

        for lang, patterns in lang_patterns.items():
            if any(p in text_lower for p in patterns):
                languages.append(lang)

        return languages

    def _hash_request(self, request: str) -> str:
        """Generate hash of request for deduplication."""
        normalized = request.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _generate_embeddings(self, text: str) -> bytes:
        """Generate embeddings using sentence-transformers.

        Returns embeddings as bytes for storage.
        """
        import numpy as np

        # Generate embedding
        embedding = self._embedding_model.encode(text, convert_to_numpy=True)

        # Convert to bytes (float32)
        return embedding.astype(np.float32).tobytes()


def embeddings_to_array(embeddings_bytes: bytes) -> list[float]:
    """Convert embeddings bytes back to float array."""
    import numpy as np
    return np.frombuffer(embeddings_bytes, dtype=np.float32).tolist()


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embedding byte arrays."""
    import numpy as np

    vec_a = np.frombuffer(a, dtype=np.float32)
    vec_b = np.frombuffer(b, dtype=np.float32)

    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot / (norm_a * norm_b))
