import datetime
import io
import json
import tempfile
import uuid
from unittest.mock import patch, MagicMock

from django.utils import timezone
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from meeting.models import Meeting, AISettings
from meeting.services.settings_service import SettingsService
from meeting.services.async_task_service import AsyncTaskService, TaskHeartbeat
from meeting.providers.base_provider import ValidationResult, ModelStatus


class AsyncAnalyzeApiTests(TestCase):
    """
    Test suite for Step 3:
    - POST /meeting/analyze/ (Async initiation returning HTTP 202)
    - GET /meeting/status/<meeting_id>/ (Polling status endpoint)
    - Progress mapping and tenant isolation
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="analyst@example.com",
            email="analyst@example.com",
            password="password123",
        )
        self.other_user = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="password123",
        )

        # Configure AI Settings for self.user
        SettingsService.save_settings(
            user=self.user,
            provider="gemini",
            api_key="AIzaSyDummyTestKeyValidFormat12345",
            model_name="gemini-2.5-flash",
        )

    def tearDown(self):
        # Clean up any active in-memory tasks
        for m in Meeting.objects.all():
            AsyncTaskService.unregister_active_task(m.id)

    def test_analyze_api_requires_authentication(self):
        """
        Unauthenticated POST /meeting/analyze/ must redirect to login.
        """
        url = reverse("analyze_meeting_api")
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 302)
        self.assertTrue("/login" in response.url)

    def test_analyze_api_missing_file(self):
        """
        Authenticated POST without meeting_file returns 400 MISSING_FILE.
        """
        self.client.login(username="analyst@example.com", password="password123")
        url = reverse("analyze_meeting_api")
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "MISSING_FILE")

    def test_analyze_api_missing_api_key(self):
        """
        User without configured API key receives 400 NO_API_KEY.
        """
        self.client.login(username="other@example.com", password="password123")
        fake_file = SimpleUploadedFile("meeting.mp4", b"dummy video content", content_type="video/mp4")
        url = reverse("analyze_meeting_api")
        response = self.client.post(url, {"meeting_file": fake_file})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "NO_API_KEY")

    def test_analyze_api_invalid_file_extension(self):
        """
        Uploading unsupported file extension returns 400 INVALID_FILE_TYPE.
        """
        self.client.login(username="analyst@example.com", password="password123")
        fake_file = SimpleUploadedFile("script.sh", b"echo hello", content_type="text/plain")
        url = reverse("analyze_meeting_api")
        response = self.client.post(url, {"meeting_file": fake_file})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "INVALID_FILE_TYPE")

    def test_analyze_api_file_too_large(self):
        """
        Uploading a file exceeding demo limit returns 400 FILE_TOO_LARGE.
        """
        self.client.login(username="analyst@example.com", password="password123")
        fake_file = SimpleUploadedFile("huge_meeting.mp4", b"x" * 2048, content_type="video/mp4")

        with override_settings(MAX_UPLOAD_SIZE=500):
            url = reverse("analyze_meeting_api")
            response = self.client.post(url, {"meeting_file": fake_file})
            self.assertEqual(response.status_code, 400)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertEqual(data["error"]["code"], "FILE_TOO_LARGE")

    @patch("meeting.services.model_validation_service.ModelValidationService.preflight_check")
    def test_analyze_api_preflight_failure(self, mock_preflight):
        """
        If preflight check fails (e.g. invalid credentials), returns 400 with preflight status.
        """
        mock_preflight.return_value = ValidationResult(
            is_valid=False,
            status=ModelStatus.ACCESS_DENIED,
            message="Invalid API Key credentials",
            model_id="gemini-2.5-flash",
        )
        self.client.login(username="analyst@example.com", password="password123")
        fake_file = SimpleUploadedFile("clip.mp4", b"dummy media bytes", content_type="video/mp4")

        url = reverse("analyze_meeting_api")
        response = self.client.post(url, {"meeting_file": fake_file})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], ModelStatus.ACCESS_DENIED.value)

    @patch("meeting.services.async_task_service.AsyncTaskService.get_executor")
    @patch("meeting.services.model_validation_service.ModelValidationService.preflight_check")
    def test_analyze_api_success_returns_202_and_dispatches_task(self, mock_preflight, mock_get_executor):
        """
        Valid upload returns HTTP 202 Accepted, creates Meeting record, and submits background task.
        """
        mock_preflight.return_value = ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message="Model accessible",
            model_id="gemini-2.5-flash",
        )
        mock_executor = MagicMock()
        mock_get_executor.return_value = mock_executor

        self.client.login(username="analyst@example.com", password="password123")
        fake_file = SimpleUploadedFile("demo_meeting.mp4", b"dummy media content", content_type="video/mp4")

        url = reverse("analyze_meeting_api")
        response = self.client.post(url, {"meeting_file": fake_file})
        self.assertEqual(response.status_code, 202)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("meeting_id", data["data"])
        self.assertIn("task_id", data["data"])
        self.assertEqual(data["data"]["status"], "processing")
        self.assertEqual(data["data"]["stage"], "queued")

        meeting = Meeting.objects.get(id=data["data"]["meeting_id"])
        self.assertEqual(meeting.user, self.user)
        self.assertEqual(meeting.status, "processing")
        self.assertEqual(meeting.stage, "queued")
        self.assertEqual(meeting.task_id, data["data"]["task_id"])

        # Verify task was dispatched to ThreadPoolExecutor
        mock_executor.submit.assert_called_once()
        args, kwargs = mock_executor.submit.call_args
        self.assertEqual(args[0], AsyncTaskService.run_pipeline_stepwise)
        self.assertEqual(args[1], meeting.id)
        self.assertEqual(args[2], data["data"]["task_id"])

    def test_status_api_requires_authentication(self):
        """
        Unauthenticated GET /meeting/status/<id>/ redirects to login.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Status Test",
            original_file="status.mp4",
            duration=0.0,
            file_size=1024,
            status="processing",
            stage="queued",
        )
        url = reverse("meeting_status_api", kwargs={"meeting_id": meeting.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue("/login" in response.url)

    def test_status_api_tenant_isolation_404(self):
        """
        User B cannot access status of User A's meeting -> 404 Not Found.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="User A Meeting",
            original_file="user_a.mp4",
            duration=0.0,
            file_size=1024,
            status="processing",
            stage="queued",
        )
        self.client.login(username="other@example.com", password="password123")
        url = reverse("meeting_status_api", kwargs={"meeting_id": meeting.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_status_api_progress_mapping_and_payload(self):
        """
        Verifies progress percentage across granular stages and completed/failed states.
        """
        self.client.login(username="analyst@example.com", password="password123")

        stages_and_expected_progress = [
            ("queued", 10),
            ("extracting_audio", 25),
            ("uploading_to_ai", 40),
            ("waiting_for_ai", 55),
            ("transcribing", 70),
            ("generating_summary", 85),
        ]

        for stage_name, expected_pct in stages_and_expected_progress:
            meeting = Meeting.objects.create(
                user=self.user,
                meeting_name=f"Meeting {stage_name}",
                original_file=f"{stage_name}.mp4",
                status="processing",
                stage=stage_name,
                duration=45.0,
                file_size=1024,
            )
            url = reverse("meeting_status_api", kwargs={"meeting_id": meeting.id})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["data"]["stage"], stage_name)
            self.assertEqual(data["data"]["progress_percentage"], expected_pct)
            self.assertEqual(data["data"]["duration"], 45.0)
            self.assertFalse(data["data"]["has_transcript"])
            self.assertFalse(data["data"]["has_ai_report"])

        # Completed meeting
        completed_meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Completed Meeting",
            original_file="comp.mp4",
            status="completed",
            stage="completed",
            duration=60.0,
            file_size=1024,
            transcript="Hello world meeting transcript.",
            ai_report="### Summary\n- Topic A",
        )
        url = reverse("meeting_status_api", kwargs={"meeting_id": completed_meeting.id})
        response = self.client.get(url)
        data = response.json()
        self.assertEqual(data["data"]["progress_percentage"], 100)
        self.assertTrue(data["data"]["has_transcript"])
        self.assertEqual(data["data"]["transcript"], "Hello world meeting transcript.")
        self.assertTrue(data["data"]["has_ai_report"])
        self.assertEqual(data["data"]["ai_report"], "### Summary\n- Topic A")

        # Failed meeting
        failed_meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Failed Meeting",
            original_file="fail.mp4",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
            error_message="Audio decoding failed.",
        )
        url = reverse("meeting_status_api", kwargs={"meeting_id": failed_meeting.id})
        response = self.client.get(url)
        data = response.json()
        self.assertEqual(data["data"]["progress_percentage"], 0)
        self.assertEqual(data["data"]["error_message"], "Audio decoding failed.")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    def test_pipeline_failure_records_translated_error_and_cleans_up(self, mock_audio_info, mock_extract, mock_get_provider):
        """
        When background pipeline fails, error message is translated and recorded, status is failed,
        and remote asset is cleaned up.
        """
        mock_extract.return_value = "dummy.mp3"
        mock_audio_info.return_value = {"duration_seconds": 12.0}

        mock_provider = MagicMock()
        mock_gemini_file = MagicMock()
        mock_gemini_file.name = "files/test_temp_audio"
        mock_provider.upload_audio.return_value = mock_gemini_file
        mock_provider.wait_until_ready.return_value = mock_gemini_file
        mock_provider.generate_transcript.side_effect = RuntimeError("Quota exhausted on remote server")
        mock_provider.translate_error.return_value = ValidationResult(
            is_valid=False,
            status=ModelStatus.QUOTA_EXCEEDED,
            message="AI account quota exhausted. Please check billing or use another key.",
            model_id="gemini-2.5-flash",
        )
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Fail Pipeline Test",
            original_file="pipeline_test.mp4",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)
        self.assertIsNotNone(task_id)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_path.mp4",
        )
        self.assertFalse(success)

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "failed")
        self.assertEqual(refreshed.stage, "failed")
        self.assertEqual(refreshed.error_message, "AI account quota exhausted. Please check billing or use another key.")
        self.assertFalse(AsyncTaskService.is_task_active(meeting.id))
        mock_provider.cleanup_audio.assert_not_called()


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class RuntimeModelFallbackPipelineTests(TestCase):
    """
    Automated test suite for P0.2:
    - Runtime Gemini model fallback during meeting processing
    - Single audio extraction (FFmpeg) guarantee
    - Single Gemini upload guarantee (reusing gemini_file_obj across fallback models)
    - Transient vs non-transient error filtering
    - Claude raw-media transcription guard
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="fallback_tester@example.com",
            email="fallback_tester@example.com",
            password="password123",
        )
        SettingsService.save_settings(
            user=self.user,
            provider="gemini",
            api_key="AIzaSyDummyTestKeyValidFormat12345",
            model_name="gemini-2.5-flash-lite",
        )
        # Mock safe_sleep globally for fast test runs
        self.sleep_patcher = patch.object(AsyncTaskService, "safe_sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def tearDown(self):
        self.sleep_patcher.stop()
        for m in Meeting.objects.all():
            AsyncTaskService.unregister_active_task(m.id)

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_selected_model_succeeds_without_fallback(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider
    ):
        """When selected model operates normally, pipeline completes with 1 extraction and 1 upload."""
        mock_extract.return_value = "extracted_audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 60.0}
        mock_save_transcript.return_value = "transcript_file.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/gemini_audio_123"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.wait_until_ready.return_value = mock_file_obj
        mock_provider.generate_transcript.return_value = "This is the complete meeting transcript."
        mock_provider.generate_report.return_value = "## Summary\n- Key decision made."
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Normal Meeting",
            original_file="dummy_meeting.mp4",
            model_name="gemini-2.5-flash-lite",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=2048,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_meeting.mp4",
        )
        self.assertTrue(success)

        # Verify single audio extraction and upload
        mock_extract.assert_called_once_with("dummy_meeting.mp4")
        mock_provider.upload_audio.assert_called_once_with("extracted_audio.mp3")
        mock_provider.generate_transcript.assert_called_once_with(mock_file_obj)
        mock_provider.generate_report.assert_called_once_with("This is the complete meeting transcript.")
        mock_provider.cleanup_audio.assert_called_once_with(mock_file_obj)

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.stage, "completed")
        self.assertEqual(refreshed.model_name, "gemini-2.5-flash-lite")
        self.assertEqual(refreshed.transcript, "This is the complete meeting transcript.")
        self.assertEqual(refreshed.ai_report, "## Summary\n- Key decision made.")

    @patch("meeting.services.async_task_service.ModelDiscoveryService.discover_and_filter")
    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_transcription_high_demand_fallback_reuses_gemini_file(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider, mock_discover
    ):
        """
        When primary model encounters 503 high demand (2 attempts), pipeline falls back to
        gemini-2.5-flash and REUSES the same uploaded gemini_file_obj without re-extracting or re-uploading.
        """
        mock_extract.return_value = "extracted_audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 90.0}
        mock_save_transcript.return_value = "transcript_file.txt"

        # Mock discovery returning fallback models
        mock_discover.return_value = [
            MagicMock(id="gemini-2.5-flash"),
            MagicMock(id="gemini-1.5-flash"),
        ]

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/gemini_audio_reuse_test"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.wait_until_ready.return_value = mock_file_obj

        # Primary model gemini-2.5-flash-lite fails with 503 High Demand (2 attempts)
        # Fallback model gemini-2.5-flash succeeds on 1st attempt
        def side_effect_transcript(file_ref):
            if mock_provider.model_name == "gemini-2.5-flash-lite":
                raise RuntimeError("503 Model 'gemini-2.5-flash-lite' is currently experiencing high demand.")
            elif mock_provider.model_name == "gemini-2.5-flash":
                return "Transcript generated by fallback gemini-2.5-flash."
            raise RuntimeError("Unexpected model")

        mock_provider.generate_transcript.side_effect = side_effect_transcript
        mock_provider.generate_report.return_value = "## Report by fallback model."
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="High Demand Fallback Meeting",
            original_file="dummy_meeting.mp4",
            model_name="gemini-2.5-flash-lite",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=2048,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_meeting.mp4",
        )
        self.assertTrue(success)

        # STRICT ASSERTIONS:
        # 1. extract_audio was called EXACTLY ONCE
        mock_extract.assert_called_once_with("dummy_meeting.mp4")

        # 2. upload_audio was called EXACTLY ONCE
        mock_provider.upload_audio.assert_called_once_with("extracted_audio.mp3")

        # 3. generate_transcript was called 3 times total (2 for primary model, 1 for fallback), all with mock_file_obj
        self.assertEqual(mock_provider.generate_transcript.call_count, 3)
        for call_args in mock_provider.generate_transcript.call_args_list:
            self.assertEqual(call_args[0][0], mock_file_obj)

        # 4. safe_sleep was called once between the 2 primary attempts
        self.assertEqual(self.mock_sleep.call_count, 1)

        # 5. Remote cleanup was called exactly once with mock_file_obj
        mock_provider.cleanup_audio.assert_called_once_with(mock_file_obj)

        # 6. Database record reflects the fallback model used and successful completion
        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.stage, "completed")
        self.assertEqual(refreshed.model_name, "gemini-2.5-flash")
        self.assertEqual(refreshed.transcript, "Transcript generated by fallback gemini-2.5-flash.")
        self.assertEqual(refreshed.ai_report, "## Report by fallback model.")

    @patch("meeting.services.async_task_service.ModelDiscoveryService.discover_and_filter")
    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    def test_non_transient_auth_error_stops_immediately_without_fallback(
        self, mock_audio_info, mock_extract, mock_get_provider, mock_discover
    ):
        """When an unauthenticated/invalid key error occurs, no fallback is attempted."""
        mock_extract.return_value = "extracted_audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 30.0}

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/gemini_audio_auth_test"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.wait_until_ready.return_value = mock_file_obj
        mock_provider.generate_transcript.side_effect = RuntimeError("401 Unauthenticated: API_KEY_INVALID")
        mock_provider.translate_error.return_value = ValidationResult(
            is_valid=False,
            status=ModelStatus.ACCESS_DENIED,
            message="Invalid API key.",
            model_id="gemini-2.5-flash-lite",
        )
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Auth Error Meeting",
            original_file="meeting.mp4",
            model_name="gemini-2.5-flash-lite",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_meeting.mp4",
        )
        self.assertFalse(success)

        # generate_transcript called exactly once (no retries, no fallback models)
        mock_provider.generate_transcript.assert_called_once()
        self.mock_sleep.assert_not_called()
        mock_provider.cleanup_audio.assert_not_called()

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "failed")
        self.assertEqual(refreshed.stage, "failed")
        self.assertEqual(refreshed.error_message, "Invalid API key.")

    @patch("meeting.services.async_task_service.ModelDiscoveryService.discover_and_filter")
    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_report_generation_high_demand_fallback_succeeds(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider, mock_discover
    ):
        """When transcript succeeds on primary model, but report generation hits 503, fallback generates report."""
        mock_extract.return_value = "extracted_audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 45.0}
        mock_save_transcript.return_value = "transcript_file.txt"

        mock_discover.return_value = [
            MagicMock(id="gemini-2.5-flash"),
        ]

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/gemini_audio_report_fallback"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.wait_until_ready.return_value = mock_file_obj
        mock_provider.generate_transcript.return_value = "Meeting discussion text."

        def side_effect_report(transcript):
            if mock_provider.model_name == "gemini-2.5-flash-lite":
                raise RuntimeError("503 Temporarily Unavailable: High demand on gemini-2.5-flash-lite")
            elif mock_provider.model_name == "gemini-2.5-flash":
                return "## Summary generated by fallback model"
            raise RuntimeError("Unknown model")

        mock_provider.generate_report.side_effect = side_effect_report
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Report Fallback Meeting",
            original_file="meeting.mp4",
            model_name="gemini-2.5-flash-lite",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_meeting.mp4",
        )
        self.assertTrue(success)

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.model_name, "gemini-2.5-flash")
        self.assertEqual(refreshed.ai_report, "## Summary generated by fallback model")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    def test_claude_provider_raw_media_guard_halts_before_extraction(
        self, mock_extract, mock_get_provider
    ):
        """When user selects Claude and attempts raw media processing, guard aborts before audio extraction."""
        mock_provider = MagicMock()
        mock_provider.provider = "claude"
        mock_provider.model_name = "claude-3-7-sonnet-20250219"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Claude Raw Media Test",
            original_file="claude_test.mp4",
            model_name="claude-3-7-sonnet-20250219",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_meeting.mp4",
        )
        self.assertFalse(success)

        # Audio extraction was never called
        mock_extract.assert_not_called()

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "failed")
        self.assertEqual(refreshed.stage, "failed")
        self.assertIn("Anthropic Claude does not natively support audio transcription", refreshed.error_message)

    @patch("meeting.services.async_task_service.ModelDiscoveryService.discover_and_filter")
    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    def test_all_candidates_fail_transiently_results_in_clean_failure(
        self, mock_audio_info, mock_extract, mock_get_provider, mock_discover
    ):
        """When all candidate models fail with 503 high demand, pipeline marks meeting as failed cleanly."""
        mock_extract.return_value = "extracted_audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 30.0}

        mock_discover.return_value = [
            MagicMock(id="gemini-2.5-flash"),
            MagicMock(id="gemini-1.5-flash"),
        ]

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/gemini_audio_all_fail"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.wait_until_ready.return_value = mock_file_obj
        mock_provider.generate_transcript.side_effect = RuntimeError("503 Service Unavailable: High Demand")
        mock_provider.translate_error.return_value = ValidationResult(
            is_valid=False,
            status=ModelStatus.TEMPORARILY_UNAVAILABLE,
            message="Model is currently experiencing high demand. Please try again shortly.",
            model_id="gemini-1.5-flash",
        )
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="All Candidates Fail Meeting",
            original_file="meeting.mp4",
            model_name="gemini-2.5-flash-lite",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="dummy_meeting.mp4",
        )
        self.assertFalse(success)

        # Primary had 2 attempts, fallback 1 had 1 attempt, fallback 2 had 1 attempt = 4 attempts total
        self.assertEqual(mock_provider.generate_transcript.call_count, 4)
        mock_provider.cleanup_audio.assert_not_called()

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "failed")
        self.assertEqual(refreshed.stage, "failed")
        self.assertEqual(refreshed.error_message, "Model is currently experiencing high demand. Please try again shortly.")


