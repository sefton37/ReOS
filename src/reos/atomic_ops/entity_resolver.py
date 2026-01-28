"""LLM-based entity resolution for atomic operations.

When a user refers to entities (scenes, acts, beats), this module uses
LLM inference to resolve which entity they mean. No fuzzy matching or
regex - pure semantic understanding.

Core principle: If uncertain, return uncertainty. Let the atomic
verification pipeline handle disambiguation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMProvider(Protocol):
    """Protocol for LLM providers."""
    def chat_json(self, system: str, user: str, temperature: float = 0.1, top_p: float = 0.9) -> str:
        ...


@dataclass
class ResolvedEntity:
    """Result of entity resolution."""
    entity_id: str | None
    entity_name: str | None
    entity_type: str  # "scene", "act", "beat"
    confidence: float  # 0.0 - 1.0
    reasoning: str
    alternatives: list[dict[str, Any]] = field(default_factory=list)  # Other possible matches
    needs_clarification: bool = False
    clarification_prompt: str | None = None


class EntityResolver:
    """LLM-based entity resolution.

    Uses cheap local inference to understand which entity the user
    is referring to, given the available entities in the system.

    When uncertain, returns alternatives and signals that clarification
    is needed - letting the atomic verification pipeline handle it.
    """

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def resolve_scene(
        self,
        user_reference: str,
        available_scenes: list[dict[str, Any]],
        conversation_context: str = "",
    ) -> ResolvedEntity:
        """Resolve a user's scene reference to an actual scene.

        Args:
            user_reference: What the user said (e.g., "the Kel Brengel scene")
            available_scenes: List of scenes with {id, title, act_title}
            conversation_context: Recent conversation for context

        Returns:
            ResolvedEntity with match or clarification needed
        """
        if not available_scenes:
            return ResolvedEntity(
                entity_id=None,
                entity_name=None,
                entity_type="scene",
                confidence=0.0,
                reasoning="No scenes available",
            )

        # Build scene list for LLM
        scene_list = "\n".join([
            f"- \"{s['title']}\" (in {s.get('act_title', 'Unknown')} act)"
            for s in available_scenes[:50]  # Limit for context window
        ])

        system = """You are an ENTITY RESOLVER. Match the user's reference to one of the available scenes.

IMPORTANT RULES:
1. Only match if you are CONFIDENT (>0.8) the user means that specific scene
2. If multiple scenes could match, return ALL candidates with your confidence for each
3. If you're not confident, say so - it's better to ask than guess wrong
4. Consider the conversation context to understand what the user is referring to

Return ONLY a JSON object:
{
    "matched": true/false,
    "entity_id": "the exact title if matched, null otherwise",
    "confidence": 0.0-1.0,
    "reasoning": "why you chose this match or why uncertain",
    "alternatives": [{"title": "...", "confidence": 0.X}, ...] if multiple possible matches,
    "needs_clarification": true if confidence < 0.8 or multiple good matches,
    "clarification_prompt": "Which scene did you mean: X or Y?" if clarification needed
}"""

        user = f"""AVAILABLE SCENES:
{scene_list}

RECENT CONVERSATION:
{conversation_context[-1500:] if conversation_context else "No prior context"}

USER REFERS TO: "{user_reference}"

Which scene is the user referring to?"""

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)

            # Find the matching scene ID if we have a match
            entity_id = None
            entity_name = data.get("entity_id")
            if entity_name:
                for s in available_scenes:
                    if s["title"].lower() == entity_name.lower():
                        entity_id = s.get("id") or s.get("scene_id")
                        entity_name = s["title"]
                        break

            return ResolvedEntity(
                entity_id=entity_id,
                entity_name=entity_name,
                entity_type="scene",
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                alternatives=data.get("alternatives", []),
                needs_clarification=data.get("needs_clarification", False),
                clarification_prompt=data.get("clarification_prompt"),
            )

        except Exception as e:
            return ResolvedEntity(
                entity_id=None,
                entity_name=None,
                entity_type="scene",
                confidence=0.0,
                reasoning=f"Entity resolution failed: {e}",
                needs_clarification=True,
                clarification_prompt=f"I couldn't understand which scene you meant by '{user_reference}'. Could you be more specific?",
            )

    def resolve_scenes_multiple(
        self,
        user_reference: str,
        available_scenes: list[dict[str, Any]],
        conversation_context: str = "",
    ) -> list[ResolvedEntity]:
        """Resolve when user refers to MULTIPLE scenes (e.g., "X and Y scenes").

        This handles the atomic decomposition case where a single user request
        needs to be split into multiple entity references.
        """
        if not available_scenes:
            return []

        scene_list = "\n".join([
            f"- \"{s['title']}\" (in {s.get('act_title', 'Unknown')} act)"
            for s in available_scenes[:50]
        ])

        system = """You are an ENTITY RESOLVER. The user is referring to ONE OR MORE scenes.

