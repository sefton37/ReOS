"""Ollama client with robustness features.

Provides a resilient HTTP client for local Ollama LLM inference with:
- Retry with exponential backoff for transient failures
- Streaming support for real-time token generation
- Async support for non-blocking operations
- Graceful degradation with helpful error messages
"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator, AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx
import tenacity

from .config import TIMEOUTS
from .settings import settings

logger = logging.getLogger(__name__)


# =============================================================================
# Health Check Types
# =============================================================================


@dataclass(frozen=True)
class OllamaHealth:
    """Health check result for Ollama server."""

    reachable: bool
    model_count: int | None
    error: str | None
    suggested_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for RPC responses."""
        return {
            "reachable": self.reachable,
            "model_count": self.model_count,
            "error": self.error,
            "suggested_action": self.suggested_action,
        }


class OllamaError(RuntimeError):
    """Error from Ollama operations."""

    def __init__(self, message: str, *, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable


class OllamaConnectionError(OllamaError):
    """Cannot connect to Ollama server."""

    def __init__(self, message: str):
        super().__init__(message, recoverable=True)


class OllamaTimeoutError(OllamaError):
    """Ollama request timed out."""

    def __init__(self, message: str):
        super().__init__(message, recoverable=True)


class OllamaModelError(OllamaError):
    """Model-related error (not found, not loaded)."""

    def __init__(self, message: str):
        super().__init__(message, recoverable=False)


# =============================================================================
# Retry Configuration
# =============================================================================


def _is_retryable_exception(exc: BaseException) -> bool:
    """Check if an exception should trigger a retry."""
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, OllamaConnectionError))


# Retry decorator for transient failures
_retry_on_transient = tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=4),
    retry=tenacity.retry_if_exception(_is_retryable_exception),
    before_sleep=lambda retry_state: logger.debug(
        "Retrying Ollama request (attempt %d) after error: %s",
        retry_state.attempt_number,
        retry_state.outcome.exception() if retry_state.outcome else "unknown",
    ),
    reraise=True,
)


# =============================================================================
# Health Check Functions
# =============================================================================


def check_ollama(
    timeout_seconds: float = TIMEOUTS.OLLAMA_CHECK,
    *,
    url: str | None = None,
) -> OllamaHealth:
    """Check local Ollama availability.

    Privacy: does not send any user content; only hits the local tags endpoint.

    Returns:
        OllamaHealth with reachability status and model count
    """
    base = (url or settings.ollama_url).rstrip("/")
    url_tags = base + "/api/tags"

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            res = client.get(url_tags)
            res.raise_for_status()
            payload = res.json()
            models = payload.get("models") or []

            if not models:
                return OllamaHealth(
                    reachable=True,
                    model_count=0,
                    error="No models installed",
                    suggested_action="Run 'ollama pull llama3.2:3b' to download a model",
                )

            return OllamaHealth(
                reachable=True,
                model_count=len(models),
                error=None,
            )

    except httpx.ConnectError:
        return OllamaHealth(
            reachable=False,
            model_count=None,
            error="Cannot connect to Ollama server",
            suggested_action="Run 'ollama serve' or check if Ollama is installed",
        )

    except httpx.TimeoutException:
        return OllamaHealth(
            reachable=False,
            model_count=None,
            error="Connection timed out",
            suggested_action="Ollama may be busy loading a model. Try again in a moment.",
        )

    except Exception as exc:
        return OllamaHealth(
            reachable=False,
            model_count=None,
            error=str(exc),
            suggested_action="Check Ollama logs for details",
        )


def list_ollama_models(
    *,
    url: str | None = None,
    timeout_seconds: float = TIMEOUTS.OLLAMA_MODELS,
) -> list[str]:
    """List available Ollama model tags."""
    base = (url or settings.ollama_url).rstrip("/")
    url_tags = base + "/api/tags"

    with httpx.Client(timeout=timeout_seconds) as client:
        res = client.get(url_tags)
        res.raise_for_status()
        payload = res.json()
        models = payload.get("models") or []

    out: list[str] = []
    if isinstance(models, list):
        for m in models:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                out.append(m["name"])
    return out


