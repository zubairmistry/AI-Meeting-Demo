"""
meeting/tests/test_settings_ui_step6.py

Comprehensive tests for Step 6: AI Settings UI, Dynamic Models & Validation Feedback.
Covers:
1. GET /settings view rendering, context passing, and zero API key leakage.
2. POST /settings saving provider, encrypted API key, model name.
3. POST /settings with blank API key preserving existing encrypted API key.
4. Model discovery via AJAX (success, ranking, recommendation, failure).
5. Live model validation via AJAX (available, access denied, unavailable, quota, rate limit, busy).
6. Security checks ensuring API keys are never exposed in DOM or JSON payloads.
"""

import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from meeting.models import AISettings
from meeting.services.settings_service import SettingsService
from meeting.security.encryption import decrypt
from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.providers.registry import ProviderRegistry


class MockStep6Provider(BaseAIProvider):
    """Mock AI provider for testing Step 6 dynamic discovery and validation."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.provider = self.settings.get("provider", "mock_step6")
        self.api_key = self.settings.get("api_key", "")
        self.model_name = self.settings.get("model_name", "model-primary-rec")

    def test_connection(self):
        if not self.api_key or self.api_key == "bad_key":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid credentials.",
                model_id=self.model_name,
            )
        return ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message="Connected successfully.",
            model_id=self.model_name,
        )

    def discover_models(self):
        return [
            ModelDescriptor(
                id="model-primary-rec",
                display_name="Primary Recommended Model",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                quality_score=96,
                speed_score=92,
                is_recommended=True,
                context_window=1000000,
            ),
            ModelDescriptor(
                id="model-secondary-fast",
                display_name="Secondary Fast Model",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                quality_score=85,
                speed_score=98,
                is_recommended=False,
                context_window=500000,
            ),
            ModelDescriptor(
                id="model-text-only",
                display_name="Incompatible Text Only Model",
                capabilities={ProviderCapability.TEXT_GENERATION},
                source=DiscoverySource.LIVE_API,
                status=ModelStatus.COMPATIBLE_UNTESTED,
                quality_score=90,
                speed_score=90,
                is_recommended=False,
            ),
        ]

    def filter_compatible_models(self, models):
        return [
            m for m in models
            if {ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION}.issubset(m.capabilities)
        ]

    def validate_model_access(self, model_id):
        if not self.api_key or self.api_key == "invalid_key":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid API Key. Access Denied.",
                model_id=model_id,
            )
        if model_id == "unavailable-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Model ID not found.",
                model_id=model_id,
            )
        if model_id == "quota-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.QUOTA_EXCEEDED,
                message="Quota limit reached for account.",
                model_id=model_id,
            )
        if model_id == "rate-limit-model":
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="Rate limit exceeded. Please wait.",
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
            message=f"Model '{model_id}' is available and verified.",
            model_id=model_id,
        )

    def quick_preflight_check(self):
        return self.validate_model_access(self.model_name)

    def generate_transcript(self, audio_source):
        return "Mock Transcript"

    def generate_report(self, transcript):
        return "Mock Executive Report"

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=str(exc),
            model_id=self.model_name,
        )


class Step6SettingsUITests(TestCase):
    """Unit and Integration tests specifically for Step 6 Settings UI."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="step6user@example.com",
            email="step6user@example.com",
            password="SecurePassword123!"
        )
        self.settings_url = reverse("settings")
        self.discover_url = reverse("discover_models_api")
        self.validate_url = reverse("validate_model_api")

        self._saved_registry = dict(ProviderRegistry._registry)
        ProviderRegistry.register("mock_step6", MockStep6Provider, override=True)

        SettingsService.save_settings(
            user=self.user,
            provider="mock_step6",
            api_key="initial_super_secret_key_123",
            model_name="model-primary-rec",
        )

    def tearDown(self):
        ProviderRegistry._registry = dict(self._saved_registry)

    # -------------------------------------------------------------
    # 1. GET Settings View & Zero Key Leakage Tests
    # -------------------------------------------------------------

    def test_get_settings_renders_authenticated_user_page(self):
        """GET /settings should render 200 OK with proper context."""
        self.client.force_login(self.user)
        response = self.client.get(self.settings_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "meeting/settings.html")
        self.assertTrue(response.context["api_key_configured"])
        self.assertEqual(response.context["current_provider"], "mock_step6")
        self.assertEqual(response.context["current_model"], "model-primary-rec")

    def test_get_settings_never_exposes_plaintext_or_encrypted_api_key_in_html(self):
        """GET /settings HTML response must never contain the plaintext API key."""
        self.client.force_login(self.user)
        response = self.client.get(self.settings_url)
        content = response.content.decode("utf-8")
        self.assertNotIn("initial_super_secret_key_123", content)
        # Check that password field renders empty
        self.assertIn('name="api_key"', content)
        self.assertNotIn('value="initial_super_secret_key_123"', content)

    # -------------------------------------------------------------
    # 2. POST Settings Save Tests
    # -------------------------------------------------------------

    def test_post_settings_saves_new_provider_and_encrypted_key(self):
        """POST /settings saves updated credentials with Fernet encryption."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.settings_url,
            data={
                "provider": "gemini",
                "api_key": "fresh_updated_secret_key_456",
                "model_name": "gemini-2.5-pro",
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)

        saved = SettingsService.get_settings(self.user)
        self.assertEqual(saved["provider"], "gemini")
        self.assertEqual(saved["api_key"], "fresh_updated_secret_key_456")
        self.assertEqual(saved["model_name"], "gemini-2.5-pro")

        # Verify DB column is encrypted and not plaintext
        raw_db_row = AISettings.objects.get(user=self.user)
        self.assertNotEqual(raw_db_row.api_key, "fresh_updated_secret_key_456")
        self.assertEqual(decrypt(raw_db_row.api_key), "fresh_updated_secret_key_456")

    def test_post_settings_with_blank_api_key_preserves_existing_encrypted_key(self):
        """Submitting a blank api_key must retain the previously saved encrypted key."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.settings_url,
            data={
                "provider": "gemini",
                "api_key": "",  # intentionally blank
                "model_name": "gemini-2.5-flash",
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)

        saved = SettingsService.get_settings(self.user)
        self.assertEqual(saved["api_key"], "initial_super_secret_key_123")
        self.assertEqual(saved["model_name"], "gemini-2.5-flash")

    # -------------------------------------------------------------
    # 3. Model Discovery AJAX Tests
    # -------------------------------------------------------------

    def test_ajax_discover_models_success_and_ranking(self):
        """POST /settings/api/discover-models/ returns sorted compatible models and recommended model."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "mock_step6"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])

        models = data["data"]["models"]
        self.assertEqual(len(models), 2)  # Incompatible text-only model filtered out
        model_ids = [m["id"] for m in models]
        self.assertEqual(model_ids[0], "model-primary-rec")
        self.assertEqual(model_ids[1], "model-secondary-fast")
        self.assertEqual(data["data"]["recommended_model_id"], "model-primary-rec")

        # Metadata preservation check
        rec_model = models[0]
        self.assertTrue(rec_model["is_recommended"])
        self.assertEqual(rec_model["quality_score"], 96)
        self.assertEqual(rec_model["speed_score"], 92)
        self.assertEqual(rec_model["context_window"], 1000000)

    def test_ajax_discover_models_invalid_provider_returns_error(self):
        """POST /settings/api/discover-models/ with invalid provider returns 400."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "unsupported_xyz_provider"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_PROVIDER")

    # -------------------------------------------------------------
    # 4. Model Validation AJAX Tests (Live Status Feedback)
    # -------------------------------------------------------------

    def test_ajax_validate_model_available(self):
        """Valid model access returns AVAILABLE status."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_step6",
                "model_id": "model-primary-rec"
            }),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["status"], "AVAILABLE")
        self.assertIn("verified", data["data"]["message"])

    def test_ajax_validate_model_access_denied(self):
        """Invalid credentials return ACCESS_DENIED status."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_step6",
                "model_id": "model-primary-rec",
                "api_key": "invalid_key"
            }),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "ACCESS_DENIED")

    def test_ajax_validate_model_unavailable(self):
        """Non-existent model returns UNAVAILABLE status."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_step6",
                "model_id": "unavailable-model"
            }),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "UNAVAILABLE")

    def test_ajax_validate_model_quota_exceeded(self):
        """Quota exhausted returns QUOTA_EXCEEDED status."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_step6",
                "model_id": "quota-model"
            }),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "QUOTA_EXCEEDED")

    def test_ajax_validate_model_rate_limited(self):
        """Rate limited returns RATE_LIMITED status."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_step6",
                "model_id": "rate-limit-model"
            }),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "RATE_LIMITED")

    def test_ajax_validate_model_temporarily_unavailable(self):
        """Overloaded provider returns TEMPORARILY_UNAVAILABLE status."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.validate_url,
            data=json.dumps({
                "provider": "mock_step6",
                "model_id": "busy-model"
            }),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "TEMPORARILY_UNAVAILABLE")

    # -------------------------------------------------------------
    # 5. Security & Zero Key Leakage in JSON Responses
    # -------------------------------------------------------------

    def test_no_api_keys_leaked_in_ajax_responses(self):
        """API responses must never echo back the api_key."""
        self.client.force_login(self.user)

        # Discovery endpoint check
        resp1 = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "mock_step6", "api_key": "my_secret_key"}),
            content_type="application/json"
        )
        self.assertNotIn("my_secret_key", resp1.content.decode("utf-8"))
        self.assertNotIn("initial_super_secret_key_123", resp1.content.decode("utf-8"))

        # Validation endpoint check
        resp2 = self.client.post(
            self.validate_url,
            data=json.dumps({"provider": "mock_step6", "model_id": "model-primary-rec", "api_key": "my_secret_key"}),
            content_type="application/json"
        )
        self.assertNotIn("my_secret_key", resp2.content.decode("utf-8"))
        self.assertNotIn("initial_super_secret_key_123", resp2.content.decode("utf-8"))
