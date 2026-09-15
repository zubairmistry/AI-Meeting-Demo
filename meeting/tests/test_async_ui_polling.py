import json
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.template.loader import render_to_string
from django.core.files.uploadedfile import SimpleUploadedFile

from meeting.models import Meeting
from meeting.services.settings_service import SettingsService
from meeting.services.async_task_service import AsyncTaskService
from meeting.providers.base_provider import ValidationResult, ModelStatus


class AsyncUiPollingIntegrationTests(TestCase):
    """
    Test suite for Step 4:
    - Verifies UI elements in index.html for real-time progress bar, stage labels, and dynamic output containers.
    - Verifies frontend contract compatibility with /meeting/analyze/ (202) and /meeting/status/<id>/ (200).
    - Verifies SSR and dynamic DOM injection contracts.
    """

    def setUp(self):
        self.client = Client()
        self.meeting_url = reverse("meeting")
        self.analyze_url = reverse("analyze_meeting_api")
        self.user = User.objects.create_user(
            username="frontend_user@example.com",
            email="frontend_user@example.com",
            password="securePassword123!",
        )
        self.client.login(username="frontend_user@example.com", password="securePassword123!")

        SettingsService.save_settings(
            user=self.user,
            provider="gemini",
            api_key="AIzaSyDummyKeyValidTestFormat12345",
            model_name="gemini-2.5-flash",
        )

    def tearDown(self):
        for m in Meeting.objects.all():
            AsyncTaskService.unregister_active_task(m.id)

    def test_meeting_ui_contains_async_progress_and_stream_elements(self):
        """
        Meeting page template must contain real-time progress bar, badges, log stream, and containers.
        """
        response = self.client.get(self.meeting_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Progress bar and stage indicators
        self.assertIn('id="processingProgressBarContainer"', content)
        self.assertIn('id="meetingProgressBar"', content)
        self.assertIn('id="processingStageLabel"', content)
        self.assertIn('id="processingPercentLabel"', content)
        self.assertIn('id="processingStatusBadge"', content)

        # 8-Stage Stepper IDs
        for i in range(1, 9):
            self.assertIn(f'id="stepperStage{i}"', content)
        for i in range(1, 8):
            self.assertIn(f'id="stepperConnector{i}"', content)

        # Live Activity Log stream
        self.assertIn('id="activityLogStream"', content)

        # Dynamic containers for Transcript & AI Report
        self.assertIn('id="transcriptContainer"', content)
        self.assertIn('id="reportContainer"', content)

        # Right sidebar meeting info fields
        self.assertIn('id="infoLastUsed"', content)
        self.assertIn('id="infoDetectedLanguage"', content)
        self.assertIn('id="infoInputFormat"', content)
        self.assertIn('id="infoRuntimeDuration"', content)
        self.assertIn('id="infoProcessingStatus"', content)

    def test_ssr_and_dynamic_containers_behavior(self):
        """
        Initial GET without transcript/report omits output elements from DOM.
        Rendering with transcript/report context populates output elements in DOM.
        """
        # Initial GET
        response = self.client.get(self.meeting_url)
        content = response.content.decode("utf-8")
        self.assertNotIn('id="meetingTranscriptContent"', content)
        self.assertNotIn('id="meetingReportContent"', content)

        # SSR context with results
        rendered = render_to_string(
            "meeting/index.html",
            {
                "status": "Completed",
                "transcript": "Verbatim meeting transcript text.",
                "report": "### Executive Summary\nKey points.",
                "request": response.wsgi_request,
                "user": self.user,
            },
        )
        self.assertIn('id="meetingTranscriptContent"', rendered)
        self.assertIn('id="meetingReportContent"', rendered)
        self.assertIn("Verbatim meeting transcript text.", rendered)
        self.assertIn("Executive Summary", rendered)

    @patch("meeting.services.async_task_service.AsyncTaskService.get_executor")
    @patch("meeting.services.model_validation_service.ModelValidationService.preflight_check")
    def test_full_async_submit_and_status_polling_contract(self, mock_preflight, mock_get_executor):
        """
        Simulates frontend AJAX flow:
        1. POST /meeting/analyze/ -> 202 Accepted with meeting_id
        2. GET /meeting/status/<meeting_id>/ -> 200 with stage queued (10%)
        3. Stage transitions -> extracting (25%), transcribing (70%), completed (100%)
        """
        mock_preflight.return_value = ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message="Model verified",
            model_id="gemini-2.5-flash",
        )
        mock_executor = MagicMock()
        mock_get_executor.return_value = mock_executor

        fake_file = SimpleUploadedFile("team_standup.mp4", b"dummy media bytes", content_type="video/mp4")

        # Step 1: Submit form via AJAX
        post_resp = self.client.post(self.analyze_url, {"meeting_file": fake_file})
        self.assertEqual(post_resp.status_code, 202)
        post_data = post_resp.json()
        self.assertTrue(post_data["success"])
        meeting_id = post_data["data"]["meeting_id"]

        # Step 2: Poll status initially (queued stage)
        status_url = reverse("meeting_status_api", kwargs={"meeting_id": meeting_id})
        poll_resp = self.client.get(status_url)
        self.assertEqual(poll_resp.status_code, 200)
        poll_data = poll_resp.json()["data"]
        self.assertEqual(poll_data["status"], "processing")
        self.assertEqual(poll_data["stage"], "queued")
        self.assertEqual(poll_data["progress_percentage"], 10)
        self.assertFalse(poll_data["has_transcript"])
        self.assertFalse(poll_data["has_ai_report"])

        # Step 3: Simulate backend stage transition to transcribing
        AsyncTaskService.update_stage(meeting_id, "transcribing")
        poll_resp2 = self.client.get(status_url)
        poll_data2 = poll_resp2.json()["data"]
        self.assertEqual(poll_data2["stage"], "transcribing")
        self.assertEqual(poll_data2["progress_percentage"], 70)

        # Step 4: Simulate backend completion with transcript and report
        Meeting.objects.filter(id=meeting_id).update(
            status="completed",
            stage="completed",
            duration=95.0,
            transcript="Full transcribed meeting audio.",
            ai_report="### AI Summary\n- Action items decided.",
        )
        poll_resp3 = self.client.get(status_url)
        poll_data3 = poll_resp3.json()["data"]
        self.assertEqual(poll_data3["status"], "completed")
        self.assertEqual(poll_data3["stage"], "completed")
        self.assertEqual(poll_data3["progress_percentage"], 100)
        self.assertEqual(poll_data3["duration"], 95.0)
        self.assertTrue(poll_data3["has_transcript"])
        self.assertEqual(poll_data3["transcript"], "Full transcribed meeting audio.")
        self.assertTrue(poll_data3["has_ai_report"])
        self.assertEqual(poll_data3["ai_report"], "### AI Summary\n- Action items decided.")

    def test_client_file_validation_js_contracts(self):
        """
        Verifies meeting.js file validation contracts:
        - 50 MB byte limit equals 52428800 bytes.
        - resetFilePreview accepts preserveAlert flag to avoid wiping validation alerts.
        - handleFile preserves alert on invalid extension and size exceeded.
        """
        import os
        from django.conf import settings as django_settings
        js_path = os.path.join(django_settings.BASE_DIR, "meeting", "static", "meeting", "js", "meeting.js")
        self.assertTrue(os.path.exists(js_path))
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()

        # 50 MB limit constant
        self.assertIn("const MAX_SIZE_BYTES = 52428800;", js_content)
        self.assertEqual(50 * 1024 * 1024, 52428800)

        # resetFilePreview parameter and conditional hideValidationMessage
        self.assertIn("function resetFilePreview(preserveAlert = false)", js_content)
        self.assertIn("if (!preserveAlert)", js_content)
        self.assertIn("hideValidationMessage();", js_content)

        # handleFile preserves alert
        self.assertIn("resetFilePreview(true);", js_content)
        self.assertIn("Unsupported file format.", js_content)
        self.assertIn("exceeds the demo limit of 50 MB.", js_content)
