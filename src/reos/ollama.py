from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .settings import settings


@dataclass(frozen=True)
class OllamaHealth:
    reachable: bool
    model_count: int | None
    error: str | None


def check_ollama(timeout_seconds: float = 1.5, *, url: str | None = None) -> OllamaHealth:
    """Check local Ollama availability.

    Privacy: does not send any user content; only hits the local tags endpoint.
    """

    base = (url or settings.ollama_url).rstrip("/")
    url_tags = base + "/api/tags"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            res = client.get(url_tags)
            res.raise_for_status()
            payload = res.json()
            models = payload.get("models") or []
            return OllamaHealth(reachable=True, model_count=len(models), error=None)
    except Exception as exc:  # noqa: BLE001
        return OllamaHealth(reachable=False, model_count=None, error=str(exc))


def list_ollama_models(*, url: str | None = None, timeout_seconds: float = 2.0) -> list[str]:
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


class OllamaError(RuntimeError):
    pass


def _default_model(timeout_seconds: float = 2.0) -> str:
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

    raise OllamaError(
        "No Ollama model configured. Set REOS_OLLAMA_MODEL or pull a model in Ollama."
    )


class OllamaClient:
    def __init__(self, *, url: str | None = None, model: str | None = None) -> None:
        self._url = (url or settings.ollama_url).rstrip("/")
        self._model = model

    def chat_text(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Chat and return assistant text."""

        payload = self._chat_payload(system=system, user=user, temperature=temperature, top_p=top_p)
        payload["format"] = ""  # plain
        return self._post_chat(payload=payload, timeout_seconds=timeout_seconds)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        timeout_seconds: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> str:
        """Chat and request JSON-formatted output.

        Returns a raw string; callers should json.loads it.
        """

        payload = self._chat_payload(system=system, user=user, temperature=temperature, top_p=top_p)
        payload["format"] = "json"
        return self._post_chat(payload=payload, timeout_seconds=timeout_seconds)

    def _chat_payload(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None,
        top_p: float | None,
    ) -> dict[str, Any]:
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

    def _post_chat(self, *, payload: dict[str, Any], timeout_seconds: float) -> str:
        url = self._url + "/api/chat"
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
        except Exception as exc:  # noqa: BLE001
            raise OllamaError(str(exc)) from exc

        message = data.get("message")
        if not isinstance(message, dict):
            raise OllamaError("Unexpected Ollama response: missing message")
        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaError("Unexpected Ollama response: missing content")
        return content.strip()
