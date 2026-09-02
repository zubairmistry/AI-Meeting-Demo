"""
Unit tests for ModelValidationService and pre-flight health checks.
"""

from django.test import SimpleTestCase

from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.services.model_validation_service import ModelValidationService
from meeting.providers.gemini_provider import GeminiProvider


class ConfigurableMockProvider(BaseAIProvider):
    """Mock provider with configurable responses and access tracking."""

    def __init__(self, model_name="test-model", validation_map=None):
        self.model_name = model_name
        self.validation_map = validation_map or {}
        self.probed_models = []
        self.preflight_called = False

    def test_connection(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="OK")

    def discover_models(self):
        return []

    def filter_compatible_models(self, models):
        return models

    def validate_model_access(self, model_id):
        self.probed_models.append(model_id)
        if model_id in self.validation_map:
            return self.validation_map[model_id]
        return ValidationResult(
            is_valid=True,
            status=ModelStatus.AVAILABLE,
            message=f"Model '{model_id}' is ready.",
            model_id=model_id,
        )

    def quick_preflight_check(self):
        self.preflight_called = True
        return self.validate_model_access(self.model_name)

    def generate_transcript(self, audio_source):
        return "transcript"

    def generate_report(self, transcript):
        return "report"

    def translate_error(self, exc):
        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=str(exc),
            model_id=self.model_name,
        )


