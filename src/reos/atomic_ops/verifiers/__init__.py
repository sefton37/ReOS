"""Verification pipeline for atomic operations.

Implements the 5-layer verification system:
1. Syntax - Parse and validate command structure
2. Semantic - Verify the command makes sense in context
3. Behavioral - Predict what the command will do
4. Safety - Check for dangerous operations
5. Intent - Verify the command matches user intent

Each layer can pass, fail, or pass with warnings. All layers except
Intent can run without LLM calls (for speed). Intent verification
uses the LLM to verify alignment with user goals.
"""

from .base import BaseVerifier, VerificationContext
from .syntax import SyntaxVerifier
from .semantic import SemanticVerifier
from .behavioral import BehavioralVerifier
from .safety import SafetyVerifier
from .intent import IntentVerifier
from .pipeline import VerificationPipeline

__all__ = [
    "BaseVerifier",
    "VerificationContext",
    "SyntaxVerifier",
    "SemanticVerifier",
    "BehavioralVerifier",
    "SafetyVerifier",
    "IntentVerifier",
    "VerificationPipeline",
]
