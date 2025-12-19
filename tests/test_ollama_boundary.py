from __future__ import annotations

from typing import Any

import pytest

from reos.ollama import OllamaClient, OllamaError, check_ollama, list_ollama_models


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, *, get_resp: _FakeResponse | None = None, post_resp: _FakeResponse | None = None) -> None:
        self._get_resp = get_resp
        self._post_resp = post_resp

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def get(self, url: str):  # noqa: ARG002
        if self._get_resp is None:
            raise RuntimeError("boom")
        return self._get_resp

    def post(self, url: str, json: dict[str, Any]):  # noqa: ARG002
        if self._post_resp is None:
            raise RuntimeError("boom")
        return self._post_resp


def test_check_ollama_reachable_true(monkeypatch: pytest.MonkeyPatch) -> None:
    import reos.ollama as ollama_mod

    def fake_client(*_args, **_kwargs):
        return _FakeClient(get_resp=_FakeResponse(payload={"models": [{"name": "m1"}] }))

    monkeypatch.setattr(ollama_mod.httpx, "Client", fake_client)

    health = check_ollama(url="http://127.0.0.1:11434")
    assert health.reachable is True
    assert health.model_count == 1
    assert health.error is None


def test_check_ollama_reachable_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import reos.ollama as ollama_mod

    def fake_client(*_args, **_kwargs):
        return _FakeClient(get_resp=None)

    monkeypatch.setattr(ollama_mod.httpx, "Client", fake_client)

    health = check_ollama(url="http://127.0.0.1:11434")
    assert health.reachable is False
    assert health.model_count is None
    assert isinstance(health.error, str)


def test_list_ollama_models_filters_names(monkeypatch: pytest.MonkeyPatch) -> None:
    import reos.ollama as ollama_mod

    def fake_client(*_args, **_kwargs):
        return _FakeClient(
            get_resp=_FakeResponse(payload={"models": [{"name": "a"}, {"nope": 1}, "x"]})
        )

    monkeypatch.setattr(ollama_mod.httpx, "Client", fake_client)

    models = list_ollama_models(url="http://127.0.0.1:11434")
    assert models == ["a"]


def test_ollama_client_raises_on_missing_message(monkeypatch: pytest.MonkeyPatch) -> None:
    import reos.ollama as ollama_mod

    def fake_client(*_args, **_kwargs):
        return _FakeClient(post_resp=_FakeResponse(payload={"nope": True}))

    monkeypatch.setattr(ollama_mod.httpx, "Client", fake_client)

    client = OllamaClient(url="http://127.0.0.1:11434", model="m")
    with pytest.raises(OllamaError):
        client.chat_text(system="s", user="u")


def test_ollama_client_raises_on_missing_content(monkeypatch: pytest.MonkeyPatch) -> None:
    import reos.ollama as ollama_mod

    def fake_client(*_args, **_kwargs):
        return _FakeClient(post_resp=_FakeResponse(payload={"message": {"role": "assistant"}}))

    monkeypatch.setattr(ollama_mod.httpx, "Client", fake_client)

    client = OllamaClient(url="http://127.0.0.1:11434", model="m")
    with pytest.raises(OllamaError):
        client.chat_text(system="s", user="u")