class ModelValidationServiceTests(SimpleTestCase):
    """Tests for ModelValidationService."""

    def test_valid_model_validation_returns_available(self):
        """Test that validating a valid model returns is_valid=True and status=AVAILABLE."""
        provider = ConfigurableMockProvider()
        result = ModelValidationService.validate_model(provider, "gemini-2.5-flash")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.status, ModelStatus.AVAILABLE)
        self.assertEqual(result.model_id, "gemini-2.5-flash")

    def test_invalid_api_credentials_returns_access_denied(self):
        """Test that invalid credentials normalize to ACCESS_DENIED."""
        provider = ConfigurableMockProvider(
            validation_map={
                "model-a": ValidationResult(
                    is_valid=False,
                    status=ModelStatus.ACCESS_DENIED,
                    message="Invalid API Key",
                    model_id="model-a",
                )
            }
        )
        result = ModelValidationService.validate_model(provider, "model-a")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.ACCESS_DENIED)

    def test_model_not_found_returns_unavailable(self):
        """Test that a 404/not found model returns UNAVAILABLE."""
        provider = ConfigurableMockProvider(
            validation_map={
                "deprecated-model": ValidationResult(
                    is_valid=False,
                    status=ModelStatus.UNAVAILABLE,
                    message="Model no longer available",
                    model_id="deprecated-model",
                )
            }
        )
        result = ModelValidationService.validate_model(provider, "deprecated-model")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.UNAVAILABLE)

    def test_quota_exhaustion_returns_quota_exceeded(self):
        """Test that quota depletion returns QUOTA_EXCEEDED."""
        provider = ConfigurableMockProvider(
            validation_map={
                "model-b": ValidationResult(
                    is_valid=False,
                    status=ModelStatus.QUOTA_EXCEEDED,
                    message="Account quota exhausted",
                    model_id="model-b",
                )
            }
        )
        result = ModelValidationService.validate_model(provider, "model-b")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.QUOTA_EXCEEDED)

    def test_rate_limiting_returns_rate_limited(self):
        """Test that rate limiting returns RATE_LIMITED."""
        provider = ConfigurableMockProvider(
            validation_map={
                "model-c": ValidationResult(
                    is_valid=False,
                    status=ModelStatus.RATE_LIMITED,
                    message="Rate limit reached",
                    model_id="model-c",
                )
            }
        )
        result = ModelValidationService.validate_model(provider, "model-c")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.RATE_LIMITED)

    def test_temporary_provider_outage_returns_temporarily_unavailable(self):
        """Test that high demand / 503 errors return TEMPORARILY_UNAVAILABLE."""
        provider = ConfigurableMockProvider(
            validation_map={
                "model-d": ValidationResult(
                    is_valid=False,
                    status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                    message="High demand",
                    model_id="model-d",
                )
            }
        )
        result = ModelValidationService.validate_model(provider, "model-d")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.TEMPORARILY_UNAVAILABLE)

    def test_unknown_provider_error_returns_unknown(self):
        """Test that unclassified errors return UNKNOWN."""
        provider = ConfigurableMockProvider(
            validation_map={
                "model-e": ValidationResult(
                    is_valid=False,
                    status=ModelStatus.UNKNOWN,
                    message="Network error",
                    model_id="model-e",
                )
            }
        )
        result = ModelValidationService.validate_model(provider, "model-e")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.status, ModelStatus.UNKNOWN)

    def test_unvalidated_discovered_model_remains_untested(self):
        """Test that discovered models are not modified if not targeted for validation."""
        provider = ConfigurableMockProvider()
        m1 = ModelDescriptor(
            id="m1",
            display_name="M1",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )
        m2 = ModelDescriptor(
            id="m2",
            display_name="M2",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )

        validated_list = ModelValidationService.validate_discovered_models(
            provider, [m1, m2], selected_model_id="m1"
        )
        self.assertEqual(validated_list[0].status, ModelStatus.AVAILABLE)
        self.assertEqual(validated_list[1].status, ModelStatus.COMPATIBLE_UNTESTED)

    def test_selective_validation_probes_only_one_model(self):
        """Test that validate_discovered_models probes ONLY the target model and not the entire list."""
        provider = ConfigurableMockProvider()
        models = [
            ModelDescriptor(
                id=f"gemini-{i}",
                display_name=f"Gemini {i}",
                capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            )
            for i in range(5)
        ]

        ModelValidationService.validate_discovered_models(
            provider, models, selected_model_id="gemini-2"
        )
        self.assertEqual(provider.probed_models, ["gemini-2"])
        self.assertEqual(len(provider.probed_models), 1)

    def test_incompatible_models_rejected_before_validation(self):
        """Test that incompatible models are filtered out and never probed."""
        provider = ConfigurableMockProvider()
        incompatible = ModelDescriptor(
            id="text-only",
            display_name="Text Only",
            capabilities={ProviderCapability.TEXT_GENERATION},
        )
        result = ModelValidationService.validate_discovered_models(
            provider, [incompatible], selected_model_id="text-only"
        )
        self.assertEqual(len(result), 0)
        self.assertEqual(len(provider.probed_models), 0)

    def test_fallback_catalog_model_can_become_available_while_preserving_source(self):
        """Test that a fallback catalog model becomes AVAILABLE without changing its DiscoverySource."""
        provider = ConfigurableMockProvider()
        catalog_model = ModelDescriptor(
            id="fallback-model",
            display_name="Fallback Model",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            source=DiscoverySource.CATALOG_FALLBACK,
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )

        result = ModelValidationService.validate_discovered_models(
            provider, [catalog_model], selected_model_id="fallback-model"
        )
        self.assertEqual(result[0].status, ModelStatus.AVAILABLE)
        # Source must strictly remain CATALOG_FALLBACK
        self.assertEqual(result[0].source, DiscoverySource.CATALOG_FALLBACK)

    def test_generic_service_does_not_import_provider_sdks(self):
        """Verify that meeting.services.model_validation_service contains no provider SDK imports."""
        import meeting.services.model_validation_service as mvs
        modules = [getattr(mvs, attr) for attr in dir(mvs)]
        for mod in modules:
            if hasattr(mod, "__name__"):
                self.assertNotIn("google.genai", mod.__name__)
                self.assertNotIn("openai", mod.__name__)
                self.assertNotIn("anthropic", mod.__name__)

    def test_preflight_check_invokes_provider_quick_check(self):
        """Test that preflight_check invokes quick_preflight_check on provider."""
        provider = ConfigurableMockProvider(model_name="active-model")
        res = ModelValidationService.preflight_check(provider)
        self.assertTrue(res.is_valid)
        self.assertTrue(provider.preflight_called)
        self.assertEqual(provider.probed_models, ["active-model"])

    def test_invalid_input_handling(self):
        """Test safe handling when provider or model_id is invalid."""
        # Non-provider object
        res1 = ModelValidationService.validate_model(None, "model-x")
        self.assertFalse(res1.is_valid)
        self.assertEqual(res1.status, ModelStatus.UNKNOWN)

        # Empty model ID
        provider = ConfigurableMockProvider()
        res2 = ModelValidationService.validate_model(provider, "")
        self.assertFalse(res2.is_valid)
        self.assertEqual(res2.status, ModelStatus.UNAVAILABLE)

        res3 = ModelValidationService.preflight_check("not-a-provider")
        self.assertFalse(res3.is_valid)
        self.assertEqual(res3.status, ModelStatus.UNKNOWN)

    def test_gemini_provider_error_translation_integration(self):
        """Test that GeminiProvider translates simulated exceptions accurately."""
        provider = GeminiProvider({"provider": "gemini", "api_key": "dummy", "model_name": "test-m"})
        
        class FakeAPIError(Exception):
            def __init__(self, code, message):
                super().__init__(message)
                self.code = code

        e_404 = FakeAPIError(404, "models/test-m is not found")
        res_404 = provider.translate_error(e_404)
        self.assertEqual(res_404.status, ModelStatus.UNAVAILABLE)

        e_403 = FakeAPIError(403, "PERMISSION_DENIED for test-m")
        res_403 = provider.translate_error(e_403)
        self.assertEqual(res_403.status, ModelStatus.ACCESS_DENIED)

        e_429_quota = FakeAPIError(429, "RESOURCE_EXHAUSTED: quota exceeded")
        res_quota = provider.translate_error(e_429_quota)
        self.assertEqual(res_quota.status, ModelStatus.QUOTA_EXCEEDED)

        e_429_rate = FakeAPIError(429, "RESOURCE_EXHAUSTED: rate limit")
        res_rate = provider.translate_error(e_429_rate)
        self.assertEqual(res_rate.status, ModelStatus.RATE_LIMITED)

        e_503 = FakeAPIError(503, "UNAVAILABLE: high demand")
        res_503 = provider.translate_error(e_503)
        self.assertEqual(res_503.status, ModelStatus.TEMPORARILY_UNAVAILABLE)
