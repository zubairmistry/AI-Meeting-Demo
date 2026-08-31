from django.apps import AppConfig


class MeetingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "meeting"

    def ready(self):
        import meeting.signals