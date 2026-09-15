import io
import json
import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from meeting.models import Meeting, AISettings
from meeting.services.settings_service import SettingsService
from meeting.services.async_task_service import AsyncTaskService
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
        mock_provider.cleanup_audio.assert_called_once_with(mock_gemini_file)
