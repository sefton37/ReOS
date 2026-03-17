"""Command matching helpers for the ReOS benchmark framework.

Provides three levels of match:
  - exact_match: normalized string equality
  - fuzzy_match: Jaccard token overlap >= threshold (default 0.8)

The semantic_match function (cosine similarity via sentence embeddings) is
defined as a stub here; it requires an optional embedding model dependency and
is populated by the runner when the dependency is available.
"""

import re
import shlex


def normalize_command(cmd: str) -> str:
    """Normalize a shell command for comparison.

    Transformations applied:
      - Strip leading/trailing whitespace
      - Collapse internal whitespace runs to a single space
      - Normalize quote styles: 'foo' → foo when unambiguous (single-word, no spaces)
      - Lowercase (shell commands are case-sensitive, but we normalize for matching)

    Note: We intentionally do NOT lowercase because shell paths and arguments
    are case-sensitive on Linux.  We DO normalize whitespace and strip outer quotes
    around simple single-token values.

    Args:
        cmd: Raw command string.

    Returns:
        Normalized command string suitable for comparison.
    """
    if not cmd:
        return ""
    # Strip outer whitespace
    cmd = cmd.strip()
    # Collapse internal whitespace
    cmd = re.sub(r"\s+", " ", cmd)
    # Normalize smart/curly quotes to plain quotes
    cmd = cmd.replace("\u2018", "'").replace("\u2019", "'")
    cmd = cmd.replace("\u201c", '"').replace("\u201d", '"')
    return cmd


def _tokenize(cmd: str) -> set[str]:
    """Split a command into a set of tokens for Jaccard comparison.

    Uses shlex to respect quoting, falling back to whitespace split on parse error.

    Args:
        cmd: Normalized command string.

    Returns:
        Set of string tokens.
    """
    try:
        return set(shlex.split(cmd))
    except ValueError:
        return set(cmd.split())


def exact_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
) -> bool:
    """Check whether actual equals expected (or any alt) after normalization.

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.

    Returns:
        True if actual matches expected or any element of alts after normalization.
    """
    if actual is None:
        # A None actual only matches a None expected (both produce no command)
        return expected is None and (not alts)
    norm_actual = normalize_command(actual)
    candidates = []
    if expected is not None:
        candidates.append(normalize_command(expected))
    if alts:
        candidates.extend(normalize_command(a) for a in alts)
    return norm_actual in candidates


def fuzzy_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
    threshold: float = 0.8,
) -> bool:
    """Check whether actual is similar to expected (or any alt) via Jaccard token overlap.

    The Jaccard similarity between two token sets A and B is:
        |A ∩ B| / |A ∪ B|

    A match is declared when similarity >= threshold against *any* candidate.

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.
        threshold: Minimum Jaccard similarity to declare a match (default 0.8).

    Returns:
        True if actual fuzzy-matches expected or any element of alts.
    """
    if actual is None or (expected is None and not alts):
        return actual is None and expected is None and not alts

    if actual is None:
        return False

    norm_actual = normalize_command(actual)
    actual_tokens = _tokenize(norm_actual)

    if not actual_tokens:
        return False

    candidates: list[str] = []
    if expected is not None:
        candidates.append(normalize_command(expected))
    if alts:
        candidates.extend(normalize_command(a) for a in alts)

    for cand in candidates:
        cand_tokens = _tokenize(cand)
        if not cand_tokens:
            continue
        intersection = actual_tokens & cand_tokens
        union = actual_tokens | cand_tokens
        similarity = len(intersection) / len(union)
        if similarity >= threshold:
            return True

    return False


def semantic_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
    threshold: float = 0.85,
) -> bool | None:
    """Check whether actual is semantically similar to expected via cosine similarity.

    This is a stub.  The full implementation requires sentence-transformers or a
    compatible embedding model.  Returns None when the dependency is unavailable,
    so callers can treat None as "not scored" rather than "failed".

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.
        threshold: Minimum cosine similarity to declare a match (default 0.85).

    Returns:
        True/False if embeddings are available, None otherwise.
    """
    try:
        from sentence_transformers import SentenceTransformer, util  # type: ignore[import]
    except ImportError:
        return None

    if actual is None or (expected is None and not alts):
        return actual is None and expected is None and not alts

    if actual is None:
        return False

    model = SentenceTransformer("all-MiniLM-L6-v2")
    emb_actual = model.encode(actual, convert_to_tensor=True)

    candidates: list[str] = []
    if expected is not None:
        candidates.append(expected)
    if alts:
        candidates.extend(alts)

    for cand in candidates:
        emb_cand = model.encode(cand, convert_to_tensor=True)
        sim = float(util.cos_sim(emb_actual, emb_cand))
        if sim >= threshold:
            return True

    return False
