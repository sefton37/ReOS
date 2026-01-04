# Git Integration Decision

## TL;DR

**Decision**: Keep git-companion code but **mark as optional M5 feature**, not core functionality.

The git integration modules (alignment.py, commit_watch.py, repo_discovery.py, etc.) will remain in the codebase but:
- Not exposed in main UI by default
- Documented as future/optional expansion
- Can be enabled via settings flag
- Does not clutter core terminal experience

---

## Context

ReOS was originally designed as a dual-purpose tool:
1. Git companion (track changes vs roadmap/charter, alignment analysis)
2. Natural language Linux control

After vision refocus (January 2025), the primary purpose is:
**"Make using Linux as easy as having a conversation"**

Git integration becomes a **secondary, optional feature** for developers.

---

## What Git Code Exists

### Files (738 total lines)
- `src/reos/alignment.py` (394 lines) - Git change analysis vs charter/roadmap
- `src/reos/commit_watch.py` (144 lines) - Commit polling and review
- `src/reos/repo_discovery.py` (129 lines) - Find git repos on disk
- `src/reos/commit_review.py` (44 lines) - Ollama-powered commit review
- `src/reos/repo_sandbox.py` (27 lines) - Path sandboxing for repo access

### MCP Tools (in mcp_tools.py)
- `reos_repo_discover` - Scan for git repos
- `reos_git_summary` - Get repo status, diff, commits
- `reos_repo_grep` - Search within repo
- `reos_repo_read_file` - Read file from repo
- `reos_repo_list_files` - List files with glob

### Integration Points
- MCP server exposes tools
- Storage system has events for commit reviews
- Agent can call git tools
- DB has repos table

---

## Options Considered

### Option 1: Delete All Git Code ❌
**Pros:**
- Cleaner codebase
- Clear focus on terminal control
- Less confusion about purpose

**Cons:**
- Throws away 738 lines of working code
- Some tools are useful (repo_read_file for project context)
- Git integration IS valuable for developers (just not core)

### Option 2: Keep As-Is ❌
**Pros:**
- No work required
- Feature already exists

**Cons:**
- Clutters MCP tool list
- Confuses users about purpose
- Git polling conflicts with terminal focus

### Option 3: Keep But Make Optional ✅ CHOSEN
**Pros:**
- Code remains for future use
- Can be enabled for power users
- Clean separation (disabled by default)
- Preserves investment

**Cons:**
- Slight maintenance burden
- Need to document clearly

---

## Implementation Plan

### Phase 1: Mark As Optional (Now)
1. **Add settings flag**:
   ```python
   # settings.py
   git_integration_enabled: bool = False  # New flag
   ```

2. **Conditional tool registration**:
   ```python
   # mcp_tools.py: list_tools()
   tools = []

   # Git tools only if enabled
   if settings.git_integration_enabled:
       tools.extend([
           Tool(name="reos_repo_discover", ...),
           Tool(name="reos_git_summary", ...),
           # ... other git tools
       ])

   # Linux tools always included
   tools.extend([
       Tool(name="linux_run_command", ...),
       Tool(name="linux_system_info", ...),
       # ... core terminal tools
   ])
   ```

3. **Update docstrings**:
   ```python
   # alignment.py
   """Git alignment analysis (OPTIONAL FEATURE - M5 roadmap).

   This module provides change analysis against project charter/roadmap.
   Disabled by default. Enable via settings.git_integration_enabled = True.

   Core ReOS functionality (terminal control) does NOT depend on this.
   """
   ```

4. **Document in README**:
   ```markdown
   ## Optional Features

   ### Git Integration (M5 - Future)
   ReOS can optionally analyze git changes vs project roadmap/charter.
   Enable in settings: `git_integration_enabled = true`

   This is NOT required for core terminal functionality.
   ```

### Phase 2: Refine Integration (M5 - Future)
When we eventually expose git integration:
1. UI toggle: Settings → "Enable Git Integration"
2. Separate tab in UI: "Projects" (alongside System, Chat, Knowledge)
3. Context-aware: Only show git features when in a git repo
4. Clear value prop: "Track code changes vs project goals"

---

## Use Cases Where Git Integration Adds Value

### 1. Developer Workflow (Future)
```
User: "Show me what changed in my repo"
ReOS: [Uses reos_git_summary]
      Modified: 15 files
      - src/api/routes.py: Added 3 endpoints
      - tests/: Updated tests for new routes

      Want me to help write a commit message?
```

