"""Instrumented Ollama provider for the ReOS benchmark framework.

Subclasses OllamaProvider to capture token counts (prompt_eval_count and
eval_count) from the raw Ollama /api/chat response body.  These fields are
normally discarded by _post_chat; the instrumented variant stores them so
the benchmark runner can record per-call token usage.
"""

from __future__ import annotations

from typing import Any

from trcore.providers.ollama import OllamaProvider


class InstrumentedOllamaProvider(OllamaProvider):
    """OllamaProvider subclass that captures token counts from Ollama responses.

    After each successful call to chat_text or chat_json, the token counts from
    the most recent response are available via ``last_token_counts``.

    Attributes:
        last_token_counts: Tuple of (prompt_tokens, completion_tokens) from the
            last response, or None if no successful call has been made yet.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_token_counts: tuple[int, int] | None = None  # (prompt, completion)

    def _post_chat(self, payload: dict[str, Any], timeout_seconds: float) -> str:
        """Send chat request to Ollama and capture token counts before returning.

        Overrides OllamaProvider._post_chat to intercept the raw response body
        and extract eval_count (completion tokens) and prompt_eval_count (prompt
        tokens) before delegating content extraction to the parent.

        The parent already handles retries, error raising, and content extraction;
        we only need to re-issue the HTTP call once ourselves.  To avoid
        duplicating that logic, we call into the parent and separately cache the
        token fields via a thin wrapper around the underlying HTTP call.
        """
        import httpx
        from trcore.providers.base import LLMError

        url = f"{self._url}/api/chat"
        # Reset on each call so stale data is never returned for a failed attempt.
        self.last_token_counts = None

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()

        except httpx.ConnectError as e:
            raise LLMError(
                f"Cannot connect to Ollama at {self._url}. "
                "Is 'ollama serve' running?"
            ) from e

        except httpx.TimeoutException as e:
            raise LLMError(
                f"Ollama request timed out after {timeout_seconds}s. "
                "The model may be loading or the request is complex."
            ) from e

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                model = payload.get("model", "unknown")
                raise LLMError(
                    f"Model '{model}' not found. "
                    f"Run 'ollama pull {model}' to download it."
                ) from e
            raise LLMError(f"Ollama HTTP error: {e}") from e

        except Exception as e:
            raise LLMError(f"Ollama request failed: {e}") from e

        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMError("Unexpected Ollama response: missing message")

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Unexpected Ollama response: missing content")

        # Capture token counts from the Ollama response fields.
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            self.last_token_counts = (prompt_tokens, completion_tokens)

        return content.strip()