@dataclass(frozen=True)
class OllamaModelDetails:
    """Detailed model information from Ollama."""

    name: str
    parameter_size: str | None
    quantization_level: str | None
    family: str | None
    size_bytes: int | None
    modified_at: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for RPC responses."""
        return {
            "name": self.name,
            "parameter_size": self.parameter_size,
            "quantization": self.quantization_level,
            "family": self.family,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


def list_ollama_models_detailed(
    *,
    url: str | None = None,
    timeout_seconds: float = TIMEOUTS.OLLAMA_MODELS,
) -> list[OllamaModelDetails]:
    """List available Ollama models with detailed information.

    Returns full model info from /api/tags including parameter_size,
    quantization_level, and family from the Ollama response.
    """
    base = (url or settings.ollama_url).rstrip("/")
    url_tags = base + "/api/tags"

    with httpx.Client(timeout=timeout_seconds) as client:
        res = client.get(url_tags)
        res.raise_for_status()
        payload = res.json()
        models = payload.get("models") or []

    out: list[OllamaModelDetails] = []
    if isinstance(models, list):
        for m in models:
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            if not isinstance(name, str):
                continue

            details = m.get("details", {})
            if not isinstance(details, dict):
                details = {}

            out.append(OllamaModelDetails(
                name=name,
                parameter_size=details.get("parameter_size"),
                quantization_level=details.get("quantization_level"),
                family=details.get("family"),
                size_bytes=m.get("size"),
                modified_at=m.get("modified_at"),
            ))
    return out


def _default_model(timeout_seconds: float = TIMEOUTS.OLLAMA_MODELS) -> str:
    """Get the default model (from settings or first available)."""
    if settings.ollama_model:
        return settings.ollama_model

    url = settings.ollama_url.rstrip("/") + "/api/tags"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            res = client.get(url)
            res.raise_for_status()
            payload = res.json()
            models = payload.get("models") or []
            if models and isinstance(models, list):
                first = models[0]
                if isinstance(first, dict) and isinstance(first.get("name"), str):
                    return first["name"]
    except Exception:
        pass

    raise OllamaModelError(
        "No Ollama model configured. Set REOS_OLLAMA_MODEL or pull a model with 'ollama pull llama3.2:3b'"
    )


# =============================================================================
# Synchronous Client
# =============================================================================


class OllamaClient:
    """Synchronous Ollama client with retry and streaming support."""

    def __init__(self, *, url: str | None = None, model: str | None = None) -> None:
        """Initialize Ollama client.

        Args:
            url: Ollama server URL. Defaults to settings.ollama_url.
            model: Model to use. Defaults to settings.ollama_model or first available.
        """
        self._url = (url or settings.ollama_url).rstrip("/")
        self._model = model

    @property
    def model(self) -> str:
        """Get the model name (resolving default if needed)."""
        return self._model or _default_model()

    def chat_text(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = TIMEOUTS.LLM_DEFAULT,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Chat and return assistant text.

        Automatically retries on transient failures.
        """
        payload = self._chat_payload(
            system=system, user=user, temperature=temperature, top_p=top_p
        )
        payload["format"] = ""  # plain text
        return self._post_chat(payload=payload, timeout_seconds=timeout_seconds)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = TIMEOUTS.LLM_DEFAULT,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Chat and request JSON-formatted output.

        Returns a raw string; callers should json.loads it.
        Automatically retries on transient failures.
        """
        payload = self._chat_payload(
            system=system, user=user, temperature=temperature, top_p=top_p
        )
        payload["format"] = "json"
        return self._post_chat(payload=payload, timeout_seconds=timeout_seconds)

    def chat_stream(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = TIMEOUTS.LLM_DEFAULT,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> Generator[str, None, None]:
        """Chat with streaming response.

        Yields tokens as they arrive from the model.
        Does NOT retry on failure (streaming is not idempotent).

        Yields:
            Individual tokens as strings
        """
        payload = self._chat_payload(
            system=system, user=user, temperature=temperature, top_p=top_p
        )
        payload["stream"] = True
        payload["format"] = ""

        url = self._url + "/api/chat"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            message = data.get("message", {})
                            content = message.get("content", "")
                            if content:
                                yield content
                            # Check if stream is done
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            logger.debug("Failed to parse streaming response line: %s", line)
                            continue

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self._url}. Is 'ollama serve' running?"
            ) from e

        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {timeout_seconds}s"
            ) from e

        except Exception as e:
            raise OllamaError(f"Streaming request failed: {e}") from e

    def _chat_payload(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None,
        top_p: float | None,
    ) -> dict[str, Any]:
        """Build the chat request payload."""
        model = self._model or _default_model()
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = float(temperature)
        if top_p is not None:
            options["top_p"] = float(top_p)
        return {
            "model": model,
            "stream": False,
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    @_retry_on_transient
    def _post_chat(self, *, payload: dict[str, Any], timeout_seconds: float) -> str:
        """Send chat request to Ollama with automatic retry."""
        url = self._url + "/api/chat"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self._url}. Is 'ollama serve' running?"
            ) from e

        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {timeout_seconds}s. "
                "The model may be loading or the request is complex."
            ) from e

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise OllamaModelError(
                    f"Model '{payload.get('model')}' not found. "
                    f"Run 'ollama pull {payload.get('model')}' to download it."
                ) from e
            raise OllamaError(f"Ollama HTTP error: {e}") from e

        except Exception as e:
            raise OllamaError(f"Ollama request failed: {e}") from e

        message = data.get("message")
        if not isinstance(message, dict):
            raise OllamaError("Unexpected Ollama response: missing message")

        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaError("Unexpected Ollama response: missing content")

        return content.strip()


# =============================================================================
# Async Client
# =============================================================================


class AsyncOllamaClient:
    """Asynchronous Ollama client for non-blocking operations."""

    def __init__(self, *, url: str | None = None, model: str | None = None) -> None:
        """Initialize async Ollama client.

        Args:
            url: Ollama server URL. Defaults to settings.ollama_url.
            model: Model to use. Defaults to settings.ollama_model or first available.
        """
        self._url = (url or settings.ollama_url).rstrip("/")
        self._model = model

    async def chat_text(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = TIMEOUTS.LLM_DEFAULT,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Chat and return assistant text asynchronously."""
        payload = self._chat_payload(
            system=system, user=user, temperature=temperature, top_p=top_p
        )
        payload["format"] = ""
        return await self._post_chat(payload=payload, timeout_seconds=timeout_seconds)

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = TIMEOUTS.LLM_DEFAULT,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Chat and request JSON-formatted output asynchronously."""
        payload = self._chat_payload(
            system=system, user=user, temperature=temperature, top_p=top_p
        )
        payload["format"] = "json"
        return await self._post_chat(payload=payload, timeout_seconds=timeout_seconds)

    async def chat_stream(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = TIMEOUTS.LLM_DEFAULT,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> AsyncGenerator[str, None]:
        """Chat with async streaming response.

        Yields tokens as they arrive from the model.

        Yields:
            Individual tokens as strings
        """
        payload = self._chat_payload(
            system=system, user=user, temperature=temperature, top_p=top_p
        )
        payload["stream"] = True
        payload["format"] = ""

        url = self._url + "/api/chat"
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            message = data.get("message", {})
                            content = message.get("content", "")
                            if content:
                                yield content
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self._url}"
            ) from e

        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Ollama request timed out after {timeout_seconds}s"
            ) from e

        except Exception as e:
            raise OllamaError(f"Async streaming request failed: {e}") from e

    def _chat_payload(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None,
        top_p: float | None,
    ) -> dict[str, Any]:
        """Build the chat request payload."""
        model = self._model or _default_model()
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = float(temperature)
        if top_p is not None:
            options["top_p"] = float(top_p)
        return {
            "model": model,
            "stream": False,
            "options": options,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def _post_chat(
        self, *, payload: dict[str, Any], timeout_seconds: float
    ) -> str:
        """Send async chat request to Ollama."""
        url = self._url + "/api/chat"

        # Manual retry for async
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    res = await client.post(url, json=payload)
                    res.raise_for_status()
                    data = res.json()

                message = data.get("message")
                if not isinstance(message, dict):
                    raise OllamaError("Unexpected Ollama response: missing message")

                content = message.get("content")
                if not isinstance(content, str):
                    raise OllamaError("Unexpected Ollama response: missing content")

                return content.strip()

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    logger.debug("Retrying async Ollama request (attempt %d)", attempt + 2)
                    continue
                break

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise OllamaModelError(
                        f"Model '{payload.get('model')}' not found"
                    ) from e
                raise OllamaError(f"Ollama HTTP error: {e}") from e

            except Exception as e:
                raise OllamaError(f"Async request failed: {e}") from e

        # All retries exhausted
        if isinstance(last_error, httpx.ConnectError):
            raise OllamaConnectionError(
                f"Cannot connect to Ollama at {self._url} after 3 attempts"
            ) from last_error
        elif isinstance(last_error, httpx.TimeoutException):
            raise OllamaTimeoutError(
                f"Ollama request timed out after 3 attempts"
            ) from last_error
        else:
            raise OllamaError(f"Async request failed: {last_error}") from last_error


# =============================================================================
# Check Ollama Installation
# =============================================================================


def check_ollama_installed() -> bool:
    """Check if Ollama binary is installed on the system."""
    import shutil
    return shutil.which("ollama") is not None


def get_install_suggestion() -> str:
    """Get a suggestion for installing Ollama."""
    return (
        "Ollama is not installed. Install it with:\n"
        "  curl -fsSL https://ollama.com/install.sh | sh\n\n"
        "Then start the server with:\n"
        "  ollama serve\n\n"
        "And pull a model:\n"
        "  ollama pull llama3.2:3b"
    )
