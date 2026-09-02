"""
Unit tests for AJAX API endpoints and pre-flight meeting upload integration.
"""

import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

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


class MockProviderForAjax(BaseAIProvider):
    """Controllable mock provider for AJAX and pre-flight testing."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.provider = self.settings.get("provider", "mock_ajax")
        self.api_key = self.settings.get("api_key", "")
        self.model_name = self.settings.get("model_name", "mock-model-rec")
        self.probed_models = []

    def test_connection(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Connected")

    def discover_models(self):
        return [
            ModelDescriptor(
                id="mock-model-rec",
                display_name="Mock Model Recommended",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                quality_score=95,
                speed_score=90,
                is_recommended=True,
            ),
            ModelDescriptor(
                id="mock-model-sec",
                display_name="Mock Model Secondary",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                quality_score=80,
                speed_score=85,
                is_recommended=False,
            ),
            ModelDescriptor(
                id="mock-incompatible-text",
                display_name="Incompatible Text Only",
                capabilities={ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
            ),
        ]

    def filter_compatible_models(self, models):
        return [
            m for m in models
            if {ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION}.issubset(m.capabilities)
        ]

    def validate_model_access(self, model_id):
        self.probed_models.append(model_id)
        if not self.api_key or self.api_key == "invalid_key":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid API key.",
                model_id=model_id,
            )
        if model_id == "deprecated-404":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Model is not available.",
                model_id=model_id,
            )
        if model_id == "quota-exhausted":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.QUOTA_EXCEEDED,
                message="Quota exhausted.",
                model_id=model_id,
            )
        if model_id == "rate-limited":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="Rate limit reached.",
                model_id=model_id,
            )
        if model_id == "high-demand-503":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                message="Model is experiencing high demand.",
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
        return "Mock Transcript"

    def generate_report(self, transcript):
        return "Mock Report"

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=str(exc),
            model_id=self.model_name,
        )


class AjaxApiTests(TestCase):
    """Tests for discover_models_api, validate_model_api, and preflight check."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="TestPassword123!"
        )
        self.discover_url = reverse("discover_models_api")
        self.validate_url = reverse("validate_model_api")
        self.home_url = reverse("meeting")

        self._saved_registry = dict(ProviderRegistry._registry)
        ProviderRegistry.register("mock_ajax", MockProviderForAjax, override=True)

        SettingsService.save_settings(
            user=self.user,
            provider="mock_ajax",
            api_key="valid_secret_key_123",
            model_name="mock-model-rec",
        )

    def tearDown(self):
        ProviderRegistry._registry = dict(self._saved_registry)

    # -------------------------------------------------------------
    # Authentication Tests
    # -------------------------------------------------------------

    def test_anonymous_user_cannot_access_discovery_endpoint(self):
        """Anonymous user should be redirected to login view on discovery request."""
        response = self.client.post(self.discover_url, data={"provider": "mock_ajax"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_anonymous_user_cannot_access_validation_endpoint(self):
        """Anonymous user should be redirected to login view on validation request."""
        response = self.client.post(
            self.validate_url,
            data={"provider": "mock_ajax", "model_id": "mock-model-rec"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    # -------------------------------------------------------------
    # Model Discovery Tests
    # -------------------------------------------------------------

    def test_authenticated_model_discovery_success(self):
        """Authenticated user receives sanitized list of compatible models."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "mock_ajax"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])
        self.assertIn("models", data["data"])

        models = data["data"]["models"]
        model_ids = [m["id"] for m in models]
        self.assertIn("mock-model-rec", model_ids)
        self.assertIn("mock-model-sec", model_ids)
        self.assertNotIn("mock-incompatible-text", model_ids)
        self.assertEqual(data["data"]["recommended_model_id"], "mock-model-rec")

    def test_discovery_with_unregistered_provider_returns_400(self):
        """Requesting discovery for an unsupported provider returns 400 with INVALID_PROVIDER."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "unsupported_provider_xyz"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_PROVIDER")

    def test_discovery_malformed_json_returns_400(self):
        """Malformed JSON payload returns 400 INVALID_JSON."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data="not a valid json {{{{",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_JSON")

    def test_discovery_response_does_not_contain_api_key(self):
        """Discovery response must never leak the API key or raw credential string."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "mock_ajax", "api_key": "super_secret_temp_key"}),
            content_type="application/json",
        )
        response_text = response.content.decode("utf-8")
        self.assertNotIn("super_secret_temp_key", response_text)
        self.assertNotIn("valid_secret_key_123", response_text)

    # -------------------------------------------------------------
    # Model Validation Tests
    # -------------------------------------------------------------

    def test_authenticated_model_validation_success(self):
        """Validating a working model returns success=True and status AVAILABLE."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({"provider": "mock_ajax", "model_id": "mock-model-rec"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["status"], "AVAILABLE")
        self.assertEqual(data["data"]["model_id"], "mock-model-rec")

    def test_validation_with_empty_model_id_returns_400(self):
        """Validating with empty model_id returns 400 INVALID_MODEL_ID."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({"provider": "mock_ajax", "model_id": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_MODEL_ID")

    def test_validation_invalid_credentials_returns_access_denied(self):
        """Invalid API key returns status ACCESS_DENIED."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_ajax",
                "model_id": "mock-model-rec",
                "api_key": "invalid_key",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "ACCESS_DENIED")

    def test_validation_model_not_found_returns_unavailable(self):
        """Unavailable/deprecated model returns status UNAVAILABLE."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_ajax",
                "model_id": "deprecated-404",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "UNAVAILABLE")

    def test_validation_quota_exhausted_returns_quota_exceeded(self):
        """Quota depletion returns QUOTA_EXCEEDED."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_ajax",
                "model_id": "quota-exhausted",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "QUOTA_EXCEEDED")

    def test_validation_rate_limited_returns_rate_limited(self):
        """Rate limit returns RATE_LIMITED."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_ajax",
                "model_id": "rate-limited",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "RATE_LIMITED")

    def test_validation_high_demand_returns_temporarily_unavailable(self):
        """High demand returns TEMPORARILY_UNAVAILABLE."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_ajax",
                "model_id": "high-demand-503",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMPORARILY_UNAVAILABLE")

    def test_validation_response_does_not_contain_api_key(self):
        """Validation response must never contain the API key."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_ajax",
                "model_id": "mock-model-rec",
                "api_key": "unsaved_secret_validate_key",
            }),
            content_type="application/json",
        )
        response_text = response.content.decode("utf-8")
        self.assertNotIn("unsaved_secret_validate_key", response_text)

    # -------------------------------------------------------------
    # Pre-Flight Integration in Meeting Upload Tests
    # -------------------------------------------------------------

    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    def test_preflight_failure_stops_before_file_save_and_ffmpeg(self, mock_fs_save, mock_extract):
        """If configured model preflight check fails, meeting upload halts before saving file or calling FFmpeg."""
        self.client.force_login(self.user)
        SettingsService.save_settings(
            user=self.user,
            provider="mock_ajax",
            api_key="valid_secret_key_123",
            model_name="deprecated-404",
        )

        test_file = SimpleUploadedFile("sample_meeting.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        self.assertIn("❌ AI Model Unavailable", response.context["status"])
        self.assertIn("Model is not available", response.context["status"])

        mock_fs_save.assert_not_called()
        mock_extract.assert_not_called()

    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_report")
    @patch("meeting.services.transcript_service.TranscriptService.save_transcript")
    @patch("meeting.services.ai_analysis_service.AIAnalysisService.generate_transcript")
    @patch("meeting.services.audio_service.AudioService.get_audio_info")
    @patch("meeting.services.audio_service.AudioService.extract_audio")
    @patch("django.core.files.storage.FileSystemStorage.save")
    @patch("django.core.files.storage.FileSystemStorage.path")
    def test_preflight_success_proceeds_with_meeting_processing(
        self, mock_fs_path, mock_fs_save, mock_extract, mock_info, mock_transcript, mock_save_tr, mock_report
    ):
        """When preflight succeeds, normal processing continues seamlessly."""
        self.client.force_login(self.user)
        mock_fs_save.return_value = "saved_sample.mp4"
        mock_fs_path.return_value = "/fake/saved_sample.mp4"
        mock_extract.return_value = "/fake/extracted.wav"
        mock_info.return_value = {"duration_seconds": 30.0}
        mock_transcript.return_value = "Speaker: Hello"
        mock_save_tr.return_value = "/fake/transcript.txt"
        mock_report.return_value = "Report Content"

        test_file = SimpleUploadedFile("sample_meeting.mp4", b"dummy video content", content_type="video/mp4")
        response = self.client.post(self.home_url, {"meeting_file": test_file})

        self.assertEqual(response.status_code, 200)
        mock_fs_save.assert_called_once()
        mock_extract.assert_called_once()
        mock_transcript.assert_called_once()

    # -------------------------------------------------------------
    # Settings UI Integration Tests
    # -------------------------------------------------------------

    def test_settings_page_renders_discovery_and_validation_elements(self):
        """Settings page renders model_select, discovery button, validation button, and config JS."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertIn("btn-discover-models", content)
        self.assertIn("btn-validate-model", content)
        self.assertIn("model_select", content)
        self.assertIn("model_status_container", content)
        self.assertIn("settings.", content)
        self.assertIn("AI_SETTINGS_CONFIG", content)
        self.assertEqual(response.context["current_model"], "mock-model-rec")
        self.assertEqual(response.context["current_provider"], "mock_ajax")

    def test_settings_form_post_saves_selected_model_successfully(self):
        """Posting settings form saves updated model_name and provider securely."""
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("settings"),
            data={
                "provider": "gemini",
                "api_key": "new_secret_key_999",
                "model_name": "gemini-1.5-pro",
            },
        )
        self.assertEqual(response.status_code, 302)
        saved = SettingsService.get_settings(self.user)
        self.assertEqual(saved["provider"], "gemini")
        self.assertEqual(saved["api_key"], "new_secret_key_999")
        self.assertEqual(saved["model_name"], "gemini-1.5-pro")

