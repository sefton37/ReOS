"""Code Mode routing - determines when to use Code Mode vs sysadmin mode.

When an Act has a repository assigned, the router detects code-related requests
and routes them to Code Mode for agentic coding capabilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.play_fs import Act
    from reos.providers import LLMProvider


class RequestType(Enum):
    """Type of request detected."""

    CODE = "code"           # Code-related: write, edit, debug, test, etc.
    SYSADMIN = "sysadmin"   # System administration: services, packages, etc.
    AMBIGUOUS = "ambiguous"  # Could be either, needs LLM classification


@dataclass(frozen=True)
class RoutingDecision:
    """Result of routing decision."""

    use_code_mode: bool
    request_type: RequestType
    confidence: float
    reason: str


# Patterns that strongly indicate code-related requests
_CODE_PATTERNS = [
    # File operations
    r"\b(create|write|edit|modify|update|add|remove|delete)\s+(a\s+)?(new\s+)?(file|class|function|method|test|module)",
    r"\b(implement|build|develop|code|program|write)\s+(a\s+)?(new\s+)?(feature|function|class|method|api|endpoint)",
    r"\badd\s+(a\s+)?(new\s+)?(function|method|class|field|property|import|type\s*hints?)",
    r"\b(refactor|rename|extract|inline|move)\s+",
    r"\bedit\s+.*\.(py|js|ts|go|rs|java|cpp|c|h|rb|php)",

    # Testing
    r"\b(run|write|add|fix|update)\s+(the\s+)?(tests?|specs?|unit\s*tests?)",
    r"\btest\s+(coverage|suite|file|case)",
    r"\bpytest|jest|mocha|rspec|unittest",
    r"\b(fix|run)\s+(the\s+)?(failing|broken)\s+test",

    # Debugging code
    r"\b(fix|debug|resolve)\s+(the\s+)?(bug|error|issue|exception|crash)",
    r"\b(why\s+(is|does)|what\s+causes)\s+.*(error|exception|fail|crash|break)",
    r"\bstack\s*trace|traceback|exception",

    # Code analysis
    r"\b(find|search|grep|look\s+for)\s+.*(function|class|method|variable|import|definition)",
    r"\b(where|how)\s+(is|does)\s+.*(defined|implemented|used|called)",
    r"\bshow\s+(me\s+)?(the\s+)?(code|implementation|definition)",

    # Build/compile
    r"\b(build|compile|lint|format|type\s*check)",
    r"\bcargo|npm|pip|poetry|gradle|maven",

    # Version control (in code context)
    r"\b(commit|push|pull|merge|rebase|branch)\s+.*(change|code|feature)",
    r"\bgit\s+(diff|status|log|show)",

    # Dependencies
    r"\b(add|install|update|remove)\s+(a\s+)?(dependency|package|library|module)",
    r"\bimport|require|from\s+\w+\s+import",

    # Class/function creation patterns
    r"\bcreate\s+(a\s+)?(new\s+)?class\b",
    r"\bimplement\s+(a\s+)?(new\s+)?(rest|api|endpoint)",
]

# Patterns that strongly indicate sysadmin requests
_SYSADMIN_PATTERNS = [
    # Services
    r"\b(start|stop|restart|enable|disable)\s+(the\s+)?(\w+\s+)?(service|daemon|systemd)",
    r"\bsystemctl|service\s+\w+\s+(start|stop|restart|status)",
    r"\bjournalctl|dmesg|syslog",
    r"\brestart\s+(the\s+)?(nginx|apache|postgresql|mysql|docker|redis)",
    r"\b(start|stop|restart)\s+(the\s+)?\w*\s*service\b",

    # System resources
    r"\b(check|show|monitor)\s+(the\s+)?(cpu|memory|disk|network|load|processes)",
    r"\b(cpu|memory|disk)\s+(usage|space|utilization)",
    r"\bfree\s+-|top|htop|ps\s+aux|df\s+-|du\s+-",

    # Packages (system level)
    r"\bapt(-get)?|dnf|yum|pacman|brew\s+install",
    r"\binstall\s+(the\s+)?(nginx|apache|mysql|postgresql|redis)\s+(package)?",

    # Users and permissions
    r"\b(add|create|delete|modify)\s+(a\s+)?(new\s+)?(user|group)\s+(named|called)?",
    r"\bchmod|chown|chgrp|passwd|usermod",

    # Network administration
    r"\b(configure|setup|check)\s+(the\s+)?(network|firewall|iptables|dns)",
    r"\bip\s+(addr|link|route)|netstat|ss\s+-|ifconfig",

    # Containers/VMs (operations, not development)
    r"\b(start|stop|restart|remove)\s+(the\s+)?(docker\s+)?(container|pod|vm)",
    r"\bdocker\s+(run|stop|rm|ps|logs)",
    r"\brestart\s+(the\s+)?docker\s+container",

    # Cron/scheduling
    r"\bcrontab|cron\s+job|scheduled\s+task",

    # Security operations
    r"\b(scan|audit|check)\s+(for\s+)?(vulnerabilities|security|malware)",
    r"\bfail2ban|ufw|firewalld",

    # Logs
    r"\b(show|check|view)\s+(me\s+)?(the\s+)?(systemd|system|service)?\s*logs",
    r"\bjournalctl|syslog|/var/log",

    # Service status
    r"\b(check|is)\s+(the\s+)?(service|daemon)\s+(running|active|status)",
]

# Compiled patterns for efficiency
_CODE_REGEX = [re.compile(p, re.IGNORECASE) for p in _CODE_PATTERNS]
_SYSADMIN_REGEX = [re.compile(p, re.IGNORECASE) for p in _SYSADMIN_PATTERNS]


class CodeModeRouter:
    """Routes requests to Code Mode when appropriate.

    When an Act has a repository assigned, the router determines whether
    incoming requests should be handled by Code Mode (agentic coding) or
    the standard sysadmin tools.
    """

    def __init__(self, llm: "LLMProvider | None" = None) -> None:
        """Initialize router.

        Args:
            llm: Optional LLM provider for LLM-based classification
                 of ambiguous requests.
        """
        self._llm = llm

    def should_use_code_mode(
        self,
        request: str,
        active_act: Act | None,
    ) -> RoutingDecision:
        """Determine if request should be handled by Code Mode.

        Args:
            request: The user's request text.
            active_act: The currently active Act, or None.

        Returns:
            RoutingDecision with use_code_mode flag and metadata.
        """
        # No active act or no repo = can't use code mode
        if active_act is None:
            return RoutingDecision(
                use_code_mode=False,
                request_type=RequestType.SYSADMIN,
                confidence=1.0,
                reason="No active Act",
            )

        if not active_act.repo_path:
            return RoutingDecision(
                use_code_mode=False,
                request_type=RequestType.SYSADMIN,
                confidence=1.0,
                reason="Active Act has no repository assigned",
            )

        # Detect request type via pattern matching
        request_type, confidence = self._classify_request(request)

        if request_type == RequestType.CODE:
            return RoutingDecision(
                use_code_mode=True,
                request_type=request_type,
                confidence=confidence,
                reason="Code-related request detected",
            )

        if request_type == RequestType.SYSADMIN:
            return RoutingDecision(
                use_code_mode=False,
                request_type=request_type,
                confidence=confidence,
                reason="Sysadmin request detected",
            )

        # Ambiguous - try LLM classification if available
        if self._llm is not None:
            llm_decision = self._classify_with_llm(request, active_act)
            if llm_decision is not None:
                return llm_decision

        # Default: if Act has repo, bias toward code mode for ambiguous requests
        return RoutingDecision(
            use_code_mode=True,
            request_type=RequestType.AMBIGUOUS,
            confidence=0.6,
            reason="Ambiguous request, defaulting to Code Mode since Act has repo",
        )

    def _classify_request(self, request: str) -> tuple[RequestType, float]:
        """Classify request using pattern matching.

        Returns:
            Tuple of (RequestType, confidence).
        """
        code_matches = sum(1 for regex in _CODE_REGEX if regex.search(request))
        sysadmin_matches = sum(1 for regex in _SYSADMIN_REGEX if regex.search(request))

        total_matches = code_matches + sysadmin_matches

        if total_matches == 0:
            return RequestType.AMBIGUOUS, 0.5

        if code_matches > 0 and sysadmin_matches == 0:
            confidence = min(0.95, 0.7 + (code_matches * 0.1))
            return RequestType.CODE, confidence

        if sysadmin_matches > 0 and code_matches == 0:
            confidence = min(0.95, 0.7 + (sysadmin_matches * 0.1))
            return RequestType.SYSADMIN, confidence

        # Both matched - compare
        if code_matches > sysadmin_matches * 2:
            return RequestType.CODE, 0.7
        if sysadmin_matches > code_matches * 2:
            return RequestType.SYSADMIN, 0.7

        return RequestType.AMBIGUOUS, 0.5

    def _classify_with_llm(
        self,
        request: str,
        active_act: Act,
    ) -> RoutingDecision | None:
        """Use LLM to classify ambiguous request.

        Returns:
            RoutingDecision if classification succeeded, None otherwise.
        """
        if self._llm is None:
            return None

        system_prompt = """You classify user requests as either CODE or SYSADMIN.

