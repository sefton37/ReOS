# Repo Understanding System - Leverage Cheap Local LLMs

## Executive Summary

**Goal:** Build comprehensive repo understanding using our cost advantage (cheap local LLMs) to provide rich context for action generation.

**Key Insight:** We can run 100 local LLM calls for the cost of 1 GPT-4 call. Use this advantage to UNDERSTAND the repo deeply before generating code.

**Connection to Play Model:**
- **Acts** = Projects with repo_path
- **Act directory** = Storage for learned repo understanding
- **ProjectMemory** = Injects understanding into actions (Priority 0 ✓)
- **This system** = BUILDS the understanding that ProjectMemory injects

## The Opportunity

### Current State (After Priority 0)
✅ **Can inject context** into action generation
✅ **ProjectMemory exists** with decisions/patterns/corrections
❌ **But understanding is PASSIVE** - only what users explicitly add
❌ **Don't analyze the repo** to build understanding

### What We Can Do
Use cheap local LLMs (Ollama) to:
1. **Scan entire repo** - Not just changed files
2. **Analyze patterns** - What conventions exist?
3. **Map architecture** - How is code organized?
4. **Extract types** - What are the key data structures?
5. **Build import graph** - What imports what?
6. **Identify conventions** - Naming, structure, style
7. **Detect anti-patterns** - What to avoid?

**Cost comparison:**
- GPT-4: $0.03/1K tokens
- Claude Opus: $0.015/1K tokens
- Llama3 70B (local): ~$0.0001/1K tokens (300x cheaper!)

**What this means:**
- 1 GPT-4 call = 300 Llama3 analyses
- Can deeply analyze entire repo for < $1
- Can run analysis every session start

## Architecture

### Component 1: Act Context Store

**Storage per Act:**
```
~/.reos-data/play/acts/{act_id}/
  context/
    repo_analysis.json          # Overall repo structure
    architecture.json           # Architecture patterns
    conventions.json            # Naming, style, patterns
    types.json                  # Key type definitions
    imports.json                # Import dependency graph
    antipatterns.json           # What to avoid
    last_analyzed.txt           # Timestamp
```

**Benefits:**
- Per-project context (talking_rock ≠ other projects)
- Persistent across sessions
- Can be versioned with repo
- Easy to inspect/debug

### Component 2: Repo Analyzer (Cheap LLM)

**ActRepoAnalyzer:**
```python
class ActRepoAnalyzer:
    """Analyze a repo using cheap local LLMs to build understanding."""

    def __init__(self, act: ActInfo, llm: LocalLLM):
        self.act = act
        self.llm = llm  # Local model (Llama3, etc.)
        self.repo_path = Path(act.repo_path)
        self.context_dir = self._get_context_dir()

    async def analyze_if_needed(self) -> RepoContext:
        """Analyze repo if not recently analyzed."""
        if not self._needs_analysis():
            return self._load_cached()

        return await self._analyze_full()

    async def _analyze_full(self) -> RepoContext:
        """Run comprehensive repo analysis."""
        # Run multiple analyses in parallel (all cheap!)
        results = await asyncio.gather(
            self._analyze_structure(),
            self._analyze_architecture(),
            self._analyze_conventions(),
            self._analyze_types(),
            self._analyze_imports(),
            self._detect_antipatterns(),
        )

        context = RepoContext(*results)
        self._save_context(context)
        return context
```

### Component 3: Analysis Tasks (All Cheap LLM)

**1. Structure Analysis**
```python
async def _analyze_structure(self) -> StructureAnalysis:
    """Understand repo organization."""

    # Get file tree
    tree = self._get_file_tree(max_depth=4)

    # Ask local LLM
    prompt = f"""Analyze this Python project structure:

{tree}

Describe:
1. Main components (what's in each top-level directory?)
2. Entry points (where does execution start?)
3. Test organization
4. Documentation location

Format as JSON:
{{
  "components": [{{" name": "models", "purpose": "..."}}],
  "entry_points": ["main.py", ...],
  "test_strategy": "...",
  "docs_location": "..."
}}
"""

    response = await self.llm.chat_json(prompt)
    return StructureAnalysis.from_dict(response)
```

