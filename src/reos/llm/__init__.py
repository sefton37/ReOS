"""LLM inference layer — thin wrapper around Ollama."""

from trcore.providers.base import LLMError, LLMProvider, ModelInfo, ProviderHealth
from trcore.providers.factory import check_provider_health, get_provider, get_provider_or_none
from trcore.providers.ollama import OllamaProvider

from .inference import OllamaInference

__all__ = [
    "LLMProvider",
    "LLMError",
    "ModelInfo",
    "ProviderHealth",
    "OllamaProvider",
    "OllamaInference",
    "get_provider",
    "get_provider_or_none",
    "check_provider_health",
]
