"""
meeting/providers/openai_provider.py

OpenAI Provider implementation conforming to BaseAIProvider.
Supports lazy SDK loading, static fallback catalog discovery, capability filtering, and error translation.
"""

import logging
import os
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

# Fallback catalog for OpenAI
FALLBACK_OPENAI_MODELS: List[Dict[str, Any]] = [
    {
        "id": "gpt-4o",
        "display_name": "GPT-4o (Recommended)",
        "capabilities": {
            ProviderCapability.AUDIO_TRANSCRIPTION,
            ProviderCapability.TEXT_GENERATION,
            ProviderCapability.NATIVE_AUDIO_INPUT,
        },
        "quality_score": 95,
        "speed_score": 90,
        "is_recommended": True,
        "context_window": 128000,
    },
    {
        "id": "gpt-4o-mini",
        "display_name": "GPT-4o Mini",
        "capabilities": {
            ProviderCapability.AUDIO_TRANSCRIPTION,
            ProviderCapability.TEXT_GENERATION,
            ProviderCapability.NATIVE_AUDIO_INPUT,
        },
        "quality_score": 88,
        "speed_score": 95,
        "is_recommended": False,
        "context_window": 128000,
    },
    {
        "id": "whisper-1",
        "display_name": "OpenAI Whisper-1",
        "capabilities": {
            ProviderCapability.AUDIO_TRANSCRIPTION,
        },
        "quality_score": 90,
        "speed_score": 85,
        "is_recommended": False,
        "context_window": 25000,
    },
    {
        "id": "gpt-4-turbo",
        "display_name": "GPT-4 Turbo",
        "capabilities": {
            ProviderCapability.TEXT_GENERATION,
        },
        "quality_score": 92,
        "speed_score": 80,
        "is_recommended": False,
        "context_window": 128000,
    },
]


