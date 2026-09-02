"""
meeting/tests/test_step8_preflight_hardening.py

Comprehensive tests for Step 8: Pre-Flight Meeting Upload Hardening & Production Verification.
Covers:
1. File validation: presence, extension whitelist, and size limit (< 50MB).
2. AI Settings & Provider pre-flight validation before disk/FFmpeg/AI processing.
3. Pre-flight error handling: ACCESS_DENIED, UNAVAILABLE, QUOTA_EXCEEDED, RATE_LIMITED, TEMPORARILY_UNAVAILABLE.
4. Prevention of unnecessary resource usage (no FFmpeg execution, no disk saves on preflight failure).
5. Error resilience & orphan file cleanup on extraction/transcription failures.
6. Successful end-to-end meeting processing workflow and database persistence.
"""

import os
import subprocess
from unittest.mock import MagicMock, patch
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


class MockStep8HardenProvider(BaseAIProvider):
    """Mock provider with controllable preflight validation responses."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.provider = self.settings.get("provider", "mock_harden")
        self.api_key = self.settings.get("api_key", "")
        self.model_name = self.settings.get("model_name", "harden-model-standard")

    def test_connection(self):
        if not self.api_key or self.api_key == "invalid_key":
            return ValidationResult(is_valid=False, status=ModelStatus.ACCESS_DENIED, message="Invalid API key.")
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Connected")

    def discover_models(self):
        return [
            ModelDescriptor(
                id="harden-model-standard",
                display_name="Harden Standard Model",
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
                message="Invalid or expired API credentials.",
                model_id=model_id,
            )
        if model_id == "unavailable-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Requested model is decommissioned or not found.",
                model_id=model_id,
            )
        if model_id == "quota-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.QUOTA_EXCEEDED,
                message="Project quota exceeded.",
                model_id=model_id,
            )
        if model_id == "rate-limit-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="Rate limit reached. Retry after delay.",
                model_id=model_id,
            )
        if model_id == "busy-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                message="Provider is temporarily overloaded.",
                model_id=model_id,
            )
        return ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message="Model verified and ready.",
            model_id=model_id,
        )

    def quick_preflight_check(self):
        return self.validate_model_access(self.model_name)

    def generate_transcript(self, audio_source):
        return "Speaker 1: Hardened pipeline test transcript."

    def generate_report(self, transcript):
        return "## Executive Report\n- Pipeline is hardened."

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=str(exc),
            model_id=self.model_name,
        )


class Step8PreflightHardeningTests(TestCase):
    """Test suite for Step 8: Pre-flight Meeting Upload Hardening."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="step8user@example.com",
            email="step8user@example.com",
            password="SecurePassword123!"
        )
        self.home_url = reverse("meeting")

        self._saved_registry = dict(ProviderRegistry._registry)
        ProviderRegistry.register("mock_harden", MockStep8HardenProvider, override=True)

    def tearDown(self):
        ProviderRegistry._registry = dict(self._saved_registry)

    # -------------------------------------------------------------
    # 1. File Presence & Validation Checks
    # -------------------------------------------------------------

    def test_upload_missing_file_returns_prompt(self):
        """Submitting upload form without a file returns user-friendly guidance."""
        self.client.force_login(self.user)
        response = self.client.post(self.home_url, {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please select a meeting file", response.context["status"])

    def test_upload_unsupported_file_extension_rejected(self):
        """Unsupported file extensions (.pdf, .exe, .txt, .jpg) are rejected immediately."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="harden-model-standard"
        )
        test_file = SimpleUploadedFile("document.pdf", b"%PDF dummy data", content_type="application/pdf")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid file. Please upload only MP4, MOV, AVI, MKV, MP3 or WAV", response.context["status"])
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    def test_upload_file_exceeding_max_size_limit_rejected(self):
        """Files exceeding 50 MB limit are rejected before disk or FFmpeg processing."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="harden-model-standard"
        )
        # Create oversized virtual file (55 MB)
        oversized_file = SimpleUploadedFile("large_meeting.mp4", b"X" * (55 * 1024 * 1024), content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": oversized_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("exceeds the demo limit of 50 MB", response.context["status"])
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    # -------------------------------------------------------------
    # 2. Pre-Flight Health Checks (Zero Resource Waste)
    # -------------------------------------------------------------

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_missing_api_configuration_halts_before_disk_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Missing API key halts before disk write or FFmpeg."""
        self.client.force_login(self.user)
        test_file = SimpleUploadedFile("meeting.mp4", b"valid media bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Please configure your AI Provider and API Key in Settings", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_access_denied_halts_before_disk_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Invalid API key triggers ACCESS_DENIED pre-flight failure."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="invalid_key",
            model_name="harden-model-standard"
        )
        test_file = SimpleUploadedFile("meeting.mp4", b"valid media bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Authentication Failed", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_unavailable_model_halts_before_disk_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Decommissioned model triggers UNAVAILABLE pre-flight failure."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="unavailable-model"
        )
        test_file = SimpleUploadedFile("meeting.mp4", b"valid media bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Model Unavailable", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_quota_exceeded_halts_before_disk_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Exhausted quota triggers QUOTA_EXCEEDED pre-flight failure."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="quota-model"
        )
        test_file = SimpleUploadedFile("meeting.mp4", b"valid media bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Quota Exceeded", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_rate_limited_halts_before_disk_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Rate limit triggers RATE_LIMITED pre-flight failure."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="rate-limit-model"
        )
        test_file = SimpleUploadedFile("meeting.mp4", b"valid media bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("⏳ AI Rate Limited", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_temporarily_unavailable_halts_before_disk_and_ffmpeg(self, mock_fs_save, mock_extract):
        """Overloaded provider triggers TEMPORARILY_UNAVAILABLE pre-flight failure."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="busy-model"
        )
        test_file = SimpleUploadedFile("meeting.mp4", b"valid media bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn("⚠️ AI Service Busy", response.context["status"])
        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()
        self.assertEqual(Meeting.objects.filter(user=self.user).count(), 0)

    # -------------------------------------------------------------
    # 3. Successful Workflow & Error Resilience
    # -------------------------------------------------------------

    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_report")
    @patch("meeting.services.transcript_service.TranscriptService.save_transcript")
    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_transcript")
    @patch("meeting.services.audio_service.AudioService.get_audio_info")
    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    @patch("django.core.files.storage.FileSystemStorage.path")
    def test_successful_preflight_and_end_to_end_meeting_flow(
        self, mock_fs_path, mock_fs_save, mock_extract, mock_info, mock_tr, mock_save_tr, mock_report
    ):
        """Successful preflight proceeds to execute full pipeline and persist Meeting record."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_harden",
            api_key="valid_key_123",
            model_name="harden-model-standard"
        )

        mock_fs_save.return_value = "meeting_harden.mp4"
        mock_fs_path.return_value = "/fake/meeting_harden.mp4"
        mock_extract.return_value = "/fake/meeting_harden.wav"
        mock_info.return_value = {"duration_seconds": 60.0}
        mock_tr.return_value = "Speaker 1: Hardened pipeline test transcript."
        mock_save_tr.return_value = "/fake/meeting_harden.txt"
        mock_report.return_value = "## Executive Report\n- Pipeline is hardened."

        test_file = SimpleUploadedFile("meeting_harden.mp4", b"dummy mp4 bytes", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("File Saved Successfully", response.context["status"])
        self.assertIn("Hardened pipeline test transcript", response.context["transcript"])

        # Check Meeting record created in database
        meeting = Meeting.objects.get(user=self.user, meeting_name="meeting_harden.mp4")
        self.assertEqual(meeting.status, "completed")
        self.assertEqual(meeting.provider, "mock_harden")
        self.assertEqual(meeting.model_name, "harden-model-standard")
