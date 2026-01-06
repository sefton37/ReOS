"""Intent Discovery - understanding user intent from multiple sources.

Intent is discovered by synthesizing understanding from:
1. The user's prompt (what they explicitly asked for)
2. The Play context (Act goals, Scene context, historical Beats)
3. The codebase state (existing patterns, architecture, conventions)
4. The Repository Map (semantic code understanding - symbols, dependencies)

This multi-source approach prevents hallucination by grounding intent
in concrete, observable reality.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.api_docs import APIDocumentation, APIDocumentationLookup
    from reos.code_mode.project_memory import ProjectMemoryStore
    from reos.code_mode.repo_map import RepoMap
    from reos.code_mode.sandbox import CodeSandbox
    from reos.providers import LLMProvider
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


@dataclass
class PromptIntent:
    """Intent extracted from the user's explicit request."""

    raw_prompt: str
    action_verb: str          # What they want done: "add", "fix", "refactor", etc.
    target: str               # What they want it done to: "function", "test", "module"
    constraints: list[str]    # Any explicit constraints mentioned
    examples: list[str]       # Any examples they provided
    summary: str              # One-sentence summary of the request


@dataclass
class PlayIntent:
    """Intent derived from The Play context."""

    act_goal: str             # The Act's overarching goal
    act_artifact: str         # What artifact this Act produces
    scene_context: str        # Current Scene context if any
    recent_work: list[str]    # Recent Beats/commits showing trajectory
    knowledge_hints: list[str]  # Relevant knowledge from KB


@dataclass
class CodebaseIntent:
    """Intent derived from codebase analysis."""

    language: str             # Primary language
    architecture_style: str   # "monolith", "microservices", "layered", etc.
    conventions: list[str]    # Observed conventions (naming, structure)
    related_files: list[str]  # Files likely relevant to this task
    existing_patterns: list[str]  # Patterns to follow
    test_patterns: str        # How tests are structured
    # RepoMap-enhanced fields
    relevant_symbols: list[str] = field(default_factory=list)  # Symbol names from repo map
    symbol_context: str = ""  # Formatted context from repo map
    # API Documentation (prevents hallucination)
    api_documentation: list["APIDocumentation"] = field(default_factory=list)


@dataclass
class DiscoveredIntent:
    """Complete intent synthesized from all sources.

    This is the single source of truth for what the system believes
    the user wants. It must be explicit and grounded in evidence.
    """

    # Core understanding
    goal: str                 # Clear statement of what should be accomplished
    why: str                  # Why this matters (from Play context)
    what: str                 # What specifically needs to change
    how_constraints: list[str]  # How it should be done (constraints)

    # Source intents
    prompt_intent: PromptIntent
    play_intent: PlayIntent
    codebase_intent: CodebaseIntent

    # Metadata
    confidence: float         # 0-1 confidence in this understanding
    ambiguities: list[str]    # Things that are unclear
    assumptions: list[str]    # Assumptions being made
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def summary(self) -> str:
        """Generate human-readable summary of discovered intent."""
        lines = [
            "## Discovered Intent",
            "",
            f"**Goal:** {self.goal}",
            f"**Why:** {self.why}",
            f"**What:** {self.what}",
            "",
        ]

        if self.how_constraints:
            lines.append("**Constraints:**")
            for c in self.how_constraints:
                lines.append(f"- {c}")
            lines.append("")

        if self.assumptions:
            lines.append("**Assumptions:**")
            for a in self.assumptions:
                lines.append(f"- {a}")
            lines.append("")

        if self.ambiguities:
            lines.append("**Ambiguities to resolve:**")
            for amb in self.ambiguities:
                lines.append(f"- {amb}")
            lines.append("")

        lines.append(f"**Confidence:** {self.confidence:.0%}")

        return "\n".join(lines)


