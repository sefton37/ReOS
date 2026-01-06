"""Provider Factory - Create LLM providers based on configuration.

This module provides a unified way to get the currently configured
LLM provider, abstracting away the provider-specific initialization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import LLMError, LLMProvider, ProviderHealth

if TYPE_CHECKING:
    from reos.db import Database

logger = logging.getLogger(__name__)


# =============================================================================
# Provider Information
# =============================================================================


@dataclass
class ProviderInfo:
    """Information about an available provider.

    Attributes:
        id: Provider identifier (e.g., "ollama", "anthropic").
        name: Human-readable name.
        description: Short description.
        is_local: Whether the provider runs locally.
        requires_api_key: Whether an API key is required.
    """

    id: str
    name: str
    description: str
    is_local: bool = False
    requires_api_key: bool = False


# Available providers
AVAILABLE_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        id="ollama",
        name="Ollama (Local)",
        description="Private, runs on your machine. No data leaves your computer.",
        is_local=True,
        requires_api_key=False,
    ),
    ProviderInfo(
        id="anthropic",
        name="Anthropic (Claude)",
        description="Cloud API powered by Claude. Requires API key.",
        is_local=False,
        requires_api_key=True,
    ),
]


def list_providers() -> list[ProviderInfo]:
    """List all available LLM providers.

    Returns:
        List of ProviderInfo for available providers.
    """
    return AVAILABLE_PROVIDERS.copy()


def get_provider_info(provider_id: str) -> ProviderInfo | None:
    """Get information about a specific provider.

    Args:
        provider_id: Provider identifier.

    Returns:
        ProviderInfo if found, None otherwise.
    """
    for p in AVAILABLE_PROVIDERS:
        if p.id == provider_id:
            return p
    return None


# =============================================================================
# Provider Factory
# =============================================================================


def get_provider(db: "Database") -> LLMProvider:
    """Get the currently configured LLM provider.

    Reads the provider type from database state and creates the
    appropriate provider instance with stored configuration.

    Args:
        db: Database instance for reading configuration.

    Returns:
        Configured LLMProvider instance.

    Raises:
        LLMError: If provider type is unknown or configuration is invalid.
    """
    provider_type = db.get_state(key="provider") or "ollama"

    if provider_type == "ollama":
        return _create_ollama_provider(db)
    elif provider_type == "anthropic":
        return _create_anthropic_provider(db)
    else:
        raise LLMError(f"Unknown provider type: {provider_type}")


def get_provider_or_none(db: "Database") -> LLMProvider | None:
    """Get the provider, returning None on configuration errors.

    Useful for cases where a provider isn't strictly required.

    Args:
        db: Database instance.

    Returns:
        LLMProvider if available, None otherwise.
    """
    try:
        return get_provider(db)
    except LLMError as e:
        logger.debug("Provider not available: %s", e)
        return None


def get_current_provider_type(db: "Database") -> str:
    """Get the currently configured provider type.

    Args:
        db: Database instance.

    Returns:
        Provider type string (e.g., "ollama", "anthropic").
    """
    return db.get_state(key="provider") or "ollama"


def set_provider_type(db: "Database", provider_type: str) -> None:
    """Set the active provider type.

    Args:
        db: Database instance.
        provider_type: Provider identifier.

    Raises:
        LLMError: If provider type is unknown.
    """
    if not get_provider_info(provider_type):
        raise LLMError(f"Unknown provider type: {provider_type}")

    db.set_state(key="provider", value=provider_type)
    logger.info("Set active provider to: %s", provider_type)


def check_provider_health(db: "Database") -> ProviderHealth:
    """Check health of the currently configured provider.

    Args:
        db: Database instance.

    Returns:
        ProviderHealth status.
    """
    try:
        provider = get_provider(db)
        return provider.check_health()
    except LLMError as e:
        return ProviderHealth(
            reachable=False,
            error=str(e),
        )


# =============================================================================
# Provider Creation
# =============================================================================


def _create_ollama_provider(db: "Database") -> LLMProvider:
    """Create an Ollama provider from database config."""
    from .ollama import OllamaProvider

    url = db.get_state(key="ollama_url")
    model = db.get_state(key="ollama_model")

    return OllamaProvider(
        url=url if url else None,
        model=model if model else None,
    )


def _create_anthropic_provider(db: "Database") -> LLMProvider:
    """Create an Anthropic provider from database config."""
    from .anthropic import AnthropicProvider
    from .secrets import get_api_key

    api_key = get_api_key("anthropic")
    model = db.get_state(key="anthropic_model")

    if not api_key:
        raise LLMError(
            "No Anthropic API key configured. "
            "Add your key in Settings > LLM Provider."
        )

    return AnthropicProvider(
        api_key=api_key,
        model=model if model else None,
    )
