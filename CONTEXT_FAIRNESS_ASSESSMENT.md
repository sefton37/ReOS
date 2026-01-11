# Context Fairness Assessment: Are We Fairly Evaluating Models?

## Executive Summary

**Critical Finding:** 🔴 **Evaluation is NOT Fair**

We're measuring "integration quality" but **NOT providing models the repo context** they need to integrate well. This is like testing a chef's ability to follow a recipe, then not giving them the recipe, and blaming them when it tastes wrong.

**The Problem:**
- We verify: "Does code integrate with the repo?" ✓
- We provide: Filenames and 3 keyword searches ✗
- We don't provide: Patterns, conventions, types, architecture ✗

**Impact:**
- Model A gets lucky, guesses conventions correctly → "95% success"
- Model B makes different guess → "60% success"
- We conclude: "Model A is better at integration"
- **Reality:** Both models were guessing blindly

## What Context Models Currently Receive

### During Action Generation (intention.py:950-1009)

**1. Intention + Acceptance:**
```python
INTENTION: {intention.what}
ACCEPTANCE: {intention.acceptance}
```

**2. Last 3 Cycles History:**
```python
1. Tried: create user.py with User class
   Result: File created successfully
   Judgment: PARTIAL
   Reflection: Need to add database integration
```

**3. Existing Files (up to 20):**
```python
Existing files in repo: models.py, database.py, api.py, utils.py, ...
```
**Note:** Just NAMES, not contents!

**4. Tool-Gathered Context (if tool_provider available):**

- **Codebase grep:** Top 3 keywords, 5 results each, 500 chars
  ```
  [Codebase search for 'User']
  models.py:15: class User:
  database.py:42: def get_user(id):
  ...
  ```

- **Project structure:** Max depth 2, 800 chars
  ```
  [Project structure]
  src/
    models/
    database/
    api/
  ```

- **Library docs:** 2 libraries, 600 chars each
  ```
  [Documentation for 'fastapi']
  FastAPI is a modern web framework...
  ```

- **Error solutions:** If debugging, 2 results, 500 chars
  ```
  [Web search for solution]
  Stack Overflow: TypeError User.id...
  ```

**Total Context:** ~4KB of text

### What Models DON'T Receive

#### ❌ ProjectMemory Decisions

ProjectMemory EXISTS and stores decisions like:
- "We use dataclasses, not TypedDict"
- "All API endpoints return JSON with snake_case keys"
- "Prefer composition over inheritance"

**But it's NOT injected into action generation!**

**Where it IS used:** Only in Intent planning (contract.py:919-931)
**Where it's NOT used:** RIVA work() cycle where actions are generated

**Code Evidence:**
```python
# contract.py:919 - Intent planning gets it
if self._project_memory is not None:
    memory_context = self._project_memory.get_relevant_context(...)
    decisions_section = f"""
PROJECT DECISIONS (must respect):
{decisions}
"""

# intention.py:448 - WorkContext DOESN'T include project_memory
class WorkContext:
    sandbox: "CodeSandbox"
    llm: "LLMProvider | None"
    checkpoint: HumanCheckpoint | AutoCheckpoint
    # ... NO project_memory field!
```

#### ❌ Pattern Definitions

PatternSuccessTracker EXISTS per-repo:
- "Import style: use `from typing import` not `import typing`"
- "Class naming: `UserModel` not `User`"
- "Error handling: use `try/except/finally` pattern"

**Not provided to models during code generation!**

#### ❌ File Contents

Models see: `"Existing files: models.py, database.py, api.py"`
Models need: Type definitions, imports, function signatures

**Example:**
```python
# Model sees:
"Existing files: models.py"

# Model needs:
"""
# models.py
from dataclasses import dataclass

@dataclass
class User:
    id: str  # <-- CRITICAL: it's str not int!
    name: str
    email: str
"""
```

#### ❌ Import Structure

Models don't know:
- What imports what
- If circular imports exist
- Import conventions (absolute vs relative)

#### ❌ Type Definitions

Models don't know:
- User.id is `str` in models.py
- But database expects `int`
- Leading to type conflicts we then measure as "integration failure"

#### ❌ Architecture Patterns

Models don't know:
- "This repo uses MVC"
- "This repo uses Clean Architecture"
- "Controllers go in /api, models in /models"

#### ❌ Learned Corrections

When users fix AI code, ProjectMemory learns:
```python
LEARNED: Never use 'pass' in function bodies
LEARNED: Always validate inputs before database operations
```

**Not provided during action generation!**

## Concrete Example: The Unfair CRM Test

### Scenario: "Make a CRM with user management"

**Model receives:**
```
INTENTION: Create user management system
ACCEPTANCE: Can create, read, update, delete users

Existing files: main.py, config.py

[Codebase search for 'user']
No matches found
```

