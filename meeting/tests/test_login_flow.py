from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User


class LoginPageUITestCase(TestCase):
    """Test suite for Phase 2 Section 2: Premium Login Page UI & Authentication Flow."""

    def setUp(self):
        self.client = Client()
        self.login_url = reverse("login")
        self.register_url = reverse("register")
        self.dashboard_url = reverse("dashboard")
        self.test_user = User.objects.create_user(
            username="alex@example.com",
            email="alex@example.com",
            password="SecurePassword2026!",
            first_name="Alex",
        )

    def test_login_page_loads_successfully(self):
        """Login page should load with status 200 and correct template."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "meeting/login.html")
        self.assertTemplateUsed(response, "meeting/base_auth.html")

    def test_login_page_contains_theme_selector(self):
        """Login page should render the 5 enterprise themes."""
        response = self.client.get(self.login_url)
        content = response.content.decode("utf-8")
        self.assertIn("themeSelectorBtn", content)
        self.assertIn('data-theme-val="classic"', content)
        self.assertIn('data-theme-val="light"', content)
        self.assertIn('data-theme-val="dark"', content)
        self.assertIn('data-theme-val="neon"', content)
        self.assertIn('data-theme-val="enterprise"', content)

    def test_login_page_contains_ai_visual(self):
        """Login page should render the brand AI visual component."""
        response = self.client.get(self.login_url)
        content = response.content.decode("utf-8")
        self.assertIn("aiVisualContainer", content)
        self.assertIn("node-audio", content)
        self.assertIn("node-report", content)
        self.assertIn("Audio Ingestion", content)
        self.assertIn("Executive Insights", content)

    def test_login_page_contains_form_fields_and_button(self):
        """Login page should render email and password inputs and 'Sign In' button."""
        response = self.client.get(self.login_url)
        content = response.content.decode("utf-8")
        self.assertIn('name="email"', content)
        self.assertIn('name="password"', content)
        self.assertIn("Sign In", content)
        self.assertIn("password-toggle", content)

    def test_login_with_invalid_credentials(self):
        """Submitting invalid credentials displays an error and does not log in."""
        response = self.client.post(
            self.login_url,
            {
                "email": "alex@example.com",
                "password": "WrongPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_nonexistent_user(self):
        """Submitting non-existent email returns generic auth error."""
        response = self.client.post(
            self.login_url,
            {
                "email": "nobody@example.com",
                "password": "RandomPassword123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_flow(self):
        """Valid credentials authenticate user and redirect to dashboard."""
        response = self.client.post(
            self.login_url,
            {
                "email": "alex@example.com",
                "password": "SecurePassword2026!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, self.dashboard_url)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.test_user.id)

    def test_authenticated_user_redirected_from_login(self):
        """Logged-in users visiting /login/ should be redirected to dashboard."""
        self.client.login(username="alex@example.com", password="SecurePassword2026!")
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, self.dashboard_url)