Identify ALL scenes the user is referring to. Users often say things like:
- "the X and Y scenes" (two scenes)
- "the scenes about Z" (could be multiple)
- "those Career scenes" (multiple in an act)

Return ONLY a JSON object:
{
    "count": number of scenes referenced,
    "scenes": [
        {
            "reference": "what part of user input refers to this",
            "matched_title": "exact scene title or null",
            "confidence": 0.0-1.0,
            "reasoning": "why this match"
        },
        ...
    ],
    "needs_clarification": true if any match is uncertain,
    "clarification_prompt": "clarification question if needed"
}"""

        user = f"""AVAILABLE SCENES:
{scene_list}

RECENT CONVERSATION:
{conversation_context[-1500:] if conversation_context else "No prior context"}

USER SAYS: "{user_reference}"

How many scenes is the user referring to, and which ones?"""

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)

            results = []
            for scene_ref in data.get("scenes", []):
                entity_name = scene_ref.get("matched_title")
                entity_id = None

                if entity_name:
                    for s in available_scenes:
                        if s["title"].lower() == entity_name.lower():
                            entity_id = s.get("id") or s.get("scene_id")
                            entity_name = s["title"]
                            break

                results.append(ResolvedEntity(
                    entity_id=entity_id,
                    entity_name=entity_name,
                    entity_type="scene",
                    confidence=float(scene_ref.get("confidence", 0.5)),
                    reasoning=scene_ref.get("reasoning", ""),
                    needs_clarification=data.get("needs_clarification", False),
                    clarification_prompt=data.get("clarification_prompt"),
                ))

            return results

        except Exception as e:
            return [ResolvedEntity(
                entity_id=None,
                entity_name=None,
                entity_type="scene",
                confidence=0.0,
                reasoning=f"Multi-entity resolution failed: {e}",
                needs_clarification=True,
                clarification_prompt=f"I couldn't understand which scenes you meant. Could you list them specifically?",
            )]

    def resolve_act(
        self,
        user_reference: str,
        available_acts: list[dict[str, Any]],
        conversation_context: str = "",
    ) -> ResolvedEntity:
        """Resolve a user's act reference to an actual act."""
        if not available_acts:
            return ResolvedEntity(
                entity_id=None,
                entity_name=None,
                entity_type="act",
                confidence=0.0,
                reasoning="No acts available",
            )

        act_list = "\n".join([f"- \"{a['title']}\"" for a in available_acts])

        system = """You are an ENTITY RESOLVER. Match the user's reference to one of the available acts.

Return ONLY a JSON object:
{
    "matched": true/false,
    "entity_id": "the exact act title if matched, null otherwise",
    "confidence": 0.0-1.0,
    "reasoning": "why you chose this match",
    "needs_clarification": true if confidence < 0.8
}"""

        user = f"""AVAILABLE ACTS:
{act_list}

USER REFERS TO: "{user_reference}"

Which act is the user referring to?"""

        try:
            raw = self.llm.chat_json(system=system, user=user, temperature=0.1, top_p=0.9)
            data = json.loads(raw)

            entity_name = data.get("entity_id")
            entity_id = None
            if entity_name:
                for a in available_acts:
                    if a["title"].lower() == entity_name.lower():
                        entity_id = a.get("id") or a.get("act_id")
                        entity_name = a["title"]
                        break

            return ResolvedEntity(
                entity_id=entity_id,
                entity_name=entity_name,
                entity_type="act",
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                needs_clarification=data.get("needs_clarification", False),
            )

        except Exception as e:
            return ResolvedEntity(
                entity_id=None,
                entity_name=None,
                entity_type="act",
                confidence=0.0,
                reasoning=f"Entity resolution failed: {e}",
                needs_clarification=True,
            )
