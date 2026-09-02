"""
meeting/providers/factory.py

Factory for instantiating AI provider instances via the ProviderRegistry.
Encapsulates provider instantiation and configuration passing.
"""

from typing import Dict, Any, Optional
from meeting.providers.registry import ProviderRegistry, ProviderNotFoundError


class ProviderFactory:
    """
    Factory for creating AI provider instances through the ProviderRegistry.
    Ensures application code never directly depends on concrete SDK classes.
    """

    @classmethod
    def create_provider(
        cls,
        provider_name: str,
        settings: Dict[str, Any],
    ) -> Any:
        """
        Instantiates a provider by name with the given settings dictionary.
        Raises ProviderNotFoundError if the provider is not registered.
        """
        provider_cls = ProviderRegistry.get(provider_name)
        return provider_cls(settings)

    @classmethod
    def create_provider_safe(
        cls,
        provider_name: str,
        settings: Dict[str, Any],
    ) -> Optional[Any]:
        """
        Safely attempts to instantiate a provider.
        Returns None if provider is not registered or settings are invalid.
        """
        try:
            return cls.create_provider(provider_name, settings)
        except (ProviderNotFoundError, ValueError, TypeError):
            return None
