from meeting.services.settings_service import SettingsService
from meeting.providers.registry import ProviderRegistry, ProviderNotFoundError


class ProviderFactory:

    @staticmethod
    def get_provider(user):
        """
        Retrieves decrypted AI settings for user and returns an initialized provider instance.
        Returns None if settings or API key is missing, or provider is not registered.
        """
        settings = SettingsService.get_settings(user)

        if not settings or not settings.get("api_key"):
            return None

        provider_name = settings.get("provider", "")

        try:
            provider_cls = ProviderRegistry.get(provider_name)
            return provider_cls(settings)
        except ProviderNotFoundError:
            return None