CODE requests involve:
- Writing, editing, or reading source code files
- Running tests, debugging code, fixing bugs
- Building/compiling projects
- Managing code dependencies
- Git operations for code changes

SYSADMIN requests involve:
- Managing system services (start/stop/restart)
- Monitoring system resources (CPU, memory, disk)
- Managing users and permissions
- Network and firewall configuration
- System package management

Context: The user is working on an Act with a repository assigned.
Repository: {repo_path}
Artifact type: {artifact_type}

Respond with ONLY one word: CODE or SYSADMIN"""

        try:
            response = self._llm.chat_text(
                system=system_prompt.format(
                    repo_path=active_act.repo_path or "unknown",
                    artifact_type=active_act.artifact_type or "unknown",
                ),
                user=f"Classify this request: {request}",
                temperature=0.0,
            )

            response_clean = response.strip().upper()

            if "CODE" in response_clean:
                return RoutingDecision(
                    use_code_mode=True,
                    request_type=RequestType.CODE,
                    confidence=0.8,
                    reason="LLM classified as code request",
                )
            if "SYSADMIN" in response_clean:
                return RoutingDecision(
                    use_code_mode=False,
                    request_type=RequestType.SYSADMIN,
                    confidence=0.8,
                    reason="LLM classified as sysadmin request",
                )

        except Exception:
            # LLM classification failed, return None to use default
            pass

        return None
