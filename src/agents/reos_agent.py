"""ReOS Agent — Natural language Linux system control.

ReOS translates natural language requests into safe system operations.
Commands are proposed, not executed — the user must approve before execution.
Designed for 1-3B models with structured prompts.
"""

from __future__ import annotations

import logging
import platform
import shutil
from typing import Any

from reos.atomic_ops.models import Classification, ExecutionSemantics
from reos.providers.base import LLMProvider

from .base_agent import AgentContext, AgentResponse, BaseAgent

logger = logging.getLogger(__name__)

REOS_SYSTEM_PROMPT = """You are ReOS, a natural language Linux system assistant.

Your role:
- Translate user requests into Linux commands
- Explain what commands do in plain language
- Prioritize safety — never suggest destructive commands without clear warning
- Propose commands for user approval; never execute directly

Rules:
- Always explain WHAT the command does before showing it
- Flag risky commands (rm, dd, mkfs, chmod 777, etc.) with warnings
- Prefer safe alternatives (e.g., trash-put over rm)
- Use the user's package manager (detected from system info)
- Format commands in code blocks for clarity
{context_section}"""


class ReOSAgent(BaseAgent):
    """ReOS system assistant agent.

    Gathers system context (OS, package manager, resources) and
    translates natural language into proposed Linux commands.
    """

    def __init__(self, llm: LLMProvider) -> None:
        super().__init__(llm)

    @property
    def agent_name(self) -> str:
        return "reos"

    def gather_context(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> AgentContext:
        """Gather system context for ReOS."""
        context = AgentContext()
        context.system_info = self._gather_system_info()
        return context

    def build_system_prompt(self, context: AgentContext) -> str:
        """Build ReOS system prompt with system context."""
        context_lines = []

        sys_info = context.system_info
        if sys_info:
            context_lines.append("\nSystem information:")
            if sys_info.get("os"):
                context_lines.append(f"  OS: {sys_info['os']}")
            if sys_info.get("kernel"):
                context_lines.append(f"  Kernel: {sys_info['kernel']}")
            if sys_info.get("package_manager"):
                context_lines.append(f"  Package manager: {sys_info['package_manager']}")
            if sys_info.get("shell"):
                context_lines.append(f"  Shell: {sys_info['shell']}")

        context_section = "\n".join(context_lines) if context_lines else ""
        return REOS_SYSTEM_PROMPT.format(context_section=context_section)

    def build_user_prompt(
        self,
        request: str,
        classification: Classification | None = None,
    ) -> str:
        """Format user request for ReOS."""
        if classification and classification.semantics == ExecutionSemantics.EXECUTE:
            return (
                f"{request}\n\n"
                "Propose the command(s) needed. Explain what each does. "
                "Mark any risky commands with [CAUTION]."
            )
        return request

    def format_response(self, raw_response: str, context: AgentContext) -> AgentResponse:
        """Post-process ReOS response, flagging commands needing approval."""
        needs_approval = any(
            marker in raw_response.lower()
            for marker in ["```", "[caution]", "sudo ", "rm ", "dd ", "mkfs"]
        )

        return AgentResponse(
            text=raw_response.strip(),
            confidence=0.9,
            needs_approval=needs_approval,
        )

    def _gather_system_info(self) -> dict[str, Any]:
        """Gather basic system information."""
        info: dict[str, Any] = {}

        try:
            info["os"] = platform.freedesktop_os_release().get("PRETTY_NAME", platform.system())
        except OSError:
            info["os"] = platform.system()

        info["kernel"] = platform.release()

        # Detect package manager
        for pm in ["apt", "dnf", "pacman", "zypper", "nix"]:
            if shutil.which(pm):
                info["package_manager"] = pm
                break

        # Detect shell
        import os

        info["shell"] = os.environ.get("SHELL", "/bin/bash")

        return info