### 2. Alignment Checking (Future)
```
User: "Am I drifting from the roadmap?"
ReOS: [Uses alignment analysis]
      Your recent changes:
      - Implemented user auth (✓ on roadmap)
      - Added social login (! not in charter)
      - Refactored DB layer (✓ matches principles)

      Social login isn't mentioned in roadmap.md. Intentional?
```

### 3. Project Context (Now - Useful)
```
User: "Set up Python dev environment for this project"
ReOS: [Uses repo_read_file to check pyproject.toml/requirements.txt]
      Found: Django 4.2, PostgreSQL, Redis in requirements.txt

      I'll install:
      1. python3-dev, postgresql, redis
      2. Create virtualenv
      3. Install requirements.txt dependencies

      Proceed?
```

**This third use case suggests keeping `repo_read_file` accessible even with git_integration_enabled=False**

---

## Refined Decision

**Keep git code with smart defaults:**

### Always Available (No Flag Required)
- `repo_read_file` - Useful for project context
- `repo_list_files` - Useful for understanding project structure
- Basic git status (via linux_run_command if user asks)

### Opt-In Only (git_integration_enabled = True)
- `repo_discover` - Scanning disk for repos
- `git_summary` - Deep analysis (diffs, commits, alignment)
- `commit_watch` - Automated commit review
- `repo_grep` - Codebase search (can use linux_run_command + grep instead)
- Alignment analysis vs charter/roadmap

### Not Exposed At All (Code remains, no MCP tools)
- `commit_review.py` - Too specific to git companion use case
- Proactive alignment triggers - Conflicts with terminal focus

---

## Documentation Updates Required

### 1. Module Docstrings
Add to each git module:
```python
"""
OPTIONAL FEATURE (M5 Roadmap)

This module provides git integration for developer workflows.
It is DISABLED by default and NOT required for core ReOS functionality.

Enable via: settings.git_integration_enabled = True

Core ReOS features (natural language Linux control) work without this.
"""
```

### 2. README.md
Add new section:
```markdown
## Optional Features

ReOS focuses on **conversational Linux control** (terminal commands, services, packages).

Additional features can be enabled:

### Git Integration (M5 - Future)
- Analyze code changes vs project roadmap
- Smart commit suggestions
- Alignment analysis

Enable in `~/.config/reos/settings.toml`:
\`\`\`toml
git_integration_enabled = true
\`\`\`

**Note:** This is NOT required for system administration features.
```

### 3. Tech Roadmap
Update M5 section:
```markdown
### M5.1: Git Integration (Optional)
- [ ] Enable via settings flag (git_integration_enabled)
- [ ] UI tab for "Projects" view
- [ ] Alignment checks (changes vs roadmap/charter)
- [ ] Smart commit grouping suggestions
- [ ] Commit review (Ollama-powered)

**Status:** Code exists, disabled by default. Not part of core product.
```

---

## Benefits of This Approach

### 1. Clarity
- New users see: "ReOS = conversational Linux"
- Power users can enable: "Also does git stuff"
- No confusion about primary purpose

### 2. Flexibility
- Code remains for future use
- Can evolve git features separately
- Easy to enable for users who want it

### 3. Cleanliness
- MCP tool list stays focused (8 core Linux tools vs 13 with git)
- UI doesn't clutter with unused features
- Documentation emphasizes terminal control

### 4. Preservation
- Don't throw away working code
- Can resume git companion vision later if demand exists
- Respects past development effort

---

## Action Items

1. ✅ Document decision (this file)
2. ⏳ Add `git_integration_enabled` setting (default: False)
3. ⏳ Conditional tool registration in mcp_tools.py
4. ⏳ Update docstrings on git modules
5. ⏳ Add "Optional Features" section to README
6. ⏳ Update tech-roadmap.md M5 section
7. ⏳ Keep repo_read_file/repo_list_files available (useful for project context)
8. ⏳ Hide commit_watch polling (conflicts with terminal focus)

---

## Closing

**Git integration stays in the codebase but takes a back seat.**

ReOS is a **conversational Linux companion first**.

Git features are a **bonus for developers**, not the main event.

This decision:
- Preserves past work
- Maintains focus
- Allows future expansion
- Keeps codebase clean

The 738 lines of git code aren't wasted—they're just **waiting their turn** on the roadmap.
