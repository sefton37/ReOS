"""CAIRN Agent — Attention minder and life organizer.

CAIRN handles personal queries, calendar, contacts, The Play (life organization),
knowledge base, and conversational interactions. Designed for 1B models — prompts
are concise and structured for small-model reliability.
"""

from __future__ import annotations

import logging
from typing import Any

from reos.atomic_ops.models import Classification
from reos.cairn.store import CairnStore
from reos import play_db
from reos.providers.base import LLMProvider

from .base_agent import AgentContext, AgentResponse, BaseAgent

logger = logging.getLogger(__name__)

CAIRN_SYSTEM_PROMPT = """You are CAIRN, an attention minder and life organizer.

Your role:
- Help the user manage their time, tasks, and priorities
- Answer questions about their schedule, contacts, and knowledge base
- Support life organization through The Play (Acts and Scenes)
- Be warm but concise — respect the user's time
- Never guilt-trip about overdue items ("X is waiting when you're ready")

Rules:
- Only state facts from the provided context — never hallucinate
- If you don't have data to answer, say so honestly
- Format responses for readability (short paragraphs, bullet points)
- When discussing The Play, use Act/Scene terminology naturally
{context_section}"""


class CAIRNAgent(BaseAgent):
    """CAIRN attention minder agent.

    Gathers context from CairnStore (knowledge), PlayDatabase (life organization),
    and calendar data, then generates responses using the LLM.
    """

    def __init__(
        self,
        llm: LLMProvider,
        cairn_store: CairnStore | None = None,
        use_play_db: bool = True,
    ) -> None:
        super().__init__(llm)
        self._cairn_store = cairn_store
        self._use_play_db = use_play_db

    @property
    def agent_name(self) -> str:
        return "cairn"

    def gather_context(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> AgentContext:
        """Gather CAIRN-relevant context from stores.

        Collects Play data, knowledge entries, and calendar events
        based on the classification domain.
        """
        context = AgentContext()

        # Gather Play data (acts and scenes) if available
        if self._use_play_db:
            try:
                context.play_data = self._gather_play_data()
            except Exception as e:
                logger.debug("Failed to gather Play data: %s", e)

        # Gather recent activity if relevant
        if self._cairn_store:
            try:
                context.knowledge_entries = self._gather_recent_activity()
            except Exception as e:
                logger.debug("Failed to gather activity: %s", e)

        return context

    def build_system_prompt(self, context: AgentContext) -> str:
        """Build CAIRN system prompt with context."""
        context_lines = []

        if context.play_data:
            acts = context.play_data.get("acts", [])
            if acts:
                context_lines.append("\nThe Play (user's life organization):")
                for act in acts:
                    context_lines.append(f"  Act: {act.get('title', 'Untitled')}")
                    for scene in act.get("scenes", []):
                        stage = scene.get("stage", "planning")
                        context_lines.append(
                            f"    Scene: {scene.get('title', 'Untitled')} [{stage}]"
                        )

        if context.knowledge_entries:
            context_lines.append("\nRelevant knowledge:")
            for entry in context.knowledge_entries[:5]:
                title = entry.get("title", "")
                content = entry.get("content", "")[:200]
                context_lines.append(f"  - {title}: {content}")

        if context.calendar_events:
            context_lines.append("\nUpcoming events:")
            for event in context.calendar_events[:5]:
                title = event.get("title", "")
                start = event.get("start", "")
                context_lines.append(f"  - {title} at {start}")

        context_section = "\n".join(context_lines) if context_lines else ""
        return CAIRN_SYSTEM_PROMPT.format(context_section=context_section)

    def build_user_prompt(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> str:
        """Format user request for CAIRN."""
        return request

    def format_response(self, raw_response: str, context: AgentContext) -> AgentResponse:
        """Post-process CAIRN response."""
        return AgentResponse(
            text=raw_response.strip(),
            confidence=1.0,
        )

    def _gather_play_data(self) -> dict[str, Any]:
        """Gather Play hierarchy from play_db module functions."""
        acts_data = []
        acts_list, _active_id = play_db.list_acts()
        for act in acts_list:
            scenes = play_db.list_scenes(act_id=act["id"])
            acts_data.append({
                "id": act["id"],
                "title": act.get("title", ""),
                "scenes": [
                    {
                        "id": s["id"],
                        "title": s.get("title", ""),
                        "stage": s.get("stage", "planning"),
                    }
                    for s in scenes
                ],
            })

        return {"acts": acts_data}

    def _gather_recent_activity(self) -> list[dict[str, Any]]:
        """Gather recent activity log entries from CairnStore."""
        if not self._cairn_store:
            return []

        try:
            entries = self._cairn_store.get_activity_log(limit=10)
            return [
                {
                    "title": e.get("action", ""),
                    "content": e.get("details", ""),
                    "category": e.get("entity_type", ""),
                }
                for e in entries
            ]
        except Exception:
            return []
