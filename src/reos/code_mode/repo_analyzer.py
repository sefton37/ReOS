"""Repo Analyzer - Build comprehensive repo understanding using cheap local LLMs.

This module leverages the cost advantage of local LLMs (300x cheaper than GPT-4)
to deeply analyze repositories and extract:
- Structure and organization
- Architecture patterns
- Coding conventions
- Type definitions
- Import dependencies
- Anti-patterns to avoid

The analysis is stored per-Act in the Play directory and injected into
ProjectMemory for fair model evaluation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.providers import LLMProvider
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


# =============================================================================
# Analysis Result Types
# =============================================================================


@dataclass
class StructureAnalysis:
    """Analysis of repository structure and organization."""

    components: list[dict[str, str]] = field(default_factory=list)  # name, purpose, path
    entry_points: list[str] = field(default_factory=list)  # main.py, __init__.py, etc.
    test_strategy: str = ""  # pytest, unittest, etc.
    docs_location: str = ""  # docs/, README.md, etc.
    analyzed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructureAnalysis:
        """Create from dictionary."""
        return cls(
            components=data.get("components", []),
            entry_points=data.get("entry_points", []),
            test_strategy=data.get("test_strategy", ""),
            docs_location=data.get("docs_location", ""),
            analyzed_at=data.get("analyzed_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ConventionAnalysis:
    """Analysis of coding conventions and patterns."""

    import_style: str = ""  # "from X import Y" vs "import X"
    class_naming: str = ""  # "UserModel" vs "User", patterns observed
    function_naming: str = ""  # snake_case, camelCase, etc.
    type_hints_usage: str = ""  # always, sometimes, never
    docstring_style: str = ""  # Google, NumPy, plain, none
    error_handling: str = ""  # Patterns for exception handling
    examples: dict[str, str] = field(default_factory=dict)  # Convention examples
    analyzed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConventionAnalysis:
        """Create from dictionary."""
        return cls(
            import_style=data.get("import_style", ""),
            class_naming=data.get("class_naming", ""),
            function_naming=data.get("function_naming", ""),
            type_hints_usage=data.get("type_hints_usage", ""),
            docstring_style=data.get("docstring_style", ""),
            error_handling=data.get("error_handling", ""),
            examples=data.get("examples", {}),
            analyzed_at=data.get("analyzed_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class RepoContext:
    """Complete repository analysis context."""

    structure: StructureAnalysis | None = None
    conventions: ConventionAnalysis | None = None
    # Future: architecture, types, imports, antipatterns

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "structure": self.structure.to_dict() if self.structure else None,
            "conventions": self.conventions.to_dict() if self.conventions else None,
            "version": "1.0",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoContext:
        """Load from dictionary."""
        return cls(
            structure=StructureAnalysis.from_dict(data["structure"]) if data.get("structure") else None,
            conventions=ConventionAnalysis.from_dict(data["conventions"]) if data.get("conventions") else None,
        )


# =============================================================================
# Repo Analyzer
# =============================================================================


class ActRepoAnalyzer:
    """Analyze a repository using cheap local LLMs.

    Uses local models (Ollama) to build comprehensive understanding of:
    - Code structure and organization
    - Architecture patterns
    - Coding conventions
    - Type definitions and data models
    - Import dependencies and risks
    - Anti-patterns to avoid

    Cost: ~$0.0025 per full analysis (300x cheaper than GPT-4)
    Time: ~30 seconds for typical repo

    The analysis is cached in the Act's context directory and reused
    across sessions until the repo changes significantly.
    """

    def __init__(self, act: Act, llm: LLMProvider):
        """Initialize analyzer.

        Args:
            act: The Act (project) to analyze
            llm: Local LLM provider (Ollama) for cheap analysis
        """
        self.act = act
        self.llm = llm
        self.repo_path = Path(act.repo_path) if act.repo_path else None

        if not self.repo_path:
            raise ValueError(f"Act {act.act_id} has no repo_path (not in Code Mode)")

        # Get context storage directory from Play
        from reos.play_fs import play_root
        act_dir = play_root() / "acts" / act.act_id
        self.context_dir = act_dir / "context"
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def _needs_analysis(self) -> bool:
        """Check if repo needs (re)analysis.

        Returns True if:
        - Never analyzed before
        - Analysis is > 24 hours old
        - Significant git commits since last analysis (TODO)
        """
        analysis_file = self.context_dir / "repo_analysis.json"
        if not analysis_file.exists():
            logger.info("Repo never analyzed, will analyze")
            return True

        # Check age
        import time
        age_hours = (time.time() - analysis_file.stat().st_mtime) / 3600
        if age_hours > 24:
            logger.info("Analysis is %.1f hours old, will re-analyze", age_hours)
            return True

        logger.info("Using cached analysis (%.1f hours old)", age_hours)
        return False

    def _load_cached(self) -> RepoContext:
        """Load cached analysis from disk."""
        analysis_file = self.context_dir / "repo_analysis.json"
        data = json.loads(analysis_file.read_text())
        logger.info("Loaded cached repo analysis from %s", analysis_file)
        return RepoContext.from_dict(data)

    def _save_context(self, context: RepoContext) -> None:
        """Save analysis to disk."""
        analysis_file = self.context_dir / "repo_analysis.json"
        analysis_file.write_text(
            json.dumps(context.to_dict(), indent=2, ensure_ascii=False) + "\n"
        )
        logger.info("Saved repo analysis to %s", analysis_file)

    async def analyze_if_needed(self) -> RepoContext:
        """Analyze repo if not recently analyzed.

        Returns cached analysis if available and recent.
        Otherwise runs full analysis (cheap! ~$0.0025).
        """
        if not self._needs_analysis():
            return self._load_cached()

        logger.info("Starting repo analysis for %s at %s", self.act.title, self.repo_path)
        context = await self._analyze_full()
        self._save_context(context)
        return context

    async def _analyze_full(self) -> RepoContext:
        """Run comprehensive repo analysis.

        Phase 1: Structure + Convention analysis
        """
        logger.info("Running structure analysis...")
        structure = await self._analyze_structure()

        logger.info("Running convention analysis...")
        conventions = await self._analyze_conventions()

        return RepoContext(structure=structure, conventions=conventions)

    async def _analyze_structure(self) -> StructureAnalysis:
        """Analyze repository structure and organization.

        Uses local LLM to understand:
        - Main components (src, tests, docs, etc.)
        - Entry points (main.py, __init__.py)
        - Test strategy (pytest, unittest)
        - Documentation location

        Cost: ~2K tokens = $0.0002
        """
        logger.info("Analyzing structure of %s", self.repo_path)

        # Get directory tree (limited depth)
        tree = self._get_directory_tree(max_depth=3)

        # Ask local LLM to analyze
        prompt = f"""Analyze this Python project structure:

```
{tree}
```

Describe the repository organization:

1. **Components**: What are the main components? For each, provide:
   - name: Directory or module name
   - purpose: What this component does
   - path: Relative path

2. **Entry points**: Where does code execution start?
   - List files like main.py, __init__.py, cli.py, server.py

3. **Test strategy**: How are tests organized?
   - pytest, unittest, or other?
   - Test file locations and naming

4. **Documentation**: Where is documentation?
   - README.md, docs/ directory, docstrings only, etc.

Respond with ONLY valid JSON in this exact format:
{{
  "components": [
    {{"name": "src/reos/code_mode", "purpose": "Code generation and RIVA verification", "path": "src/reos/code_mode"}},
    {{"name": "tests", "purpose": "Test suite", "path": "tests"}}
  ],
  "entry_points": ["main.py", "src/reos/__init__.py"],
  "test_strategy": "pytest with tests/ directory",
  "docs_location": "README.md and inline docstrings"
}}

Be specific and accurate. Only include what you actually see in the structure.
"""

        try:
            # Call local LLM (cheap!)
            response = await asyncio.to_thread(
                self.llm.chat_json,
                system="You are a code structure analyzer. Respond with valid JSON only.",
                user=prompt,
                temperature=0.1,  # Low temperature for consistent analysis
                timeout_seconds=30.0,
            )

            # Parse response
            if isinstance(response, str):
                data = json.loads(response)
            else:
                data = response

            logger.info("Structure analysis complete: found %d components", len(data.get("components", [])))

            return StructureAnalysis(
                components=data.get("components", []),
                entry_points=data.get("entry_points", []),
                test_strategy=data.get("test_strategy", ""),
                docs_location=data.get("docs_location", ""),
                analyzed_at=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            logger.error("Structure analysis failed: %s", e, exc_info=True)
            # Return empty analysis rather than failing
            return StructureAnalysis(
                analyzed_at=datetime.now(timezone.utc).isoformat(),
            )

    def _get_directory_tree(self, max_depth: int = 3) -> str:
        """Get directory tree as text.

        Args:
            max_depth: Maximum depth to traverse

        Returns:
            Tree structure as text
        """
        if not self.repo_path.exists():
            return "<repo not found>"

        lines = []
        lines.append(str(self.repo_path.name) + "/")

        def add_tree(path: Path, prefix: str = "", depth: int = 0):
            if depth >= max_depth:
                return

            try:
                items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))

                # Filter out common noise
                items = [
                    item for item in items
                    if not item.name.startswith(".")
                    and item.name not in ["__pycache__", "node_modules", ".venv", "venv", ".git"]
                ]

                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    current_prefix = "└── " if is_last else "├── "
                    lines.append(prefix + current_prefix + item.name + ("/" if item.is_dir() else ""))

                    if item.is_dir():
                        extension = "    " if is_last else "│   "
                        add_tree(item, prefix + extension, depth + 1)

            except PermissionError:
                pass

        add_tree(self.repo_path)
        return "\n".join(lines)

    def _sample_python_files(self, count: int = 10) -> list[tuple[str, str]]:
        """Sample Python files from the repository.

        Args:
            count: Maximum number of files to sample

        Returns:
            List of (relative_path, content) tuples
        """
        if not self.repo_path.exists():
            return []

        # Find all Python files
        python_files = []
        for py_file in self.repo_path.rglob("*.py"):
            # Skip common noise directories
            if any(
                part in py_file.parts
                for part in [".venv", "venv", "__pycache__", "node_modules", ".git", "build", "dist"]
            ):
                continue

            # Skip test files (we want production code patterns)
            if "test" in py_file.name.lower():
                continue

            python_files.append(py_file)

        # Sample intelligently: prefer files from different directories
        sampled = []
        seen_dirs = set()

        # First pass: one file per directory
        for py_file in python_files:
            if len(sampled) >= count:
                break

            parent_dir = py_file.parent
            if parent_dir not in seen_dirs:
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    # Skip empty or very small files
                    if len(content.strip()) > 100:
                        rel_path = py_file.relative_to(self.repo_path)
                        sampled.append((str(rel_path), content))
                        seen_dirs.add(parent_dir)
                except Exception as e:
                    logger.debug("Could not read %s: %s", py_file, e)

        # Second pass: fill remaining slots with any files
        if len(sampled) < count:
            for py_file in python_files:
                if len(sampled) >= count:
                    break

                rel_path = str(py_file.relative_to(self.repo_path))
                if not any(rel_path == path for path, _ in sampled):
                    try:
                        content = py_file.read_text(encoding="utf-8", errors="ignore")
                        if len(content.strip()) > 100:
                            sampled.append((rel_path, content))
                    except Exception as e:
                        logger.debug("Could not read %s: %s", py_file, e)

        logger.info("Sampled %d Python files for convention analysis", len(sampled))
        return sampled

    async def _analyze_conventions(self) -> ConventionAnalysis:
        """Analyze coding conventions and patterns.

        Uses local LLM to understand:
        - Import style (from X import Y vs import X)
        - Class naming (UserModel vs User)
        - Function naming (snake_case, camelCase)
        - Type hints usage (always, sometimes, never)
        - Docstring style (Google, NumPy, plain)
        - Error handling patterns

        Cost: ~5K tokens = $0.0005
        """
        logger.info("Analyzing conventions of %s", self.repo_path)

        # Sample representative Python files
        samples = self._sample_python_files(count=10)

        if not samples:
            logger.warning("No Python files found for convention analysis")
            return ConventionAnalysis(analyzed_at=datetime.now(timezone.utc).isoformat())

        # Prepare code samples for LLM (limit size)
        code_samples = []
        for path, content in samples[:10]:
            # Take first 500 lines max per file to avoid token bloat
            lines = content.split("\n")[:500]
            code_samples.append(f"# File: {path}\n" + "\n".join(lines))

        combined_samples = "\n\n" + ("\n\n" + "="*60 + "\n\n").join(code_samples)

        # Ask local LLM to analyze
        prompt = f"""Analyze coding conventions in these Python code samples:

{combined_samples}

Identify the patterns and conventions used:

1. **Import style**: How are imports typically written?
   - "from X import Y" vs "import X"?
   - Grouped by type (stdlib, third-party, local)?
   - Any specific patterns?

2. **Class naming**: What naming convention for classes?
   - Examples: UserModel vs User, BaseClient vs ClientBase
   - Any suffixes/prefixes (Model, Service, Manager)?

3. **Function naming**: What naming convention for functions?
   - snake_case, camelCase, or mixed?
   - Any patterns (get_, set_, _private)?

4. **Type hints**: How consistently are type hints used?
   - Always, sometimes, never?
   - For function params? Return types? Variables?

5. **Docstring style**: What docstring format?
   - Google style, NumPy style, plain text, or none?
   - Examples if present

6. **Error handling**: How are errors handled?
   - Custom exceptions or built-in?
   - Raise patterns, try/except patterns

Respond with ONLY valid JSON in this exact format:
{{
  "import_style": "Primarily 'from X import Y', grouped by stdlib/third-party/local",
  "class_naming": "PascalCase with descriptive suffixes (e.g., UserModel, AuthService)",
  "function_naming": "snake_case throughout, private functions prefixed with _",
  "type_hints_usage": "Always used for function parameters and return types",
  "docstring_style": "Google-style docstrings with Args/Returns/Raises sections",
  "error_handling": "Custom exceptions from exceptions.py, specific error types raised",
  "examples": {{
    "import": "from pathlib import Path\\nfrom reos.models import User",
    "class": "class UserModel:\\n    ...",
    "function": "def get_user(user_id: str) -> User | None:",
    "docstring": "\\\"\\\"\\\"Get user by ID.\\n\\nArgs:\\n    user_id: User identifier\\n\\nReturns:\\n    User or None\\n\\\"\\\"\\\""
  }}
}}

Be specific and include actual examples from the code when possible.
"""

        try:
            # Call local LLM (cheap!)
            response = await asyncio.to_thread(
                self.llm.chat_json,
                system="You are a code convention analyzer. Respond with valid JSON only.",
                user=prompt,
                temperature=0.1,  # Low temperature for consistent analysis
                timeout_seconds=45.0,
            )

            # Parse response
            if isinstance(response, str):
                data = json.loads(response)
            else:
                data = response

            logger.info("Convention analysis complete")

            return ConventionAnalysis(
                import_style=data.get("import_style", ""),
                class_naming=data.get("class_naming", ""),
                function_naming=data.get("function_naming", ""),
                type_hints_usage=data.get("type_hints_usage", ""),
                docstring_style=data.get("docstring_style", ""),
                error_handling=data.get("error_handling", ""),
                examples=data.get("examples", {}),
                analyzed_at=datetime.now(timezone.utc).isoformat(),
            )

        except Exception as e:
            logger.error("Convention analysis failed: %s", e, exc_info=True)
            # Return empty analysis rather than failing
            return ConventionAnalysis(
                analyzed_at=datetime.now(timezone.utc).isoformat(),
            )
