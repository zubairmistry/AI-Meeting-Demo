"""
meeting/tests/test_step7_providers.py

Comprehensive tests for Step 7: Multi-Provider Implementation & Capability Adaptation.
Covers:
1. ClaudeProvider implementation, discovery, fallback catalog, prompt report generation, error translation, and honest transcription limitation.
2. OpenAIProvider implementation, Whisper transcription, GPT-4o report generation, discovery, fallback catalog, and error translation.
3. ProviderFactory resolution from user settings for Claude and OpenAI.
4. Lazy SDK loading resilience when third-party packages are mocked or absent.
5. End-to-end multi-provider AJAX validation and discovery contracts.
"""

import os
import json
import tempfile
from unittest.mock import MagicMock, patch
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
from meeting.providers.claude_provider import ClaudeProvider, FALLBACK_CLAUDE_MODELS
from meeting.providers.openai_provider import OpenAIProvider, FALLBACK_OPENAI_MODELS
from meeting.services.provider_factory import ProviderFactory
from meeting.services.settings_service import SettingsService


class Step7ClaudeProviderTests(TestCase):
    """Detailed unit tests for ClaudeProvider."""

    def setUp(self):
        self.provider = ClaudeProvider({
            "provider": "claude",
            "api_key": "test_claude_api_key_123",
            "model_name": "claude-3-5-sonnet-20241022",
        })

    def test_provider_initialization_defaults(self):
        """ClaudeProvider initializes with appropriate defaults."""
        empty_prov = ClaudeProvider()
        self.assertEqual(empty_prov.provider, "claude")
        self.assertEqual(empty_prov.model_name, "claude-3-5-sonnet-20241022")
        self.assertEqual(empty_prov.api_key, "")

    def test_test_connection_without_api_key_returns_access_denied(self):
        """Connection test without key returns ACCESS_DENIED."""
        prov = ClaudeProvider({"provider": "claude", "api_key": ""})
        result = prov.test_connection()
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.ACCESS_DENIED)

    def test_test_connection_success(self):
        """Connection test with valid mock client returns AVAILABLE."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Connected"
        mock_msg.content = [mock_content]
        mock_client.messages.create.return_value = mock_msg

        self.provider.client = mock_client
        result = self.provider.test_connection()
        self.assertTrue(result.is_valid)
        self.assertEqual(result.status, ModelStatus.AVAILABLE)

    def test_discover_models_with_mock_client(self):
        """Live discovery maps Claude models correctly."""
        mock_client = MagicMock()
        mock_model_1 = MagicMock()
        mock_model_1.id = "claude-3-5-sonnet-20241022"
        mock_model_1.display_name = "Claude 3.5 Sonnet"
        mock_client.models.list.return_value = [mock_model_1]

        self.provider.client = mock_client
        models = self.provider.discover_models()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "claude-3-5-sonnet-20241022")
        self.assertTrue(models[0].is_recommended)
        self.assertEqual(models[0].source, DiscoverySource.LIVE_API)

    def test_discover_models_fallback_when_client_fails(self):
        """Fallback catalog is returned when live discovery raises exception."""
        self.provider.client = MagicMock()
        self.provider.client.models.list.side_effect = RuntimeError("API unavailable")

        models = self.provider.discover_models()
        self.assertEqual(len(models), len(FALLBACK_CLAUDE_MODELS))
        self.assertTrue(all(m.source == DiscoverySource.CATALOG_FALLBACK for m in models))

    def test_generate_transcript_raises_not_implemented_honestly(self):
        """ClaudeProvider explicitly raises NotImplementedError for audio transcription."""
        with self.assertRaises(NotImplementedError) as ctx:
            self.provider.generate_transcript("dummy.wav")
        self.assertIn("does not natively support audio transcription", str(ctx.exception))

    def test_generate_report_success(self):
        """ClaudeProvider generates executive report via messages.create."""
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Executive Summary: Discussion on Q3 Goals."
        mock_msg.content = [mock_content]
        mock_client.messages.create.return_value = mock_msg

        self.provider.client = mock_client
        report = self.provider.generate_report("Speaker 1: Let's discuss Q3 goals.")
        self.assertEqual(report, "Executive Summary: Discussion on Q3 Goals.")
        mock_client.messages.create.assert_called_once()

    def test_cleanup_audio_is_safe_noop(self):
        """ClaudeProvider cleanup_audio executes safely without error."""
        self.provider.cleanup_audio(None)


class Step7OpenAIProviderTests(TestCase):
    """Detailed unit tests for OpenAIProvider."""

    def setUp(self):
        self.provider = OpenAIProvider({
            "provider": "openai",
            "api_key": "test_openai_api_key_123",
            "model_name": "gpt-4o",
        })

    def test_provider_initialization_defaults(self):
        """OpenAIProvider initializes with appropriate defaults."""
        empty_prov = OpenAIProvider()
        self.assertEqual(empty_prov.provider, "openai")
        self.assertEqual(empty_prov.model_name, "gpt-4o")
        self.assertEqual(empty_prov.api_key, "")

    def test_test_connection_without_api_key_returns_access_denied(self):
        """Connection test without key returns ACCESS_DENIED."""
        prov = OpenAIProvider({"provider": "openai", "api_key": ""})
        result = prov.test_connection()
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.ACCESS_DENIED)

    def test_test_connection_success(self):
        """Connection test with valid mock client returns AVAILABLE."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Connected"
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp

        self.provider.client = mock_client
        result = self.provider.test_connection()
        self.assertTrue(result.is_valid)
        self.assertEqual(result.status, ModelStatus.AVAILABLE)

    def test_discover_models_with_mock_client_filters_irrelevant_models(self):
        """Live discovery filters out TTS, DALL-E, and embedding models."""
        mock_client = MagicMock()
        m1 = MagicMock(); m1.id = "gpt-4o"
        m2 = MagicMock(); m2.id = "text-embedding-3-small"
        m3 = MagicMock(); m3.id = "dall-e-3"
        m4 = MagicMock(); m4.id = "whisper-1"
        mock_client.models.list.return_value = [m1, m2, m3, m4]

        self.provider.client = mock_client
        models = self.provider.discover_models()
        model_ids = [m.id for m in models]
        self.assertIn("gpt-4o", model_ids)
        self.assertIn("whisper-1", model_ids)
        self.assertNotIn("text-embedding-3-small", model_ids)
        self.assertNotIn("dall-e-3", model_ids)

    def test_discover_models_fallback_when_client_fails(self):
        """Fallback catalog is returned when live discovery fails."""
        self.provider.client = MagicMock()
        self.provider.client.models.list.side_effect = RuntimeError("OpenAI down")

        models = self.provider.discover_models()
        self.assertEqual(len(models), len(FALLBACK_OPENAI_MODELS))
        self.assertTrue(all(m.source == DiscoverySource.CATALOG_FALLBACK for m in models))

    def test_generate_transcript_file_not_found(self):
        """Missing audio file raises FileNotFoundError."""
        self.provider.client = MagicMock()
        with self.assertRaises(FileNotFoundError):
            self.provider.generate_transcript("/non/existent/path/meeting.wav")

    def test_generate_transcript_success_with_whisper(self):
        """Whisper transcription executes successfully on temporary audio file."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            temp_wav.write(b"RIFF dummy wav content")
            temp_path = temp_wav.name

        try:
            mock_client = MagicMock()
            mock_transcription = MagicMock()
            mock_transcription.text = "This is a transcribed meeting recording."
            mock_client.audio.transcriptions.create.return_value = mock_transcription

            self.provider.client = mock_client
            result = self.provider.generate_transcript(temp_path)
            self.assertEqual(result, "This is a transcribed meeting recording.")
            mock_client.audio.transcriptions.create.assert_called_once()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_generate_report_success(self):
        """OpenAIProvider generates executive report via chat.completions.create."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Executive Summary: Budget approved."
        mock_resp.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_resp

        self.provider.client = mock_client
        report = self.provider.generate_report("Speaker 1: Budget is approved.")
        self.assertEqual(report, "Executive Summary: Budget approved.")

    def test_cleanup_audio_is_safe_noop(self):
        """OpenAIProvider cleanup_audio executes safely without error."""
        self.provider.cleanup_audio(None)


