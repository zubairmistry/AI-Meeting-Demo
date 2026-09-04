"""
meeting/tests/test_model_e2e_validation.py

Automated Unit and Integration Tests for Task 1:
Model Validation + Sample-Video End-to-End Testing Pipeline.
"""

import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from meeting.models import Meeting, AISettings
from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.providers.registry import ProviderRegistry
from meeting.services.model_validation_service import ModelValidationService
from meeting.services.settings_service import SettingsService


class MockE2EAIProvider(BaseAIProvider):
    """Full-featured mock provider for E2E validation testing."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.provider = self.settings.get("provider", "mock_e2e")
        self.api_key = self.settings.get("api_key", "valid-test-key-123")
        self.model_name = self.settings.get("model_name", "mock-model-alpha")
        self.cleaned_up_sources = []
        self.fail_access = False
        self.fail_upload = False
        self.fail_wait = False
        self.fail_transcribe = False
        self.empty_transcribe = False
        self.fail_report = False
        self.empty_report = False

    def test_connection(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Connected")

    def discover_models(self):
        return [
            ModelDescriptor(
                id="mock-model-alpha",
                display_name="Mock Model Alpha",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=True,
            ),
            ModelDescriptor(
                id="mock-model-beta",
                display_name="Mock Model Beta",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=False,
            ),
        ]

    def filter_compatible_models(self, models):
        return models

    def validate_model_access(self, model_id):
        if self.fail_access or self.api_key == "bad-key":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Access denied or invalid API key.",
                model_id=model_id,
            )
        return ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message="Model accessible.",
            model_id=model_id,
        )

    def quick_preflight_check(self):
        return self.validate_model_access(self.model_name)

    def upload_audio(self, audio_path):
        if self.fail_upload:
            raise RuntimeError("Remote upload connection failed.")
        return {"name": "remote_audio_mock_123", "path": audio_path}

    def wait_until_ready(self, audio_file):
        if self.fail_wait:
            raise TimeoutError("Remote audio processing timed out.")
        return audio_file

    def generate_transcript(self, audio_source):
        if self.fail_transcribe:
            raise RuntimeError("Transcription API failed.")
        if self.empty_transcribe:
            return ""
        return "This is a valid meeting transcript discussing sprint objectives and action items."

    def generate_report(self, transcript):
        if self.fail_report:
            raise RuntimeError("Report generation API failed.")
        if self.empty_report:
            return "   "
        return "### Executive Summary\n- Deliverables on schedule.\n- Action items assigned."

    def cleanup_audio(self, audio_source):
        self.cleaned_up_sources.append(audio_source)

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNAVAILABLE,
            message=str(exc),
            model_id=self.model_name,
        )


class ModelE2EValidationUnitTests(TestCase):
    """Unit tests for ModelValidationService.validate_model_e2e."""

    def setUp(self):
        self.user = User.objects.create_user(username="e2e_user@example.com", password="Pass2026!e2e")
        self.provider = MockE2EAIProvider()

    def test_sample_video_resource_exists_and_resolves(self):
        """Verify the built-in sample meeting video exists, is readable, and has valid size."""
        sample_path = ModelValidationService.get_sample_video_path()
        self.assertIsInstance(sample_path, Path)
        self.assertTrue(sample_path.exists(), f"Sample video file missing at {sample_path}")
        self.assertTrue(os.path.isfile(sample_path))
        self.assertGreater(os.path.getsize(sample_path), 1000, "Sample video file must be > 1KB")

    def test_selected_model_is_configured_on_provider(self):
        """Verify that validating a specific model_id sets provider.model_name to that model."""
        self.provider.model_name = "default-model"
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-beta")
        self.assertTrue(result.is_valid)
        self.assertEqual(self.provider.model_name, "mock-model-beta")
        self.assertEqual(result.model_id, "mock-model-beta")

    def test_existing_access_validation_failure_short_circuits(self):
        """Verify initial access validation failure returns immediately with access_validation_failed stage."""
        self.provider.fail_access = True
        with patch("meeting.services.audio_service.AudioService.extract_audio") as mock_extract:
            result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
            self.assertFalse(result.is_valid)
            self.assertEqual(result.stage, "access_validation_failed")
            mock_extract.assert_not_called()

    def test_sample_video_missing_returns_error(self):
        """Verify missing sample video returns sample_video_missing stage."""
        fake_path = Path("meeting/resources/non_existent_file.mp4")
        result = ModelValidationService.validate_model_e2e(
            self.provider, "mock-model-alpha", sample_video_path=fake_path
        )
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "sample_video_missing")

    def test_successful_e2e_validation(self):
        """Verify complete successful E2E validation returns is_valid=True and validation_success stage."""
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.status, ModelStatus.AVAILABLE)
        self.assertEqual(result.stage, "validation_success")
        self.assertIn("mock-model-alpha", result.message)

    def test_audio_extraction_failure(self):
        """Verify FFmpeg extraction failure returns audio_extraction_failed stage."""
        with patch("meeting.services.audio_service.AudioService.extract_audio", side_effect=RuntimeError("FFmpeg crash")):
            result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
            self.assertFalse(result.is_valid)
            self.assertEqual(result.stage, "audio_extraction_failed")

    def test_audio_upload_failure(self):
        """Verify remote upload failure returns audio_upload_failed stage."""
        self.provider.fail_upload = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "audio_upload_failed")

    def test_audio_processing_wait_failure(self):
        """Verify remote wait failure returns audio_processing_failed stage."""
        self.provider.fail_wait = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "audio_processing_failed")

    def test_transcription_failure(self):
        """Verify transcription API failure returns transcription_failed stage."""
        self.provider.fail_transcribe = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "transcription_failed")

    def test_empty_transcript_failure(self):
        """Verify empty/blank transcript returns empty_transcript stage."""
        self.provider.empty_transcribe = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "empty_transcript")

    def test_report_generation_failure(self):
        """Verify report generation API failure returns report_generation_failed stage."""
        self.provider.fail_report = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "report_generation_failed")

    def test_empty_report_failure(self):
        """Verify empty/blank report returns empty_report stage."""
        self.provider.empty_report = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "empty_report")

    def test_remote_audio_cleanup_called_on_success(self):
        """Verify provider.cleanup_audio is invoked when E2E validation succeeds."""
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertTrue(result.is_valid)
        self.assertEqual(len(self.provider.cleaned_up_sources), 1)

    def test_remote_audio_cleanup_called_on_report_failure(self):
        """Verify provider.cleanup_audio is invoked even when downstream report generation fails."""
        self.provider.fail_report = True
        result = ModelValidationService.validate_model_e2e(self.provider, "mock-model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(len(self.provider.cleaned_up_sources), 1)


class ModelE2EValidationIntegrationTests(TestCase):
    """Integration tests for AJAX endpoint /settings/api/validate-model/ with E2E workflow."""

    def setUp(self):
        self.user = User.objects.create_user(username="ajax_e2e@example.com", password="AjaxPass2026!")
        self.client.login(username="ajax_e2e@example.com", password="AjaxPass2026!")
        self.validate_url = reverse("validate_model_api")
        self.discover_url = reverse("discover_models_api")
        ProviderRegistry.register("mock_e2e_provider", MockE2EAIProvider)

    def tearDown(self):
        ProviderRegistry.unregister("mock_e2e_provider")

    def test_ajax_validate_model_e2e_success(self):
        """Verify AJAX endpoint executes E2E validation and returns success JSON."""
        payload = {
            "provider": "mock_e2e_provider",
            "model_id": "mock-model-alpha",
            "api_key": "valid-secret-key-12345",
        }
        response = self.client.post(
            self.validate_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["model_id"], "mock-model-alpha")
        self.assertEqual(data["data"]["status"], "AVAILABLE")
        self.assertEqual(data["data"]["stage"], "validation_success")

    def test_no_meeting_record_created_by_sample_validation(self):
        """Verify that running model validation creates zero Meeting database records."""
        initial_meeting_count = Meeting.objects.count()
        payload = {
            "provider": "mock_e2e_provider",
            "model_id": "mock-model-alpha",
            "api_key": "valid-secret-key-12345",
        }
        self.client.post(
            self.validate_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(Meeting.objects.count(), initial_meeting_count)

    def test_discover_models_behaviour_remains_unchanged(self):
        """Verify that Discover Models endpoint still discovers all compatible models without requiring E2E validation."""
        payload = {
            "provider": "mock_e2e_provider",
            "api_key": "valid-secret-key-12345",
        }
        response = self.client.post(
            self.discover_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        models = data["data"]["models"]
        self.assertEqual(len(models), 2)
        model_ids = [m["id"] for m in models]
        self.assertIn("mock-model-alpha", model_ids)
        self.assertIn("mock-model-beta", model_ids)

    def test_api_key_not_exposed_in_response(self):
        """Verify that the raw API key never appears in the validation response payload."""
        raw_key = "super-secret-api-key-xyz-987"
        payload = {
            "provider": "mock_e2e_provider",
            "model_id": "mock-model-alpha",
            "api_key": raw_key,
        }
        response = self.client.post(
            self.validate_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body_text = response.content.decode("utf-8")
        self.assertNotIn(raw_key, body_text)