**Model doesn't receive:**
```
PROJECT DECISIONS:
- Use dataclasses for data models (not TypedDict or attrs)
- All database IDs are strings (UUID format)
- Import style: from X import Y (not import X)
- API responses use snake_case (not camelCase)
- Error handling: always raise custom exceptions (not ValueError)

PATTERNS:
- Class naming: {Entity}Model (e.g., UserModel not User)
- File structure: models/{entity}_model.py
- Database: Use SQLAlchemy ORM (not raw SQL)

TYPE DEFINITIONS (from existing code):
# config.py
DATABASE_URL: str = "postgresql://..."
API_VERSION: str = "v1"

# main.py
from fastapi import FastAPI
app: FastAPI = FastAPI()
```

### What Happens

**Model generates:**
```python
# user.py
class User:  # ❌ Should be UserModel
    id: int  # ❌ Should be str (UUID)
    name: str

# Uses attrs instead of dataclasses ❌
# Uses camelCase in API ❌
# Creates circular import with main.py ❌
```

**Our Evaluation:**
```
❌ Type conflict: User.id (int vs str expected)
❌ Naming inconsistency: User (should be UserModel)
❌ Pattern violation: attrs (should be dataclasses)
❌ Circular import detected
❌ Architecture violation: file in wrong location

VERDICT: Integration FAILED
Lesson: "This model is bad at integration"
```

**Reality:**
Model had NO WAY to know:
- IDs should be strings
- Naming convention is {Entity}Model
- Repo uses dataclasses
- Where files should go

**Fair Evaluation Would Be:**
```
Given context:
- Use dataclasses for models
- IDs are UUID strings
- Class naming: {Entity}Model
- Place in models/ directory

Did model follow these rules? YES/NO
```

## The Fairness Problem

### What We're Actually Testing

**Current Test:**
"Can models magically guess repo conventions and architecture without being told?"

**Fair Test Would Be:**
"Given repo conventions and architecture, can models follow them?"

### The Evaluation Bias

**Scenario 1: Model A (Lucky Guess)**
```python
# Model A happens to guess:
class UserModel:  # ✓ Lucky guess on naming!
    id: str  # ✓ Lucky guess on type!
```
**Result:** "Model A has 90% integration success!"

**Scenario 2: Model B (Different Guess)**
```python
# Model B guesses differently:
class User:  # ✗ Wrong naming
    id: int  # ✗ Wrong type
```
**Result:** "Model B has 60% integration success!"

**Truth:** Both guessed. Model A got lucky. Model B didn't.

**Our Conclusion:** "Model A is better at integration"
**Reality:** Neither model knew the conventions. One got lucky.

## Impact on Learning

### What We Think We're Learning

After 10 CRM attempts with Claude Sonnet:
- 7 succeeded (70% success rate)
- Claude Sonnet is good at CRM integration

### What We're Actually Learning

After 10 CRM attempts with Claude Sonnet:
- 7 times Claude guessed conventions correctly by luck
- 3 times Claude guessed wrong
- **We learned:** Claude Sonnet's guessing luck is 70%
- **We didn't learn:** How Claude performs with actual context

### The Compounding Problem

**Attempt 1:** Model creates user.py with `class User, id: int`
- Integration fails (should be UserModel, id: str)
- We measure: "Integration failure"
- ProjectMemory learns: "Should use UserModel and str IDs"
- **But this is NOT fed back to the model in attempt 2!**

**Attempt 2:** Model makes same mistake
- Integration fails again
- We measure: "Model doesn't learn"
- **Reality:** Model was never told what to learn!

**Result:** We think the model "doesn't improve" when really we're not providing the lessons.

## Where Context IS Provided (Intent Planning)

### Contract Generation (contract.py:917-931)

```python
# BUILD PROJECT DECISIONS SECTION
if self._project_memory is not None:
    memory_context = self._project_memory.get_relevant_context(...)
    if memory_context.relevant_decisions:
        decisions = "\n".join(
            f"- {d.decision}" for d in memory_context.relevant_decisions
        )
        decisions_section = f"""
PROJECT DECISIONS (must respect):
{decisions}
"""
```

**This IS injected into acceptance criteria generation!**

### Intent Planner (intent.py:469-519)

```python
def _inject_project_memory(self, prompt, repo_path, play_intent, codebase_intent):
    """Inject project memory into intent."""

    # Inject decisions as knowledge hints
    for decision in memory_context.relevant_decisions:
        hint = f"PROJECT DECISION: {decision.decision}"
        play_intent.knowledge_hints.append(hint)

    # Inject patterns
    for pattern in memory_context.applicable_patterns:
        codebase_intent.existing_patterns.append(pattern.description)

    # Inject learned corrections
    for correction in memory_context.recent_corrections:
        if correction.inferred_rule:
            hint = f"LEARNED: {correction.inferred_rule}"
            play_intent.knowledge_hints.append(hint)
```

