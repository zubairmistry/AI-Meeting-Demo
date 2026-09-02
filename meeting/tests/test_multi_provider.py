"""
Unit and integration tests for Multi-Provider Extensibility, Remote Asset Lifecycle Management & Fallback Resilience.
"""

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.providers.registry import ProviderRegistry
from meeting.providers.gemini_provider import GeminiProvider
from meeting.providers.claude_provider import ClaudeProvider, FALLBACK_CLAUDE_MODELS
from meeting.providers.openai_provider import OpenAIProvider, FALLBACK_OPENAI_MODELS
from meeting.services.ai_analysis_service import AIAnalysisService
from meeting.services.settings_service import SettingsService


class MultiProviderTests(TestCase):
    """Tests for ClaudeProvider, OpenAIProvider, registry lookups, error translations, and remote asset cleanup."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="multiprovideruser",
            email="multiprovider@example.com",
            password="SecurePassword123!"
        )
        self.discover_url = reverse("discover_models_api")
        self.validate_url = reverse("validate_model_api")

    # -------------------------------------------------------------
    # Registry Registration & Lookup Tests
    # -------------------------------------------------------------

    def test_claude_registry_lookup(self):
        """ClaudeProvider is registered and resolvable from ProviderRegistry."""
        self.assertTrue(ProviderRegistry.is_registered("claude"))
        provider_cls = ProviderRegistry.get("claude")
        self.assertEqual(provider_cls, ClaudeProvider)
        instance = provider_cls({"provider": "claude", "api_key": "test-key"})
        self.assertIsInstance(instance, BaseAIProvider)

    def test_openai_registry_lookup(self):
        """OpenAIProvider is registered and resolvable from ProviderRegistry."""
        self.assertTrue(ProviderRegistry.is_registered("openai"))
        provider_cls = ProviderRegistry.get("openai")
        self.assertEqual(provider_cls, OpenAIProvider)
        instance = provider_cls({"provider": "openai", "api_key": "test-key"})
        self.assertIsInstance(instance, BaseAIProvider)

    def test_missing_optional_sdk_does_not_crash_provider_initialization(self):
        """Instantiating Claude and OpenAI providers without SDKs installed does not raise."""
        claude = ClaudeProvider({"provider": "claude", "api_key": "dummy"})
        openai_prov = OpenAIProvider({"provider": "openai", "api_key": "dummy"})
        self.assertEqual(claude.provider, "claude")
        self.assertEqual(openai_prov.provider, "openai")

    # -------------------------------------------------------------
    # Model Discovery & Fallback Catalog Tests
    # -------------------------------------------------------------

    def test_claude_fallback_discovery(self):
        """ClaudeProvider returns fallback catalog descriptors with CATALOG_FALLBACK."""
        provider = ClaudeProvider({"provider": "claude", "api_key": ""})
        models = provider.discover_models()
        self.assertGreater(len(models), 0)
        self.assertTrue(all(m.source == DiscoverySource.CATALOG_FALLBACK for m in models))
        model_ids = [m.id for m in models]
        self.assertIn("claude-3-5-sonnet-20241022", model_ids)

    def test_openai_fallback_discovery(self):
        """OpenAIProvider returns fallback catalog descriptors with CATALOG_FALLBACK."""
        provider = OpenAIProvider({"provider": "openai", "api_key": ""})
        models = provider.discover_models()
        self.assertGreater(len(models), 0)
        self.assertTrue(all(m.source == DiscoverySource.CATALOG_FALLBACK for m in models))
        model_ids = [m.id for m in models]
        self.assertIn("gpt-4o", model_ids)
        self.assertIn("whisper-1", model_ids)

    def test_capability_filtering(self):
        """Capability filtering separates multimodal transcription from text-only models."""
        claude = ClaudeProvider()
        claude_models = claude.discover_models()
        compatible_claude = claude.filter_compatible_models(claude_models)
        self.assertTrue(all(ProviderCapability.TEXT_GENERATION in m.capabilities for m in compatible_claude))

        openai_prov = OpenAIProvider()
        openai_models = openai_prov.discover_models()
        compatible_openai = openai_prov.filter_compatible_models(openai_models)
        compatible_ids = [m.id for m in compatible_openai]
        self.assertIn("gpt-4o", compatible_ids)
        self.assertIn("gpt-4o-mini", compatible_ids)
        self.assertNotIn("whisper-1", compatible_ids)  # whisper-1 lacks TEXT_GENERATION

    # -------------------------------------------------------------
    # Error Translation Tests
    # -------------------------------------------------------------

    def test_claude_error_translation(self):
        """ClaudeProvider normalizes SDK exceptions into structured ValidationResults."""
        claude = ClaudeProvider({"provider": "claude", "model_name": "claude-3-5-sonnet-20241022"})

        # 401 Unauthorized
        err_401 = Exception("401 authentication_error: invalid x-api-key")
        res_401 = claude.translate_error(err_401)
        self.assertEqual(res_401.status, ModelStatus.ACCESS_DENIED)

        # 404 Not Found
        err_404 = Exception("404 not_found: model does not exist")
        res_404 = claude.translate_error(err_404)
        self.assertEqual(res_404.status, ModelStatus.UNAVAILABLE)

        # 429 Rate Limit / Overloaded
        err_429 = Exception("429 rate_limit_error: request limit exceeded")
        res_429 = claude.translate_error(err_429)
        self.assertEqual(res_429.status, ModelStatus.RATE_LIMITED)

        # 529 Overloaded
        err_529 = Exception("529 overloaded_error: Server is overloaded")
        res_529 = claude.translate_error(err_529)
        self.assertEqual(res_529.status, ModelStatus.TEMPORARILY_UNAVAILABLE)

    def test_openai_error_translation(self):
        """OpenAIProvider normalizes SDK exceptions into structured ValidationResults."""
        openai_prov = OpenAIProvider({"provider": "openai", "model_name": "gpt-4o"})

        # 401 Unauthorized
        err_401 = Exception("Error code: 401 - {'error': {'message': 'Incorrect API key provided'}}")
        res_401 = openai_prov.translate_error(err_401)
        self.assertEqual(res_401.status, ModelStatus.ACCESS_DENIED)

        # 404 Not Found
        err_404 = Exception("Error code: 404 - {'error': {'message': 'The model does not exist'}}")
        res_404 = openai_prov.translate_error(err_404)
        self.assertEqual(res_404.status, ModelStatus.UNAVAILABLE)

        # 429 Quota Exceeded
        err_quota = Exception("Error code: 429 - {'error': {'message': 'You exceeded your current quota'}}")
        res_quota = openai_prov.translate_error(err_quota)
        self.assertEqual(res_quota.status, ModelStatus.QUOTA_EXCEEDED)

        # 503 Unavailable
        err_503 = Exception("Error code: 503 - {'error': {'message': 'Service Unavailable'}}")
        res_503 = openai_prov.translate_error(err_503)
        self.assertEqual(res_503.status, ModelStatus.TEMPORARILY_UNAVAILABLE)

    # -------------------------------------------------------------
    # Remote Audio Asset Lifecycle & Cleanup Tests
    # -------------------------------------------------------------

    def test_gemini_remote_audio_cleanup_calls_delete(self):
        """GeminiProvider.cleanup_audio calls client.files.delete for remote assets."""
        provider = GeminiProvider({"provider": "gemini", "api_key": "fake_key"})
        mock_client = MagicMock()
        provider.client = mock_client

        mock_audio_file = MagicMock()
        mock_audio_file.name = "files/test_remote_file_12345"

        provider.cleanup_audio(mock_audio_file)
        mock_client.files.delete.assert_called_once_with(name="files/test_remote_file_12345")

    def test_gemini_cleanup_safely_handles_deletion_exceptions(self):
        """GeminiProvider.cleanup_audio shields exceptions and does not crash caller."""
        provider = GeminiProvider({"provider": "gemini", "api_key": "fake_key"})
        mock_client = MagicMock()
        mock_client.files.delete.side_effect = RuntimeError("Remote deletion network timeout")
        provider.client = mock_client

        mock_audio_file = MagicMock()
        mock_audio_file.name = "files/problematic_file"

        # Should not raise exception
        provider.cleanup_audio(mock_audio_file)
        mock_client.files.delete.assert_called_once()

    def test_ai_analysis_service_always_calls_cleanup_audio_through_finally(self):
        """AIAnalysisService.generate_transcript calls cleanup_audio in finally block on success."""
        mock_provider = MagicMock(spec=BaseAIProvider)
        mock_audio_source = MagicMock()
        mock_provider.upload_audio.return_value = mock_audio_source
        mock_provider.wait_until_ready.return_value = mock_audio_source
        mock_provider.generate_transcript.return_value = "Speaker 1: Successful transcript."

        with patch("meeting.services.provider_factory.ProviderFactory.get_provider", return_value=mock_provider):
            result = AIAnalysisService.generate_transcript(self.user, "/path/to/meeting.wav")

            self.assertEqual(result, "Speaker 1: Successful transcript.")
            mock_provider.cleanup_audio.assert_called_once_with(mock_audio_source)

    def test_cleanup_occurs_when_transcript_generation_raises(self):
        """AIAnalysisService.generate_transcript calls cleanup_audio in finally block even when an error occurs."""
        mock_provider = MagicMock(spec=BaseAIProvider)
        mock_audio_source = MagicMock()
        mock_provider.upload_audio.return_value = mock_audio_source
        mock_provider.wait_until_ready.return_value = mock_audio_source
        mock_provider.generate_transcript.side_effect = RuntimeError("Generation failed mid-stream")

        with patch("meeting.services.provider_factory.ProviderFactory.get_provider", return_value=mock_provider):
            with self.assertRaises(RuntimeError):
                AIAnalysisService.generate_transcript(self.user, "/path/to/meeting.wav")

            mock_provider.cleanup_audio.assert_called_once_with(mock_audio_source)

    # -------------------------------------------------------------
    # Multi-Provider AJAX API Tests
    # -------------------------------------------------------------

    def test_ajax_discovery_endpoint_behavior_for_claude(self):
        """AJAX discovery executes for Claude and correctly reflects its capability profile."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "claude"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])
        # Because Claude lacks AUDIO_TRANSCRIPTION, meeting filter yields 0 full-flow models
        models = data["data"]["models"]
        self.assertEqual(len(models), 0)

    def test_ajax_discovery_endpoint_works_for_openai(self):
        """AJAX discovery returns compatible models for OpenAI provider."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "openai"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        models = data["data"]["models"]
        self.assertGreater(len(models), 0)
        model_ids = [m["id"] for m in models]
        self.assertIn("gpt-4o", model_ids)
        self.assertEqual(data["data"]["recommended_model_id"], "gpt-4o")

    def test_no_api_keys_appear_in_json_responses_or_logs(self):
        """Model discovery response for multi-providers never contains raw API key string."""
        self.client.force_login(self.user)
        secret_key = "super_secret_openai_test_key_xyz"
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "openai", "api_key": secret_key}),
            content_type="application/json",
        )
        response_text = response.content.decode("utf-8")
        self.assertNotIn(secret_key, response_text)

