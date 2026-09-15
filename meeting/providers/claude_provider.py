"""
meeting/providers/claude_provider.py

Anthropic Claude Provider implementation conforming to BaseAIProvider.
Supports lazy SDK loading, static fallback catalog discovery, and error translation.
"""

import logging
from typing import List, Dict, Any, Optional

from meeting.prompts.meeting_report_prompt import MEETING_REPORT_PROMPT
from meeting.providers.base_provider import (
    BaseAIProvider,
    ProviderCapability,
    DiscoverySource,
    ModelStatus,
    ModelDescriptor,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Fallback catalog for Anthropic Claude
FALLBACK_CLAUDE_MODELS: List[Dict[str, Any]] = [
    {
        "id": "claude-3-5-sonnet-20241022",
        "display_name": "Claude 3.5 Sonnet (Recommended)",
        "quality_score": 95,
        "speed_score": 90,
        "is_recommended": True,
        "context_window": 200000,
    },
    {
        "id": "claude-3-5-haiku-20241022",
        "display_name": "Claude 3.5 Haiku",
        "quality_score": 85,
        "speed_score": 95,
        "is_recommended": False,
        "context_window": 200000,
    },
    {
        "id": "claude-3-opus-20240229",
        "display_name": "Claude 3 Opus",
        "quality_score": 95,
        "speed_score": 70,
        "is_recommended": False,
        "context_window": 200000,
    },
]


class ClaudeProvider(BaseAIProvider):
    """
    Anthropic Claude AI Provider.
    Implements reasoning, report generation, model discovery, and access verification.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        cfg = settings or {}
        self.provider = cfg.get("provider", "claude")
        self.api_key = cfg.get("api_key", "")
        self.model_name = cfg.get("model_name", "claude-3-5-sonnet-20241022")
        self.client = None

    def _ensure_client(self):
        if not self.api_key:
            raise ValueError("Anthropic API key is not configured.")
        if not self.client:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError(
                    "The 'anthropic' package is not installed. Please install it to use live Anthropic Claude features."
                )

    def test_connection(self) -> ValidationResult:
        """Tests provider reachability and credentials."""
        if not self.api_key:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Anthropic API key is not configured.",
                model_id=self.model_name,
            )
        try:
            self._ensure_client()
            message = self.client.messages.create(
                model=self.model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "Reply with one word: Connected"}]
            )
            reply = message.content[0].text if message.content else "Connected"
            return ValidationResult(
                is_valid=True,
                status=ModelStatus.AVAILABLE,
                message=reply,
                model_id=self.model_name,
            )
        except Exception as e:
            return self.translate_error(e)

    def discover_models(self) -> List[ModelDescriptor]:
        """Discovers Claude models or returns curated fallback catalog."""
        try:
            self._ensure_client()
            if hasattr(self.client, "models") and hasattr(self.client.models, "list"):
                models_pager = self.client.models.list()
                descriptors = []
                for m in models_pager:
                    model_id = getattr(m, "id", "")
                    if not model_id:
                        continue
                    display_name = getattr(m, "display_name", model_id)
                    is_rec = "3-5-sonnet" in model_id.lower()
                    descriptors.append(
                        ModelDescriptor(
                            id=model_id,
                            display_name=display_name,
                            capabilities={ProviderCapability.TEXT_GENERATION},
                            source=DiscoverySource.LIVE_API,
                            status=ModelStatus.COMPATIBLE_UNTESTED,
                            quality_score=95 if "sonnet" in model_id or "opus" in model_id else 85,
                            speed_score=90,
                            is_recommended=is_rec,
                            context_window=200000,
                        )
                    )
                if descriptors:
                    return descriptors
        except Exception as exc:
            logger.debug("Live Claude model discovery unavailable: %s. Using catalog fallback.", exc)

        # Fallback catalog
        fallback_descriptors: List[ModelDescriptor] = []
        for item in FALLBACK_CLAUDE_MODELS:
            fallback_descriptors.append(
                ModelDescriptor(
                    id=item["id"],
                    display_name=item["display_name"],
                    capabilities={ProviderCapability.TEXT_GENERATION},
                    source=DiscoverySource.CATALOG_FALLBACK,
                    status=ModelStatus.COMPATIBLE_UNTESTED,
                    quality_score=item["quality_score"],
                    speed_score=item["speed_score"],
                    is_recommended=item["is_recommended"],
                    context_window=item["context_window"],
                )
            )
        return fallback_descriptors

    def filter_compatible_models(
        self, models: List[ModelDescriptor]
    ) -> List[ModelDescriptor]:
        """
        Filters models supporting text generation.
        """
        return [m for m in models if ProviderCapability.TEXT_GENERATION in m.capabilities]

    def validate_model_access(self, model_id: str) -> ValidationResult:
        """Performs live model validation probe."""
        if not self.api_key:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Anthropic API key is not configured.",
                model_id=model_id,
            )
        try:
            self._ensure_client()
            self.client.messages.create(
                model=model_id,
                max_tokens=5,
                messages=[{"role": "user", "content": "ping"}]
            )
            return ValidationResult(
                is_valid=True,
                status=ModelStatus.AVAILABLE,
                message="Model verified and accessible.",
                model_id=model_id,
            )
        except Exception as e:
            return self.translate_error(e)

    def quick_preflight_check(self) -> ValidationResult:
        """Quick preflight health check."""
        return self.validate_model_access(self.model_name)

    def generate_transcript(self, audio_source: Any) -> str:
        """
        Anthropic Claude API does not natively support audio transcription.
        """
        raise NotImplementedError(
            "Anthropic Claude API does not natively support audio transcription. Please use an audio-capable provider (e.g. Gemini, OpenAI Whisper)."
        )

    def generate_report(self, transcript: str) -> str:
        """Generates executive summary and action items from transcript."""
        self._ensure_client()
        prompt = MEETING_REPORT_PROMPT.format(transcript=transcript)
        message = self.client.messages.create(
            model=self.model_name,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text if message.content else ""

    def translate_error(self, exc: Exception) -> ValidationResult:
        """Normalizes Anthropic exceptions into structured ValidationResult."""
        if isinstance(exc, NotImplementedError):
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message=str(exc),
                model_id=self.model_name,
            )

        err_str = str(exc)
        if self.api_key and self.api_key in err_str:
            err_str = err_str.replace(self.api_key, "[REDACTED]")

        status_code = getattr(exc, "status_code", None)

        if status_code == 401 or "authentication" in err_str.lower() or "api_key" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid Anthropic API key. Please check your credentials in AI Settings.",
                model_id=self.model_name,
            )
        if status_code == 403 or "permission" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message=f"Access denied for model '{self.model_name}'.",
                model_id=self.model_name,
            )
        if status_code == 404 or "not_found" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message=f"Model '{self.model_name}' is not found or not available for your account.",
                model_id=self.model_name,
            )
        if status_code == 429 or "rate_limit" in err_str.lower():
            if "quota" in err_str.lower() or "credit" in err_str.lower() or "balance" in err_str.lower():
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.QUOTA_EXCEEDED,
                    message="Anthropic credit balance/quota exhausted.",
                    model_id=self.model_name,
                )
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="Anthropic rate limit reached. Please wait a moment and try again.",
                model_id=self.model_name,
            )
        if status_code in (500, 529, 503) or "overloaded" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                message=f"Anthropic model '{self.model_name}' is temporarily overloaded. Please try again shortly.",
                model_id=self.model_name,
            )

        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=f"Anthropic error: {err_str[:120]}",
            model_id=self.model_name,
        )

    def cleanup_audio(self, audio_source: Any) -> None:
        """No-op for Claude."""
        pass