class OpenAIProvider(BaseAIProvider):
    """
    OpenAI AI Provider.
    Implements audio transcription via Whisper/GPT-4o, report generation, and access verification.
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        cfg = settings or {}
        self.provider = cfg.get("provider", "openai")
        self.api_key = cfg.get("api_key", "")
        self.model_name = cfg.get("model_name", "gpt-4o")
        self.client = None

    def _ensure_client(self):
        if not self.api_key:
            raise ValueError("OpenAI API key is not configured.")
        if not self.client:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise RuntimeError(
                    "The 'openai' package is not installed. Please install it to use live OpenAI features."
                )

    def test_connection(self) -> ValidationResult:
        """Tests provider reachability and credentials."""
        if not self.api_key:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="OpenAI API key is not configured.",
                model_id=self.model_name,
            )
        try:
            self._ensure_client()
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "Reply with one word: Connected"}],
                max_tokens=5,
            )
            reply = response.choices[0].message.content if response.choices else "Connected"
            return ValidationResult(
                is_valid=True,
                status=ModelStatus.AVAILABLE,
                message=reply or "Connected",
                model_id=self.model_name,
            )
        except Exception as e:
            return self.translate_error(e)

    def discover_models(self) -> List[ModelDescriptor]:
        """Discovers OpenAI models or returns curated fallback catalog."""
        try:
            self._ensure_client()
            models_pager = self.client.models.list()
            descriptors = []
            for m in models_pager:
                model_id = getattr(m, "id", "")
                if not model_id:
                    continue
                lower_id = model_id.lower()
                if not (lower_id.startswith("gpt-") or lower_id.startswith("whisper") or lower_id.startswith("o1") or lower_id.startswith("o3")):
                    continue
                if "embedding" in lower_id or "dall-e" in lower_id or "tts" in lower_id or "moderation" in lower_id:
                    continue

                is_rec = lower_id == "gpt-4o"
                caps = {ProviderCapability.TEXT_GENERATION}
                if "4o" in lower_id:
                    caps.add(ProviderCapability.AUDIO_TRANSCRIPTION)
                    caps.add(ProviderCapability.NATIVE_AUDIO_INPUT)
                elif "whisper" in lower_id:
                    caps = {ProviderCapability.AUDIO_TRANSCRIPTION}

                descriptors.append(
                    ModelDescriptor(
                        id=model_id,
                        display_name=model_id,
                        capabilities=caps,
                        source=DiscoverySource.LIVE_API,
                        status=ModelStatus.COMPATIBLE_UNTESTED,
                        quality_score=95 if "4o" in lower_id else 85,
                        speed_score=90,
                        is_recommended=is_rec,
                        context_window=128000 if "gpt" in lower_id else 25000,
                    )
                )
            if descriptors:
                return descriptors
        except Exception as exc:
            logger.debug("Live OpenAI model discovery unavailable: %s. Using catalog fallback.", exc)

        # Fallback catalog
        fallback_descriptors: List[ModelDescriptor] = []
        for item in FALLBACK_OPENAI_MODELS:
            fallback_descriptors.append(
                ModelDescriptor(
                    id=item["id"],
                    display_name=item["display_name"],
                    capabilities=item["capabilities"],
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
        Filters models strictly to those satisfying application requirements.
        """
        required = {
            ProviderCapability.AUDIO_TRANSCRIPTION,
            ProviderCapability.TEXT_GENERATION,
        }
        return [m for m in models if required.issubset(m.capabilities)]

    def validate_model_access(self, model_id: str) -> ValidationResult:
        """Performs live model access validation probe."""
        if not self.api_key:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="OpenAI API key is not configured.",
                model_id=model_id,
            )
        try:
            self._ensure_client()
            self.client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
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

    def upload_audio(self, audio_path: str) -> str:
        """Returns the local path for OpenAI Whisper/audio processing."""
        return audio_path

    def wait_until_ready(self, audio_file: Any, timeout_seconds: int = 120) -> Any:
        """No asynchronous processing wait needed for local audio paths."""
        return audio_file

    def generate_transcript(self, audio_source: Any) -> str:
        """Transcribes audio using OpenAI Whisper API."""
        self._ensure_client()
        audio_path = str(audio_source)
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        with open(audio_path, "rb") as f:
            transcription = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
            return getattr(transcription, "text", str(transcription))

    def generate_report(self, transcript: str) -> str:
        """Generates executive meeting report from transcript."""
        self._ensure_client()
        prompt = MEETING_REPORT_PROMPT.format(transcript=transcript)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
        )
        return response.choices[0].message.content if response.choices else ""

    def translate_error(self, exc: Exception) -> ValidationResult:
        """Normalizes OpenAI exceptions into structured ValidationResult."""
        err_str = str(exc)
        status_code = getattr(exc, "status_code", None)

        if status_code == 401 or "401" in err_str or "api_key" in err_str.lower() or "api key" in err_str.lower() or "unauthorized" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid OpenAI API key. Please check your credentials in AI Settings.",
                model_id=self.model_name,
            )
        if status_code == 403 or "403" in err_str or "permission" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message=f"Access denied for OpenAI model '{self.model_name}'.",
                model_id=self.model_name,
            )
        if status_code == 404 or "404" in err_str or "not_found" in err_str.lower() or "not exist" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message=f"Model '{self.model_name}' does not exist or you do not have access to it.",
                model_id=self.model_name,
            )
        if status_code == 429 or "429" in err_str or "rate_limit" in err_str.lower() or "quota" in err_str.lower():
            if "insufficient_quota" in err_str.lower() or "quota" in err_str.lower() or "credit" in err_str.lower():
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.QUOTA_EXCEEDED,
                    message="OpenAI quota exceeded. Please check your account billing.",
                    model_id=self.model_name,
                )
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="OpenAI rate limit reached. Please wait a moment and try again.",
                model_id=self.model_name,
            )
        if status_code in (500, 503) or "500" in err_str or "503" in err_str or "unavailable" in err_str.lower():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                message=f"OpenAI service is temporarily unavailable. Please try again shortly.",
                model_id=self.model_name,
            )

        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=f"OpenAI error: {err_str[:120]}",
            model_id=self.model_name,
        )

    def cleanup_audio(self, audio_source: Any) -> None:
        """No-op for OpenAI."""
        pass