**2. Architecture Analysis**
```python
async def _analyze_architecture(self) -> ArchitectureAnalysis:
    """Detect architecture pattern."""

    # Read key files
    main_files = self._get_key_files()  # main.py, __init__.py, etc.

    prompt = f"""Analyze architecture pattern:

{main_files}

What architecture pattern is used?
- MVC
- Clean Architecture (layers)
- Hexagonal
- Microservices
- Monolith
- Other

Describe:
1. Pattern name
2. Layer structure
3. Dependency rules
4. Key abstractions

Format as JSON."""

    response = await self.llm.chat_json(prompt)
    return ArchitectureAnalysis.from_dict(response)
```

**3. Convention Analysis**
```python
async def _analyze_conventions(self) -> ConventionAnalysis:
    """Extract coding conventions."""

    # Sample multiple files
    samples = self._sample_files(count=10, pattern="*.py")

    prompt = f"""Analyze coding conventions in these samples:

{samples}

Identify:
1. Import style (from X import Y vs import X)
2. Class naming (UserModel vs User vs user_model)
3. Function naming (snake_case, camelCase?)
4. Type hints usage (always, sometimes, never?)
5. Docstring style (Google, NumPy, plain?)
6. Error handling patterns

Format as JSON with examples."""

    response = await self.llm.chat_json(prompt)
    return ConventionAnalysis.from_dict(response)
```

**4. Type Analysis**
```python
async def _analyze_types(self) -> TypeAnalysis:
    """Extract key type definitions."""

    # Use tree-sitter to extract classes/types
    types = self._extract_types_tree_sitter()

    # Ask LLM to categorize
    prompt = f"""Categorize these types:

{types}

Group into:
1. Data models (entities)
2. DTOs / API types
3. Configuration types
4. Error types
5. Other

For each, note:
- Field types (User.id is str? int?)
- Required vs optional
- Relationships

Format as JSON."""

    response = await self.llm.chat_json(prompt)
    return TypeAnalysis.from_dict(response)
```

**5. Import Graph Analysis**
```python
async def _analyze_imports(self) -> ImportAnalysis:
    """Build import dependency graph."""

    # Parse all imports using AST
    import_graph = self._build_import_graph()

    # Detect issues
    circular = self._detect_circular_imports(import_graph)

    prompt = f"""Analyze import structure:

Graph: {import_graph}
Circular: {circular}

Describe:
1. Layering (what imports what?)
2. Core vs peripheral modules
3. Forbidden patterns (what shouldn't import what?)
4. Suggested organization

Format as JSON."""

    response = await self.llm.chat_json(prompt)
    return ImportAnalysis.from_dict(response)
```

**6. Anti-pattern Detection**
```python
async def _detect_antipatterns(self) -> AntipatternAnalysis:
    """Find patterns to AVOID."""

    # Sample code
    samples = self._sample_files(count=15)

    prompt = f"""Find anti-patterns in this code:

{samples}

Look for:
1. Code smells (long functions, God classes)
2. Inconsistencies (mixed styles)
3. Bad practices (mutable defaults, broad excepts)
4. Security issues (SQL injection risks)

For each, describe:
- What it is
- Why it's bad
- How to avoid it

Format as JSON with examples."""

    response = await self.llm.chat_json(prompt)
    return AntipatternAnalysis.from_dict(response)
```

### Component 4: Context Injection (Into ProjectMemory)

**After analysis, inject into ProjectMemory:**

