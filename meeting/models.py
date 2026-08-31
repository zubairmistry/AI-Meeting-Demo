from django.db import models
from django.contrib.auth.models import User


class AISettings(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="ai_settings"
    )

    PROVIDER_CHOICES = [
        ("gemini", "Google Gemini"),
        ("claude", "Anthropic Claude"),
        ("openai", "OpenAI"),
    ]

    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_CHOICES,
        default="gemini"
    )

    api_key = models.TextField()

    model_name = models.CharField(
        max_length=100
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.provider}"

class Meeting(models.Model):

    STATUS_CHOICES = [
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="meetings"
    )

    meeting_name = models.CharField(
        max_length=255
    )

    original_file = models.FileField(
        upload_to="meetings/original/"
    )

    audio_file = models.FileField(
        upload_to="meetings/audio/"
    )

    transcript_file = models.FileField(
        upload_to="meetings/transcripts/"
    )

    provider = models.CharField(
        max_length=20
    )

    model_name = models.CharField(
        max_length=100
    )

    meeting_type = models.CharField(
        max_length=100,
        blank=True
    )

    transcript = models.TextField()

    ai_report = models.TextField()

    duration = models.FloatField()

    file_size = models.BigIntegerField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="processing"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.meeting_name

    @property
    def formatted_duration(self):
        return format_duration(self.duration)


def format_duration(seconds):
    """
    Formats a duration in seconds into a human-readable string:
    - 0-59 sec: SS sec (e.g. '45 sec', '08 sec', '00 sec')
    - 60s to <1hr: MM min SS sec (e.g. '01 min 08 sec', '01 min 00 sec')
    - >= 1hr: HH hr MM min SS sec (e.g. '01 hr 01 min 08 sec')
    """
    if seconds is None:
        return "00 sec"

    try:
        total_sec = int(seconds)
    except (ValueError, TypeError):
        return "00 sec"

    if total_sec < 0:
        total_sec = 0

    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60

    if hours > 0:
        return f"{hours:02d} hr {minutes:02d} min {secs:02d} sec"
    elif minutes > 0:
        return f"{minutes:02d} min {secs:02d} sec"
    else:
        return f"{secs:02d} sec"
