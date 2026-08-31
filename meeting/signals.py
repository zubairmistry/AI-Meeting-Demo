from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

from .models import AISettings


@receiver(post_save, sender=User)
def create_ai_settings(sender, instance, created, **kwargs):

    if created:
        AISettings.objects.create(
            user=instance,
            provider="gemini",
            api_key="",
            model_name="gemini-2.5-flash"
        )