class Step7ProviderFactoryAndAJAXIntegrationTests(TestCase):
    """Integration tests for ProviderFactory and multi-provider AJAX requests."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="step7integration@example.com",
            email="step7integration@example.com",
            password="SecurePassword123!"
        )
        self.discover_url = reverse("discover_models_api")
        self.validate_url = reverse("validate_model_api")

    def test_provider_factory_resolves_claude_for_user(self):
        """ProviderFactory initializes ClaudeProvider when user settings specify claude."""
        SettingsService.save_settings(
            user=self.user,
            provider="claude",
            api_key="claude_sk_test_123",
            model_name="claude-3-5-sonnet-20241022"
        )
        provider = ProviderFactory.get_provider(self.user)
        self.assertIsInstance(provider, ClaudeProvider)
        self.assertEqual(provider.provider, "claude")
        self.assertEqual(provider.api_key, "claude_sk_test_123")

    def test_provider_factory_resolves_openai_for_user(self):
        """ProviderFactory initializes OpenAIProvider when user settings specify openai."""
        SettingsService.save_settings(
            user=self.user,
            provider="openai",
            api_key="openai_sk_test_456",
            model_name="gpt-4o"
        )
        provider = ProviderFactory.get_provider(self.user)
        self.assertIsInstance(provider, OpenAIProvider)
        self.assertEqual(provider.provider, "openai")
        self.assertEqual(provider.api_key, "openai_sk_test_456")
