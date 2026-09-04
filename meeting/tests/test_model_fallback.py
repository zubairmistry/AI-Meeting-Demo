"""
meeting/tests/test_model_fallback.py

Automated Unit & Integration Tests for Task 2:
Automatic Model Fallback during E2E Sample-Video Validation.
"""

import json
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from meeting.models import Meeting
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


class MultiCandidateMockProvider(BaseAIProvider):
    """Configurable mock provider supporting granular per-model failure simulation."""

    def __init__(self, settings=None, failure_map=None, discovered_models=None):
        self.settings = settings or {}
        self.provider = self.settings.get("provider", "mock_fallback")
        self.api_key = self.settings.get("api_key", "valid-secret-key-999")
        self.model_name = self.settings.get("model_name", "model-alpha")
        self.failure_map = failure_map or {}
        self.discovered_models_list = discovered_models or [
            ModelDescriptor(
                id="model-alpha",
                display_name="Model Alpha",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=True,
                quality_score=95,
                speed_score=90,
            ),
            ModelDescriptor(
                id="model-beta",
                display_name="Model Beta",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=False,
                quality_score=90,
                speed_score=85,
            ),
            ModelDescriptor(
                id="model-gamma",
                display_name="Model Gamma",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=False,
                quality_score=80,
                speed_score=80,
            ),
            ModelDescriptor(
                id="model-delta",
                display_name="Model Delta",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                is_recommended=False,
                quality_score=70,
                speed_score=70,
            ),
        ]
        self.probed_models = []
        self.cleaned_up_sources = []

    def test_connection(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Connected")

    def discover_models(self):
        return list(self.discovered_models_list)

    def filter_compatible_models(self, models):
        return models

    def validate_model_access(self, model_id):
        self.probed_models.append(model_id)
        if self.api_key == "invalid-key":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid API credentials.",
                model_id=model_id,
            )

        fail_mode = self.failure_map.get(model_id)
        if fail_mode == "access_denied":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message=f"Model '{model_id}' access denied.",
                model_id=model_id,
            )
        if fail_mode == "unavailable":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message=f"Model '{model_id}' not available.",
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

    def upload_audio(self, audio_path):
        fail_mode = self.failure_map.get(self.model_name)
        if fail_mode == "upload_fail":
            raise RuntimeError(f"Audio upload failed for '{self.model_name}'.")
        return {"name": f"remote_audio_{self.model_name}", "path": audio_path}

    def wait_until_ready(self, audio_file):
        fail_mode = self.failure_map.get(self.model_name)
        if fail_mode == "wait_timeout":
            raise TimeoutError(f"Audio processing timed out for '{self.model_name}'.")
        return audio_file

    def generate_transcript(self, audio_source):
        fail_mode = self.failure_map.get(self.model_name)
        if fail_mode == "transcribe_fail":
            raise RuntimeError(f"Transcription failed for '{self.model_name}'.")
        if fail_mode == "empty_transcript":
            return ""
        return f"Transcript for {self.model_name}: Discussing project milestones and deliverables."

    def generate_report(self, transcript):
        fail_mode = self.failure_map.get(self.model_name)
        if fail_mode == "report_fail":
            raise RuntimeError(f"Report generation failed for '{self.model_name}'.")
        if fail_mode == "empty_report":
            return "   "
        return f"Executive summary for {self.model_name}: All milestones on track."

    def cleanup_audio(self, audio_source):
        self.cleaned_up_sources.append(audio_source)

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNAVAILABLE,
            message=str(exc),
            model_id=self.model_name,
        )


