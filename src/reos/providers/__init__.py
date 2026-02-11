"""LLM Providers - Pluggable backend support for LLM services.

.. deprecated::
    For new code, prefer importing from the ``llm`` package::

        from llm import LLMProvider, OllamaProvider, get_provider

    This module remains for backward compatibility and provides
    provider-management functions not in the ``llm`` facade.

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
    "check_ollama_installed",
    "get_ollama_install_command",
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