class IntentDiscoverer:
    """Discovers user intent from multiple sources.

    Uses different analytical perspectives to build a complete picture
    of what the user wants, grounded in observable evidence.

    When a RepoMap is provided, uses semantic code understanding for:
    - Finding related files via symbol search
    - Getting relevant context within token budget
    - Understanding dependencies between files

    When a ProjectMemoryStore is provided, recalls project-specific:
    - Decisions ("We use dataclasses, not TypedDict")
    - Patterns ("Tests go in tests/, named test_*.py")
    - Corrections (learned preferences from past sessions)
    """

    def __init__(
        self,
        sandbox: "CodeSandbox",
        llm: "LLMProvider | None" = None,
        repo_map: "RepoMap | None" = None,
        project_memory: "ProjectMemoryStore | None" = None,
        api_lookup: "APIDocumentationLookup | None" = None,
    ) -> None:
        self.sandbox = sandbox
        self._llm = llm
        self._repo_map = repo_map
        self._project_memory = project_memory
        self._api_lookup = api_lookup

    def discover(
        self,
        prompt: str,
        act: Act,
        knowledge_context: str = "",
    ) -> DiscoveredIntent:
        """Discover intent from all available sources.

        Args:
            prompt: The user's explicit request.
            act: The active Act with context.
            knowledge_context: Optional knowledge base context.

        Returns:
            DiscoveredIntent synthesizing all sources.
        """
        # Phase 1: Extract intent from each source
        prompt_intent = self._analyze_prompt(prompt)
        play_intent = self._analyze_play_context(act, knowledge_context)
        codebase_intent = self._analyze_codebase(prompt)

        # Phase 1.5: Inject project memory context
        if self._project_memory is not None:
            self._inject_project_memory(
                prompt, act.repo_path, play_intent, codebase_intent
            )

        # Phase 2: Synthesize into unified intent
        return self._synthesize_intent(
            prompt=prompt,
            prompt_intent=prompt_intent,
            play_intent=play_intent,
            codebase_intent=codebase_intent,
        )

    def _analyze_prompt(self, prompt: str) -> PromptIntent:
        """Extract intent from the user's explicit prompt."""
        if self._llm is not None:
            return self._analyze_prompt_with_llm(prompt)
        return self._analyze_prompt_heuristic(prompt)

    def _analyze_prompt_heuristic(self, prompt: str) -> PromptIntent:
        """Fallback prompt analysis without LLM."""
        # Simple heuristic extraction
        words = prompt.lower().split()

        # Find action verb
        action_verbs = ["add", "create", "write", "implement", "fix", "debug",
                       "refactor", "update", "modify", "remove", "delete", "test"]
        action_verb = next((w for w in words if w in action_verbs), "implement")

        # Find target
        targets = ["function", "class", "method", "test", "module", "file",
                  "feature", "endpoint", "api", "bug", "error"]
        target = next((w for w in words if w in targets), "code")

        return PromptIntent(
            raw_prompt=prompt,
            action_verb=action_verb,
            target=target,
            constraints=[],
            examples=[],
            summary=prompt[:200],
        )

    def _analyze_prompt_with_llm(self, prompt: str) -> PromptIntent:
        """Extract intent from prompt using LLM."""
        system = """You analyze user requests to extract structured intent.
Output JSON with these fields:
{
    "action_verb": "the main action (add, fix, create, refactor, etc.)",
    "target": "what the action applies to (function, class, test, etc.)",
    "constraints": ["any explicit constraints or requirements"],
    "examples": ["any examples the user provided"],
    "summary": "one clear sentence summarizing the request"
}"""

        try:
            response = self._llm.chat_json(  # type: ignore
                system=system,
                user=prompt,
                temperature=0.1,
            )
            data = json.loads(response)
            return PromptIntent(
                raw_prompt=prompt,
                action_verb=data.get("action_verb", "implement"),
                target=data.get("target", "code"),
                constraints=data.get("constraints", []),
                examples=data.get("examples", []),
                summary=data.get("summary", prompt[:200]),
            )
        except Exception as e:
            logger.warning("LLM prompt analysis failed: %s", e)
            return self._analyze_prompt_heuristic(prompt)

    def _analyze_play_context(
        self,
        act: Act,
        knowledge_context: str,
    ) -> PlayIntent:
        """Extract intent from The Play context."""
        # Get Act context
        act_goal = act.title
        act_artifact = act.artifact_type or "software"

        # Parse code_config for additional context
        code_config = act.code_config or {}
        language = code_config.get("language", "unknown")

        # Get recent work from git
        recent_work = []
        try:
            commits = self.sandbox.recent_commits(count=5)
            recent_work = [c.message for c in commits]
        except Exception:
            pass

        # Parse knowledge hints
        knowledge_hints = []
        if knowledge_context:
            # Extract key points from knowledge context
            for line in knowledge_context.split("\n"):
                if line.strip() and len(line) < 200:
                    knowledge_hints.append(line.strip())
            knowledge_hints = knowledge_hints[:5]  # Limit

        return PlayIntent(
            act_goal=act_goal,
            act_artifact=act_artifact,
            scene_context="",  # TODO: Get from active Scene
            recent_work=recent_work,
            knowledge_hints=knowledge_hints,
        )

    def _inject_project_memory(
        self,
        prompt: str,
        repo_path: str,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> None:
        """Inject project memory context into intent.

        Retrieves relevant memories and injects them into:
        - play_intent.knowledge_hints (decisions, learned corrections)
        - codebase_intent.existing_patterns (project patterns)
        - codebase_intent.conventions (inferred from decisions)
        """
        if self._project_memory is None:
            return

        try:
            memory_context = self._project_memory.get_relevant_context(
                repo_path=repo_path,
                prompt=prompt,
                file_paths=codebase_intent.related_files if codebase_intent.related_files else None,
            )

            if memory_context.is_empty():
                return

            # Inject decisions as knowledge hints
            for decision in memory_context.relevant_decisions:
                hint = f"PROJECT DECISION: {decision.decision}"
                if hint not in play_intent.knowledge_hints:
                    play_intent.knowledge_hints.append(hint)

            # Inject patterns into codebase conventions/patterns
            for pattern in memory_context.applicable_patterns:
                if pattern.description not in codebase_intent.existing_patterns:
                    codebase_intent.existing_patterns.append(pattern.description)

            # Inject learned corrections as knowledge hints
            for correction in memory_context.recent_corrections:
                if correction.inferred_rule:
                    hint = f"LEARNED: {correction.inferred_rule}"
                    if hint not in play_intent.knowledge_hints:
                        play_intent.knowledge_hints.append(hint)

            logger.debug(
                "Injected project memory: %d decisions, %d patterns, %d corrections",
                len(memory_context.relevant_decisions),
                len(memory_context.applicable_patterns),
                len(memory_context.recent_corrections),
            )

        except Exception as e:
            logger.warning("Failed to inject project memory: %s", e)

    def _analyze_codebase(self, prompt: str) -> CodebaseIntent:
        """Extract intent from codebase analysis.

        If RepoMap is available and indexed, uses semantic search
        to find relevant code. Otherwise falls back to grep-based search.
        """
        # Detect language
        language = self._detect_language()

        # Detect architecture style
        architecture = self._detect_architecture()

        # Find related files - use RepoMap if available
        related = self._find_related_files(prompt)

        # Detect conventions
        conventions = self._detect_conventions()

        # Detect test patterns
        test_patterns = self._detect_test_patterns()

        # Get RepoMap-enhanced context if available
        relevant_symbols: list[str] = []
        symbol_context = ""
        existing_patterns: list[str] = []

        if self._repo_map is not None:
            try:
                # Get relevant context using RepoMap
                symbol_context = self._repo_map.get_relevant_context(
                    prompt, token_budget=600
                )

                # Find relevant symbols
                symbols = self._find_symbols_for_prompt(prompt)
                relevant_symbols = [s.qualified_name for s in symbols[:10]]

                # Extract patterns from found symbols
                existing_patterns = self._extract_patterns_from_symbols(symbols)

            except Exception as e:
                logger.debug("RepoMap analysis failed: %s", e)

        # Look up API documentation to prevent hallucination
        api_documentation: list["APIDocumentation"] = []
        if self._api_lookup is not None:
            try:
                # Extract symbols from prompt
                prompt_symbols = self._api_lookup.extract_symbols_from_prompt(prompt)

                # Also extract from related files
                for file_path in related[:3]:  # Limit to avoid slowdown
                    try:
                        content = self.sandbox.read_file(file_path)
                        code_symbols = self._api_lookup.extract_symbols_from_code(
                            content, language
                        )
                        prompt_symbols.extend(code_symbols)
                    except Exception:
                        pass

                # Deduplicate and lookup
                unique_symbols = list(set(prompt_symbols))[:15]
                api_documentation = self._api_lookup.get_documentation_batch(
                    unique_symbols, language
                )
                logger.debug(
                    "Found API documentation for %d symbols",
                    len(api_documentation),
                )
            except Exception as e:
                logger.debug("API documentation lookup failed: %s", e)

        return CodebaseIntent(
            language=language,
            architecture_style=architecture,
            conventions=conventions,
            related_files=related,
            existing_patterns=existing_patterns,
            test_patterns=test_patterns,
            relevant_symbols=relevant_symbols,
            symbol_context=symbol_context,
            api_documentation=api_documentation,
        )

    def _detect_language(self) -> str:
        """Detect primary language of the codebase."""
        py_files = len(self.sandbox.find_files("**/*.py"))
        ts_files = len(self.sandbox.find_files("**/*.ts"))
        js_files = len(self.sandbox.find_files("**/*.js"))
        rs_files = len(self.sandbox.find_files("**/*.rs"))
        go_files = len(self.sandbox.find_files("**/*.go"))

        counts = {
            "python": py_files,
            "typescript": ts_files,
            "javascript": js_files,
            "rust": rs_files,
            "go": go_files,
        }

        if max(counts.values()) == 0:
            return "unknown"

        return max(counts, key=lambda k: counts[k])

    def _detect_architecture(self) -> str:
        """Detect architecture style from structure."""
        has_src = len(self.sandbox.find_files("src/**/*")) > 0
        has_tests = len(self.sandbox.find_files("tests/**/*")) > 0
        has_services = len(self.sandbox.find_files("**/services/**/*")) > 0
        has_handlers = len(self.sandbox.find_files("**/handlers/**/*")) > 0

        if has_services and has_handlers:
            return "layered"
        if has_src and has_tests:
            return "standard"
        return "flat"

    def _find_related_files(self, prompt: str) -> list[str]:
        """Find files likely relevant to the request.

        Uses RepoMap for semantic search when available, falling back
        to grep-based search otherwise.
        """
        related: list[str] = []

        # Try RepoMap first for better context
        if self._repo_map is not None:
            try:
                # Find symbols related to the prompt
                symbols = self._find_symbols_for_prompt(prompt)
                for sym in symbols:
                    if hasattr(sym, "location") and hasattr(sym.location, "file_path"):
                        file_path = sym.location.file_path
                        if file_path not in related:
                            related.append(file_path)

                # Also find callers of those symbols for broader context
                for sym in symbols[:3]:  # Limit to avoid too many lookups
                    if hasattr(sym, "name") and hasattr(sym, "location"):
                        try:
                            callers = self._repo_map.find_callers(
                                sym.name, sym.location.file_path
                            )
                            for caller in callers[:2]:
                                if hasattr(caller, "file_path"):
                                    if caller.file_path not in related:
                                        related.append(caller.file_path)
                        except Exception:
                            pass

                if related:
                    return related[:10]
            except Exception as e:
                logger.debug("RepoMap file search failed: %s", e)

        # Fallback: grep-based search
        words = prompt.lower().split()
        for word in words:
            # Search for files matching the word
            matches = self.sandbox.grep(
                pattern=word,
                glob_pattern="**/*.py",
                max_results=5,
            )
            for m in matches:
                if m.path not in related:
                    related.append(m.path)

        return related[:10]  # Limit to 10

    def _detect_conventions(self) -> list[str]:
        """Detect coding conventions from the codebase."""
        conventions = []

        # Check for type hints
        try:
            type_hints = self.sandbox.grep(
                pattern=r"def \w+\([^)]*:[^)]+\)",
                glob_pattern="**/*.py",
                max_results=1,
            )
            if type_hints:
                conventions.append("Uses type hints")
        except Exception:
            pass

        # Check for docstrings
        try:
            docstrings = self.sandbox.grep(
                pattern=r'""".*"""',
                glob_pattern="**/*.py",
                max_results=1,
            )
            if docstrings:
                conventions.append("Uses docstrings")
        except Exception:
            pass

        # Check for dataclasses
        try:
            dataclasses = self.sandbox.grep(
                pattern=r"@dataclass",
                glob_pattern="**/*.py",
                max_results=1,
            )
            if dataclasses:
                conventions.append("Uses dataclasses")
        except Exception:
            pass

        return conventions

    def _detect_test_patterns(self) -> str:
        """Detect how tests are structured."""
        test_files = self.sandbox.find_files("**/test_*.py")
        if test_files:
            return "pytest (test_*.py)"

        spec_files = self.sandbox.find_files("**/*_spec.py")
        if spec_files:
            return "spec (*_spec.py)"

        return "unknown"

    def _find_symbols_for_prompt(self, prompt: str) -> list[Any]:
        """Find symbols relevant to the prompt using RepoMap.

        Extracts keywords from the prompt and searches for matching symbols.

        Args:
            prompt: The user's request.

        Returns:
            List of Symbol objects from the repo map.
        """
        if self._repo_map is None:
            return []

        symbols = []

        # Extract potential symbol names from prompt
        words = prompt.split()
        keywords = []

        for word in words:
            # Clean word of punctuation
            clean = word.strip(".,!?()[]{}:;\"'")
            # Look for CamelCase or snake_case words as likely symbol names
            if (
                len(clean) > 2
                and (clean[0].isupper() or "_" in clean or clean.islower())
                and clean not in ("the", "and", "for", "with", "from", "that", "this")
            ):
                keywords.append(clean)

        # Search for each keyword
        for keyword in keywords[:5]:  # Limit to 5 keywords
            try:
                found = self._repo_map.find_symbol(keyword)
                for sym in found[:3]:  # Limit per keyword
                    if sym not in symbols:
                        symbols.append(sym)
            except Exception as e:
                logger.debug("Symbol search failed for '%s': %s", keyword, e)

        return symbols[:15]  # Return at most 15 symbols

    def _extract_patterns_from_symbols(self, symbols: list[Any]) -> list[str]:
        """Extract coding patterns from found symbols.

        Analyzes symbols to identify patterns that should be followed.

        Args:
            symbols: List of Symbol objects.

        Returns:
            List of pattern descriptions.
        """
        patterns = []

        if not symbols:
            return patterns

        # Check for decorator patterns
        decorators_seen: set[str] = set()
        for sym in symbols:
            if hasattr(sym, "decorators") and sym.decorators:
                decorators_seen.update(sym.decorators)

        if "@dataclass" in decorators_seen:
            patterns.append("Use @dataclass for data classes")
        if "@property" in decorators_seen:
            patterns.append("Use @property for computed attributes")
        if any("pytest" in d or "fixture" in d for d in decorators_seen):
            patterns.append("Use pytest fixtures for test setup")

        # Check for type hint patterns
        has_type_hints = any(
            hasattr(sym, "signature") and sym.signature and "->" in sym.signature
            for sym in symbols
        )
        if has_type_hints:
            patterns.append("Include return type annotations")

        # Check for docstring patterns
        has_docstrings = any(
            hasattr(sym, "docstring") and sym.docstring
            for sym in symbols
        )
        if has_docstrings:
            patterns.append("Include docstrings for public functions")

        # Check for naming conventions
        class_symbols = [s for s in symbols if hasattr(s, "kind") and str(s.kind) == "SymbolKind.CLASS"]
        func_symbols = [s for s in symbols if hasattr(s, "kind") and str(s.kind) == "SymbolKind.FUNCTION"]

        if class_symbols and all(s.name[0].isupper() for s in class_symbols if s.name):
            patterns.append("Use PascalCase for class names")
        if func_symbols and all("_" in s.name or s.name.islower() for s in func_symbols if s.name):
            patterns.append("Use snake_case for function names")

        return patterns

    def _synthesize_intent(
        self,
        prompt: str,
        prompt_intent: PromptIntent,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> DiscoveredIntent:
        """Synthesize all intents into unified understanding."""
        if self._llm is not None:
            return self._synthesize_with_llm(
                prompt, prompt_intent, play_intent, codebase_intent
            )
        return self._synthesize_heuristic(
            prompt, prompt_intent, play_intent, codebase_intent
        )

    def _synthesize_heuristic(
        self,
        prompt: str,
        prompt_intent: PromptIntent,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> DiscoveredIntent:
        """Synthesize without LLM."""
        goal = prompt_intent.summary
        why = f"Part of {play_intent.act_goal}"
        what = f"{prompt_intent.action_verb} {prompt_intent.target}"

        constraints = list(prompt_intent.constraints)
        if codebase_intent.language != "unknown":
            constraints.append(f"Use {codebase_intent.language}")
        if codebase_intent.conventions:
            constraints.extend(codebase_intent.conventions)

        return DiscoveredIntent(
            goal=goal,
            why=why,
            what=what,
            how_constraints=constraints,
            prompt_intent=prompt_intent,
            play_intent=play_intent,
            codebase_intent=codebase_intent,
            confidence=0.7,
            ambiguities=[],
            assumptions=[],
        )

    def _synthesize_with_llm(
        self,
        prompt: str,
        prompt_intent: PromptIntent,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> DiscoveredIntent:
        """Synthesize using LLM for deeper understanding."""
        system = """You synthesize user intent from multiple sources into a clear understanding.

Given:
1. The user's prompt and extracted intent
2. The Play context (project goals, recent work)
3. The codebase context (language, architecture, conventions)

Output JSON:
{
    "goal": "Clear, specific statement of what should be accomplished",
    "why": "Why this matters in the context of the project",
    "what": "Specifically what needs to change in the code",
    "how_constraints": ["Constraints on how to implement"],
    "confidence": 0.0-1.0,
    "ambiguities": ["Things that are unclear"],
    "assumptions": ["Assumptions being made"]
}

Be specific. Ground everything in the provided context. Flag ambiguities honestly."""

        # Build symbol context section if available
        symbol_section = ""
        if codebase_intent.symbol_context:
            symbol_section = f"""

RELEVANT CODE SYMBOLS:
{codebase_intent.symbol_context[:1500]}
"""
        if codebase_intent.relevant_symbols:
            symbol_section += f"""
- Key Symbols: {', '.join(codebase_intent.relevant_symbols[:8])}
"""
        if codebase_intent.existing_patterns:
            symbol_section += f"""
- Existing Patterns: {', '.join(codebase_intent.existing_patterns[:5])}
"""

        context = f"""
USER PROMPT: {prompt}

PROMPT ANALYSIS:
- Action: {prompt_intent.action_verb}
- Target: {prompt_intent.target}
- Summary: {prompt_intent.summary}

PLAY CONTEXT:
- Act Goal: {play_intent.act_goal}
- Artifact: {play_intent.act_artifact}
- Recent Work: {', '.join(play_intent.recent_work[:3])}

CODEBASE CONTEXT:
- Language: {codebase_intent.language}
- Architecture: {codebase_intent.architecture_style}
- Conventions: {', '.join(codebase_intent.conventions)}
- Related Files: {', '.join(codebase_intent.related_files[:5])}
{symbol_section}"""

        try:
            response = self._llm.chat_json(  # type: ignore
                system=system,
                user=context,
                temperature=0.2,
            )
            data = json.loads(response)

            return DiscoveredIntent(
                goal=data.get("goal", prompt_intent.summary),
                why=data.get("why", f"Part of {play_intent.act_goal}"),
                what=data.get("what", f"{prompt_intent.action_verb} {prompt_intent.target}"),
                how_constraints=data.get("how_constraints", []),
                prompt_intent=prompt_intent,
                play_intent=play_intent,
                codebase_intent=codebase_intent,
                confidence=data.get("confidence", 0.7),
                ambiguities=data.get("ambiguities", []),
                assumptions=data.get("assumptions", []),
            )
        except Exception as e:
            logger.warning("LLM synthesis failed: %s", e)
            return self._synthesize_heuristic(
                prompt, prompt_intent, play_intent, codebase_intent
            )
