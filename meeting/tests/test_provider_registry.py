"""
Unit tests for ProviderRegistry, ProviderFactory, and BaseAIProvider contracts.
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
from meeting.providers.registry import (
    ProviderRegistry,
    ProviderNotFoundError,
)
from meeting.providers.factory import ProviderFactory


class DummyProvider(BaseAIProvider):
    """Dummy provider for testing registry without SDK dependencies."""

    def __init__(self, settings):
        self.settings = settings
        self.initialized = True

    def test_connection(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Connected")

    def discover_models(self):
        return [
            ModelDescriptor(
                id="dummy-model",
                display_name="Dummy Model",
                capabilities={ProviderCapability.TEXT_GENERATION, ProviderCapability.AUDIO_TRANSCRIPTION},
                status=ModelStatus.AVAILABLE,
            )
        ]

    def filter_compatible_models(self, models):
        return models

    def validate_model_access(self, model_id):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Ready", model_id=model_id)

    def quick_preflight_check(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Healthy")

    def generate_transcript(self, audio_source):
        return "Dummy transcript"

    def generate_report(self, transcript):
        return "Dummy report"

    def translate_error(self, exc):
        return ValidationResult(is_valid=False, status=ModelStatus.UNKNOWN, message=str(exc))


class ProviderRegistryTests(SimpleTestCase):
    """Tests for ProviderRegistry and ProviderFactory."""

    def setUp(self):
        self._saved_registry = dict(ProviderRegistry._registry)

    def tearDown(self):
        ProviderRegistry._registry = dict(self._saved_registry)

    def test_base_provider_contract_importable(self):
        """Confirm all base provider classes and enums are importable and structured."""
        self.assertIn(ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability)
        self.assertIn(ProviderCapability.TEXT_GENERATION, ProviderCapability)
        self.assertIn(DiscoverySource.LIVE_API, DiscoverySource)
        self.assertIn(DiscoverySource.CATALOG_FALLBACK, DiscoverySource)
        self.assertIn(ModelStatus.AVAILABLE, ModelStatus)
        self.assertIn(ModelStatus.UNAVAILABLE, ModelStatus)
        self.assertIn(ModelStatus.ACCESS_DENIED, ModelStatus)

        descriptor = ModelDescriptor(
            id="test-model",
            display_name="Test Model",
            capabilities={ProviderCapability.TEXT_GENERATION},
            source=DiscoverySource.LIVE_API,
            status=ModelStatus.AVAILABLE,
        )
        d_dict = descriptor.to_dict()
        self.assertEqual(d_dict["id"], "test-model")
        self.assertEqual(d_dict["status"], "AVAILABLE")

        result = ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="Success")
        r_dict = result.to_dict()
        self.assertTrue(r_dict["is_valid"])
        self.assertEqual(r_dict["status"], "AVAILABLE")

    def test_provider_registration_and_retrieval(self):
        """Test registering a provider and retrieving its class."""
        ProviderRegistry.register("dummy", DummyProvider, override=True)
        self.assertTrue(ProviderRegistry.is_registered("dummy"))
        self.assertEqual(ProviderRegistry.get("dummy"), DummyProvider)

    def test_case_insensitive_registration_and_lookup(self):
        """Test that provider identifiers are normalized case-insensitively."""
        ProviderRegistry.register("TestProvider", DummyProvider, override=True)
        self.assertTrue(ProviderRegistry.is_registered("testprovider"))
        self.assertTrue(ProviderRegistry.is_registered("TESTPROVIDER"))
        self.assertEqual(ProviderRegistry.get("testprovider"), DummyProvider)
        self.assertEqual(ProviderRegistry.get("TESTPROVIDER"), DummyProvider)

    def test_provider_listing(self):
        """Test listing registered providers."""
        ProviderRegistry.clear()
        ProviderRegistry.register("alpha", DummyProvider)
        ProviderRegistry.register("beta", DummyProvider)
        self.assertEqual(ProviderRegistry.list_providers(), ["alpha", "beta"])

    def test_unknown_provider_raises_clear_error(self):
        """Test that requesting an unregistered provider raises ProviderNotFoundError."""
        ProviderRegistry.clear()
        ProviderRegistry.register("gemini", DummyProvider)
        with self.assertRaises(ProviderNotFoundError) as ctx:
            ProviderRegistry.get("nonexistent_provider")
        self.assertIn("nonexistent_provider", str(ctx.exception))
        self.assertIn("gemini", str(ctx.exception))

    def test_registry_does_not_instantiate_sdk_on_listing(self):
        """Test that listing or checking registry does not instantiate classes."""
        class CountingDummy:
            instance_count = 0
            def __init__(self, settings):
                CountingDummy.instance_count += 1

        ProviderRegistry.register("counting", CountingDummy, override=True)
        self.assertTrue(ProviderRegistry.is_registered("counting"))
        providers = ProviderRegistry.list_providers()
        self.assertIn("counting", providers)
        self.assertEqual(CountingDummy.instance_count, 0)

    def test_provider_factory_creation(self):
        """Test that ProviderFactory instantiates the provider with settings."""
        ProviderRegistry.register("dummy_factory", DummyProvider, override=True)
        settings = {"provider": "dummy_factory", "api_key": "test_key", "model_name": "test_model"}
        instance = ProviderFactory.create_provider("dummy_factory", settings)
        self.assertIsInstance(instance, DummyProvider)
        self.assertEqual(instance.settings["api_key"], "test_key")

    def test_provider_factory_safe_creation(self):
        """Test that create_provider_safe returns None for unknown providers."""
        result = ProviderFactory.create_provider_safe("unknown_provider", {})
        self.assertIsNone(result)

    def test_default_gemini_registered(self):
        """Test that the default Gemini provider is registered in the application."""
        from meeting.providers import ProviderRegistry as PR
        self.assertTrue(PR.is_registered("gemini"))
