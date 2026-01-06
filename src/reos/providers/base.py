"""Base LLM Provider Protocol - Abstract interface for LLM backends.

All LLM providers (Ollama, Anthropic, OpenAI, etc.) implement this protocol
to provide a unified interface for chat completions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Base exception for LLM provider errors.

    Wraps all provider-specific errors (network, auth, rate limits, etc.)
    into a single exception type for consistent error handling.
    """

    pass


@dataclass
class ProviderHealth:
    """Health status of an LLM provider.

    Attributes:
        reachable: Whether the provider is accessible.
        model_count: Number of available models (for local providers).
        error: Error message if not reachable.
        current_model: Currently selected model name.
    """

    reachable: bool
    model_count: int = 0
    error: str | None = None
    current_model: str | None = None


@dataclass
class ModelInfo:
    """Information about an available model.

    Attributes:
        name: Model identifier (e.g., "llama3.2:3b", "claude-sonnet-4-20250514").
        size_gb: Model size in gigabytes (for local models).
        context_length: Maximum context window size.
        capabilities: List of capabilities (e.g., ["tools", "vision"]).
        description: Human-readable description.
    """

    name: str
    size_gb: float | None = None
    context_length: int | None = None
    capabilities: list[str] = field(default_factory=list)
    description: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract interface for LLM providers.

    All providers must implement these methods to be usable by ReOS.
    The interface matches the existing OllamaClient API for compatibility.

    Example:
        provider = get_provider(db)
        response = provider.chat_text(
            system="You are a helpful assistant.",
            user="Hello!",
            temperature=0.7,
        )
    """

    @property
    def provider_type(self) -> str:
        """Provider identifier (e.g., "ollama", "anthropic")."""
        ...

    def chat_text(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate a plain text response.

        Args:
            system: System prompt/instructions.
            user: User message.
            timeout_seconds: Request timeout in seconds.
            temperature: Sampling temperature (0.0-2.0, provider-dependent).
            top_p: Nucleus sampling parameter (0.0-1.0).

        Returns:
            Plain text response (trimmed).

        Raises:
            LLMError: On any failure (network, auth, parsing, etc.).
        """
        ...

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate a JSON-formatted response.

        The provider should request JSON output from the model.
        Returns raw JSON string - caller is responsible for parsing.

        Args:
            system: System prompt/instructions (should request JSON output).
            user: User message.
            timeout_seconds: Request timeout in seconds.
            temperature: Sampling temperature.
            top_p: Nucleus sampling parameter.

        Returns:
            Raw JSON string (caller should use json.loads()).

        Raises:
            LLMError: On any failure.
        """
        ...

    def list_models(self) -> list[ModelInfo]:
        """List available models.

        Returns:
            List of ModelInfo for available models.
            For cloud providers, returns preconfigured model list.
            For local providers, queries the actual available models.
        """
        ...

    def check_health(self) -> ProviderHealth:
        """Check provider health and connectivity.

        Returns:
            ProviderHealth with reachability status.
        """
        ...
