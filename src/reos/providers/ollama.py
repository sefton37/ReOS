"""Ollama Provider - Local LLM inference via Ollama.

Wraps the existing OllamaClient to implement the LLMProvider protocol.
Adds installation detection and auto-install support.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any

import httpx

from reos.settings import settings

from .base import LLMError, LLMProvider, ModelInfo, ProviderHealth

logger = logging.getLogger(__name__)


# =============================================================================
# Installation Detection
# =============================================================================


def check_ollama_installed() -> bool:
    """Check if Ollama binary is installed on the system."""
    return shutil.which("ollama") is not None


def get_ollama_install_command() -> str:
    """Get the command to install Ollama.

    Returns the official Ollama install script command.
    This should be run through the approval system.
    """
    return "curl -fsSL https://ollama.com/install.sh | sh"


# =============================================================================
# Ollama Provider
# =============================================================================


class OllamaProvider:
    """LLM Provider implementation for Ollama.

    Wraps the existing Ollama HTTP API to implement the LLMProvider protocol.
    Supports local model inference with GPU acceleration.

    Example:
        provider = OllamaProvider(url="http://localhost:11434", model="llama3.2:3b")
        response = provider.chat_text(
            system="You are helpful.",
            user="Hello!",
        )
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize Ollama provider.

        Args:
            url: Ollama server URL. Defaults to settings.ollama_url.
            model: Model to use. Defaults to first available or settings.ollama_model.
        """
        self._url = (url or settings.ollama_url).rstrip("/")
        self._model = model

    @property
    def provider_type(self) -> str:
        """Provider identifier."""
        return "ollama"

    def chat_text(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate plain text response."""
        payload = self._build_payload(
            system=system,
            user=user,
            temperature=temperature,
            top_p=top_p,
        )
        payload["format"] = ""
        return self._post_chat(payload, timeout_seconds)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Generate JSON-formatted response."""
        payload = self._build_payload(
            system=system,
            user=user,
            temperature=temperature,
            top_p=top_p,
        )
        payload["format"] = "json"
        return self._post_chat(payload, timeout_seconds)

    def list_models(self) -> list[ModelInfo]:
        """List available Ollama models."""
        try:
            url = f"{self._url}/api/tags"
            with httpx.Client(timeout=5.0) as client:
                res = client.get(url)
                res.raise_for_status()
                data = res.json()

            models = []
            for m in data.get("models", []):
                if isinstance(m, dict) and isinstance(m.get("name"), str):
                    # Parse model details
                    details = m.get("details", {})
                    size_bytes = m.get("size", 0)
                    size_gb = size_bytes / (1024**3) if size_bytes else None

                    # Extract capabilities from model name/family
                    capabilities = []
                    name_lower = m["name"].lower()
                    if "llava" in name_lower or "vision" in name_lower:
                        capabilities.append("vision")
                    if details.get("families") and "tools" in str(details.get("families")):
                        capabilities.append("tools")

                    models.append(
                        ModelInfo(
                            name=m["name"],
                            size_gb=round(size_gb, 1) if size_gb else None,
                            context_length=details.get("context_length"),
                            capabilities=capabilities,
                            description=details.get("family"),
                        )
                    )

            return models

        except Exception as e:
            logger.warning("Failed to list Ollama models: %s", e)
            return []

    def check_health(self) -> ProviderHealth:
        """Check Ollama server health."""
        try:
            url = f"{self._url}/api/tags"
            with httpx.Client(timeout=2.0) as client:
                res = client.get(url)
                res.raise_for_status()
                data = res.json()
                models = data.get("models", [])

            return ProviderHealth(
                reachable=True,
                model_count=len(models),
                current_model=self._model or self._get_default_model(),
            )

        except Exception as e:
            return ProviderHealth(
                reachable=False,
                error=str(e),
            )

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

    def _build_payload(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None,
        top_p: float | None,
    ) -> dict[str, Any]:
        """Build the chat request payload."""
        model = self._model or self._get_default_model()
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

    def _post_chat(self, payload: dict[str, Any], timeout_seconds: float) -> str:
        """Send chat request to Ollama."""
        url = f"{self._url}/api/chat"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
        except Exception as e:
            raise LLMError(f"Ollama request failed: {e}") from e

        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMError("Unexpected Ollama response: missing message")

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Unexpected Ollama response: missing content")

        return content.strip()

    def _get_default_model(self) -> str:
        """Get the default model (first available or from settings)."""
        if settings.ollama_model:
            return settings.ollama_model

        try:
            models = self.list_models()
            if models:
                return models[0].name
        except Exception:
            pass

        raise LLMError(
            "No Ollama model configured. Set REOS_OLLAMA_MODEL or pull a model."
        )


# Type assertion to verify protocol compliance
def _check_protocol() -> None:
    """Verify OllamaProvider implements LLMProvider protocol."""
    provider: LLMProvider = OllamaProvider()
    _ = provider  # noqa: F841
