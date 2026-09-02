"""
meeting/services/model_discovery_service.py

Generic, provider-agnostic model discovery, capability filtering,
and candidate ranking service for the AI Meeting Assistant.
Does NOT import any provider-specific SDKs.
"""

import logging
from typing import List, Set, Optional

from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    ModelDescriptor,
)

logger = logging.getLogger(__name__)

# Minimum capabilities strictly required for meeting intelligence
REQUIRED_MEETING_CAPABILITIES: Set[ProviderCapability] = {
    ProviderCapability.AUDIO_TRANSCRIPTION,
    ProviderCapability.TEXT_GENERATION,
}


class ModelDiscoveryService:
    """
    Provider-agnostic service for discovering, capability-filtering,
    and ranking AI models suitable for meeting processing.
    """

    @staticmethod
    def get_required_capabilities() -> Set[ProviderCapability]:
        """Returns the canonical set of capabilities required by the application."""
        return set(REQUIRED_MEETING_CAPABILITIES)

    @classmethod
    def filter_compatible_models(
        cls,
        models: List[ModelDescriptor],
        required_capabilities: Optional[Set[ProviderCapability]] = None,
    ) -> List[ModelDescriptor]:
        """
        Filters a list of ModelDescriptor instances, retaining only those that satisfy
        all required capabilities. Optional capabilities (e.g. NATIVE_AUDIO_INPUT, STREAMING)
        do not cause rejection.

        Preserves all ModelDescriptor metadata, DiscoverySource, and ModelStatus.
        """
        if required_capabilities is None:
            required_capabilities = cls.get_required_capabilities()

        compatible: List[ModelDescriptor] = []
        for model in models:
            if not isinstance(model, ModelDescriptor):
                continue

            # Model must satisfy all required capabilities
            if required_capabilities.issubset(model.capabilities):
                compatible.append(model)
            else:
                logger.debug(
                    "Model '%s' rejected: has %s, missing %s",
                    model.id,
                    [c.value for c in model.capabilities],
                    [c.value for c in (required_capabilities - model.capabilities)],
                )

        return compatible

    @classmethod
    def rank_compatible_models(
        cls,
        models: List[ModelDescriptor],
    ) -> List[ModelDescriptor]:
        """
        Ranks compatible models deterministically based on:
        1. Recommended status (priority bonus)
        2. Weighted composite score: (quality_score * 0.6) + (speed_score * 0.4)
        3. Lexicographical model ID for deterministic tie-breaking.

        Returns a new sorted list (highest ranked first).
        """
        def sort_key(m: ModelDescriptor):
            rec_bonus = 10000 if m.is_recommended else 0
            score = (m.quality_score * 0.6) + (m.speed_score * 0.4)
            return (rec_bonus + score, m.id)

        return sorted(models, key=sort_key, reverse=True)

    @classmethod
    def get_recommended_model(
        cls,
        models: List[ModelDescriptor],
    ) -> Optional[ModelDescriptor]:
        """
        Returns the highest-ranked compatible model, or None if the list is empty.
        """
        ranked = cls.rank_compatible_models(models)
        return ranked[0] if ranked else None

    @classmethod
    def discover_and_filter(
        cls,
        provider: BaseAIProvider,
        required_capabilities: Optional[Set[ProviderCapability]] = None,
    ) -> List[ModelDescriptor]:
        """
        Orchestrates model discovery from a provider instance and applies
        application capability filtering and candidate ranking.
        """
        if not isinstance(provider, BaseAIProvider):
            raise TypeError(f"Expected BaseAIProvider instance, got {type(provider).__name__}")

        raw_models = provider.discover_models()
        compatible = cls.filter_compatible_models(
            raw_models, required_capabilities=required_capabilities
        )
        return cls.rank_compatible_models(compatible)
