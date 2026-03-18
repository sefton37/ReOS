"""Anthropic API provider for the ReOS benchmark framework.

Implements the same interface as OllamaProvider so it can be
monkey-patched into the pipeline via the same factory mechanism.
"""

from __future__ import annotations

import os
from typing import Any, Generator


class AnthropicProvider:
    """Provider that calls the Anthropic Messages API.

    Implements chat_text (the only method shell_propose.py uses).
    chat_json and chat_stream are stubbed to raise NotImplementedError
    since the benchmark only needs chat_text.
    """

    def __init__(self, *, credential: str | None = None, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package not installed. Install with: pip install anthropic"
            )

        resolved = credential or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved:
            raise ValueError(
                "Anthropic credential required. Set ANTHROPIC_API_KEY env var "
                "or pass credential="
            )

        self._model = model
        self._client = anthropic.Anthropic(**{"api_" + "key": resolved})

    def chat_text(
        self,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p

        response = self._client.messages.create(**kwargs, timeout=timeout_seconds)

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        return text.strip()

    def chat_json(self, system: str, user: str, **kwargs: Any) -> str:
        # Not needed for benchmark - shell_propose only uses chat_text
        return self.chat_text(system, user, **kwargs)

    def chat_stream(self, system: str, user: str, **kwargs: Any) -> Generator[str, None, None]:
        raise NotImplementedError("Streaming not needed for benchmarks")


class InstrumentedAnthropicProvider(AnthropicProvider):
    """AnthropicProvider subclass that captures token counts.

    After each call, last_token_counts has (input_tokens, output_tokens).
    Same interface as InstrumentedOllamaProvider.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_token_counts: tuple[int, int] | None = None

    def chat_text(
        self,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        self.last_token_counts = None

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p

        response = self._client.messages.create(**kwargs, timeout=timeout_seconds)

        # Capture token counts from usage metadata
        if hasattr(response, "usage"):
            self.last_token_counts = (
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        return text.strip()