```python
async def inject_into_project_memory(
    repo_context: RepoContext,
    project_memory: ProjectMemoryStore,
    repo_path: str
):
    """Convert RepoContext into ProjectMemory decisions/patterns."""

    # Architecture decisions
    if repo_context.architecture:
        project_memory.add_decision(
            repo_path=repo_path,
            decision=f"Architecture: {repo_context.architecture.pattern_name}",
            rationale=f"Detected pattern with {repo_context.architecture.layer_count} layers",
            scope="global",
            source="analyzed",
        )

        # Layer rules as decisions
        for rule in repo_context.architecture.dependency_rules:
            project_memory.add_decision(
                repo_path=repo_path,
                decision=rule,
                rationale="Architecture constraint",
                scope="global",
                source="analyzed",
            )

    # Conventions as patterns
    if repo_context.conventions:
        project_memory.add_pattern(
            repo_path=repo_path,
            pattern_type="naming",
            description=f"Class naming: {repo_context.conventions.class_naming}",
            example_code=repo_context.conventions.class_example,
            source="analyzed",
        )

        project_memory.add_pattern(
            repo_path=repo_path,
            pattern_type="import",
            description=f"Import style: {repo_context.conventions.import_style}",
            example_code=repo_context.conventions.import_example,
            source="analyzed",
        )

    # Type definitions as decisions
    if repo_context.types:
        for entity, type_info in repo_context.types.data_models.items():
            project_memory.add_decision(
                repo_path=repo_path,
                decision=f"{entity} type structure: {type_info.definition}",
                rationale="Core data model",
                scope=f"module:{type_info.module}",
                source="analyzed",
            )

    # Anti-patterns as learned corrections
    if repo_context.antipatterns:
        for antipattern in repo_context.antipatterns:
            project_memory.add_correction(
                repo_path=repo_path,
                original_code=antipattern.example_bad,
                corrected_code=antipattern.example_good,
                reason=antipattern.why_bad,
                inferred_rule=f"AVOID: {antipattern.name}",
                source="analyzed",
            )
```

## Usage Flow

### Session Start (Automatic)

```python
# In create_optimized_context or similar
async def initialize_act_context(act: ActInfo, llm_local: LocalLLM, db: Database):
    """Initialize context for an Act at session start."""

    if not act.has_repo:
        return None  # Not in Code Mode

    # Analyze repo using cheap local LLM
    analyzer = ActRepoAnalyzer(act, llm_local)
    repo_context = await analyzer.analyze_if_needed()  # Cached if recent

    # Get or create ProjectMemory
    project_memory = ProjectMemoryStore(db)

    # Inject analyzed context into ProjectMemory
    await inject_into_project_memory(repo_context, project_memory, act.repo_path)

    return project_memory
```

### Action Generation (Priority 0 Active)

```python
# In determine_next_action (already implemented)
if ctx.project_memory:
    memory = ctx.project_memory.get_relevant_context(
        repo_path=repo_path,
        prompt=intention.what,
    )

    # This NOW includes analyzed context:
    # - Architecture decisions (injected from analysis)
    # - Convention patterns (injected from analysis)
    # - Type definitions (injected from analysis)
    # - Anti-patterns to avoid (injected from analysis)
```

## Cost Analysis

### Example: Analyzing talking_rock

**Repo stats:**
- ~150 Python files
- ~20K lines of code
- 6 analyses to run

**Token estimates:**
- Structure analysis: ~2K tokens
- Architecture analysis: ~3K tokens
- Convention analysis: ~5K tokens
- Type analysis: ~4K tokens
- Import analysis: ~3K tokens
- Anti-pattern analysis: ~8K tokens
**Total: ~25K tokens**

**Cost comparison:**
- With GPT-4: 25K * $0.03/1K = **$0.75 per analysis**
- With Llama3 local: 25K * $0.0001/1K = **$0.0025 per analysis**

**300x cheaper!**

**Frequency:**
- Run on first session: $0.0025
- Re-run if repo changed significantly: $0.0025
- Cache for 24 hours (or until git commits detected)

**Even if we run this 100 times:** $0.25 total

## Benefits

### 1. Fair Evaluation (Solves Priority 0)
- Models get comprehensive context
- Not guessing conventions
- Following explicit rules

### 2. Addresses Priorities 1-3
- **Priority 1** (File contents): Type analysis provides key definitions
- **Priority 2** (Import structure): Import analysis maps dependencies
- **Priority 3** (Architecture): Architecture analysis provides patterns

### 3. Competitive Advantage
- Big tech can't run 100 analyses per session (too expensive)
- We can (300x cheaper with local)
- Deeper understanding = better integration

### 4. Continuous Learning
- Analysis runs automatically
- Updates as repo evolves
- Learns from changes

### 5. Debuggability
- All analysis stored as JSON
- Can inspect what was learned
- Can manually edit if needed

## Implementation Plan

### Phase 1: Basic Analysis (1 week)
1. **ActRepoAnalyzer** class
   - Structure analysis
   - Convention analysis
   - Basic type extraction

2. **Context storage**
   - JSON files in Act directory
   - Caching logic
   - Timestamp tracking

3. **Integration**
   - Inject into ProjectMemory on session start
   - Wire into create_optimized_context()

