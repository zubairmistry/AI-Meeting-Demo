from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User


class RegisterPageUITestCase(TestCase):
    """Test suite for Phase 2 Section 1: Premium Register Page UI & Flow."""

    def setUp(self):
        self.client = Client()
        self.register_url = reverse("register")
        self.login_url = reverse("login")
        self.dashboard_url = reverse("dashboard")

    def test_register_page_loads_successfully(self):
        """Register page should load with status 200 and correct template."""
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "meeting/register.html")
        self.assertTemplateUsed(response, "meeting/base_auth.html")

    def test_register_page_contains_theme_selector(self):
        """Register page should render the 5 enterprise themes."""
        response = self.client.get(self.register_url)
        content = response.content.decode("utf-8")
        self.assertIn("themeSelectorBtn", content)
        self.assertIn('data-theme-val="classic"', content)
        self.assertIn('data-theme-val="light"', content)
        self.assertIn('data-theme-val="dark"', content)
        self.assertIn('data-theme-val="neon"', content)
        self.assertIn('data-theme-val="enterprise"', content)

    def test_register_page_contains_ai_visual_nodes(self):
        """Register page should render the 4 AI process nodes."""
        response = self.client.get(self.register_url)
        content = response.content.decode("utf-8")
        self.assertIn("aiVisualContainer", content)
        self.assertIn("node-audio", content)
        self.assertIn("node-ai", content)
        self.assertIn("node-intelligence", content)
        self.assertIn("node-report", content)
        self.assertIn("Audio Ingestion", content)
        self.assertIn("Speech-to-Text", content)
        self.assertIn("Cognitive Synthesis", content)
        self.assertIn("Executive Insights", content)

    def test_register_page_contains_form_fields_and_button(self):
        """Register page should render form inputs and 'Get Started with AI' button."""
        response = self.client.get(self.register_url)
        content = response.content.decode("utf-8")
        self.assertIn('name="first_name"', content)
        self.assertIn('name="email"', content)
        self.assertIn('name="password1"', content)
        self.assertIn('name="password2"', content)
        self.assertIn("Get Started with AI", content)
        self.assertIn("password-toggle", content)

    def test_registration_short_name_error(self):
        """Names with less than 3 chars should trigger a validation error."""
        response = self.client.post(
            self.register_url,
            {
                "first_name": "Al",
                "email": "alex@example.com",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Name must contain at least 3 characters.")
        self.assertFalse(User.objects.filter(email="alex@example.com").exists())

    def test_registration_password_mismatch_error(self):
        """Mismatched passwords should trigger a validation error."""
        response = self.client.post(
            self.register_url,
            {
                "first_name": "Alexander",
                "email": "alex@example.com",
                "password1": "ComplexPass123!",
                "password2": "DifferentPass456!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="alex@example.com").exists())

    def test_registration_duplicate_email_error(self):
        """Existing email registration should trigger a validation error."""
        User.objects.create_user(
            username="existing@example.com",
            email="existing@example.com",
            password="Password123!",
        )

        response = self.client.post(
            self.register_url,
            {
                "first_name": "Existing User",
                "email": "existing@example.com",
                "password1": "Password123!",
                "password2": "Password123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This email is already registered.")

    def test_successful_registration_flow(self):
        """Valid registration creates the user and redirects to dashboard."""
        response = self.client.post(
            self.register_url,
            {
                "first_name": "Jane Doe",
                "email": "janedoe@example.com",
                "password1": "SecurePass2026!",
                "password2": "SecurePass2026!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, self.dashboard_url)
        self.assertTrue(User.objects.filter(email="janedoe@example.com").exists())
        user = User.objects.get(email="janedoe@example.com")
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Doe")
