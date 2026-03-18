"""Command matching helpers for the ReOS benchmark framework.

Provides three levels of match:
  - exact_match: normalized string equality
  - fuzzy_match: Jaccard token overlap >= threshold (default 0.8)

Extended scoring (Plan A) adds four more matchers:
  - structural_match: same base command ignoring arguments and sudo
  - sudo_normalized_match: exact after stripping "sudo " from both sides
  - command_equivalence_match: known equivalent commands (e.g. netstat/ss)
  - placeholder_normalized_match: exact after collapsing common placeholder patterns

The semantic_match function (cosine similarity via sentence embeddings) is
defined as a stub here; it requires an optional embedding model dependency and
is populated by the runner when the dependency is available.
"""

import re
import re as _re
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


# ─────────────────────────────────────────────────────────────────────────────
# Plan A: extended scoring matchers
# ─────────────────────────────────────────────────────────────────────────────


def structural_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
) -> bool:
    """Match if the base command (first token, ignoring sudo) is the same.

    Strips a leading "sudo " prefix and takes the first token before any pipe.
    This catches cases where the model produces the right command with different
    arguments or a sudo prefix the corpus did not anticipate.

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.

    Returns:
        True if the base command of actual matches any candidate.
    """
    if actual is None or expected is None:
        return False

    def base_cmd(cmd: str) -> str:
        """Extract the base command, stripping sudo and taking first token."""
        cmd = cmd.strip()
        if cmd.startswith("sudo "):
            cmd = cmd[5:].strip()
        # Handle pipes — take the first command segment
        cmd = cmd.split("|")[0].strip()
        parts = cmd.split()
        return parts[0] if parts else ""

    actual_base = base_cmd(actual)
    if not actual_base:
        return False
    candidates = [expected] + (alts or [])
    return any(base_cmd(c) == actual_base for c in candidates if c)


def sudo_normalized_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
) -> bool:
    """Exact match after normalizing the sudo prefix on both sides.

    Handles cases where the model adds or omits "sudo " relative to the corpus
    expected command.  Normalization also applies normalize_command().

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.

    Returns:
        True if the sudo-stripped commands are equal.
    """
    if actual is None:
        return expected is None and not alts

    def strip_sudo(cmd: str) -> str:
        cmd = normalize_command(cmd)
        return cmd[5:].strip() if cmd.startswith("sudo ") else cmd

    norm = strip_sudo(actual)
    candidates: list[str] = []
    if expected is not None:
        candidates.append(strip_sudo(expected))
    if alts:
        candidates.extend(strip_sudo(a) for a in alts)
    return norm in candidates


# Groups of commands that are functionally equivalent for scoring purposes.
# A match is declared when actual and expected both fall into the same group.
EQUIVALENT_COMMANDS: list[set[str]] = [
    {"pgrep", "ps aux | grep", "ps -ef | grep"},
    {"killall", "pkill"},
    {"ls -la", "ls -al", "ls -a -l"},
    {"netstat", "ss"},
    {"ifconfig", "ip addr", "ip a"},
    {"route", "ip route", "ip r"},
    {"find . -name", "locate"},
    {"cat /etc/passwd", "getent passwd"},
    {"free -h", "free -m", "free --human"},
    {"df -h", "df --human-readable"},
    {"which", "type", "command -v"},
    {"wget", "curl -O", "curl -o"},
    {"nslookup", "dig", "host"},
    {"dmesg", "journalctl -k"},
    {"systemctl --failed", "systemctl list-units --failed"},
]


def command_equivalence_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
) -> bool:
    """Match if actual and expected are known equivalent commands.

    Uses EQUIVALENT_COMMANDS groups.  A command is "in" a group if it starts
    with any member of the group (prefix match to handle arguments).

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.

    Returns:
        True if actual and any candidate fall into the same equivalence group.
    """
    if actual is None or expected is None:
        return False

    def base_form(cmd: str) -> str:
        cmd = normalize_command(cmd)
        if cmd.startswith("sudo "):
            cmd = cmd[5:].strip()
        return cmd

    a = base_form(actual)
    candidates = [base_form(expected)]
    if alts:
        candidates.extend(base_form(x) for x in alts)

    for group in EQUIVALENT_COMMANDS:
        a_in = any(a.startswith(eq) for eq in group)
        if a_in:
            for cand in candidates:
                if any(cand.startswith(eq) for eq in group):
                    return True
    return False


# Placeholder normalization: map common generic/example tokens to canonical forms
# so that "adduser newuser" and "adduser USER" score as equivalent.
_PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (_re.compile(r"/path/to/\S+"), "/PATH"),
    (_re.compile(r"/home/\w+/\S*"), "/PATH"),
    (_re.compile(r"filename\S*"), "FILE"),
    (_re.compile(r"file\.\w+"), "FILE"),
    (_re.compile(r"<[^>]+>"), "PARAM"),
    (_re.compile(r"\{[^}]+\}"), "PARAM"),
    (_re.compile(r"/dev/sd[a-z]\d*"), "/dev/DISK"),
    (_re.compile(r"/dev/sdX\d*"), "/dev/DISK"),
    (_re.compile(r"your_\w+"), "PARAM"),
    (_re.compile(r"package[_-]?name"), "PACKAGE"),
    (_re.compile(r"process[_-]?name"), "PROCESS"),
    (_re.compile(r"\bnewadmin\b|\badmin_user\b|\bnewuser\b"), "USER"),
]


def placeholder_normalized_match(
    actual: str | None,
    expected: str | None,
    alts: list[str] | None = None,
) -> bool:
    """Match after collapsing common placeholder patterns to canonical forms.

    Handles cases where the model uses generic placeholders (e.g. "<filename>",
    "/path/to/file", "your_package") while the corpus uses a concrete example
    (or vice versa).

    Args:
        actual: The command produced by the pipeline (may be None).
        expected: The canonical expected command (may be None).
        alts: Optional list of acceptable alternative commands.

    Returns:
        True if the placeholder-normalized commands are equal.
    """
    if actual is None:
        return expected is None and not alts

    def normalize_placeholders(cmd: str) -> str:
        cmd = normalize_command(cmd)
        if cmd.startswith("sudo "):
            cmd = cmd[5:].strip()
        for pattern, replacement in _PLACEHOLDER_PATTERNS:
            cmd = pattern.sub(replacement, cmd)
        return cmd

    norm = normalize_placeholders(actual)
    candidates: list[str] = []
    if expected is not None:
        candidates.append(normalize_placeholders(expected))
    if alts:
        candidates.extend(normalize_placeholders(a) for a in alts)
    return norm in candidates
