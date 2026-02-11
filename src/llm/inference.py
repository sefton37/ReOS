"""High-level inference interface wrapping OllamaProvider.

Provides a cleaner API for common LLM operations:
- generate() for text completion
- classify() for structured JSON output
- stream() for streaming responses
"""

import json
from collections.abc import Generator

from reos.providers.base import LLMError
from reos.providers.ollama import OllamaProvider


class OllamaInference:
    """High-level inference interface for Ollama models.

    Wraps OllamaProvider with more intuitive method names and handles
    common patterns like JSON parsing for classification tasks.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize inference client.

        Args:
            url: Ollama API URL (defaults to http://localhost:11434)
            model: Model name (e.g., "llama3.2:1b")
        """
        self.provider = OllamaProvider(url=url, model=model)

    def generate(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate text completion.

        Args:
            system: System prompt defining behavior
            user: User prompt with the task
            timeout_seconds: Request timeout
            temperature: Sampling temperature (0.0-1.0)
            top_p: Nucleus sampling threshold

        Returns:
            Generated text response

        Raises:
            LLMError: If generation fails
        """
        return self.provider.chat_text(
            system=system,
            user=user,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
        )

    def classify(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> dict:
        """Generate structured JSON classification.

        Uses Ollama's JSON mode to ensure valid JSON output.

        Args:
            system: System prompt defining the classification schema
            user: User prompt with content to classify
            timeout_seconds: Request timeout
            temperature: Sampling temperature (0.0-1.0)
            top_p: Nucleus sampling threshold

        Returns:
            Parsed JSON object as a dictionary

        Raises:
            LLMError: If classification fails or JSON is invalid
        """
        json_str = self.provider.chat_json(
            system=system,
            user=user,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
        )

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise LLMError(f"Failed to parse JSON response: {e}") from e

    def stream(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> Generator[str, None, None]:
        """Stream text completion token by token.

        Args:
            system: System prompt defining behavior
            user: User prompt with the task
            timeout_seconds: Request timeout
            temperature: Sampling temperature (0.0-1.0)
            top_p: Nucleus sampling threshold

        Yields:
            Text chunks as they're generated

        Raises:
            LLMError: If streaming fails
        """
        yield from self.provider.chat_stream(
            system=system,
            user=user,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            top_p=top_p,
        )