**This IS injected when planning intentions!**

### The Gap

**Intent Planning:** Gets ProjectMemory ✓
**Action Generation:** Does NOT get ProjectMemory ✗

**Why This Matters:**
- Intent planning happens once at the start
- Action generation happens 10-50 times during work
- Most integration decisions happen during action generation
- That's where models need context, but don't get it!

## What Fair Evaluation Requires

### Minimum Context for Fair Integration Testing

**1. ProjectMemory Decisions:**
```
PROJECT DECISIONS:
- Use dataclasses for data models
- Database IDs are UUID strings
- Import style: from X import Y
- API responses use snake_case
- Error handling with custom exceptions
```

**2. Repo Patterns:**
```
CODE PATTERNS:
- Class naming: {Entity}Model
- File structure: {category}/{entity}_{type}.py
- Database: SQLAlchemy ORM required
- Testing: pytest with fixtures in conftest.py
```

**3. Type Context (for related files):**
```python
TYPE CONTEXT (from existing code):
# models/base.py
class BaseModel:
    id: str  # UUID format
    created_at: datetime
    updated_at: datetime

# database/connection.py
def get_db() -> Session:
    # Returns SQLAlchemy session
```

**4. Import Structure:**
```
IMPORT STRUCTURE:
- models/ imported by services/
- services/ imported by api/
- api/ imported by main.py
AVOID: Circular imports between models/ and services/
```

**5. Architecture Guidelines:**
```
ARCHITECTURE:
Pattern: Clean Architecture (layers pattern)
- models/: Data entities (no business logic)
- services/: Business logic (uses models, no HTTP)
- api/: HTTP endpoints (uses services)
- No direct model-to-API calls
```

### With This Context, Fair Evaluation Is:

**Question:** Given these conventions, did the model follow them?
- ✓ If yes: Model is good at integration (when given context)
- ✗ If no: Model struggles with following guidelines

**Not:** Did the model guess conventions correctly?

## Recommendations

### Priority 0: Fix Immediate Unfairness (CRITICAL)

**Problem:** ProjectMemory exists but isn't used in action generation

**Fix:** Add project_memory to WorkContext

```python
# intention.py
class WorkContext:
    sandbox: "CodeSandbox"
    llm: "LLMProvider | None"
    checkpoint: HumanCheckpoint | AutoCheckpoint
    project_memory: "ProjectMemoryStore | None" = None  # ADD THIS
    # ... rest of fields
```

**Inject into action prompts:**
```python
# intention.py:determine_action()

# Get project memory context
memory_context_section = ""
if ctx.project_memory:
    memory = ctx.project_memory.get_relevant_context(
        repo_path=str(ctx.sandbox.repo_path),
        prompt=intention.what,
    )
    if memory.relevant_decisions:
        decisions = "\n".join(f"- {d.decision}" for d in memory.relevant_decisions)
        memory_context_section = f"""

PROJECT DECISIONS (must respect):
{decisions}
"""
    if memory.applicable_patterns:
        patterns = "\n".join(f"- {p.description}" for p in memory.applicable_patterns)
        memory_context_section += f"""

CODE PATTERNS (must follow):
{patterns}
"""

user_prompt = f"""Determine the next action for this intention:

INTENTION: {intention.what}
ACCEPTANCE: {intention.acceptance}
{history}{existing_context}{memory_context_section}

What should we try next?"""
```

**Effort:** 2-3 hours
**Impact:** CRITICAL - Makes current evaluation fair

### Priority 1: Provide File Contents Context

**Problem:** Models see filenames, not contents

**Current:**
```
Existing files: models.py, database.py, api.py
```

**Should be:**
```
Existing files and key definitions:

models.py:
  - class UserModel(BaseModel): id: str, name: str, email: str
  - class PostModel(BaseModel): id: str, author_id: str, content: str

database.py:
  - def get_session() -> Session
  - def get_user(id: str) -> UserModel

api.py:
  - @app.post("/users", response_model=UserModel)
  - @app.get("/users/{id}", response_model=UserModel)
```

**Implementation:**
```python
def get_file_summaries(ctx: WorkContext, file_paths: list[str]) -> str:
    """Extract key definitions from files."""
    summaries = []
    for path in file_paths[:10]:  # Limit to 10 files
        content = ctx.sandbox.read(path)
        # Use tree-sitter to extract classes, functions, types
        summary = extract_definitions(content)
        summaries.append(f"{path}:\n{summary}")
    return "\n\n".join(summaries)
```

