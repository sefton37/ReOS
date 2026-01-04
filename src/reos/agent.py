from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from .db import Database
from .mcp_tools import Tool, ToolError, call_tool, list_tools, render_tool_result
from .ollama import OllamaClient
from .play_fs import list_acts as play_list_acts
from .play_fs import read_me_markdown as play_read_me_markdown
from .system_index import get_or_refresh_context as get_system_context

# Intent detection patterns for conversational troubleshooting
_APPROVAL_PATTERN = re.compile(
    r"^(yes|y|ok|okay|sure|go|yep|do it|proceed|go ahead|approve|approved|run it|execute)$",
    re.IGNORECASE,
)
_REJECTION_PATTERN = re.compile(
    r"^(no|n|nope|cancel|stop|don't|abort|nevermind|never mind|reject|denied)$",
    re.IGNORECASE,
)
_NUMERIC_CHOICE_PATTERN = re.compile(r"^([1-9])$")
_ORDINAL_PATTERN = re.compile(
    r"^(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)(\s+one)?$",
    re.IGNORECASE,
)
_REFERENCE_PATTERN = re.compile(
    r"\b(it|that|this|the service|the container|the package|the error|the file|the command)\b",
    re.IGNORECASE,
)

# Map ordinals to numbers
_ORDINAL_MAP = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
}


@dataclass(frozen=True)
class DetectedIntent:
    """Result of intent detection on user input."""

    intent_type: str  # "approval", "rejection", "choice", "reference", "question"
    choice_number: int | None = None  # For numeric/ordinal choices
    reference_term: str | None = None  # The pronoun/reference detected
    confidence: float = 1.0


def _generate_id() -> str:
    """Generate a short unique ID."""
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    """Structured response from ChatAgent.respond()."""

    answer: str
    conversation_id: str
    message_id: str
    message_type: str = "text"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    pending_approval_id: str | None = None


