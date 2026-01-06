"""LLM Providers - Pluggable backend support for multiple LLM services.

This package provides a unified interface for different LLM providers:
- Ollama: Local inference, runs on your machine
- Anthropic: Claude API (cloud)
- Future: OpenAI, local llama.cpp, etc.

Usage:
    from reos.providers import get_provider, LLMProvider

    # Get the configured provider
    provider = get_provider(db)

    # Use it
    response = provider.chat_text(
        system="You are helpful.",
        user="Hello!",
    )

Provider selection is stored in the database and can be changed
via the Settings UI.
"""

from __future__ import annotations

# Base types
from reos.providers.base import (
    LLMError,
    LLMProvider,
    ModelInfo,
    ProviderHealth,
)

# Provider implementations
from reos.providers.ollama import (
    OllamaProvider,
    check_ollama_installed,
    get_ollama_install_command,
)
from reos.providers.anthropic import (
    AnthropicProvider,
    check_anthropic_available,
    CLAUDE_MODELS,
)

# Factory functions
from reos.providers.factory import (
    get_provider,
    get_provider_or_none,
    get_current_provider_type,
    set_provider_type,
    check_provider_health,
    list_providers,
    get_provider_info,
    ProviderInfo,
    AVAILABLE_PROVIDERS,
)

# Secrets management
from reos.providers.secrets import (
    store_api_key,
    get_api_key,
    delete_api_key,
    has_api_key,
    check_keyring_available,
    get_keyring_backend_name,
    list_stored_providers,
)

__all__ = [
    # Base types
    "LLMError",
    "LLMProvider",
    "ModelInfo",
    "ProviderHealth",
    # Providers
    "OllamaProvider",
    "AnthropicProvider",
    "check_ollama_installed",
    "get_ollama_install_command",
    "check_anthropic_available",
    "CLAUDE_MODELS",
    # Factory
    "get_provider",
    "get_provider_or_none",
    "get_current_provider_type",
    "set_provider_type",
    "check_provider_health",
    "list_providers",
    "get_provider_info",
    "ProviderInfo",
    "AVAILABLE_PROVIDERS",
    # Secrets
    "store_api_key",
    "get_api_key",
    "delete_api_key",
    "has_api_key",
    "check_keyring_available",
    "get_keyring_backend_name",
    "list_stored_providers",
]
