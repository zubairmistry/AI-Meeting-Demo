"""
meeting/providers/registry.py

Centralized provider registry for the AI Meeting Assistant.
Maintains a mapping of provider identifiers (e.g. 'gemini') to their
respective provider implementation classes without premature SDK instantiation.
"""

import logging
from typing import Dict, Type, List, Optional

logger = logging.getLogger(__name__)


class ProviderNotFoundError(KeyError):
    """Raised when a requested provider is not registered in the ProviderRegistry."""
    pass


class ProviderRegistry:
    """
    Centralized registry for AI provider classes.
    Stores provider classes (types) rather than initialized instances,
    ensuring zero SDK overhead when discovering or listing registered providers.
    """

    _registry: Dict[str, Type] = {}

    @classmethod
    def register(cls, provider_name: str, provider_cls: Type, override: bool = False) -> None:
        """
        Registers a provider class under a normalized provider identifier.
        """
        if not provider_name or not isinstance(provider_name, str):
            raise ValueError("Provider name must be a non-empty string.")

        normalized_name = provider_name.strip().lower()

        if normalized_name in cls._registry and not override:
            logger.warning(
                "Provider '%s' is already registered with %s. Use override=True to replace.",
                normalized_name,
                cls._registry[normalized_name].__name__,
            )
            return

        cls._registry[normalized_name] = provider_cls
        logger.debug("Registered AI provider '%s' -> %s", normalized_name, provider_cls.__name__)

    @classmethod
    def get(cls, provider_name: str) -> Type:
        """
        Retrieves the provider class registered under provider_name.
        Raises ProviderNotFoundError if not registered.
        """
        if not provider_name or not isinstance(provider_name, str):
            raise ProviderNotFoundError(f"Invalid provider name: {provider_name!r}")

        normalized_name = provider_name.strip().lower()

        if normalized_name not in cls._registry:
            available = cls.list_providers()
            raise ProviderNotFoundError(
                f"AI Provider '{normalized_name}' is not registered. Available providers: {available}"
            )

        return cls._registry[normalized_name]

    @classmethod
    def is_registered(cls, provider_name: str) -> bool:
        """Checks whether a provider identifier is currently registered."""
        if not provider_name or not isinstance(provider_name, str):
            return False
        return provider_name.strip().lower() in cls._registry

    @classmethod
    def list_providers(cls) -> List[str]:
        """Returns a sorted list of all registered provider identifiers."""
        return sorted(list(cls._registry.keys()))

    @classmethod
    def unregister(cls, provider_name: str) -> Optional[Type]:
        """Unregisters a provider by identifier if present."""
        if not provider_name or not isinstance(provider_name, str):
            return None
        return cls._registry.pop(provider_name.strip().lower(), None)

    @classmethod
    def clear(cls) -> None:
        """Clears all registered providers (primarily for test isolation)."""
        cls._registry.clear()
