"""
meeting/providers package

Exposes the base provider contracts, registry, and factory.
Registers available provider implementations.
"""

from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.providers.registry import (
    ProviderRegistry,
    ProviderNotFoundError,
)
from meeting.providers.factory import ProviderFactory
from meeting.providers.gemini_provider import GeminiProvider
from meeting.providers.claude_provider import ClaudeProvider
from meeting.providers.openai_provider import OpenAIProvider

# Register existing provider implementations
ProviderRegistry.register("gemini", GeminiProvider)
ProviderRegistry.register("claude", ClaudeProvider)
ProviderRegistry.register("openai", OpenAIProvider)

__all__ = [
    "BaseAIProvider",
    "ProviderCapability",
    "DiscoverySource",
    "ModelStatus",
    "ModelDescriptor",
    "ValidationResult",
    "ProviderRegistry",
    "ProviderNotFoundError",
    "ProviderFactory",
    "GeminiProvider",
    "ClaudeProvider",
    "OpenAIProvider",
]
