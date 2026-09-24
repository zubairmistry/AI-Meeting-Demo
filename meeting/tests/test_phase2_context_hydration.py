import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from meeting.models import Meeting, AISettings
from meeting.services.settings_service import SettingsService


class Phase2ContextHydrationTests(TestCase):
    """
    Test suite for Phase 2.1 Step 1 (Backend Context Hydration)
    and Step 2 (Template Dynamic Binding).
    """

    def setUp(self):
        self.client = Client()
        self.meeting_url = reverse("meeting")
        self.settings_url = reverse("settings")
        self.user = User.objects.create_user(
            username="context_test_user@example.com",
            email="context_test_user@example.com",
            password="SecureTestPassword2026!",
        )

    def test_home_context_unconfigured_user_without_meetings(self):
        """
        An authenticated user without AI configuration and without meetings
        must receive clean default placeholders and unconfigured states.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context

        # Backward compatibility preserved
        self.assertEqual(ctx["status"], "Waiting for meeting upload...")
        self.assertEqual(ctx["transcript"], "")
        self.assertEqual(ctx["report"], "")
        self.assertIn("max_upload_size", ctx)
        self.assertIn("max_upload_size_mb", ctx)

        # AI Provider context (default signal creates provider="gemini" with empty api_key)
        self.assertFalse(ctx["is_provider_configured"])
        self.assertEqual(ctx["active_provider"], "gemini")
        self.assertEqual(ctx["active_provider_name"], "Google Gemini")
        self.assertEqual(ctx["active_model"], "gemini-2.5-flash")
        self.assertNotIn("api_key", ctx)

        # Storage metrics
        self.assertEqual(ctx["user_storage_bytes"], 0)
        self.assertEqual(ctx["user_storage_display"], "0 MB")
        self.assertEqual(ctx["storage_quota_display"], "10 GB")
        self.assertEqual(ctx["storage_percentage"], 0)

        # Latest meeting info
        self.assertIsNone(ctx["latest_meeting"])
        self.assertEqual(ctx["latest_meeting_date"], "No recent meetings")
        self.assertEqual(ctx["latest_meeting_format"], "—")
        self.assertEqual(ctx["latest_meeting_duration"], "—")
        self.assertEqual(ctx["latest_meeting_status"], "READY")
        self.assertEqual(ctx["latest_meeting_status_class"], "text-muted")

        # Template HTML binding
        content = response.content.decode("utf-8")
        self.assertIn("Not Configured", content)
        self.assertIn(self.settings_url, content)
        self.assertIn("0 MB / 10 GB", content)
        self.assertIn("0%", content)
        self.assertIn("No recent meetings", content)
        self.assertIn("Auto (Speech)", content)
        self.assertIn("READY", content)

    def test_home_context_configured_user_with_meetings(self):
        """
        A user with configured Gemini provider and meeting history
        must receive hydrated telemetry, formatted storage, and latest meeting details.
        """
        secret_api_key = "AIzaSySecretRealKeyFormat9876543210"
        SettingsService.save_settings(
            user=self.user,
            provider="gemini",
            api_key=secret_api_key,
            model_name="gemini-2.5-flash",
        )

        # Create older meeting
        Meeting.objects.create(
            user=self.user,
            meeting_name="old_sync.mp4",
            original_file="old_sync.mp4",
            status="completed",
            duration=65.0,
            file_size=50 * 1024 * 1024,  # 50 MB
        )

        # Create latest meeting
        latest = Meeting.objects.create(
            user=self.user,
            meeting_name="latest_strategy.mkv",
            original_file="latest_strategy.mkv",
            status="completed",
            duration=135.0,  # 02 min 15 sec
            file_size=150 * 1024 * 1024,  # 150 MB
        )

        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context

        # AI Provider context
        self.assertTrue(ctx["is_provider_configured"])
        self.assertEqual(ctx["active_provider"], "gemini")
        self.assertEqual(ctx["active_provider_name"], "Google Gemini")
        self.assertEqual(ctx["active_model"], "gemini-2.5-flash")
        self.assertNotIn("api_key", ctx)

        # Storage metrics (50 MB + 150 MB = 200 MB)
        self.assertEqual(ctx["user_storage_bytes"], 200 * 1024 * 1024)
        self.assertEqual(ctx["user_storage_display"], "200.00 MB")
        self.assertEqual(ctx["storage_quota_display"], "10 GB")
        expected_pct = round(((200 * 1024 * 1024) / (10 * 1024 * 1024 * 1024)) * 100, 1)
        self.assertEqual(ctx["storage_percentage"], expected_pct)

        # Latest meeting info
        self.assertEqual(ctx["latest_meeting"].id, latest.id)
        self.assertEqual(ctx["latest_meeting_format"], "MKV")
        self.assertEqual(ctx["latest_meeting_duration"], "02 min 15 sec")
        self.assertEqual(ctx["latest_meeting_status"], "COMPLETED")
        self.assertEqual(ctx["latest_meeting_status_class"], "text-success")

        # HTML assertions
        content = response.content.decode("utf-8")
        self.assertIn("Connected", content)
        self.assertIn("Google Gemini", content)
        self.assertIn("gemini-2.5-flash", content)
        self.assertIn("200.00 MB / 10 GB", content)
        self.assertIn("MKV", content)
        self.assertIn("02 min 15 sec", content)
        self.assertIn("COMPLETED", content)

        # Confidentiality: decrypted API key must NEVER be in context or HTML
        self.assertNotIn(secret_api_key, content)

    def test_home_context_claude_provider_configuration(self):
        """
        Verify that configuring Anthropic Claude updates active provider and model display.
        """
        SettingsService.save_settings(
            user=self.user,
            provider="claude",
            api_key="sk-ant-api03-testKeySecret12345",
            model_name="claude-3-7-sonnet",
        )

        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertTrue(ctx["is_provider_configured"])
        self.assertEqual(ctx["active_provider"], "claude")
        self.assertEqual(ctx["active_provider_name"], "Anthropic Claude")
        self.assertEqual(ctx["active_model"], "claude-3-7-sonnet")

        content = response.content.decode("utf-8")
        self.assertIn("Anthropic Claude", content)
        self.assertIn("claude-3-7-sonnet", content)
        self.assertNotIn("sk-ant-api03-testKeySecret12345", content)

    def test_home_context_storage_capping_at_100_percent(self):
        """
        Storage percentage must be safely capped at 100.0% even if user exceeds 10 GB.
        """
        # Create 12 GB worth of meetings (12 * 1024^3 bytes)
        Meeting.objects.create(
            user=self.user,
            meeting_name="massive_recording.mp4",
            original_file="massive_recording.mp4",
            status="completed",
            duration=3600.0,
            file_size=12 * 1024 * 1024 * 1024,
        )

        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)

        ctx = response.context
        self.assertEqual(ctx["user_storage_display"], "12.00 GB")
        self.assertEqual(ctx["storage_percentage"], 100.0)

    def test_latest_meeting_failed_status_mapping(self):
        """
        If the user's latest meeting is failed, status must be FAILED with text-danger class.
        """
        Meeting.objects.create(
            user=self.user,
            meeting_name="failed_recording.mp4",
            original_file="failed_recording.mp4",
            status="failed",
            duration=30.0,
            file_size=1024 * 1024,
        )

        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)

        ctx = response.context
        self.assertEqual(ctx["latest_meeting_status"], "FAILED")
        self.assertEqual(ctx["latest_meeting_status_class"], "text-danger")

        content = response.content.decode("utf-8")
        self.assertIn("FAILED", content)
        self.assertIn("text-danger", content)

    def test_dom_contracts_remain_intact(self):
        """
        All critical DOM IDs used by meeting.js must exist in the rendered output.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)
        content = response.content.decode("utf-8")

        required_dom_ids = [
            'id="meetingDropzone"',
            'id="btnBrowseFiles"',
            'id="meeting_file_input"',
            'id="meetingFilePreviewCard"',
            'id="btnAnalyzeMeeting"',
            'id="processingProgressBarContainer"',
            'id="meetingProgressBar"',
            'id="processingStageLabel"',
            'id="processingPercentLabel"',
            'id="processingStatusBadge"',
            'id="infoLastUsed"',
            'id="infoDetectedLanguage"',
            'id="infoInputFormat"',
            'id="infoRuntimeDuration"',
            'id="infoProcessingStatus"',
            'id="btnAnalyzeAnother"',
        ]

        for dom_id in required_dom_ids:
            self.assertIn(dom_id, content, f"Missing required DOM contract: {dom_id}")

    def test_home_context_user_without_any_ai_settings_record(self):
        """
        If a user has no AISettings record at all in the database,
        the view must gracefully fall back to empty provider and 'Not Configured'.
        """
        AISettings.objects.filter(user=self.user).delete()

        self.client.force_login(self.user)
        response = self.client.get(self.meeting_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertFalse(ctx["is_provider_configured"])
        self.assertEqual(ctx["active_provider"], "")
        self.assertEqual(ctx["active_provider_name"], "Not Configured")
        self.assertEqual(ctx["active_model"], "—")

    def test_meeting_js_live_sidebar_sync_contracts(self):
        """
        Verify that meeting.js implements Step 3 live sidebar synchronization:
        - syncSidebarMeetingInfo function exists and is defensive
        - updates #infoProcessingStatus across COMPLETED, FAILED, RUNNING, READY
        - updates #infoRuntimeDuration with formatted duration
        - guards against overwriting duration with undefined/null
        - updates #infoLastUsed on completion
        - pollMeetingStatus calls syncSidebarMeetingInfo
        - exposed via window.syncSidebarMeetingInfo
        """
        import os
        from django.conf import settings as django_settings

        js_path = os.path.join(django_settings.BASE_DIR, "meeting", "static", "meeting", "js", "meeting.js")
        self.assertTrue(os.path.exists(js_path))
        with open(js_path, "r", encoding="utf-8") as f:
            js_code = f.read()

        # Step 3 function definition
        self.assertIn("function syncSidebarMeetingInfo(data)", js_code)

        # Status mapping
        self.assertIn('infoStatus.textContent = "COMPLETED";', js_code)
        self.assertIn('infoStatus.textContent = "FAILED";', js_code)
        self.assertIn('infoStatus.textContent = "RUNNING";', js_code)
        self.assertIn('infoStatus.textContent = "READY";', js_code)

        # Duration safety check
        self.assertIn("data.duration !== undefined && data.duration !== null", js_code)
        self.assertIn("formatDurationSecs(numDuration)", js_code)

        # Last used update
        self.assertIn('data.status === "completed"', js_code)
        self.assertIn("getFormattedDate()", js_code)

        # Integration in polling loop
        self.assertIn("syncSidebarMeetingInfo(data);", js_code)

        # Window export
        self.assertIn("window.syncSidebarMeetingInfo = syncSidebarMeetingInfo;", js_code)

    def test_meeting_status_api_supplies_sidebar_sync_payload(self):
        """
        Verify that GET /meeting/status/<meeting_id>/ returns all necessary fields
        (status, duration, stage, progress_percentage) for live sidebar synchronization.
        """
        meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="test_sync.mp4",
            original_file="test_sync.mp4",
            status="processing",
            stage="extracting_audio",
            duration=85.0,
            file_size=1024 * 1024,
        )

        self.client.force_login(self.user)
        status_url = reverse("meeting_status_api", kwargs={"meeting_id": meeting.id})
        response = self.client.get(status_url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        m_data = data["data"]
        self.assertEqual(m_data["status"], "processing")
        self.assertEqual(m_data["stage"], "extracting_audio")
        self.assertEqual(m_data["duration"], 85.0)
        self.assertIn("progress_percentage", m_data)


