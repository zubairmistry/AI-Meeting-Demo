from meeting.models import AISettings
from meeting.security.encryption import encrypt, decrypt
from cryptography.fernet import InvalidToken


class SettingsService:

    @staticmethod
    def save_settings(user, provider, api_key, model_name):

        existing = AISettings.objects.filter(user=user).first()

        if api_key and api_key.strip():
            encrypted_key = encrypt(api_key.strip())
        elif existing and existing.api_key:
            encrypted_key = existing.api_key
        else:
            encrypted_key = ""

        AISettings.objects.update_or_create(
            user=user,
            defaults={
                "provider": provider,
                "api_key": encrypted_key,
                "model_name": model_name,
            }
        )

    @staticmethod
    def get_settings(user):

        try:
            settings_obj = AISettings.objects.get(user=user)
        except AISettings.DoesNotExist:
            return None

        api_key = ""
        if settings_obj.api_key:
            try:
                api_key = decrypt(settings_obj.api_key)
            except (InvalidToken, Exception):
                api_key = ""

        return {
            "provider": settings_obj.provider,
            "api_key": api_key,
            "model_name": settings_obj.model_name,
        }