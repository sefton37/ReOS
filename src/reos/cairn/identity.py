"""Identity extraction from The Play.

This module builds an IdentityModel from The Play filesystem hierarchy,
extracting the user's identity facets for coherence verification.

Sources of identity:
- me.md: Core identity (highest priority)
- Acts: Major life projects and goals
- Scenes: Sub-projects and contexts
- Beats: Specific items and tasks
- KB entries: Knowledge and notes
- Anti-patterns: Stored in cairn_anti_patterns.json or items with rejection notes

The identity model is rebuilt on demand, ensuring coherence checks
always use the current self-understanding.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from reos.cairn.coherence import IdentityFacet, IdentityModel
from reos import play_fs

if TYPE_CHECKING:
    from reos.cairn.store import CairnStore

logger = logging.getLogger(__name__)


def _anti_patterns_path() -> Path:
    """Path to the anti-patterns JSON file."""
    return play_fs.play_root() / "cairn_anti_patterns.json"


def build_identity_model(
    store: "CairnStore | None" = None,
    include_kb: bool = True,
    max_facets: int = 50,
) -> IdentityModel:
    """Build an IdentityModel from The Play filesystem.

    Extracts identity from the hierarchical Play structure:
    1. Core identity from me.md
    2. Goal facets from Acts
    3. Project facets from Scenes
    4. Task facets from Beats
    5. Knowledge facets from KB entries
    6. Anti-patterns from stored rejections

    Args:
        store: Optional CairnStore for accessing metadata (e.g., for priority weighting)
        include_kb: Whether to include KB entries as facets
        max_facets: Maximum number of facets to include

    Returns:
        IdentityModel with extracted facets and anti-patterns
    """
    play_fs.ensure_play_skeleton()

    # 1. Read core identity from me.md
    core = play_fs.read_me_markdown()
    logger.debug("Read core identity from me.md: %d chars", len(core))

    facets: list[IdentityFacet] = []

    # 2. Extract facets from Acts (goals/projects)
    try:
        acts, _ = play_fs.list_acts()
        for act in acts:
            facet = IdentityFacet(
                name="goal",
                source=f"act:{act.act_id}",
                content=_build_act_content(act),
                weight=2.0 if act.active else 1.0,  # Active act gets higher weight
            )
            facets.append(facet)
            logger.debug("Added goal facet from Act: %s", act.title)

            # 3. Extract facets from Scenes (sub-projects)
            try:
                scenes = play_fs.list_scenes(act_id=act.act_id)
                for scene in scenes:
                    facet = IdentityFacet(
                        name="project",
                        source=f"scene:{act.act_id}/{scene.scene_id}",
                        content=_build_scene_content(scene),
                        weight=1.5 if act.active else 1.0,
                    )
                    facets.append(facet)

                    # 4. Extract facets from Beats (tasks)
                    try:
                        beats = play_fs.list_beats(act_id=act.act_id, scene_id=scene.scene_id)
                        for beat in beats:
                            # Only include beats with notes (meaningful content)
                            if beat.notes.strip():
                                facet = IdentityFacet(
                                    name="task",
                                    source=f"beat:{act.act_id}/{scene.scene_id}/{beat.beat_id}",
                                    content=_build_beat_content(beat),
                                    weight=1.0,
                                )
                                facets.append(facet)
                    except Exception as e:
                        logger.warning("Failed to read beats for scene %s: %s", scene.scene_id, e)
            except Exception as e:
                logger.warning("Failed to read scenes for act %s: %s", act.act_id, e)
    except Exception as e:
        logger.warning("Failed to read acts: %s", e)

    # 5. Extract facets from KB entries (optional)
    if include_kb:
        kb_facets = _extract_kb_facets(max_facets - len(facets))
        facets.extend(kb_facets)
        logger.debug("Added %d KB facets", len(kb_facets))

    # Limit facets
    if len(facets) > max_facets:
        # Sort by weight descending, keep top N
        facets.sort(key=lambda f: -f.weight)
        facets = facets[:max_facets]

    # 6. Load anti-patterns
    anti_patterns = load_anti_patterns()
    logger.debug("Loaded %d anti-patterns", len(anti_patterns))

    return IdentityModel(
        core=core,
        facets=facets,
        anti_patterns=anti_patterns,
    )


def _build_act_content(act: play_fs.Act) -> str:
    """Build content string from an Act."""
    parts = [f"Goal: {act.title}"]
    if act.notes:
        parts.append(f"Description: {act.notes}")
    if act.repo_path:
        parts.append(f"Code project at: {act.repo_path}")
    return "\n".join(parts)


def _build_scene_content(scene: play_fs.Scene) -> str:
    """Build content string from a Scene."""
    parts = [f"Project: {scene.title}"]
    if scene.intent:
        parts.append(f"Intent: {scene.intent}")
    if scene.status:
        parts.append(f"Status: {scene.status}")
    if scene.time_horizon:
        parts.append(f"Timeframe: {scene.time_horizon}")
    if scene.notes:
        parts.append(f"Notes: {scene.notes}")
    return "\n".join(parts)


def _build_beat_content(beat: play_fs.Beat) -> str:
    """Build content string from a Beat."""
    parts = [f"Task: {beat.title}"]
    if beat.status:
        parts.append(f"Status: {beat.status}")
    if beat.notes:
        parts.append(f"Notes: {beat.notes}")
    return "\n".join(parts)


def _extract_kb_facets(max_count: int) -> list[IdentityFacet]:
    """Extract facets from KB entries across all acts."""
    if max_count <= 0:
        return []

    facets: list[IdentityFacet] = []

    try:
        acts, _ = play_fs.list_acts()
        for act in acts:
            try:
                # List KB files for this act
                kb_files = play_fs.kb_list_files(act_id=act.act_id)
                for kb_file in kb_files:
                    if len(facets) >= max_count:
                        break
                    try:
                        content = play_fs.kb_read(act_id=act.act_id, path=kb_file)
                        if content.strip() and len(content) > 50:  # Skip near-empty files
                            facet = IdentityFacet(
                                name="knowledge",
                                source=f"kb:{act.act_id}/{kb_file}",
                                content=content[:2000],  # Limit content size
                                weight=1.0,
                            )
                            facets.append(facet)
                    except Exception as e:
                        logger.debug("Failed to read KB file %s: %s", kb_file, e)
            except Exception as e:
                logger.debug("Failed to list KB files for act %s: %s", act.act_id, e)

            if len(facets) >= max_count:
                break

    except Exception as e:
        logger.warning("Failed to extract KB facets: %s", e)

    return facets


def load_anti_patterns() -> list[str]:
    """Load anti-patterns from storage.

    Anti-patterns are stored in cairn_anti_patterns.json.
    They represent topics, sources, or patterns the user wants
    to automatically reject from their attention.

    Returns:
        List of anti-pattern strings
    """
    path = _anti_patterns_path()
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        patterns = data.get("anti_patterns", [])
        return [p for p in patterns if isinstance(p, str) and p.strip()]
    except Exception as e:
        logger.warning("Failed to load anti-patterns: %s", e)
        return []


def add_anti_pattern(pattern: str, reason: str | None = None) -> list[str]:
    """Add an anti-pattern.

    Args:
        pattern: The pattern to reject (e.g., "spam", "marketing email")
        reason: Optional reason for adding this pattern

    Returns:
        Updated list of anti-patterns
    """
    if not pattern or not pattern.strip():
        raise ValueError("Pattern cannot be empty")

    pattern = pattern.strip().lower()
    path = _anti_patterns_path()

    # Load existing patterns
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    patterns = data.get("anti_patterns", [])
    history = data.get("history", [])

    # Check for duplicate
    if pattern in patterns:
        return patterns

    # Add pattern
    patterns.append(pattern)

    # Record history
    from datetime import datetime, timezone
    history.append({
        "action": "add",
        "pattern": pattern,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Save
    data["anti_patterns"] = patterns
    data["history"] = history[-100:]  # Keep last 100 history entries
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    logger.info("Added anti-pattern: %s", pattern)
    return patterns


def remove_anti_pattern(pattern: str) -> list[str]:
    """Remove an anti-pattern.

    Args:
        pattern: The pattern to remove

    Returns:
        Updated list of anti-patterns
    """
    pattern = pattern.strip().lower()
    path = _anti_patterns_path()

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    patterns = data.get("anti_patterns", [])
    history = data.get("history", [])

    if pattern not in patterns:
        return patterns

    # Remove pattern
    patterns.remove(pattern)

    # Record history
    from datetime import datetime, timezone
    history.append({
        "action": "remove",
        "pattern": pattern,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Save
    data["anti_patterns"] = patterns
    data["history"] = history[-100:]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    logger.info("Removed anti-pattern: %s", pattern)
    return patterns


def get_identity_hash(identity: IdentityModel) -> str:
    """Compute a hash of the identity model for versioning.

    Used in CoherenceTrace to track which version of identity
    was used for a decision.

    Args:
        identity: The identity model to hash

    Returns:
        SHA256 hash of the identity content
    """
    content = identity.core
    content += "\n".join(f.content for f in identity.facets)
    content += "\n".join(identity.anti_patterns)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def get_relevant_identity_context(
    identity: IdentityModel,
    query: str,
    max_facets: int = 5,
) -> str:
    """Get relevant identity context for a query.

    Useful for building prompts that include identity context
    without overwhelming the LLM with the full identity model.

    Args:
        identity: The identity model
        query: The query to find relevant context for
        max_facets: Maximum facets to include

    Returns:
        Formatted string with relevant identity context
    """
    parts = []

    # Always include core identity summary
    core_lines = identity.core.split("\n")
    core_summary = "\n".join(core_lines[:20])  # First 20 lines
    parts.append(f"## Core Identity\n{core_summary}")

    # Find relevant facets
    query_words = set(query.lower().split())
    relevant = identity.get_relevant_facets(list(query_words))

    if relevant:
        facet_texts = []
        for facet in relevant[:max_facets]:
            facet_texts.append(f"- [{facet.name}] {facet.content[:200]}")
        parts.append(f"## Relevant Context\n" + "\n".join(facet_texts))

    # Include active anti-patterns
    if identity.anti_patterns:
        parts.append(f"## Rejected Patterns\n" + ", ".join(identity.anti_patterns[:10]))

    return "\n\n".join(parts)
