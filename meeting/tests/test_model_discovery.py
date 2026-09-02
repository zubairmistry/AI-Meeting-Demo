"""
Unit tests for ModelDiscoveryService and capability-based filtering.
"""

import sys
from django.test import SimpleTestCase

from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)
from meeting.services.model_discovery_service import (
    ModelDiscoveryService,
    REQUIRED_MEETING_CAPABILITIES,
)
from meeting.providers.gemini_provider import GeminiProvider


class MockProvider(BaseAIProvider):
    """Mock provider with controllable discovery outputs for testing."""

    def __init__(self, models_to_return=None):
        self.models_to_return = models_to_return or []

    def test_connection(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="OK")

    def discover_models(self):
        return list(self.models_to_return)

    def filter_compatible_models(self, models):
        return ModelDiscoveryService.filter_compatible_models(models)

    def validate_model_access(self, model_id):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="OK", model_id=model_id)

    def quick_preflight_check(self):
        return ValidationResult(is_valid=True, status=ModelStatus.AVAILABLE, message="OK")

    def generate_transcript(self, audio_source):
        return "transcript"

    def generate_report(self, transcript):
        return "report"

    def translate_error(self, exc):
        return ValidationResult(is_valid=False, status=ModelStatus.UNKNOWN, message=str(exc))


