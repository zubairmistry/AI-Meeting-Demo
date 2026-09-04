from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.template.loader import render_to_string


class MeetingPageUITestCase(TestCase):
    """Deep verification test suite for Phase 2 UI Refinements: Unified Theme Selector & 3-Column Workspace."""

    def setUp(self):
        self.client = Client()
        self.meeting_url = reverse("meeting")
        self.login_url = reverse("login")
        self.register_url = reverse("register")
        self.dashboard_url = reverse("dashboard")
        self.settings_url = reverse("settings")
        self.test_user = User.objects.create_user(
            username="testuser@example.com",
            email="testuser@example.com",
            password="TestPassword2026!",
            first_name="Jane",
        )

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated requests to meeting page must redirect to login."""
        response = self.client.get(self.meeting_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.login_url, response.url)

    def test_meeting_page_loads_for_authenticated_user(self):
        """Authenticated user successfully accesses the meeting workspace."""
        self.client.login(username="testuser@example.com", password="TestPassword2026!")
        response = self.client.get(self.meeting_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "meeting/index.html")
        self.assertTemplateUsed(response, "meeting/base.html")

    def test_upload_form_contract_and_csrf(self):
        """Upload form must have POST, multipart/form-data, csrf token, and name='meeting_file'."""
        self.client.login(username="testuser@example.com", password="TestPassword2026!")
        response = self.client.get(self.meeting_url)
        content = response.content.decode("utf-8")

        self.assertIn('method="POST"', content)
        self.assertIn('enctype="multipart/form-data"', content)
        self.assertIn('name="meeting_file"', content)
        self.assertIn('csrfmiddlewaretoken', content)
        self.assertIn('id="meeting_file_input"', content)

    def test_three_column_architecture_elements_exist(self):
        """Meeting page must contain the Left Sidebar, Center Workspace, and Right Sidebar elements."""
        self.client.login(username="testuser@example.com", password="TestPassword2026!")
        response = self.client.get(self.meeting_url)
        content = response.content.decode("utf-8")

        # Left Sidebar elements
        self.assertIn('AI Provider Status', content)
        self.assertIn('Storage Used', content)
        self.assertIn('Need Help?', content)
        self.assertIn('Gemini', content)
        self.assertIn('OpenAI', content)
        self.assertIn('Claude', content)
        self.assertIn('New Meeting', content)
        self.assertIn('Dashboard', content)
        self.assertIn('Meetings', content)
        self.assertIn('Calendar', content)
        self.assertIn('Reports', content)
        self.assertIn('Settings', content)
        self.assertIn('AI Providers', content)
        self.assertIn('Activity Logs', content)

        # Center Workspace elements
        self.assertIn('id="meetingDropzone"', content)
        self.assertIn('id="btnBrowseFiles"', content)
        self.assertIn('id="meetingFilePreviewCard"', content)
        self.assertIn('id="btnAnalyzeMeeting"', content)
        self.assertIn('meeting-stepper', content)
        self.assertIn('1. Uploading', content)
        self.assertIn('2. Pre-flight', content)
        self.assertIn('3. Extraction', content)
        self.assertIn('4. Transcription', content)
        self.assertIn('5. AI Analysis', content)
        self.assertIn('6. Report', content)
        self.assertIn('7. Cleanup', content)
        self.assertIn('8. Completed', content)
        self.assertIn('Live Activity Log', content)

        # Right Sidebar elements
        self.assertIn('Meeting Information', content)
        self.assertIn('Last Used', content)
        self.assertIn('Detected Language', content)
        self.assertIn('Input Format', content)
        self.assertIn('Runtime Duration', content)
        self.assertIn('Processing Status', content)
        self.assertIn('Download Reports', content)
        self.assertIn('Download TXT', content)
        self.assertIn('Download Word', content)
        self.assertIn('Send via Outlook', content)
        self.assertIn('id="btnAnalyzeAnother"', content)

    def test_unified_theme_selector_across_all_pages(self):
        """All pages (Meeting, Dashboard, Settings, Login, Register) use the unified theme selector design."""
        self.client.login(username="testuser@example.com", password="TestPassword2026!")

        # Meeting page
        meeting_resp = self.client.get(self.meeting_url)
        content_meeting = meeting_resp.content.decode("utf-8")
        self.assertIn("theme-pill-btn", content_meeting)
        self.assertIn("theme-icon-orb", content_meeting)
        self.assertIn('data-theme-val="classic"', content_meeting)
        self.assertIn('data-theme-val="light"', content_meeting)
        self.assertIn('data-theme-val="dark"', content_meeting)
        self.assertIn('data-theme-val="neon"', content_meeting)
        self.assertIn('data-theme-val="enterprise"', content_meeting)

        # Dashboard page
        dash_resp = self.client.get(self.dashboard_url)
        content_dash = dash_resp.content.decode("utf-8")
        self.assertIn("theme-pill-btn", content_dash)
        self.assertIn("theme-icon-orb", content_dash)

        # Settings page
        settings_resp = self.client.get(self.settings_url)
        content_settings = settings_resp.content.decode("utf-8")
        self.assertIn("theme-pill-btn", content_settings)
        self.assertIn("theme-icon-orb", content_settings)

        # Logout to test auth pages
        self.client.logout()

        # Login page
        login_resp = self.client.get(self.login_url)
        content_login = login_resp.content.decode("utf-8")
        self.assertIn("theme-pill-btn", content_login)
        self.assertIn("theme-icon-orb", content_login)

        # Register page
        reg_resp = self.client.get(self.register_url)
        content_reg = reg_resp.content.decode("utf-8")
        self.assertIn("theme-pill-btn", content_reg)
        self.assertIn("theme-icon-orb", content_reg)

    def test_login_and_register_share_unified_ai_visual_nodes(self):
        """Login and Register pages share the exact same 4-node animated 3D AI visual architecture."""
        login_resp = self.client.get(self.login_url)
        content_login = login_resp.content.decode("utf-8")

        reg_resp = self.client.get(self.register_url)
        content_reg = reg_resp.content.decode("utf-8")

        for node_class in ["node-audio", "node-ai", "node-intelligence", "node-report"]:
            self.assertIn(node_class, content_login)
            self.assertIn(node_class, content_reg)

        self.assertIn("ai-core-hub", content_login)
        self.assertIn("ai-core-hub", content_reg)

    def test_transcript_and_report_rendered_when_provided(self):
        """Transcript and Report sections render dynamically when context contains data."""
        self.client.login(username="testuser@example.com", password="TestPassword2026!")
        response = self.client.get(self.meeting_url)
        content = response.content.decode("utf-8")

        # Initial GET without processing does not render output blocks
        self.assertNotIn('id="meetingTranscriptContent"', content)
        self.assertNotIn('id="meetingReportContent"', content)

        # Rendering with mock context
        context = {
            "status": "Completed successfully",
            "transcript": "Speaker 1: Welcome to the quarterly roadmap review.",
            "report": "Executive Summary: Strong Q3 progress with all key deliverables on track.",
            "request": response.wsgi_request,
            "user": self.test_user,
        }
        rendered = render_to_string("meeting/index.html", context)
        self.assertIn('id="meetingTranscriptContent"', rendered)
        self.assertIn('id="meetingReportContent"', rendered)
        self.assertIn('id="btnCopyTranscript"', rendered)
        self.assertIn('id="btnCopyReport"', rendered)
        self.assertIn('id="btnDownloadTranscriptTxt"', rendered)
        self.assertIn('id="btnDownloadReportTxt"', rendered)
        self.assertIn('id="btnAnalyzeAnother"', rendered)
        self.assertIn("Speaker 1: Welcome to the quarterly roadmap review.", rendered)
        self.assertIn("Executive Summary: Strong Q3 progress", rendered)
