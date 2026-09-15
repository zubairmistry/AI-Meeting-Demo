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


    def test_validate_model_access_without_api_key_returns_access_denied(self):
        """Model validation probe without API key returns ACCESS_DENIED."""
        prov = ClaudeProvider({"provider": "claude", "api_key": ""})
        result = prov.validate_model_access("claude-3-5-sonnet-20241022")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.ACCESS_DENIED)

    def test_validate_model_access_success(self):
        """Model validation probe with valid mock client returns AVAILABLE."""
        mock_client = MagicMock()
        self.provider.client = mock_client
        result = self.provider.validate_model_access("claude-3-5-sonnet-20241022")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.status, ModelStatus.AVAILABLE)
        mock_client.messages.create.assert_called_once_with(
            model="claude-3-5-sonnet-20241022",
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}]
        )

    def test_quick_preflight_check(self):
        """Quick preflight check calls validate_model_access with active model."""
        mock_client = MagicMock()
        self.provider.client = mock_client
        result = self.provider.quick_preflight_check()
        self.assertTrue(result.is_valid)
        self.assertEqual(result.status, ModelStatus.AVAILABLE)

    def test_filter_compatible_models_returns_text_generation_models(self):
        """filter_compatible_models retains models with TEXT_GENERATION capability."""
        m1 = ModelDescriptor(id="c1", display_name="C1", capabilities={ProviderCapability.TEXT_GENERATION})
        m2 = ModelDescriptor(id="c2", display_name="C2", capabilities={ProviderCapability.AUDIO_TRANSCRIPTION})
        res = self.provider.filter_compatible_models([m1, m2])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].id, "c1")

    def test_translate_error_various_status_codes(self):
        """translate_error normalizes 401, 403, 404, 429, 529, and NotImplementedError."""
        # 401 Auth
        e401 = Exception("401 Unauthorized: Invalid API Key")
        e401.status_code = 401
        r401 = self.provider.translate_error(e401)
        self.assertEqual(r401.status, ModelStatus.ACCESS_DENIED)

        # 403 Permission
        e403 = Exception("403 Forbidden: Permission denied")
        e403.status_code = 403
        r403 = self.provider.translate_error(e403)
        self.assertEqual(r403.status, ModelStatus.ACCESS_DENIED)

        # 404 Not Found
        e404 = Exception("404 Not Found")
        e404.status_code = 404
        r404 = self.provider.translate_error(e404)
        self.assertEqual(r404.status, ModelStatus.UNAVAILABLE)

        # 429 Quota
        e429_quota = Exception("429 Rate limit: credit balance is too low")
        e429_quota.status_code = 429
        r429_quota = self.provider.translate_error(e429_quota)
        self.assertEqual(r429_quota.status, ModelStatus.QUOTA_EXCEEDED)

        # 429 Rate limit
        e429 = Exception("429 Too Many Requests")
        e429.status_code = 429
        r429 = self.provider.translate_error(e429)
        self.assertEqual(r429.status, ModelStatus.RATE_LIMITED)

        # 529 Overloaded
        e529 = Exception("529 Overloaded")
        e529.status_code = 529
        r529 = self.provider.translate_error(e529)
        self.assertEqual(r529.status, ModelStatus.TEMPORARILY_UNAVAILABLE)

        # NotImplementedError
        e_ni = NotImplementedError("Anthropic Claude does not support audio transcription.")
        r_ni = self.provider.translate_error(e_ni)
        self.assertEqual(r_ni.status, ModelStatus.UNAVAILABLE)
        self.assertIn("does not support audio transcription", r_ni.message)

    def test_translate_error_redacts_api_key(self):
        """translate_error strips API key from error output to prevent secret leakage."""
        secret_key = "test_claude_api_key_123"
        e = Exception(f"Failed request with token {secret_key}")
        res = self.provider.translate_error(e)
        self.assertNotIn(secret_key, res.message)
        self.assertIn("[REDACTED]", res.message)

    def test_lazy_sdk_loading_missing_package_raises_runtime_error(self):
        """_ensure_client raises clean RuntimeError when anthropic cannot be imported."""
        prov = ClaudeProvider({"provider": "claude", "api_key": "test_key"})
        with patch.dict("sys.modules", {"anthropic": None}):
            with self.assertRaises(RuntimeError) as ctx:
                prov._ensure_client()
            self.assertIn("anthropic", str(ctx.exception).lower())


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

    def test_claude_discover_models_api(self):
        """AJAX endpoint discover-models returns Claude models with fallback catalog."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.discover_url,
            data=json.dumps({"provider": "claude", "api_key": "test_key_123"}),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        models = data["data"]["models"]
        self.assertTrue(len(models) >= 3)
        model_ids = [m["id"] for m in models]
        self.assertIn("claude-3-5-sonnet-20241022", model_ids)

    @patch("meeting.providers.claude_provider.ClaudeProvider._ensure_client")
    def test_claude_validate_model_api_capability_aware(self, mock_ensure):
        """AJAX endpoint validate-model performs capability-aware validation for Claude."""
        self.client.force_login(self.user)
        with patch("meeting.providers.claude_provider.ClaudeProvider.validate_model_access") as mock_val, \
             patch("meeting.providers.claude_provider.ClaudeProvider.generate_report") as mock_rep:
            mock_val.return_value = ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="OK")
            mock_rep.return_value = "Executive Summary: Q3 Roadmap."

            response = self.client.post(
                self.validate_url,
                data=json.dumps({
                    "provider": "claude",
                    "model_id": "claude-3-5-sonnet-20241022",
                    "api_key": "test_key_123"
                }),
                content_type="application/json"
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["data"]["status"], "AVAILABLE")
            self.assertEqual(data["data"]["stage"], "validation_success")

    def test_claude_meeting_pipeline_raw_audio_fails_with_clear_message(self):
        """Meeting pipeline refuses raw audio processing with Claude and updates status with clear message."""
        from meeting.models import Meeting
        from meeting.services.async_task_service import AsyncTaskService

        SettingsService.save_settings(
            user=self.user,
            provider="claude",
            api_key="test_key_123",
            model_name="claude-3-5-sonnet-20241022"
        )
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Claude Raw Audio Meeting",
            provider="claude",
            model_name="claude-3-5-sonnet-20241022",
            duration=0.0,
            file_size=1024,
            status="processing"
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, self.user)
        self.assertIsNotNone(task_id)

        # Run pipeline stepwise on raw audio file
        success = AsyncTaskService.run_pipeline_stepwise(meeting.id, task_id, "dummy_media.mp4")
        self.assertFalse(success)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "failed")
        self.assertIn("Anthropic Claude does not", meeting.error_message)

    def test_claude_meeting_pipeline_with_existing_transcript_succeeds(self):
        """Meeting pipeline succeeds with Claude when transcript already exists."""
        from meeting.models import Meeting
        from meeting.services.async_task_service import AsyncTaskService

        SettingsService.save_settings(
            user=self.user,
            provider="claude",
            api_key="test_key_123",
            model_name="claude-3-5-sonnet-20241022"
        )
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Claude Pre-transcribed Meeting",
            provider="claude",
            model_name="claude-3-5-sonnet-20241022",
            duration=15.0,
            file_size=1024,
            status="processing",
            transcript="Speaker 1: Reviewing quarterly goals and metrics."
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, self.user)
        self.assertIsNotNone(task_id)

        with patch("meeting.providers.claude_provider.ClaudeProvider.generate_report") as mock_report:
            mock_report.return_value = "Executive Summary: Review of quarterly goals and metrics."
            success = AsyncTaskService.run_pipeline_stepwise(meeting.id, task_id, "dummy_media.mp4")
            self.assertTrue(success)

            meeting.refresh_from_db()
            self.assertEqual(meeting.status, "completed")
            self.assertEqual(meeting.stage, "completed")
            self.assertIn("Executive Summary", meeting.ai_report)