class CheckpointAwareResumePipelineTests(TestCase):
    """
    Automated test suite for P0.3:
    - Checkpoint-aware pipeline resumption
    - Audio extraction reuse (skipping FFmpeg)
    - Gemini remote file reuse (skipping upload & indexing)
    - Transcript checkpoint reuse (skipping transcription)
    - Report checkpoint reuse & idempotency
    - Recovery when artifacts/references are missing or invalid
    - Combined P0.2 fallback + P0.3 checkpoint resume integration
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="checkpoint_tester@example.com",
            email="checkpoint_tester@example.com",
            password="password123",
        )
        SettingsService.save_settings(
            user=self.user,
            provider="gemini",
            api_key="AIzaSyDummyTestKeyValidFormat12345",
            model_name="gemini-2.5-flash-lite",
        )
        self.sleep_patcher = patch.object(AsyncTaskService, "safe_sleep")
        self.mock_sleep = self.sleep_patcher.start()

    def tearDown(self):
        self.sleep_patcher.stop()
        for m in Meeting.objects.all():
            AsyncTaskService.unregister_active_task(m.id)

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_fresh_meeting_executes_all_pipeline_stages(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider
    ):
        """A fresh meeting with no existing checkpoints runs all 5 stages in sequence."""
        mock_extract.return_value = "fresh_audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 40.0}
        mock_save_transcript.return_value = "fresh_transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/fresh_gemini_file"
        mock_file_obj.state.name = "ACTIVE"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.wait_until_ready.return_value = mock_file_obj
        mock_provider.generate_transcript.return_value = "Fresh meeting transcript."
        mock_provider.generate_report.return_value = "## Fresh Report"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Fresh Meeting",
            original_file="fresh.mp4",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="fresh_video.mp4",
        )
        self.assertTrue(success)

        # All stages executed
        mock_extract.assert_called_once_with("fresh_video.mp4")
        mock_provider.upload_audio.assert_called_once_with("fresh_audio.mp3")
        mock_provider.generate_transcript.assert_called_once_with(mock_file_obj)
        mock_provider.generate_report.assert_called_once_with("Fresh meeting transcript.")
        mock_provider.cleanup_audio.assert_called_once_with(mock_file_obj)

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.stage, "completed")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_audio_path")
    def test_resume_with_existing_audio_file_skips_ffmpeg_extraction(
        self, mock_get_audio_path, mock_save_transcript, mock_extract, mock_get_provider
    ):
        """When a valid extracted audio file already exists, FFmpeg audio extraction is skipped."""
        mock_get_audio_path.return_value = "/mock/existing/audio.mp3"
        mock_save_transcript.return_value = "transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/resumed_gemini_file"
        mock_file_obj.state.name = "ACTIVE"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.generate_transcript.return_value = "Resumed audio transcript."
        mock_provider.generate_report.return_value = "## Resumed Report"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Resume Audio Test",
            original_file="meeting.mp4",
            audio_file="audio.mp3",
            duration=30.0,
            status="processing",
            stage="extracting_audio",
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(success)

        # Audio extraction was SKIPPED
        mock_extract.assert_not_called()
        # Upload called with existing audio
        mock_provider.upload_audio.assert_called_once_with("/mock/existing/audio.mp3")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_audio_path")
    def test_resume_with_invalid_or_missing_audio_artifact_re_extracts(
        self, mock_get_audio_path, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider
    ):
        """When get_existing_audio_path returns None (e.g. corrupt or missing), FFmpeg is safely re-executed."""
        mock_get_audio_path.return_value = None
        mock_extract.return_value = "newly_extracted.mp3"
        mock_audio_info.return_value = {"duration_seconds": 25.0}
        mock_save_transcript.return_value = "transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file_obj = MagicMock()
        mock_file_obj.name = "files/new_gemini_file"
        mock_file_obj.state.name = "ACTIVE"
        mock_provider.upload_audio.return_value = mock_file_obj
        mock_provider.generate_transcript.return_value = "Transcript text."
        mock_provider.generate_report.return_value = "## Report"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Missing Audio Test",
            original_file="missing.mp4",
            audio_file="corrupt.mp3",
            status="processing",
            stage="extracting_audio",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="missing.mp4",
        )
        self.assertTrue(success)

        # Extraction re-run
        mock_extract.assert_called_once_with("missing.mp4")
        mock_provider.upload_audio.assert_called_once_with("newly_extracted.mp3")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_resume_with_active_gemini_file_skips_extraction_upload_and_wait(
        self, mock_save_transcript, mock_extract, mock_get_provider
    ):
        """When an ACTIVE remote Gemini file exists, extraction, upload, and wait_until_ready are all skipped."""
        mock_save_transcript.return_value = "transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_active_file = MagicMock()
        mock_active_file.name = "files/active_already_indexed"
        mock_active_file.state.name = "ACTIVE"
        mock_provider.get_file.return_value = mock_active_file
        mock_provider.generate_transcript.return_value = "Transcribed directly from existing remote file."
        mock_provider.generate_report.return_value = "## Executive Summary"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Active Gemini File Test",
            original_file="meeting.mp4",
            gemini_file_name="files/active_already_indexed",
            status="processing",
            stage="transcribing",
            duration=30.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(success)

        # SKIPPED: extraction, upload, wait_until_ready
        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.wait_until_ready.assert_not_called()

        # Direct transcription and report
        mock_provider.get_file.assert_called_once_with("files/active_already_indexed")
        mock_provider.generate_transcript.assert_called_once_with(mock_active_file)
        mock_provider.generate_report.assert_called_once_with("Transcribed directly from existing remote file.")
        mock_provider.cleanup_audio.assert_called_once_with(mock_active_file)

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_resume_with_processing_gemini_file_waits_for_ready_and_skips_upload(
        self, mock_save_transcript, mock_extract, mock_get_provider
    ):
        """When remote Gemini file is in PROCESSING state, upload is skipped and wait_until_ready is called."""
        mock_save_transcript.return_value = "transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_proc_file = MagicMock()
        mock_proc_file.name = "files/processing_remote_file"
        mock_proc_file.state.name = "PROCESSING"
        mock_ready_file = MagicMock()
        mock_ready_file.name = "files/processing_remote_file"
        mock_ready_file.state.name = "ACTIVE"
        mock_provider.get_file.return_value = mock_proc_file
        mock_provider.wait_until_ready.return_value = mock_ready_file
        mock_provider.generate_transcript.return_value = "Transcript after indexing ready."
        mock_provider.generate_report.return_value = "## Report"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Processing Gemini File Test",
            original_file="meeting.mp4",
            gemini_file_name="files/processing_remote_file",
            status="processing",
            stage="waiting_for_ai",
            duration=30.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(success)

        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.wait_until_ready.assert_called_once_with(mock_proc_file)
        mock_provider.generate_transcript.assert_called_once_with(mock_ready_file)

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_resume_with_stale_or_missing_gemini_file_recovers_by_uploading(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider
    ):
        """When stored gemini_file_name cannot be retrieved (returns None), pipeline recovers by uploading."""
        mock_extract.return_value = "extracted.mp3"
        mock_audio_info.return_value = {"duration_seconds": 20.0}
        mock_save_transcript.return_value = "transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_provider.get_file.return_value = None  # Stale / expired file
        mock_new_file = MagicMock()
        mock_new_file.name = "files/newly_uploaded_file"
        mock_new_file.state.name = "ACTIVE"
        mock_provider.upload_audio.return_value = mock_new_file
        mock_provider.generate_transcript.return_value = "Transcript after fresh upload."
        mock_provider.generate_report.return_value = "## Report"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Stale Gemini File Test",
            original_file="meeting.mp4",
            gemini_file_name="files/expired_stale_file_123",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(success)

        mock_provider.get_file.assert_called_once_with("files/expired_stale_file_123")
        mock_provider.upload_audio.assert_called_once()
        mock_provider.generate_transcript.assert_called_once_with(mock_new_file)

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    def test_resume_with_existing_transcript_skips_extraction_upload_and_transcription(
        self, mock_extract, mock_get_provider
    ):
        """When a valid transcript is already saved, extraction, upload, and transcription are all SKIPPED."""
        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_provider.generate_report.return_value = "## Generated Summary Report from Existing Transcript"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Resume Transcript Checkpoint Test",
            original_file="meeting.mp4",
            transcript="Already completed meeting transcript from earlier run.",
            transcript_file="meeting.txt",
            status="processing",
            stage="generating_summary",
            duration=120.0,
            file_size=2048,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(success)

        # STRICT ASSERTIONS: Zero audio extraction, zero upload, zero transcription
        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.wait_until_ready.assert_not_called()
        mock_provider.generate_transcript.assert_not_called()

        # Only generate_report was executed
        mock_provider.generate_report.assert_called_once_with("Already completed meeting transcript from earlier run.")

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.stage, "completed")
        self.assertEqual(refreshed.ai_report, "## Generated Summary Report from Existing Transcript")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    def test_resume_with_existing_report_and_transcript_is_idempotent_noop(
        self, mock_extract, mock_get_provider
    ):
        """When both transcript and ai_report exist, pipeline is an immediate idempotent no-op."""
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Fully Completed Meeting",
            original_file="done.mp4",
            transcript="Existing transcript.",
            ai_report="## Existing Report.",
            status="completed",
            stage="completed",
            duration=60.0,
            file_size=1024,
        )
        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="done.mp4",
        )
        self.assertTrue(success)

        # Zero provider calls
        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.generate_transcript.assert_not_called()
        mock_provider.generate_report.assert_not_called()

        refreshed = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.stage, "completed")

    @patch("meeting.services.async_task_service.ModelDiscoveryService.discover_and_filter")
    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_p02_fallback_combined_with_checkpoint_resume(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider, mock_discover
    ):
        """
        Integration test:
        1. Run 1: Primary transcription model fails $\rightarrow$ P0.2 fallback succeeds $\rightarrow$ transcript saved $\rightarrow$ report fails.
        2. Run 2: Resume starts directly at report stage $\rightarrow$ report succeeds $\rightarrow$ ZERO re-extraction or re-upload.
        """
        mock_extract.return_value = "audio.mp3"
        mock_audio_info.return_value = {"duration_seconds": 60.0}
        mock_save_transcript.return_value = "transcript.txt"

        mock_discover.return_value = [
            MagicMock(id="gemini-2.5-flash"),
        ]

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file = MagicMock()
        mock_file.name = "files/combined_gemini_file"
        mock_file.state.name = "ACTIVE"
        mock_provider.upload_audio.return_value = mock_file
        mock_provider.wait_until_ready.return_value = mock_file

        # Run 1: Transcription falls back to gemini-2.5-flash, but report fails
        def side_effect_transcript(file_ref):
            if mock_provider.model_name == "gemini-2.5-flash-lite":
                raise RuntimeError("503 High demand on gemini-2.5-flash-lite")
            elif mock_provider.model_name == "gemini-2.5-flash":
                return "Transcript generated by fallback."
            raise RuntimeError("Unknown model")

        mock_provider.generate_transcript.side_effect = side_effect_transcript
        mock_provider.generate_report.side_effect = RuntimeError("503 Report generation service overloaded")
        mock_provider.translate_error.return_value = ValidationResult(
            is_valid=False,
            status=ModelStatus.TEMPORARILY_UNAVAILABLE,
            message="Overloaded",
            model_id="gemini-2.5-flash",
        )
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Combined Fallback and Resume Meeting",
            original_file="meeting.mp4",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_1 = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        # Run 1 execution
        run_1_success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_1,
            media_filepath="meeting.mp4",
        )
        self.assertFalse(run_1_success)

        # Verify Run 1 saved transcript checkpoint
        refreshed_after_run_1 = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed_after_run_1.status, "failed")
        self.assertEqual(refreshed_after_run_1.stage, "failed")
        self.assertEqual(refreshed_after_run_1.transcript, "Transcript generated by fallback.")
        self.assertEqual(refreshed_after_run_1.model_name, "gemini-2.5-flash")

        # Reset mock call counters for Run 2 (Resume)
        mock_extract.reset_mock()
        mock_provider.upload_audio.reset_mock()
        mock_provider.generate_transcript.reset_mock()
        mock_provider.generate_report.reset_mock()
        mock_provider.generate_report.side_effect = None
        mock_provider.generate_report.return_value = "## Final Executive Report on Resume"

        # Run 2 (Resume with allow_retry=True)
        task_2 = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        self.assertIsNotNone(task_2)

        run_2_success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_2,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(run_2_success)

        # STRICT VERIFICATION ON RESUME:
        # NO extraction, NO upload, NO transcription!
        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.generate_transcript.assert_not_called()
        mock_provider.generate_report.assert_called_once_with("Transcript generated by fallback.")

        # Final meeting state
        final_meeting = Meeting.objects.get(id=meeting.id)
        self.assertEqual(final_meeting.status, "completed")
        self.assertEqual(final_meeting.stage, "completed")
        self.assertEqual(final_meeting.ai_report, "## Final Executive Report on Resume")
        self.assertEqual(final_meeting.model_name, "gemini-2.5-flash")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.TranscriptService.save_transcript")
    def test_incomplete_worker_interruption_preserves_gemini_remote_reference_for_resume(
        self, mock_save_transcript, mock_audio_info, mock_extract, mock_get_provider
    ):
        """
        Verifies:
        1. When a worker fails mid-pipeline, cleanup_audio is NOT called and gemini_file_name is preserved.
        2. When manual retry resumes, the preserved gemini_file_name is retrieved and reused.
        3. Upon successful final completion, cleanup_audio is called and gemini_file_name is cleared.
        """
        mock_extract.return_value = "extracted.mp3"
        mock_audio_info.return_value = {"duration_seconds": 45.0}
        mock_save_transcript.return_value = "transcript.txt"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash-lite"
        mock_file = MagicMock()
        mock_file.name = "files/preserved_remote_file_789"
        mock_file.state.name = "ACTIVE"
        mock_provider.upload_audio.return_value = mock_file
        mock_provider.wait_until_ready.return_value = mock_file
        mock_provider.get_file.return_value = mock_file

        # Run 1: Transcription fails
        mock_provider.generate_transcript.side_effect = RuntimeError("503 Service Unavailable: High demand")
        mock_provider.translate_error.return_value = ValidationResult(
            is_valid=False,
            status=ModelStatus.TEMPORARILY_UNAVAILABLE,
            message="High demand",
            model_id="gemini-2.5-flash-lite",
        )
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Preserve Gemini Reference Test",
            original_file="meeting.mp4",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        task_1 = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user)

        run_1_success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_1,
            media_filepath="meeting.mp4",
        )
        self.assertFalse(run_1_success)

        # Incomplete run: cleanup_audio NOT called, gemini_file_name PRESERVED in DB
        mock_provider.cleanup_audio.assert_not_called()
        refreshed_after_run_1 = Meeting.objects.get(id=meeting.id)
        self.assertEqual(refreshed_after_run_1.gemini_file_name, "files/preserved_remote_file_789")

        # Run 2: Resume
        mock_extract.reset_mock()
        mock_provider.upload_audio.reset_mock()
        mock_provider.generate_transcript.side_effect = None
        mock_provider.generate_transcript.return_value = "Successfully transcribed on resume."
        mock_provider.generate_report.return_value = "## Complete Report"

        task_2 = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        run_2_success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_2,
            media_filepath="meeting.mp4",
        )
        self.assertTrue(run_2_success)

        # Verification on resume:
        # Reused existing Gemini file, no re-extract, no re-upload
        mock_provider.get_file.assert_called_once_with("files/preserved_remote_file_789")
        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()

        # On successful completion: cleanup_audio WAS called, gemini_file_name cleared
        mock_provider.cleanup_audio.assert_called_once_with(mock_file)
        final_meeting = Meeting.objects.get(id=meeting.id)
        self.assertEqual(final_meeting.status, "completed")
        self.assertEqual(final_meeting.stage, "completed")
        self.assertIsNone(final_meeting.gemini_file_name)

    def test_stale_task_detected_when_unregistered_and_inactive_past_60s(self):
        """
        Verify that check_and_reap_stale_task marks a meeting as failed when:
        1. status == 'processing'
        2. not is_task_active (no in-memory thread)
        3. updated_at is older than 60 seconds
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Stale Meeting Test",
            original_file="stale.mp4",
            status="processing",
            stage="transcribing",
            gemini_file_name="files/remote_stale_123",
            duration=0.0,
            file_size=1024,
        )
        # Manually backdate updated_at to 120 seconds ago
        past_time = timezone.now() - datetime.timedelta(seconds=120)
        Meeting.objects.filter(id=meeting.id).update(updated_at=past_time)

        # Ensure not in active tasks
        AsyncTaskService.unregister_active_task(meeting.id)
        self.assertFalse(AsyncTaskService.is_task_active(meeting.id))

        reaped = AsyncTaskService.check_and_reap_stale_task(meeting.id)
        self.assertTrue(reaped)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "failed")
        self.assertEqual(meeting.stage, "failed")
        self.assertIn("interrupted", meeting.error_message)
        # Checkpoints like gemini_file_name must NOT be wiped by reaper
        self.assertEqual(meeting.gemini_file_name, "files/remote_stale_123")

    def test_fresh_processing_task_under_60s_not_reaped(self):
        """
        Verify that a processing meeting whose updated_at is within the 60s grace
        period is NOT reaped, preventing race conditions during worker startup.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Fresh Meeting Test",
            original_file="fresh.mp4",
            status="processing",
            stage="queued",
            duration=0.0,
            file_size=1024,
        )
        # Set updated_at to only 10 seconds ago
        recent_time = timezone.now() - datetime.timedelta(seconds=10)
        Meeting.objects.filter(id=meeting.id).update(updated_at=recent_time)
        AsyncTaskService.unregister_active_task(meeting.id)

        reaped = AsyncTaskService.check_and_reap_stale_task(meeting.id)
        self.assertFalse(reaped)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "processing")
        self.assertEqual(meeting.stage, "queued")

    def test_active_worker_never_reaped_even_if_updated_at_old(self):
        """
        CRITICAL SAFETY RULE: An actively running in-memory worker must NEVER
        be marked stale solely because updated_at is older than 60s or 15m.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Active Long Running Meeting",
            original_file="long.mp4",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        # Backdate updated_at by 30 minutes
        very_old_time = timezone.now() - datetime.timedelta(minutes=30)
        Meeting.objects.filter(id=meeting.id).update(updated_at=very_old_time)

        # Register as actively running in memory
        AsyncTaskService.register_active_task(meeting.id, "active-task-uuid-999")
        self.assertTrue(AsyncTaskService.is_task_active(meeting.id))

        reaped = AsyncTaskService.check_and_reap_stale_task(meeting.id)
        self.assertFalse(reaped)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "processing")
        self.assertEqual(meeting.stage, "transcribing")

        # Cleanup
        AsyncTaskService.unregister_active_task(meeting.id)

    def test_meeting_status_api_auto_reaps_stale_task(self):
        """
        Verify that calling meeting_status_api on a stale processing meeting
        automatically detects and reaps the task, returning failed status with retry guidance.
        """
        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Status API Stale Test",
            original_file="status_stale.mp4",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        past_time = timezone.now() - datetime.timedelta(seconds=180)
        Meeting.objects.filter(id=meeting.id).update(updated_at=past_time)
        AsyncTaskService.unregister_active_task(meeting.id)

        response = self.client.get(f"/meeting/status/{meeting.id}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["status"], "failed")
        self.assertEqual(data["data"]["stage"], "failed")
        self.assertEqual(data["data"]["progress_percentage"], 0)
        self.assertIn("interrupted", data["data"]["error_message"])

        # DB must be updated
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "failed")

    def test_dashboard_and_detail_views_auto_reap_stale_tasks(self):
        """
        Verify that accessing the dashboard or detail view triggers on-demand reaping.
        """
        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Dashboard Stale Test",
            original_file="dash_stale.mp4",
            status="processing",
            stage="uploading_to_ai",
            duration=0.0,
            file_size=1024,
        )
        past_time = timezone.now() - datetime.timedelta(seconds=90)
        Meeting.objects.filter(id=meeting.id).update(updated_at=past_time)
        AsyncTaskService.unregister_active_task(meeting.id)

        # Access dashboard
        dash_response = self.client.get("/dashboard/")
        self.assertEqual(dash_response.status_code, 200)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "failed")

        # Access meeting detail
        detail_response = self.client.get(f"/meeting/{meeting.id}/")
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Failed")
        self.assertContains(detail_response, "Retry Meeting Processing")

    def test_retry_api_requires_authentication(self):
        """
        Verify that retry_meeting_api requires login.
        """
        response = self.client.post("/meeting/retry/999/")
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_retry_api_rejects_get_method(self):
        """
        Verify that retry_meeting_api is POST-only.
        """
        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Method Test",
            original_file="method.mp4",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
        )
        response = self.client.get(f"/meeting/retry/{meeting.id}/")
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

    def test_retry_api_tenant_isolation(self):
        """
        Verify that a user cannot retry another user's meeting (returns 404).
        """
        other_user = User.objects.create_user(
            username="other_distinct@example.com", email="other_distinct@example.com", password="otherpassword123"
        )
        other_meeting = Meeting.objects.create(
            user=other_user,
            meeting_name="Other User Meeting",
            original_file="other.mp4",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
        )
        self.client.force_login(self.user)
        response = self.client.post(f"/meeting/retry/{other_meeting.id}/")
        self.assertEqual(response.status_code, 404)

    def test_retry_api_rejects_completed_meeting(self):
        """
        Verify that retry_meeting_api returns HTTP 400 ALREADY_COMPLETED for completed meetings.
        """
        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Completed Meeting",
            original_file="completed.mp4",
            status="completed",
            stage="completed",
            transcript="Existing transcript.",
            ai_report="Existing report.",
            duration=60.0,
            file_size=1024,
        )
        response = self.client.post(f"/meeting/retry/{meeting.id}/")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "ALREADY_COMPLETED")

    def test_retry_api_rejects_active_processing_meeting(self):
        """
        Verify that retry_meeting_api returns HTTP 409 ALREADY_PROCESSING if the meeting
        is currently actively executing in memory.
        """
        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Actively Processing Meeting",
            original_file="active.mp4",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        AsyncTaskService.register_active_task(meeting.id, "live-task-uuid-111")

        try:
            response = self.client.post(f"/meeting/retry/{meeting.id}/")
            self.assertEqual(response.status_code, 409)
            data = response.json()
            self.assertFalse(data["success"])
            self.assertEqual(data["error"]["code"], "ALREADY_PROCESSING")
        finally:
            AsyncTaskService.unregister_active_task(meeting.id)

    @patch("meeting.services.async_task_service.AsyncTaskService.get_executor")
    @patch("meeting.services.model_validation_service.ModelValidationService.preflight_check")
    def test_retry_api_success_on_failed_meeting(self, mock_preflight, mock_get_executor):
        """
        Verify that retry_meeting_api successfully queues a retry task for a failed meeting,
        generating a new task_id while preserving the Meeting row ID.
        """
        mock_preflight.return_value = MagicMock(is_valid=True, status=ModelStatus.AVAILABLE)
        mock_executor = MagicMock()
        mock_get_executor.return_value = mock_executor

        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Retry Target Meeting",
            original_file="target.mp4",
            audio_file="target.mp3",
            transcript="Partial transcript checkpoint.",
            status="failed",
            stage="failed",
            error_message="Previous transient error",
            duration=45.0,
            file_size=2048,
        )

        response = self.client.post(f"/meeting/retry/{meeting.id}/")
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["meeting_id"], meeting.id)
        self.assertEqual(data["data"]["status"], "processing")
        self.assertEqual(data["data"]["stage"], "queued")
        new_task_id = data["data"]["task_id"]
        self.assertTrue(bool(new_task_id))

        # Checkpoint data preserved
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "processing")
        self.assertEqual(meeting.stage, "queued")
        self.assertEqual(meeting.task_id, new_task_id)
        self.assertEqual(meeting.transcript, "Partial transcript checkpoint.")
        self.assertEqual(str(meeting.audio_file), "target.mp3")
        self.assertIsNone(meeting.error_message)

        mock_executor.submit.assert_called_once()

        # Cleanup active task
        AsyncTaskService.unregister_active_task(meeting.id)

    @patch("meeting.services.provider_factory.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.transcript_service.TranscriptService.save_transcript")
    def test_retry_case_a_resumes_from_gemini_remote_file(
        self, mock_save_transcript, mock_get_audio_info, mock_extract, mock_get_provider
    ):
        """
        CASE A: Gemini remote file exists and is active.
        Pipeline must skip FFmpeg extraction and skip upload, directly reusing remote file.
        """
        mock_file = MagicMock()
        mock_file.name = "files/active_remote_abc"
        mock_file.state.name = "ACTIVE"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash"
        mock_provider.get_file.return_value = mock_file
        mock_provider.generate_transcript.return_value = "Transcript from reused remote audio."
        mock_provider.generate_report.return_value = "## Reused Summary"
        mock_get_provider.return_value = mock_provider
        mock_save_transcript.return_value = "media/transcripts/target.txt"

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Case A Test",
            original_file="non_existent_local.mp4",
            gemini_file_name="files/active_remote_abc",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
        )

        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="non_existent_local.mp4",
        )
        self.assertTrue(success)

        # Reused remote file
        mock_provider.get_file.assert_called_once_with("files/active_remote_abc")
        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.generate_transcript.assert_called_once()
        mock_provider.generate_report.assert_called_once()

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "completed")
        self.assertEqual(meeting.transcript, "Transcript from reused remote audio.")

    @patch("meeting.services.provider_factory.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_audio_path")
    @patch("meeting.services.transcript_service.TranscriptService.save_transcript")
    def test_retry_case_b_resumes_from_extracted_mp3_when_remote_expired(
        self, mock_save_transcript, mock_get_audio_path, mock_extract, mock_get_provider
    ):
        """
        CASE B: Remote Gemini file is expired / missing, but local extracted MP3 exists.
        Pipeline must skip FFmpeg extraction and re-upload the existing audio.
        """
        mock_get_audio_path.return_value = "C:/fake/path/audio.mp3"

        mock_file = MagicMock()
        mock_file.name = "files/new_remote_xyz"
        mock_file.state.name = "ACTIVE"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash"
        mock_provider.get_file.side_effect = RuntimeError("404 Remote File Not Found")
        mock_provider.upload_audio.return_value = mock_file
        mock_provider.generate_transcript.return_value = "Transcript from re-uploaded MP3."
        mock_provider.generate_report.return_value = "## Summary"
        mock_get_provider.return_value = mock_provider
        mock_save_transcript.return_value = "media/transcripts/audio.txt"

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Case B Test",
            original_file="video.mp4",
            audio_file="audio.mp3",
            gemini_file_name="files/expired_file",
            status="failed",
            stage="failed",
            duration=30.0,
            file_size=1024,
        )

        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="video.mp4",
        )
        self.assertTrue(success)

        mock_extract.assert_not_called()
        mock_provider.upload_audio.assert_called_once_with("C:/fake/path/audio.mp3")
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "completed")

    @patch("meeting.services.provider_factory.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AudioService.extract_audio")
    @patch("meeting.services.async_task_service.AudioService.get_audio_info")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_original_media_path")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_audio_path")
    @patch("meeting.services.transcript_service.TranscriptService.save_transcript")
    def test_retry_case_c_resumes_from_original_media_when_audio_missing(
        self, mock_save_transcript, mock_get_audio_path, mock_get_orig_path, mock_get_audio_info, mock_extract, mock_get_provider
    ):
        """
        CASE C: Remote file missing, extracted audio missing, but original media exists.
        Pipeline extracts audio from original media, uploads, and proceeds.
        """
        mock_get_audio_path.return_value = None
        mock_get_orig_path.return_value = "C:/fake/path/original_recording.mp4"
        mock_extract.return_value = "C:/fake/path/new_extracted.mp3"
        mock_get_audio_info.return_value = {"duration_seconds": 65.0}

        mock_file = MagicMock()
        mock_file.name = "files/new_remote_case_c"
        mock_file.state.name = "ACTIVE"

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash"
        mock_provider.upload_audio.return_value = mock_file
        mock_provider.generate_transcript.return_value = "Transcript from re-extracted audio."
        mock_provider.generate_report.return_value = "## Summary"
        mock_get_provider.return_value = mock_provider
        mock_save_transcript.return_value = "media/transcripts/orig.txt"

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Case C Test",
            original_file="original_recording.mp4",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
        )

        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="original_recording.mp4",
        )
        self.assertTrue(success)

        mock_extract.assert_called_once_with("C:/fake/path/original_recording.mp4")
        mock_provider.upload_audio.assert_called_once_with("C:/fake/path/new_extracted.mp3")

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "completed")
        self.assertEqual(meeting.duration, 65.0)

    @patch("meeting.services.provider_factory.ProviderFactory.get_provider")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_original_media_path")
    @patch("meeting.services.async_task_service.AsyncTaskService.get_existing_audio_path")
    def test_retry_case_d_fails_gracefully_when_all_media_missing(
        self, mock_get_audio_path, mock_get_orig_path, mock_get_provider
    ):
        """
        CASE D: Remote file missing, extracted audio missing, AND original media missing
        (e.g., container recycling wiped ephemeral disk).
        Pipeline must fail gracefully with explicit message.
        """
        mock_get_audio_path.return_value = None
        mock_get_orig_path.return_value = None

        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Case D Test",
            original_file="lost_media.mp4",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
        )

        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="",
        )
        self.assertFalse(success)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "failed")
        self.assertEqual(meeting.stage, "failed")
        self.assertIn("no longer available on the server", meeting.error_message)

    @patch("meeting.services.provider_factory.ProviderFactory.get_provider")
    def test_retry_resumes_from_transcript_generating_only_report(self, mock_get_provider):
        """
        Verify that when a meeting already has a valid transcript checkpoint,
        retry skips audio extraction, upload, and transcription, directly generating the report.
        """
        mock_provider = MagicMock()
        mock_provider.provider = "gemini"
        mock_provider.model_name = "gemini-2.5-flash"
        mock_provider.generate_report.return_value = "## Complete Report from Transcript Checkpoint"
        mock_get_provider.return_value = mock_provider

        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Transcript Checkpoint Test",
            original_file="some_media.mp4",
            transcript="Already saved transcript content.",
            status="failed",
            stage="failed",
            duration=45.0,
            file_size=1024,
        )

        task_id = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=meeting.id,
            task_id=task_id,
            media_filepath="some_media.mp4",
        )
        self.assertTrue(success)

        mock_provider.generate_transcript.assert_not_called()
        mock_provider.upload_audio.assert_not_called()
        mock_provider.generate_report.assert_called_once_with("Already saved transcript content.")

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "completed")
        self.assertEqual(meeting.ai_report, "## Complete Report from Transcript Checkpoint")

    def test_concurrent_retry_requests_prevent_duplicate_workers(self):
        """
        Verify that multiple concurrent calls to acquire_processing_lease on the same
        meeting permit only one worker lease to be granted.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Concurrency Lease Test",
            original_file="concurrency.mp4",
            status="failed",
            stage="failed",
            duration=0.0,
            file_size=1024,
        )

        lease_1 = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        self.assertIsNotNone(lease_1)

        # Second concurrent attempt while first is active in memory
        lease_2 = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        self.assertIsNone(lease_2)

        # Cleanup
        AsyncTaskService.unregister_active_task(meeting.id)

    def test_multi_worker_active_task_in_other_worker_never_reaped(self):
        """
        GUNICORN MULTI-WORKER SAFETY:
        Simulate Worker 2 receiving a status/dashboard/reap check while Worker 1 is
        actively executing in another process (is_task_active is False in Worker 2,
        but updated_at was heartbeated 15s ago, well within STALE_INACTIVE_TIMEOUT).
        Worker 2 MUST NOT reap Worker 1's active task.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Multi-Worker Active Meeting",
            original_file="worker1.mp4",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        # Set updated_at to 15 seconds ago (active heartbeat from peer worker)
        recent_time = timezone.now() - datetime.timedelta(seconds=15)
        Meeting.objects.filter(id=meeting.id).update(updated_at=recent_time)

        # In current process (Worker 2), is_task_active is False
        self.assertFalse(AsyncTaskService.is_task_active(meeting.id))

        reaped = AsyncTaskService.check_and_reap_stale_task(meeting.id)
        self.assertFalse(reaped)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "processing")
        self.assertEqual(meeting.stage, "transcribing")

    def test_multi_worker_crashed_task_reaped_after_timeout(self):
        """
        GUNICORN MULTI-WORKER RECOVERY:
        Simulate Worker 1 crashing 120s ago (is_task_active is False in Worker 2,
        and updated_at is 120s old > STALE_INACTIVE_TIMEOUT of 60s).
        Worker 2 MUST reap the orphaned task to status='failed'.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Multi-Worker Dead Meeting",
            original_file="crashed.mp4",
            status="processing",
            stage="uploading_to_ai",
            duration=0.0,
            file_size=1024,
        )
        # Set updated_at to 120 seconds ago
        crashed_time = timezone.now() - datetime.timedelta(seconds=120)
        Meeting.objects.filter(id=meeting.id).update(updated_at=crashed_time)

        self.assertFalse(AsyncTaskService.is_task_active(meeting.id))

        reaped = AsyncTaskService.check_and_reap_stale_task(meeting.id)
        self.assertTrue(reaped)

        meeting.refresh_from_db()
        self.assertEqual(meeting.status, "failed")
        self.assertEqual(meeting.stage, "failed")
        self.assertIn("interrupted", meeting.error_message)

    def test_multi_worker_lease_acquisition_rejected_when_other_worker_active(self):
        """
        GUNICORN MULTI-WORKER CONCURRENCY:
        Simulate Worker 2 attempting acquire_processing_lease while Worker 1 is
        actively executing (is_task_active False in Worker 2, but updated_at is fresh).
        Lease MUST be rejected (returns None).
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Multi-Worker Lease Conflict",
            original_file="conflict.mp4",
            task_id="worker-1-live-task-uuid",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        recent_time = timezone.now() - datetime.timedelta(seconds=5)
        Meeting.objects.filter(id=meeting.id).update(updated_at=recent_time)

        self.assertFalse(AsyncTaskService.is_task_active(meeting.id))

        lease = AsyncTaskService.acquire_processing_lease(meeting.id, user=self.user, allow_retry=True)
        self.assertIsNone(lease)

    def test_multi_worker_retry_api_rejects_processing_meeting_in_other_worker(self):
        """
        GUNICORN MULTI-WORKER RETRY CONFLICT:
        Simulate user hitting retry endpoint on Worker 2 while Worker 1 is actively
        processing (is_task_active is False in Worker 2, but updated_at is fresh).
        POST /meeting/retry/<id>/ MUST return HTTP 409 ALREADY_PROCESSING.
        """
        self.client.force_login(self.user)
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Multi-Worker Retry Conflict",
            original_file="active_other.mp4",
            task_id="worker-1-live-task-uuid",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        recent_time = timezone.now() - datetime.timedelta(seconds=5)
        Meeting.objects.filter(id=meeting.id).update(updated_at=recent_time)

        self.assertFalse(AsyncTaskService.is_task_active(meeting.id))

        response = self.client.post(f"/meeting/retry/{meeting.id}/")
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "ALREADY_PROCESSING")


class TaskHeartbeatTests(TransactionTestCase):
    """
    HEARTBEAT MULTI-THREADED TESTS:
    Uses TransactionTestCase to enable SQLite concurrent writes across threads.
    """

    def test_task_heartbeat_lifecycle_and_updates(self):
        """
        Verify that TaskHeartbeat runs as a background thread, periodically updates
        the meeting's updated_at timestamp in the database, and stops cleanly.
        """
        import time
        user = User.objects.create_user(
            username="hb_test_user@example.com",
            email="hb_test_user@example.com",
            password="password123",
        )
        meeting = Meeting.objects.create(
            user=user,
            meeting_name="Heartbeat Test Meeting",
            original_file="hb.mp4",
            status="processing",
            stage="transcribing",
            duration=0.0,
            file_size=1024,
        )
        old_time = timezone.now() - datetime.timedelta(seconds=30)
        Meeting.objects.filter(id=meeting.id).update(updated_at=old_time)

        heartbeat = TaskHeartbeat(meeting.id, interval=0.05)
        heartbeat.start()
        try:
            time.sleep(0.15)
        finally:
            heartbeat.stop()

        meeting.refresh_from_db()
        age = (timezone.now() - meeting.updated_at).total_seconds()
        self.assertLess(age, 2.0)