class ChatAgent:
    """Minimal tool-using chat agent for ReOS.

    Principles:
    - Local-only (Ollama).
    - Metadata-first; diffs only on explicit opt-in.
    - Repo-first; repo selection is configured via REOS_REPO_PATH or by running inside a git repo.
    """

    def __init__(self, *, db: Database, ollama: OllamaClient | None = None) -> None:
        self._db = db
        self._ollama_override = ollama

    def _get_persona(self) -> dict[str, Any]:
        persona_id = self._db.get_active_persona_id()
        if persona_id:
            row = self._db.get_agent_persona(persona_id=persona_id)
            if row is not None:
                return row

        return {
            "system_prompt": (
                "You are ReOS, a local-first AI companion for Linux system administration. "
                "You run entirely on the user's machine using Ollama - no cloud services.\n\n"
                "REASONING FIRST:\n"
                "Before acting, THINK through the task:\n"
                "1. What is the user asking for? (e.g., 'remove nextcloud containers')\n"
                "2. What resources match? Look at NAMES - 'nextcloud-redis' contains 'nextcloud'!\n"
                "3. What steps are needed? List them: stop → remove → verify\n"
                "4. Execute each step\n\n"
                "PATTERN MATCHING:\n"
                "- 'nextcloud containers' = ANY container with 'nextcloud' in the name\n"
                "- 'redis services' = ANY service with 'redis' in the name\n"
                "- When user says 'X containers', find ALL containers containing 'X'\n\n"
                "TOOLS:\n"
                "- linux_system_info: Get CPU, memory, disk, uptime\n"
                "- linux_list_services: Show systemd services\n"
                "- linux_docker_containers: List Docker containers\n"
                "- linux_run_command: Execute shell commands (docker, apt, systemctl)\n\n"
                "EXECUTION:\n"
                "- When user confirms (yes, proceed, do it), EXECUTE immediately\n"
                "- For Docker: linux_run_command with 'docker stop X && docker rm X'\n"
                "- For multiple items, run commands for EACH one\n"
                "- Don't just describe - DO IT when confirmed!\n\n"
                "RESPONSE FORMAT:\n"
                "1. State what you understood\n"
                "2. List the matching resources (by name pattern)\n"
                "3. Explain what you'll do\n"
                "4. Ask for confirmation OR execute if already confirmed"
            ),
            "default_context": "",
            "temperature": 0.2,
            "top_p": 0.9,
            "tool_call_limit": 5,
        }

    def _get_ollama_client(self) -> OllamaClient:
        if self._ollama_override is not None:
            return self._ollama_override

        url = self._db.get_state(key="ollama_url")
        model = self._db.get_state(key="ollama_model")
        return OllamaClient(
            url=url if isinstance(url, str) and url else None,
            model=model if isinstance(model, str) and model else None,
        )

    def respond(
        self,
        user_text: str,
        *,
        conversation_id: str | None = None,
    ) -> ChatResponse:
        """Respond to user message with conversation context.

        Args:
            user_text: The user's message
            conversation_id: Optional conversation ID for context continuity.
                           If None, creates a new conversation.

        Returns:
            ChatResponse with answer and metadata
        """
        # Get or create conversation
        if conversation_id is None:
            conversation_id = _generate_id()
            self._db.create_conversation(conversation_id=conversation_id)
        else:
            # Verify conversation exists, create if not
            conv = self._db.get_conversation(conversation_id=conversation_id)
            if conv is None:
                self._db.create_conversation(conversation_id=conversation_id)

        # Store user message
        user_message_id = _generate_id()
        self._db.add_message(
            message_id=user_message_id,
            conversation_id=conversation_id,
            role="user",
            content=user_text,
            message_type="text",
        )

        tools = list_tools()

        persona = self._get_persona()
        temperature = float(persona.get("temperature") or 0.2)
        top_p = float(persona.get("top_p") or 0.9)
        tool_call_limit = int(persona.get("tool_call_limit") or 3)
        tool_call_limit = max(0, min(6, tool_call_limit))

        persona_system = str(persona.get("system_prompt") or "")
        persona_context = str(persona.get("default_context") or "")
        persona_prefix = persona_system
        if persona_context:
            persona_prefix = persona_prefix + "\n\n" + persona_context

        play_context = self._get_play_context()
        if play_context:
            persona_prefix = persona_prefix + "\n\n" + play_context

        # Add daily system state context (RAG)
        system_context = self._get_system_context()
        if system_context:
            persona_prefix = persona_prefix + "\n\n" + system_context

        # Add conversation history context
        conversation_context = self._build_conversation_context(conversation_id)
        if conversation_context:
            persona_prefix = persona_prefix + "\n\n" + conversation_context

        ollama = self._get_ollama_client()

        wants_diff = self._user_opted_into_diff(user_text)

        tool_calls = self._select_tools(
            user_text=user_text,
            tools=tools,
            wants_diff=wants_diff,
            persona_prefix=persona_prefix,
            ollama=ollama,
            temperature=temperature,
            top_p=top_p,
            tool_call_limit=tool_call_limit,
        )

        tool_results: list[dict[str, Any]] = []
        for call in tool_calls[:tool_call_limit]:
            try:
                if call.name == "reos_git_summary" and not wants_diff:
                    args = {k: v for k, v in call.arguments.items() if k != "include_diff"}
                    call = ToolCall(name=call.name, arguments=args)

                result = call_tool(self._db, name=call.name, arguments=call.arguments)
                tool_results.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": True,
                        "result": result,
                    }
                )
            except ToolError as exc:
                tool_results.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "ok": False,
                        "error": {"code": exc.code, "message": exc.message, "data": exc.data},
                    }
                )

        answer = self._answer(
            user_text=user_text,
            tools=tools,
            tool_results=tool_results,
            wants_diff=wants_diff,
            persona_prefix=persona_prefix,
            ollama=ollama,
            temperature=temperature,
            top_p=top_p,
        )

        # Store assistant response
        assistant_message_id = _generate_id()
        self._db.add_message(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            message_type="text",
            metadata=json.dumps({"tool_calls": tool_results}) if tool_results else None,
        )

        # Generate title for new conversations (first message)
        messages = self._db.get_messages(conversation_id=conversation_id, limit=3)
        if len(messages) <= 2:  # Just the user message and assistant response
            title = user_text[:50] + ("..." if len(user_text) > 50 else "")
            self._db.update_conversation_title(conversation_id=conversation_id, title=title)

        return ChatResponse(
            answer=answer,
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            message_type="text",
            tool_calls=tool_results,
        )

    def respond_text(self, user_text: str) -> str:
        """Simple text-only response (backwards compatibility)."""
        response = self.respond(user_text)
        return response.answer

    def _build_conversation_context(self, conversation_id: str) -> str:
        """Build conversation history context for LLM."""
        # Get recent messages (excluding current - it will be added separately)
        messages = self._db.get_recent_messages(conversation_id=conversation_id, limit=10)

        if len(messages) <= 1:  # Only current message or empty
            return ""

        # Format as conversation history (exclude last message which is the current user message)
        history_messages = messages[:-1]
        if not history_messages:
            return ""

        lines = ["CONVERSATION HISTORY:"]
        for msg in history_messages:
            role = str(msg.get("role", "")).upper()
            content = str(msg.get("content", ""))
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _get_system_context(self) -> str:
        """Get daily system state context for RAG."""
        try:
            return get_system_context(self._db)
        except Exception:  # noqa: BLE001
            return ""

    def _get_play_context(self) -> str:
        try:
            acts, active_id = play_list_acts()
        except Exception:  # noqa: BLE001
            return ""

        if not active_id:
            return ""

        act = next((a for a in acts if a.act_id == active_id), None)
        if act is None:
            return ""

        ctx = f"ACTIVE_ACT: {act.title}".strip()
        if act.notes.strip():
            ctx = ctx + "\n" + f"ACT_NOTES: {act.notes.strip()}"

        try:
            me = play_read_me_markdown().strip()
        except Exception:  # noqa: BLE001
            me = ""

        if me:
            # Keep this small and stable; it should be identity-level context,
            # not a task list.
            cap = 2000
            if len(me) > cap:
                me = me[:cap] + "\n…"
            ctx = ctx + "\n\n" + "ME_CONTEXT:\n" + me

        return ctx

    def _user_opted_into_diff(self, user_text: str) -> bool:
        t = user_text.lower()
        return any(
            phrase in t
            for phrase in [
                "include diff",
                "show diff",
                "full diff",
                "git diff",
                "patch",
                "unified diff",
            ]
        )

    def detect_intent(self, user_text: str) -> DetectedIntent | None:
        """Detect conversational intent from short user responses.

        Returns:
            DetectedIntent if a special intent is detected, None for normal questions.
        """
        text = user_text.strip()

        # Check for approval
        if _APPROVAL_PATTERN.match(text):
            return DetectedIntent(intent_type="approval")

        # Check for rejection
        if _REJECTION_PATTERN.match(text):
            return DetectedIntent(intent_type="rejection")

        # Check for numeric choice (1-9)
        numeric_match = _NUMERIC_CHOICE_PATTERN.match(text)
        if numeric_match:
            return DetectedIntent(
                intent_type="choice",
                choice_number=int(numeric_match.group(1)),
            )

        # Check for ordinal choice (first, second, etc.)
        ordinal_match = _ORDINAL_PATTERN.match(text)
        if ordinal_match:
            ordinal = ordinal_match.group(1).lower()
            return DetectedIntent(
                intent_type="choice",
                choice_number=_ORDINAL_MAP.get(ordinal, 1),
            )

        # Check for references (it, that, the service, etc.)
        reference_match = _REFERENCE_PATTERN.search(text)
        if reference_match and len(text) < 100:  # Short messages with references
            return DetectedIntent(
                intent_type="reference",
                reference_term=reference_match.group(1).lower(),
            )

        return None

    def resolve_reference(
        self,
        reference_term: str,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Resolve a reference term (it, that, etc.) from conversation context.

        Returns:
            Dict with resolved entity info, or None if cannot resolve.
        """
        # Get recent messages to find what "it" refers to
        messages = self._db.get_recent_messages(conversation_id=conversation_id, limit=5)

        if not messages:
            return None

        # Look for entities in recent assistant messages
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue

            content = str(msg.get("content", ""))
            metadata_str = msg.get("metadata")

            # Check tool calls in metadata for services/containers
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str)
                    tool_calls = metadata.get("tool_calls", [])
                    for tc in tool_calls:
                        if not tc.get("ok"):
                            continue
                        result = tc.get("result", {})

                        # Service mentioned
                        if "service" in reference_term or "service" in str(tc.get("name", "")):
                            if isinstance(result, dict) and "name" in result:
                                return {"type": "service", "name": result["name"]}

                        # Container mentioned
                        if "container" in reference_term or "container" in str(tc.get("name", "")):
                            if isinstance(result, dict) and ("id" in result or "name" in result):
                                return {
                                    "type": "container",
                                    "id": result.get("id"),
                                    "name": result.get("name"),
                                }

                        # File mentioned
                        if "file" in reference_term:
                            if isinstance(result, dict) and "path" in result:
                                return {"type": "file", "path": result["path"]}

                except (json.JSONDecodeError, TypeError):
                    pass

            # Simple text matching for common patterns
            patterns = [
                (r"service[:\s]+([a-zA-Z0-9_-]+)", "service"),
                (r"container[:\s]+([a-zA-Z0-9_-]+)", "container"),
                (r"`([^`]+\.service)`", "service"),
                (r"package[:\s]+([a-zA-Z0-9_-]+)", "package"),
            ]

            for pattern, entity_type in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return {"type": entity_type, "name": match.group(1)}

        return None

    def get_pending_approval_for_conversation(
        self,
        conversation_id: str,
    ) -> dict[str, Any] | None:
        """Get the most recent pending approval for a conversation."""
        approvals = self._db.get_pending_approvals()
        for approval in approvals:
            if approval.get("conversation_id") == conversation_id:
                return approval
        return None

    def _select_tools(
        self,
        *,
        user_text: str,
        tools: list[Tool],
        wants_diff: bool,
        persona_prefix: str,
        ollama: OllamaClient,
        temperature: float,
        top_p: float,
        tool_call_limit: int,
    ) -> list[ToolCall]:
        # Simplified tool specs - just names and short descriptions
        # Full schemas overwhelm smaller models
        tool_specs = [
            {
                "name": t.name,
                "description": t.description[:100] if t.description else "",
            }
            for t in tools
        ]

        system = (
            persona_prefix
            + "\n\n"
            + "You are deciding which tools to call to answer the user.\n\n"
            + "IMPORTANT RULES:\n"
            + "- For system/hardware questions: USE linux_system_info\n"
            + "- For listing services: USE linux_list_services\n"
            + "- For listing Docker containers: USE linux_docker_containers\n"
            + "- For git/repo questions: USE reos_git_summary\n"
            + "- For EXECUTING commands (docker stop, apt install, systemctl, etc.): USE linux_run_command\n"
            + "- When user says 'yes', 'proceed', 'do it', 'confirm': USE linux_run_command to execute!\n"
            + "- linux_run_command takes {\"command\": \"the shell command\"}\n"
            + f"- Call 1-{tool_call_limit} tools. DO NOT return empty tool_calls.\n\n"
            + "Return JSON:\n"
            + "{\"tool_calls\": [{\"name\": \"tool_name\", \"arguments\": {}}]}\n"
        )

        user = (
            "TOOLS:\n" + json.dumps(tool_specs, indent=2) + "\n\n" +
            "USER_MESSAGE:\n" + user_text + "\n\n" +
            f"USER_OPTED_INTO_DIFF: {wants_diff}\n"
        )

        raw = ollama.chat_json(system=system, user=user, temperature=temperature, top_p=top_p)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: get system info if LLM returns invalid JSON
            return [ToolCall(name="linux_system_info", arguments={})]

        calls = payload.get("tool_calls")
        if not isinstance(calls, list):
            return []

        out: list[ToolCall] = []
        valid_tool_names = {t.name for t in tools}

        for c in calls:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            args = c.get("arguments") or {}  # Default to empty dict if missing

            if not isinstance(name, str):
                continue
            if not isinstance(args, dict):
                args = {}

            # Map common LLM mistakes to actual tool names
            name_mapping = {
                "uptime": "linux_system_info",
                "system_info": "linux_system_info",
                "services": "linux_list_services",
                "list_services": "linux_list_services",
                "run_command": "linux_run_command",
                "run": "linux_run_command",
                "packages": "linux_list_packages",
                "docker": "linux_list_docker_containers",
                "containers": "linux_list_docker_containers",
                "git_summary": "reos_git_summary",
                "git": "reos_git_summary",
            }
            if name in name_mapping:
                name = name_mapping[name]

            # Only add if it's a valid tool
            if name in valid_tool_names:
                out.append(ToolCall(name=name, arguments=args))

        return out

    def _answer(
        self,
        *,
        user_text: str,
        tools: list[Tool],
        tool_results: list[dict[str, Any]],
        wants_diff: bool,
        persona_prefix: str,
        ollama: OllamaClient,
        temperature: float,
        top_p: float,
    ) -> str:
        tool_dump = []
        for r in tool_results:
            rendered = render_tool_result(r.get("result")) if r.get("ok") else json.dumps(r.get("error"), indent=2)
            tool_dump.append(
                {
                    "name": r.get("name"),
                    "arguments": r.get("arguments"),
                    "ok": r.get("ok"),
                    "output": rendered,
                }
            )

        system = (
            persona_prefix
            + "\n\n"
            + "Answer the user using the available tool outputs.\n\n"
            + "Rules:\n"
            + "- Be descriptive, non-judgmental, and local-first.\n"
            + "- If no repo is configured/detected, ask the user to set REOS_REPO_PATH or run ReOS inside a git repo.\n"
            + "- Do not fabricate repository state; rely on tool outputs.\n"
            + "- If the user did not opt into diffs, do not ask for or display diffs.\n"
        )

        user = (
            f"USER_OPTED_INTO_DIFF: {wants_diff}\n\n"
            "USER_MESSAGE:\n" + user_text + "\n\n"
            "TOOL_RESULTS:\n" + json.dumps(tool_dump, indent=2, ensure_ascii=False)
        )

        return ollama.chat_text(system=system, user=user, temperature=temperature, top_p=top_p)