class ModelFallbackUnitTests(TestCase):
    """Unit tests for ModelValidationService.validate_model_with_fallback."""

    def test_selected_model_succeeds_no_fallback_attempted(self):
        """Selected model succeeds on first attempt: fallback_used=False, single attempt."""
        provider = MultiCandidateMockProvider()
        result = ModelValidationService.validate_model_with_fallback(provider, "model-alpha")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.model_id, "model-alpha")
        self.assertEqual(result.details["selected_model"], "model-alpha")
        self.assertEqual(result.details["verified_model"], "model-alpha")
        self.assertFalse(result.details["fallback_used"])
        self.assertEqual(len(result.details["attempted_models"]), 1)
        self.assertEqual(result.details["attempted_models"][0]["model_id"], "model-alpha")

    def test_selected_model_fails_second_model_succeeds(self):
        """Model A fails (transcription), Model B succeeds: fallback_used=True."""
        provider = MultiCandidateMockProvider(failure_map={"model-alpha": "transcribe_fail"})
        result = ModelValidationService.validate_model_with_fallback(provider, "model-alpha")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.model_id, "model-beta")
        self.assertEqual(result.details["selected_model"], "model-alpha")
        self.assertEqual(result.details["verified_model"], "model-beta")
        self.assertTrue(result.details["fallback_used"])
        self.assertEqual(len(result.details["attempted_models"]), 2)
        self.assertFalse(result.details["attempted_models"][0]["success"])
        self.assertEqual(result.details["attempted_models"][0]["stage"], "transcription_failed")
        self.assertTrue(result.details["attempted_models"][1]["success"])
        self.assertEqual(result.details["attempted_models"][1]["stage"], "validation_success")

    def test_first_two_fail_third_succeeds(self):
        """Model A & B fail, Model C succeeds: 3 attempts, fallback_used=True."""
        provider = MultiCandidateMockProvider(failure_map={
            "model-alpha": "unavailable",
            "model-beta": "report_fail",
        })
        result = ModelValidationService.validate_model_with_fallback(provider, "model-alpha")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.model_id, "model-gamma")
        self.assertEqual(result.details["selected_model"], "model-alpha")
        self.assertEqual(result.details["verified_model"], "model-gamma")
        self.assertTrue(result.details["fallback_used"])
        self.assertEqual(len(result.details["attempted_models"]), 3)

    def test_all_discovered_models_fail(self):
        """All models fail: returns is_valid=False, stage=all_models_failed, fallback_used=True."""
        provider = MultiCandidateMockProvider(failure_map={
            "model-alpha": "unavailable",
            "model-beta": "upload_fail",
            "model-gamma": "empty_transcript",
            "model-delta": "report_fail",
        })
        result = ModelValidationService.validate_model_with_fallback(provider, "model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.stage, "all_models_failed")
        self.assertEqual(result.details["selected_model"], "model-alpha")
        self.assertIsNone(result.details["verified_model"])
        self.assertTrue(result.details["fallback_used"])
        self.assertEqual(len(result.details["attempted_models"]), 4)

    def test_only_one_candidate_exists_and_fails_fallback_used_is_false(self):
        """When only 1 model is discovered and fails, fallback_used=False because no alternate was attempted."""
        single_list = [
            ModelDescriptor(
                id="model-solo",
                display_name="Model Solo",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            )
        ]
        provider = MultiCandidateMockProvider(
            discovered_models=single_list,
            failure_map={"model-solo": "transcribe_fail"}
        )
        result = ModelValidationService.validate_model_with_fallback(provider, "model-solo")
        self.assertFalse(result.is_valid)
        self.assertFalse(result.details["fallback_used"])
        self.assertEqual(len(result.details["attempted_models"]), 1)

    def test_selected_model_is_always_attempted_first(self):
        """Regardless of discovery order, selected model (e.g. model-gamma) is placed first."""
        provider = MultiCandidateMockProvider()
        result = ModelValidationService.validate_model_with_fallback(provider, "model-gamma")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.details["attempted_models"][0]["model_id"], "model-gamma")
        self.assertFalse(result.details["fallback_used"])

    def test_discovery_order_preserved_after_selected_model(self):
        """When model-gamma is selected and fails, order tested is gamma, alpha, beta, delta."""
        provider = MultiCandidateMockProvider(failure_map={
            "model-gamma": "unavailable",
            "model-alpha": "unavailable",
        })
        result = ModelValidationService.validate_model_with_fallback(provider, "model-gamma")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.model_id, "model-beta")
        attempted_ids = [a["model_id"] for a in result.details["attempted_models"]]
        self.assertEqual(attempted_ids, ["model-gamma", "model-alpha", "model-beta"])

    def test_duplicate_candidate_ids_attempted_only_once(self):
        """Duplicate model IDs are deduplicated and attempted at most once."""
        provider = MultiCandidateMockProvider(failure_map={"model-alpha": "unavailable"})
        # Client passes duplicate IDs
        result = ModelValidationService.validate_model_with_fallback(
            provider,
            "model-alpha",
            candidate_models=["model-alpha", "model-alpha", "model-beta", "model-beta"],
        )
        attempted_ids = [a["model_id"] for a in result.details["attempted_models"]]
        self.assertEqual(len(attempted_ids), len(set(attempted_ids)))

    def test_unknown_client_candidate_ids_not_accepted(self):
        """Arbitrary/unsupported client candidate IDs not in authoritative discovery are ignored."""
        provider = MultiCandidateMockProvider(failure_map={"model-alpha": "unavailable"})
        result = ModelValidationService.validate_model_with_fallback(
            provider,
            "model-alpha",
            candidate_models=["model-alpha", "evil-injected-model-xyz", "model-beta"],
        )
        attempted_ids = [a["model_id"] for a in result.details["attempted_models"]]
        self.assertNotIn("evil-injected-model-xyz", attempted_ids)
        self.assertEqual(result.model_id, "model-beta")

    def test_credential_access_failure_stops_fallback_immediately(self):
        """Provider-level credential failure (401 / bad key) aborts immediately without trying all models."""
        provider = MultiCandidateMockProvider(settings={"api_key": "invalid-key"})
        result = ModelValidationService.validate_model_with_fallback(provider, "model-alpha")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.ACCESS_DENIED)
        self.assertFalse(result.details["fallback_used"])
        self.assertEqual(len(result.details["attempted_models"]), 1)

    def test_per_candidate_cleanup_occurs_between_attempts(self):
        """Remote audio cleanup is called for failed candidates before moving to next candidate."""
        provider = MultiCandidateMockProvider(failure_map={"model-alpha": "transcribe_fail"})
        result = ModelValidationService.validate_model_with_fallback(provider, "model-alpha")
        self.assertTrue(result.is_valid)
        # alpha had remote audio cleaned up on transcribe failure, beta had remote audio cleaned up on success
        self.assertEqual(len(provider.cleaned_up_sources), 2)