class ModelDiscoveryServiceTests(SimpleTestCase):
    """Tests for generic ModelDiscoveryService."""

    def test_fully_compatible_model_accepted(self):
        """Test that a model with AUDIO_TRANSCRIPTION + TEXT_GENERATION is compatible."""
        model = ModelDescriptor(
            id="audio-and-text-model",
            display_name="Audio & Text Model",
            capabilities={
                ProviderCapability.AUDIO_TRANSCRIPTION,
                ProviderCapability.TEXT_GENERATION,
            },
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )
        result = ModelDiscoveryService.filter_compatible_models([model])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "audio-and-text-model")

    def test_missing_audio_transcription_rejected(self):
        """Test that a model with only TEXT_GENERATION is rejected."""
        model = ModelDescriptor(
            id="text-only-model",
            display_name="Text Only Model",
            capabilities={ProviderCapability.TEXT_GENERATION},
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )
        result = ModelDiscoveryService.filter_compatible_models([model])
        self.assertEqual(len(result), 0)

    def test_missing_text_generation_rejected(self):
        """Test that a model with only AUDIO_TRANSCRIPTION is rejected."""
        model = ModelDescriptor(
            id="audio-only-model",
            display_name="Audio Only Model",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION},
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )
        result = ModelDiscoveryService.filter_compatible_models([model])
        self.assertEqual(len(result), 0)

    def test_optional_capabilities_do_not_cause_rejection(self):
        """Test that optional capabilities (NATIVE_AUDIO_INPUT, STREAMING) do not disqualify a model."""
        model = ModelDescriptor(
            id="rich-multimodal-model",
            display_name="Rich Multimodal Model",
            capabilities={
                ProviderCapability.AUDIO_TRANSCRIPTION,
                ProviderCapability.TEXT_GENERATION,
                ProviderCapability.NATIVE_AUDIO_INPUT,
                ProviderCapability.STREAMING,
            },
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )
        result = ModelDiscoveryService.filter_compatible_models([model])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "rich-multimodal-model")

    def test_model_metadata_survives_filtering(self):
        """Test that all ModelDescriptor metadata attributes survive compatibility filtering intact."""
        model = ModelDescriptor(
            id="meta-model",
            display_name="Meta Model Display",
            capabilities={
                ProviderCapability.AUDIO_TRANSCRIPTION,
                ProviderCapability.TEXT_GENERATION,
            },
            source=DiscoverySource.LIVE_API,
            status=ModelStatus.COMPATIBLE_UNTESTED,
            status_message="Ready for testing",
            quality_score=92,
            speed_score=88,
            is_recommended=True,
            context_window=200000,
        )
        filtered = ModelDiscoveryService.filter_compatible_models([model])
        self.assertEqual(len(filtered), 1)
        m = filtered[0]
        self.assertEqual(m.id, "meta-model")
        self.assertEqual(m.display_name, "Meta Model Display")
        self.assertEqual(m.source, DiscoverySource.LIVE_API)
        self.assertEqual(m.status, ModelStatus.COMPATIBLE_UNTESTED)
        self.assertEqual(m.status_message, "Ready for testing")
        self.assertEqual(m.quality_score, 92)
        self.assertEqual(m.speed_score, 88)
        self.assertTrue(m.is_recommended)
        self.assertEqual(m.context_window, 200000)

    def test_live_api_and_catalog_fallback_distinguishable(self):
        """Test that DiscoverySource.LIVE_API and CATALOG_FALLBACK are preserved accurately."""
        live_model = ModelDescriptor(
            id="live-model",
            display_name="Live Model",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            source=DiscoverySource.LIVE_API,
        )
        catalog_model = ModelDescriptor(
            id="catalog-model",
            display_name="Catalog Model",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            source=DiscoverySource.CATALOG_FALLBACK,
        )
        result = ModelDiscoveryService.filter_compatible_models([live_model, catalog_model])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].source, DiscoverySource.LIVE_API)
        self.assertEqual(result[1].source, DiscoverySource.CATALOG_FALLBACK)

    def test_compatible_untested_status_not_auto_converted_to_available(self):
        """Test that discovery does not falsely convert COMPATIBLE_UNTESTED to AVAILABLE."""
        model = ModelDescriptor(
            id="untested-model",
            display_name="Untested Model",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            status=ModelStatus.COMPATIBLE_UNTESTED,
        )
        result = ModelDiscoveryService.filter_compatible_models([model])
        self.assertEqual(result[0].status, ModelStatus.COMPATIBLE_UNTESTED)
        self.assertNotEqual(result[0].status, ModelStatus.AVAILABLE)

    def test_generic_service_does_not_import_provider_sdks(self):
        """Test that meeting.services.model_discovery_service does not import google.genai or other SDKs."""
        import meeting.services.model_discovery_service as mds
        service_modules = [getattr(mds, attr) for attr in dir(mds)]
        for mod in service_modules:
            if hasattr(mod, "__name__"):
                self.assertNotIn("google.genai", mod.__name__)
                self.assertNotIn("openai", mod.__name__)
                self.assertNotIn("anthropic", mod.__name__)

    def test_deterministic_candidate_ranking(self):
        """Test that models are ranked deterministically by recommendation status and composite score."""
        m_standard = ModelDescriptor(
            id="standard-model",
            display_name="Standard",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            quality_score=80,
            speed_score=80,
            is_recommended=False,
        )
        m_pro = ModelDescriptor(
            id="pro-model",
            display_name="Pro",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            quality_score=95,
            speed_score=70,
            is_recommended=False,
        )
        m_rec = ModelDescriptor(
            id="rec-model",
            display_name="Recommended",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            quality_score=90,
            speed_score=90,
            is_recommended=True,
        )

        ranked = ModelDiscoveryService.rank_compatible_models([m_standard, m_pro, m_rec])
        self.assertEqual(ranked[0].id, "rec-model")
        # Pro has (95*0.6 + 70*0.4) = 57 + 28 = 85. Standard has (80*0.6 + 80*0.4) = 80.
        self.assertEqual(ranked[1].id, "pro-model")
        self.assertEqual(ranked[2].id, "standard-model")

    def test_get_recommended_model(self):
        """Test retrieving the top recommended model from a candidate list."""
        m1 = ModelDescriptor(
            id="m1",
            display_name="M1",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            quality_score=50,
            speed_score=50,
        )
        m2 = ModelDescriptor(
            id="m2",
            display_name="M2",
            capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
            quality_score=90,
            speed_score=90,
            is_recommended=True,
        )
        recommended = ModelDiscoveryService.get_recommended_model([m1, m2])
        self.assertIsNotNone(recommended)
        self.assertEqual(recommended.id, "m2")

    def test_discover_and_filter_orchestration(self):
        """Test the end-to-end orchestration helper discover_and_filter."""
        provider = MockProvider(
            models_to_return=[
                ModelDescriptor(
                    id="valid-1",
                    display_name="Valid 1",
                    capabilities={ProviderCapability.AUDIO_TRANSCRIPTION, ProviderCapability.TEXT_GENERATION},
                ),
                ModelDescriptor(
                    id="invalid-1",
                    display_name="Invalid 1",
                    capabilities={ProviderCapability.TEXT_GENERATION},
                ),
            ]
        )
        result = ModelDiscoveryService.discover_and_filter(provider)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "valid-1")

    def test_gemini_fallback_catalog_when_unconfigured(self):
        """Test that GeminiProvider without an active API key returns the fallback catalog."""
        provider = GeminiProvider({"provider": "gemini", "api_key": ""})
        models = provider.discover_models()
        self.assertTrue(len(models) > 0)
        # All fallback models should be marked CATALOG_FALLBACK
        for m in models:
            self.assertEqual(m.source, DiscoverySource.CATALOG_FALLBACK)
            self.assertEqual(m.status, ModelStatus.COMPATIBLE_UNTESTED)