**Effort:** 1 day
**Impact:** HIGH - Prevents type conflicts, import errors

### Priority 2: Provide Import Structure

**Problem:** Models don't know what imports what

**Add to context:**
```
IMPORT STRUCTURE:
  main.py imports: api/, services/, config
  api/ imports: services/, models/
  services/ imports: models/, database/
  models/ imports: (nothing - leaf nodes)

CIRCULAR IMPORT RISKS:
  - Do NOT import api/ from services/
  - Do NOT import main.py from anywhere
```

**Implementation:**
```python
def analyze_import_graph(ctx: WorkContext) -> str:
    """Build import dependency graph."""
    # Scan all Python files
    # Extract imports
    # Build DAG
    # Return summary showing what imports what
    # Flag any existing circular imports
```

**Effort:** 2 days
**Impact:** HIGH - Prevents circular imports

### Priority 3: Provide Architecture Context

**Problem:** Models don't know repo architecture

**Add to context:**
```
ARCHITECTURE PATTERN: Clean Architecture (3-layer)

Layer 1 - Models (models/):
  - Pure data entities
  - No business logic
  - No dependencies on other layers

Layer 2 - Services (services/):
  - Business logic
  - Can import: models/, database/
  - Cannot import: api/

Layer 3 - API (api/):
  - HTTP endpoints
  - Can import: services/, models/
  - Route definitions only, logic in services

RULES:
  - Always place entities in models/
  - Business logic goes in services/
  - HTTP handling in api/
  - Dependencies flow one direction only
```

**Effort:** 3 days
**Impact:** VERY HIGH - Prevents architecture violations

### Priority 4: Continuous Context Updates

**Problem:** Context is gathered once, doesn't update

**Solution:** Update context after each action
- File created → Add to existing files list + show contents
- File edited → Update definition summary
- Pattern emerged → Add to pattern context

**Effort:** 1 week
**Impact:** HIGH - Context stays current during long sessions

## Measuring Fairness

### Before Fix (Current State)

```python
# Model receives minimal context
context_score = 2/10  # Only filenames + keyword search

# We measure integration quality
integration_success = 60%  # Model B

# But model was mostly guessing
guessing_percentage = 80%
actual_integration_skill = ???  # Can't tell!
```

### After Fix (With Context)

```python
# Model receives full context
context_score = 9/10  # Decisions, patterns, types, architecture

# We measure integration quality
integration_success = 85%  # Model B

# Model had information needed
guessing_percentage = 10%
actual_integration_skill = 85%  # Now we know!

# Fair comparison:
# Model A with context: 90%
# Model B with context: 85%
# Conclusion: Model A is slightly better (5% difference, not 30%!)
```

## Comparison with Manual Development

### How Humans Code (Fair)

1. Read existing code
2. Understand patterns and conventions
3. Look at type definitions
4. Check architecture
5. Write code following what they learned
6. **Evaluation:** Did they follow conventions? YES/NO

### How AI Codes (Current - Unfair)

1. ~~Read existing code~~ See filenames only
2. ~~Understand patterns~~ Guess blindly
3. ~~Look at types~~ Don't have access
4. ~~Check architecture~~ Not provided
5. Write code following... nothing
6. **Evaluation:** Did they follow conventions? Usually NO

**Is this fair?** NO.

### How AI Should Code (Fair)

1. Read existing code ← Provided as context
2. Understand patterns ← ProjectMemory injected
3. Look at type definitions ← File summaries provided
4. Check architecture ← Architecture context given
5. Write code following conventions
6. **Evaluation:** Did they follow conventions? NOW FAIR

## Conclusion

### Current State: Unfair Evaluation

We're testing **psychic ability** (can models guess conventions?) not **integration ability** (can models follow conventions when told?).

### What We Need: Fair Evaluation

Provide models the **same information a human developer would have**:
- Project decisions and conventions
- Code patterns to follow
- Type definitions from existing code
- Import structure
- Architecture guidelines

### Impact on Learning

**Without Fair Context:**
- Can't distinguish "good at integration" from "lucky guessing"
- Learning is corrupted by random chance
- Model comparisons are meaningless
- Improvements don't translate to real-world use

**With Fair Context:**
- Measure true integration ability
- Learning reflects actual model capability
- Model comparisons are meaningful
- Improvements help real-world development

### Bottom Line

**Current Question:** "Which model is luckiest at guessing repo conventions?"
**Fair Question:** "Which model best follows conventions when given context?"

The second question is what matters for real-world usage, where developers DO have context about their repo.

**Priority 0:** Add ProjectMemory to action generation (2-3 hours) ← DO THIS FIRST
**Then:** Priorities 1-4 for comprehensive context provision

Without this fix, all our integration quality measurements are measuring luck, not skill.
