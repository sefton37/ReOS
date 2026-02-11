"""Tests for llm.inference — OllamaInference wrapper."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from llm.inference import OllamaInference
from reos.providers.base import LLMError


class TestOllamaInference:
    """Test the OllamaInference high-level wrapper."""

    def _make_inference(self) -> tuple[OllamaInference, MagicMock]:
        """Create an OllamaInference with a mocked provider."""
        with patch("llm.inference.OllamaProvider") as mock_cls:
            mock_provider = MagicMock()
            mock_cls.return_value = mock_provider
            inference = OllamaInference(url="http://test:11434", model="test-model")
            return inference, mock_provider

    def test_generate_delegates_to_chat_text(self):
        inference, provider = self._make_inference()
        provider.chat_text.return_value = "Hello world"

        result = inference.generate(system="sys", user="hi")

        assert result == "Hello world"
        provider.chat_text.assert_called_once_with(
            system="sys",
            user="hi",
            timeout_seconds=60.0,
            temperature=None,
            top_p=None,
        )

    def test_generate_passes_temperature(self):
        inference, provider = self._make_inference()
        provider.chat_text.return_value = "ok"

        inference.generate(system="sys", user="hi", temperature=0.5, top_p=0.9)

        provider.chat_text.assert_called_once_with(
            system="sys",
            user="hi",
            timeout_seconds=60.0,
            temperature=0.5,
            top_p=0.9,
        )

    def test_classify_parses_json(self):
        inference, provider = self._make_inference()
        provider.chat_json.return_value = '{"label": "greeting", "score": 0.95}'

        result = inference.classify(system="classify", user="hello")

        assert result == {"label": "greeting", "score": 0.95}

    def test_classify_raises_on_invalid_json(self):
        inference, provider = self._make_inference()
        provider.chat_json.return_value = "not json at all"

        with pytest.raises(LLMError, match="Failed to parse JSON"):
            inference.classify(system="classify", user="hello")

    def test_stream_yields_tokens(self):
        inference, provider = self._make_inference()
        provider.chat_stream.return_value = iter(["Hello", " ", "world"])

        tokens = list(inference.stream(system="sys", user="hi"))

        assert tokens == ["Hello", " ", "world"]

    def test_generate_propagates_llm_error(self):
        inference, provider = self._make_inference()
        provider.chat_text.side_effect = LLMError("Connection failed")

        with pytest.raises(LLMError, match="Connection failed"):
            inference.generate(system="sys", user="hi")
