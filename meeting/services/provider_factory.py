from meeting.services.settings_service import SettingsService
from meeting.providers.gemini_provider import GeminiProvider


class ProviderFactory:

    @staticmethod
    def get_provider(user):

        settings = SettingsService.get_settings(user)

        if not settings or not settings.get("api_key"):
            return None

        provider = settings["provider"]

        if provider == "gemini":
            return GeminiProvider(settings)

        return None