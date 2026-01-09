"""Provider handlers.

Manages LLM provider settings and Anthropic API configuration.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from reos.db import Database
from reos.rpc.router import register
from reos.rpc.types import INVALID_PARAMS, RpcError


@register("providers/list", needs_db=True)
def handle_providers_list(db: Database) -> dict[str, Any]:
    """List available LLM providers and current selection."""
    from reos.providers import (
        list_providers,
        get_current_provider_type,
        check_keyring_available,
        has_api_key,
    )

    current = get_current_provider_type(db)
    providers = list_providers()

    return {
        "current_provider": current,
        "available_providers": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "is_local": p.is_local,
                "requires_api_key": p.requires_api_key,
                "has_api_key": has_api_key(p.id) if p.requires_api_key else None,
            }
            for p in providers
        ],
        "keyring_available": check_keyring_available(),
    }


@register("providers/set", needs_db=True)
def handle_providers_set(db: Database, *, provider: str) -> dict[str, Any]:
    """Set active LLM provider."""
    from reos.providers import set_provider_type, get_provider_info, LLMError

    info = get_provider_info(provider)
    if not info:
        raise RpcError(code=INVALID_PARAMS, message=f"Unknown provider: {provider}")

    try:
        set_provider_type(db, provider)
    except LLMError as e:
        raise RpcError(code=-32010, message=str(e)) from e

    return {"ok": True, "provider": provider}


@register("providers/status", needs_db=True)
def handle_providers_status(db: Database) -> dict[str, Any]:
    """Get current provider status and health."""
    from reos.providers import (
        get_current_provider_type,
        check_provider_health,
        get_provider_or_none,
    )

    provider_type = get_current_provider_type(db)
    health = check_provider_health(db)
    provider = get_provider_or_none(db)

    result = {
        "provider": provider_type,
        "health": asdict(health),
    }

    # Add models if provider is available
    if provider:
        try:
            models = provider.list_models()
            result["models"] = [
                {
                    "name": m.name,
                    "size_gb": m.size_gb,
                    "context_length": m.context_length,
                    "capabilities": m.capabilities,
                    "description": m.description,
                }
                for m in models
            ]
        except Exception:
            result["models"] = []

    return result


@register("anthropic/set_key", needs_db=True)
def handle_anthropic_set_key(db: Database, *, api_key: str) -> dict[str, Any]:
    """Store Anthropic API key in system keyring."""
    from reos.providers import store_api_key, AnthropicProvider, check_keyring_available

    if not api_key or len(api_key) < 10:
        raise RpcError(code=INVALID_PARAMS, message="Invalid API key format")

    if not check_keyring_available():
        raise RpcError(
            code=-32010,
            message="System keyring not available. Cannot securely store API key.",
        )

    # Test the key before storing
    try:
        provider = AnthropicProvider(api_key=api_key)
        health = provider.check_health()
        if not health.reachable:
            raise RpcError(
                code=-32010,
                message=f"Invalid API key: {health.error or 'Connection failed'}",
            )
    except RpcError:
        raise
    except Exception as e:
        raise RpcError(code=-32010, message=f"API key validation failed: {e}") from e

    # Store the key
    store_api_key("anthropic", api_key)

    return {"ok": True}


@register("anthropic/delete_key", needs_db=True)
def handle_anthropic_delete_key(_db: Database) -> dict[str, Any]:
    """Delete Anthropic API key from keyring."""
    from reos.providers import delete_api_key

    deleted = delete_api_key("anthropic")
    return {"ok": deleted}


@register("anthropic/set_model", needs_db=True)
def handle_anthropic_set_model(db: Database, *, model: str) -> dict[str, Any]:
    """Set Anthropic model preference."""
    from reos.providers import CLAUDE_MODELS

    valid_models = [m.name for m in CLAUDE_MODELS]
    if model not in valid_models:
        raise RpcError(
            code=INVALID_PARAMS,
            message=f"Invalid model. Valid options: {', '.join(valid_models)}",
        )

    db.set_state(key="anthropic_model", value=model)
    return {"ok": True, "model": model}


@register("anthropic/status", needs_db=True)
def handle_anthropic_status(db: Database) -> dict[str, Any]:
    """Get Anthropic provider status."""
    from reos.providers import (
        AnthropicProvider,
        get_api_key,
        has_api_key,
        check_keyring_available,
        CLAUDE_MODELS,
    )

    has_key = has_api_key("anthropic")
    stored_model = db.get_state(key="anthropic_model")
    model = stored_model if stored_model else "claude-sonnet-4-20250514"

    result = {
        "has_api_key": has_key,
        "keyring_available": check_keyring_available(),
        "model": model,
        "available_models": [
            {
                "name": m.name,
                "context_length": m.context_length,
                "capabilities": m.capabilities,
                "description": m.description,
            }
            for m in CLAUDE_MODELS
        ],
    }

    # Test connection if key is available
    if has_key:
        try:
            api_key = get_api_key("anthropic")
            if api_key:
                provider = AnthropicProvider(api_key=api_key, model=model)
                health = provider.check_health()
                result["health"] = asdict(health)
            else:
                result["health"] = {"reachable": False, "error": "No API key found"}
        except Exception as e:
            result["health"] = {"reachable": False, "error": str(e)}
    else:
        result["health"] = {"reachable": False, "error": "No API key configured"}

    return result
