"""
End-to-End Regression Tests for Meeting Pre-Flight Health Checks & Processing Workflow.
"""

import subprocess
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from meeting.models import Meeting
from meeting.services.settings_service import SettingsService
from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.providers.registry import ProviderRegistry


class MockProviderForPreflightE2E(BaseAIProvider):
    """Controllable mock provider for End-to-End preflight testing."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.provider = self.settings.get("provider", "mock_preflight")
        self.api_key = self.settings.get("api_key", "")
        self.model_name = self.settings.get("model_name", "mock-model-standard")

    def test_connection(self):
        if not self.api_key or self.api_key == "invalid_key":
            return ValidationResult(is_valid=False, status=ModelStatus.ACCESS_DENIED, message="Invalid API key.")
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Connected")

    def discover_models(self):
        return [
            ModelDescriptor(
                id="mock-model-standard",
                display_name="Mock Model Standard",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=True,
            )
        ]

    def filter_compatible_models(self, models):
        return models

    def validate_model_access(self, model_id):
        if not self.api_key or self.api_key == "invalid_key":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid or expired API key. Please check your credentials in AI Settings.",
                model_id=model_id,
            )
        if model_id == "deprecated-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Model 'deprecated-model' is no longer available. Please select another model in AI Settings.",
                model_id=model_id,
            )
        if model_id == "quota-exhausted-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.QUOTA_EXCEEDED,
                message="API quota exceeded for your project. Please check your billing/quota.",
                model_id=model_id,
            )
        if model_id == "rate-limited-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="Rate limit reached. Please wait a few moments before trying again.",
                model_id=model_id,
            )
        if model_id == "high-demand-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                message="Model is experiencing high demand. Please try again shortly.",
                model_id=model_id,
            )
        return ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message="Model verified and accessible.",
            model_id=model_id,
        )

    def quick_preflight_check(self):
        return self.validate_model_access(self.model_name)

    def generate_transcript(self, audio_source):
        return "Speaker 1: Welcome to the quarterly project review.\nSpeaker 2: Progress is on track."

    def generate_report(self, transcript):
        return "## Executive Summary\n- Project progress is on track.\n\n## Action Items\n- Continue implementation."

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=str(exc),
            model_id=self.model_name,
        )


class MeetingPreflightE2ETests(TestCase):
    """Regression tests verifying meeting pre-flight health checks and end-to-end processing."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="meetinguser",
            email="meetinguser@example.com",
            password="MeetingPassword123!"
        )
        self.home_url = reverse("meeting")

        self._saved_registry = dict(ProviderRegistry._registry)
        ProviderRegistry.register("mock_preflight", MockProviderForPreflightE2E, override=True)

    def tearDown(self):
        ProviderRegistry._registry = dict(self._saved_registry)

    # -------------------------------------------------------------
    # Pre-Flight Failure Tests (Zero Resource Waste)
    # -------------------------------------------------------------

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_upload_without_configured_settings_fails_before_disk_write(self, mock_fs_save, mock_extract):
        """Upload without configured API key halts immediately with no disk write or FFmpeg execution."""
        self.client.force_login(self.user)
        test_file = SimpleUploadedFile("meeting_test.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Please configure your", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_invalid_credentials_stops_before_file_save_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Invalid credentials trigger ACCESS_DENIED pre-flight failure before disk write or FFmpeg."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="invalid_key",
            model_name="mock-model-standard",
        )

        test_file = SimpleUploadedFile("meeting_test.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Authentication Failed", response.context["status"])
        self.assertIn("Invalid or expired API key", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_unavailable_model_stops_before_file_save_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Deprecated or unavailable model triggers UNAVAILABLE pre-flight failure before disk write or FFmpeg."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="deprecated-model",
        )

        test_file = SimpleUploadedFile("meeting_test.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Model Unavailable", response.context["status"])
        self.assertIn("deprecated-model", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_quota_exceeded_stops_before_file_save_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Quota depletion triggers QUOTA_EXCEEDED pre-flight failure before disk write or FFmpeg."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="quota-exhausted-model",
        )

        test_file = SimpleUploadedFile("meeting_test.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Quota Exceeded", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_rate_limited_stops_before_file_save_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Rate limit triggers RATE_LIMITED pre-flight failure before disk write or FFmpeg."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="rate-limited-model",
        )

        test_file = SimpleUploadedFile("meeting_test.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("⏳ AI Rate Limited", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_temporary_outage_stops_before_file_save_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Temporary provider high-demand triggers TEMPORARILY_UNAVAILABLE pre-flight failure."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="high-demand-model",
        )

        test_file = SimpleUploadedFile("meeting_test.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("⚠️ AI Service Busy", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    # -------------------------------------------------------------
    # Pre-Flight Success & Full Processing E2E Tests
    # -------------------------------------------------------------

    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_report")
    @patch("meeting.services.transcript_service.TranscriptService.save_transcript")
    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_transcript")
    @patch("meeting.services.audio_service.AudioService.get_audio_info")
    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    @patch("django.core.files.storage.FileSystemStorage.path")
    def test_preflight_success_proceeds_with_full_workflow_and_creates_meeting(
        self, mock_fs_path, mock_fs_save, mock_extract, mock_info, mock_transcript, mock_save_tr, mock_report
    ):
        """When preflight succeeds, the entire meeting processing workflow completes and persists a Meeting record."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="mock-model-standard",
        )

        mock_fs_save.return_value = "saved_sample_meeting.mp4"
        mock_fs_path.return_value = "/fake/saved_sample_meeting.mp4"
        mock_extract.return_value = "/fake/extracted_meeting.wav"
        mock_info.return_value = {"duration_seconds": 125.5}
        mock_transcript.return_value = "Speaker 1: Welcome to the quarterly project review.\nSpeaker 2: Progress is on track."
        mock_save_tr.return_value = "/fake/saved_sample_meeting.txt"
        mock_report.return_value = "## Executive Summary\n- Project progress is on track.\n\n## Action Items\n- Continue implementation."

        test_file = SimpleUploadedFile("sample_meeting.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("File Saved Successfully : saved_sample_meeting.mp4", response.context["status"])
        self.assertIn("Speaker 1: Welcome", response.context["transcript"])
        self.assertIn("Executive Summary", response.context["report"])

        mock_fs_save.assert_called_once()
        mock_extract.assert_called_once_with("/fake/saved_sample_meeting.mp4")
        mock_transcript.assert_called_once_with(self.user, "/fake/extracted_meeting.wav")
        mock_save_tr.assert_called_once_with(
            "Speaker 1: Welcome to the quarterly project review.\nSpeaker 2: Progress is on track.",
            media_path="/fake/saved_sample_meeting.mp4"
        )
        mock_report.assert_called_once_with(
            self.user,
            "Speaker 1: Welcome to the quarterly project review.\nSpeaker 2: Progress is on track."
        )

        # Verify database record
        meeting = Meeting.objects.get(user=self.user, meeting_name="saved_sample_meeting.mp4")
        self.assertEqual(meeting.status, "completed")
        self.assertEqual(meeting.provider, "mock_preflight")
        self.assertEqual(meeting.model_name, "mock-model-standard")
        self.assertEqual(meeting.duration, 125.5)
        self.assertEqual(meeting.original_file, "saved_sample_meeting.mp4")
        self.assertEqual(meeting.audio_file, "extracted_meeting.wav")
        self.assertEqual(meeting.transcript_file, "saved_sample_meeting.txt")

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    @patch("django.core.files.storage.FileSystemStorage.path")
    def test_audio_extraction_failure_is_handled_gracefully(self, mock_fs_path, mock_fs_save, mock_extract):
        """Audio extraction FFmpeg failure returns graceful user error without crashing."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="mock-model-standard",
        )

        mock_fs_save.return_value = "bad_media.mp4"
        mock_fs_path.return_value = "/fake/bad_media.mp4"
        mock_extract.side_effect = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")

        test_file = SimpleUploadedFile("bad_media.mp4", b"corrupted content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ Failed to extract audio", response.context["status"])
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_transcript")
    @patch("meeting.services.audio_service.AudioService.get_audio_info")
    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    @patch("django.core.files.storage.FileSystemStorage.path")
    def test_transcript_generation_failure_is_handled_gracefully(
        self, mock_fs_path, mock_fs_save, mock_extract, mock_info, mock_transcript
    ):
        """Empty transcript returns a helpful error and does not create completed Meeting record."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="mock-model-standard",
        )

        mock_fs_save.return_value = "audio_only.wav"
        mock_fs_path.return_value = "/fake/audio_only.wav"
        mock_extract.return_value = "/fake/audio_only.wav"
        mock_info.return_value = {"duration_seconds": 45.0}
        mock_transcript.return_value = ""

        test_file = SimpleUploadedFile("audio_only.wav", b"wav dummy content", content_type="audio/wav")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Failed to generate transcript", response.context["status"])
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    @patch("django.core.files.storage.FileSystemStorage.path")
    def test_processing_timeout_is_handled_gracefully(self, mock_fs_path, mock_fs_save, mock_extract):
        """TimeoutError during processing returns user-friendly timeout guidance."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_preflight",
            api_key="valid_secret_key",
            model_name="mock-model-standard",
        )

        mock_fs_save.return_value = "long_meeting.mp4"
        mock_fs_path.return_value = "/fake/long_meeting.mp4"
        mock_extract.side_effect = TimeoutError("Processing timed out")

        test_file = SimpleUploadedFile("long_meeting.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Meeting processing timed out", response.context["status"])
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

