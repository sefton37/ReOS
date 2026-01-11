"""Model selection based on task complexity.

This module selects the appropriate model tier for a task.
Small models for boilerplate, large models for complex tasks.

Goal: Use compute efficiently. Don't use a 70B model to add an import.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.code_mode.optimization.complexity import TaskComplexity

logger = logging.getLogger(__name__)


class ModelTier(Enum):
    """Model capability tiers.

    SMALL: Fast, cheap, good for boilerplate (3-7B)
    MEDIUM: Balanced, general purpose (8-30B)
    LARGE: Most capable, for complex tasks (70B+)
    """

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass
class ModelSelection:
    """Model selection result.

    Attributes:
        tier: Selected model tier
        model_name: Specific model name to use
        reason: Why this model was selected
        confidence: Confidence in the selection
    """

    tier: ModelTier
    model_name: str
    reason: str
    confidence: float = 0.8


# Default model mappings by tier
# These should be configured based on available models
DEFAULT_MODELS = {
    ModelTier.SMALL: [
        "llama3.2:3b",
        "qwen2.5:3b",
        "phi3:mini",
    ],
    ModelTier.MEDIUM: [
        "llama3.2:8b",
        "qwen2.5:7b",
        "mistral:7b",
        "codellama:7b",
    ],
    ModelTier.LARGE: [
        "llama3.2:70b",
        "qwen2.5:72b",
        "codellama:34b",
        "deepseek-coder:33b",
    ],
}


def select_model(
    complexity: "TaskComplexity",
    available_models: list[str] | None = None,
    default_model: str | None = None,
) -> ModelSelection:
    """Select appropriate model for task.

    Args:
        complexity: Task complexity analysis
        available_models: List of available model names (from Ollama)
        default_model: Default model if selection fails

    Returns:
        ModelSelection with chosen model and reason
    """
    # Determine tier based on complexity
    if complexity.score < 0.3:
        tier = ModelTier.SMALL
        reason = "Simple task, small model sufficient"
    elif complexity.score > 0.7:
        tier = ModelTier.LARGE
        reason = "Complex task, needs capable model"
    elif complexity.has_external_deps:
        tier = ModelTier.MEDIUM
        reason = "External dependencies, need moderate capability"
    elif complexity.scope_ambiguous:
        tier = ModelTier.MEDIUM
        reason = "Ambiguous scope, need balanced model"
    else:
        tier = ModelTier.MEDIUM
        reason = "Moderate complexity"

    # Find available model for tier
    model_name = _find_model_for_tier(tier, available_models)

    if model_name is None:
        # Fall back to default
        if default_model:
            model_name = default_model
            reason = f"{reason} (using default: {default_model})"
        else:
            # No default, use first available
            if available_models:
                model_name = available_models[0]
                reason = f"{reason} (tier unavailable, using {model_name})"
            else:
                model_name = "llama3.2"
                reason = f"{reason} (no models available, defaulting)"

    logger.debug(
        "Selected model %s (tier: %s) for complexity %.2f: %s",
        model_name,
        tier.value,
        complexity.score,
        reason,
    )

    return ModelSelection(
        tier=tier,
        model_name=model_name,
        reason=reason,
    )


def _find_model_for_tier(
    tier: ModelTier,
    available_models: list[str] | None,
) -> str | None:
    """Find an available model for the given tier.

    Args:
        tier: Desired model tier
        available_models: List of available model names

    Returns:
        Model name or None if no suitable model found
    """
    if not available_models:
        return None

    # Get preferred models for tier
    preferred = DEFAULT_MODELS.get(tier, [])

    # Check if any preferred model is available
    for model in preferred:
        # Check exact match
        if model in available_models:
            return model

        # Check partial match (e.g., "llama3.2:8b" matches "llama3.2")
        base_name = model.split(":")[0]
        for avail in available_models:
            if avail.startswith(base_name):
                return avail

    # No preferred model found for tier
    # Try adjacent tiers
    if tier == ModelTier.SMALL:
        # Try medium
        return _find_model_for_tier(ModelTier.MEDIUM, available_models)
    elif tier == ModelTier.LARGE:
        # Try medium
        return _find_model_for_tier(ModelTier.MEDIUM, available_models)

    return None


def get_tier_for_model(model_name: str) -> ModelTier:
    """Determine the tier of a model by name.

    Args:
        model_name: Model name (e.g., "llama3.2:8b")

    Returns:
        Estimated model tier
    """
    model_lower = model_name.lower()

    # Check for size indicators
    if any(s in model_lower for s in [":3b", ":1b", ":2b", "mini", "tiny"]):
        return ModelTier.SMALL
    if any(s in model_lower for s in [":70b", ":72b", ":33b", ":34b", ":40b"]):
        return ModelTier.LARGE

    # Check by model family
    if any(s in model_lower for s in ["phi", "gemma:2b"]):
        return ModelTier.SMALL

    # Default to medium
    return ModelTier.MEDIUM


def recommend_models_for_system(
    ram_gb: int,
    has_gpu: bool = False,
    vram_gb: int = 0,
) -> dict[ModelTier, str]:
    """Recommend models based on system capabilities.

    Args:
        ram_gb: System RAM in GB
        has_gpu: Whether system has GPU
        vram_gb: GPU VRAM in GB

    Returns:
        Dict mapping tiers to recommended model names
    """
    recommendations = {}

    # Small tier
    recommendations[ModelTier.SMALL] = "llama3.2:3b"

    # Medium tier - depends on RAM
    if ram_gb >= 16 or (has_gpu and vram_gb >= 8):
        recommendations[ModelTier.MEDIUM] = "llama3.2:8b"
    else:
        recommendations[ModelTier.MEDIUM] = "llama3.2:3b"

    # Large tier - only if resources allow
    if has_gpu and vram_gb >= 24:
        recommendations[ModelTier.LARGE] = "llama3.2:70b"
    elif ram_gb >= 64:
        recommendations[ModelTier.LARGE] = "llama3.2:70b"
    else:
        # No large model recommendation
        recommendations[ModelTier.LARGE] = recommendations[ModelTier.MEDIUM]

    return recommendations