### Phase 2: Advanced Analysis (1 week)
4. **Architecture detection**
   - Pattern recognition
   - Layer extraction
   - Dependency rules

5. **Import graph**
   - Full dependency map
   - Circular detection
   - Layering analysis

6. **Anti-pattern detection**
   - Code smell detection
   - Security scan
   - Style consistency

### Phase 3: Continuous Updates (1 week)
7. **Incremental analysis**
   - Only re-analyze changed areas
   - Git commit triggers
   - Diff-based updates

8. **Quality metrics**
   - Track analysis accuracy
   - User feedback integration
   - Confidence scores

## Success Metrics

### Quantitative
- **Analysis cost:** < $0.01 per session
- **Analysis time:** < 30 seconds for full repo
- **Cache hit rate:** > 80% (reuse previous analysis)
- **Context size:** 2-5KB injected per action

### Qualitative
- **Fewer type conflicts:** Models know User.id is str
- **No circular imports:** Models follow import rules
- **Consistent style:** Models match repo conventions
- **Architecture compliance:** Models respect layers

### Comparison
**Before (Priority 0 only):**
- Context: User-provided decisions only
- Completeness: ~20% (what users remember to add)

**After (With repo analysis):**
- Context: Analyzed + user-provided
- Completeness: ~90% (comprehensive understanding)

## Example: Real Context Improvement

### Before Priority 0 + Analysis
```
INTENTION: Add user authentication

Existing files: auth.py, user.py, database.py
```

### After Priority 0 (Now)
```
INTENTION: Add user authentication

Existing files: auth.py, user.py, database.py

PROJECT DECISIONS (must respect):
- Use dataclasses for data models (user added)
- Database IDs are strings (user added)
```

### After Priority 0 + Repo Analysis (Proposed)
```
INTENTION: Add user authentication

Existing files: auth.py, user.py, database.py

PROJECT DECISIONS (must respect):
- Use dataclasses for data models (user added)
- Database IDs are UUID strings (user added)
- Architecture: Clean Architecture with 3 layers (ANALYZED)
  * models/ = Pure data entities (no business logic)
  * services/ = Business logic (can import models, database)
  * api/ = HTTP endpoints (can import services, models)
- Import rules: (ANALYZED)
  * NEVER import api/ from services/ (circular risk)
  * NEVER import main.py from anywhere
- Type structure: User entity (ANALYZED)
  * User.id: str (UUID format)
  * User.email: str (required, unique)
  * User.password_hash: str (required)
  * Location: models/user_model.py

CODE PATTERNS (must follow):
- Class naming: {Entity}Model (e.g., UserModel not User) (user added)
- Import style: from X import Y (not import X) (ANALYZED)
- Function naming: snake_case (ANALYZED)
- Type hints: Always use (ANALYZED)
- Docstrings: Google style (ANALYZED)
- Error handling: Raise custom exceptions from exceptions.py (ANALYZED)

LEARNED (from previous corrections):
- Never use 'pass' in function bodies (user corrected)
- Always validate inputs before database operations (user corrected)

AVOID (anti-patterns detected):
- Don't use mutable default arguments (ANALYZED)
- Don't use bare except: (ANALYZED)
- Don't mix sync and async without clear separation (ANALYZED)

KEY FILES (type definitions):
models/user_model.py:
  @dataclass
  class UserModel:
      id: str  # UUID
      email: str
      password_hash: str
      created_at: datetime

services/auth_service.py:
  def authenticate(email: str, password: str) -> UserModel | None
  def hash_password(password: str) -> str
```

## Bottom Line

**Current State (Priority 0):**
- ✅ Can inject context
- ❌ Context is limited (user-provided only)

**Proposed (Repo Analysis):**
- ✅ Can inject context
- ✅ Context is comprehensive (analyzed + user-provided)
- ✅ Leverages our cost advantage (300x cheaper local LLM)
- ✅ Addresses Priorities 1, 2, 3 automatically

**Key Insight:**
We're not just storing what users tell us - we're **actively analyzing** the repo to build understanding. This is feasible because local LLMs are so cheap.

**Next Step:**
Implement Phase 1 (Basic Analysis) - 1 week to build ActRepoAnalyzer with structure/convention/type analysis.