class ModelFallbackIntegrationTests(TestCase):
    """Integration tests for AJAX endpoint /settings/api/validate-model/ with fallback."""

    def setUp(self):
        self.user = User.objects.create_user(username="fallback_user@example.com", password="FbPass2026!")
        self.client.login(username="fallback_user@example.com", password="FbPass2026!")
        self.validate_url = reverse("validate_model_api")
        self.discover_url = reverse("discover_models_api")

        def factory(settings=None):
            # Model alpha fails upload, beta succeeds
            return MultiCandidateMockProvider(
                settings=settings,
                failure_map={"model-alpha": "upload_fail"}
            )

        ProviderRegistry.register("mock_fallback_provider", factory)

    def tearDown(self):
        ProviderRegistry.unregister("mock_fallback_provider")

    def test_ajax_validate_model_with_fallback_success(self):
        """AJAX validation automatically falls back from model-alpha to model-beta and returns structured data."""
        payload = {
            "provider": "mock_fallback_provider",
            "model_id": "model-alpha",
            "api_key": "valid-secret-key-12345",
            "candidate_models": ["model-alpha", "model-beta", "model-gamma"],
        }
        response = self.client.post(
            self.validate_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["selected_model"], "model-alpha")
        self.assertEqual(data["data"]["verified_model"], "model-beta")
        self.assertTrue(data["data"]["fallback_used"])
        self.assertEqual(len(data["data"]["attempted_models"]), 2)
        self.assertIn("model-beta", data["data"]["message"])

    def test_no_meeting_record_created_during_fallback(self):
        """Executing multi-model fallback validation creates zero Meeting database records."""
        initial_meeting_count = Meeting.objects.count()
        payload = {
            "provider": "mock_fallback_provider",
            "model_id": "model-alpha",
            "api_key": "valid-secret-key-12345",
        }
        self.client.post(
            self.validate_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(Meeting.objects.count(), initial_meeting_count)

    def test_discover_models_endpoint_remains_unchanged(self):
        """Discover Models endpoint returns all 4 models untouched."""
        payload = {
            "provider": "mock_fallback_provider",
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
        self.assertEqual(len(data["data"]["models"]), 4)

    def test_api_key_not_exposed_in_fallback_response(self):
        """API key is never exposed in the response payload or attempted models."""
        raw_key = "secret-key-do-not-leak-777"
        payload = {
            "provider": "mock_fallback_provider",
            "model_id": "model-alpha",
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
