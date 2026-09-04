from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Dict, Any, Set, Optional


class ProviderCapability(Enum):
    """Enumeration of capabilities an AI provider or model may support."""
    AUDIO_TRANSCRIPTION = "audio_transcription"
    TEXT_GENERATION = "text_generation"
    NATIVE_AUDIO_INPUT = "native_audio_input"
    STREAMING = "streaming"


class DiscoverySource(Enum):
    """Origin of the discovered model descriptor."""
    LIVE_API = "LIVE_API"
    CATALOG_FALLBACK = "CATALOG_FALLBACK"


class ModelStatus(Enum):
    """Status classification of an AI model."""
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    ACCESS_DENIED = "ACCESS_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    COMPATIBLE_UNTESTED = "COMPATIBLE_UNTESTED"
    UNKNOWN = "UNKNOWN"


class ModelDescriptor:
    """Represents a discovered model independently of any specific AI provider."""

    def __init__(
        self,
        id: str,
        display_name: str,
        capabilities: Optional[Set[ProviderCapability]] = None,
        source: DiscoverySource = DiscoverySource.LIVE_API,
        status: ModelStatus = ModelStatus.COMPATIBLE_UNTESTED,
        status_message: str = "",
        quality_score: int = 50,
        speed_score: int = 50,
        is_recommended: bool = False,
        context_window: int = 128000,
    ):
        self.id = id
        self.display_name = display_name
        self.capabilities = capabilities if capabilities is not None else set()
        self.source = source
        self.status = status
        self.status_message = status_message
        self.quality_score = quality_score
        self.speed_score = speed_score
        self.is_recommended = is_recommended
        self.context_window = context_window

    def to_dict(self) -> Dict[str, Any]:
        """Converts the descriptor to a serializable dictionary representation."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "capabilities": [
                c.value if isinstance(c, ProviderCapability) else str(c)
                for c in self.capabilities
            ],
            "source": self.source.value if isinstance(self.source, DiscoverySource) else str(self.source),
            "status": self.status.value if isinstance(self.status, ModelStatus) else str(self.status),
            "status_message": self.status_message,
            "quality_score": self.quality_score,
            "speed_score": self.speed_score,
            "is_recommended": self.is_recommended,
            "context_window": self.context_window,
        }


class ValidationResult:
    """Represents the outcome of a provider connection or model access test."""

    def __init__(
        self,
        is_valid: bool,
        status: ModelStatus,
        message: str,
        model_id: str = "",
        stage: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.is_valid = is_valid
        self.status = status
        self.message = message
        self.model_id = model_id
        self.stage = stage
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Converts the validation result to a serializable dictionary representation."""
        data = {
            "is_valid": self.is_valid,
            "status": self.status.value if isinstance(self.status, ModelStatus) else str(self.status),
            "message": self.message,
            "model_id": self.model_id,
        }
        if self.stage:
            data["stage"] = self.stage
        if self.details:
            data["details"] = self.details
        return data


class BaseAIProvider(ABC):
    """
    Abstract base interface for all AI Meeting Assistant providers.
    Encapsulates SDK communication, model discovery, validation, transcription,
    and report generation in a provider-agnostic manner.
    """

    @abstractmethod
    def test_connection(self) -> ValidationResult:
        """
        Verifies API key authenticity and provider reachability.
        Returns a ValidationResult instance.
        """
        pass

    @abstractmethod
    def discover_models(self) -> List[ModelDescriptor]:
        """
        Discovers all models available on the provider account.
        Returns a list of ModelDescriptor instances.
        """
        pass

    @abstractmethod
    def filter_compatible_models(
        self, models: List[ModelDescriptor]
    ) -> List[ModelDescriptor]:
        """
        Filters models strictly to those meeting application capability requirements.
        Returns a list of compatible ModelDescriptor instances.
        """
        pass

    @abstractmethod
    def validate_model_access(self, model_id: str) -> ValidationResult:
        """
        Performs live access and capability verification for a specific model.
        Returns a ValidationResult instance.
        """
        pass

    @abstractmethod
    def quick_preflight_check(self) -> ValidationResult:
        """
        Executes a sub-second health check before processing a meeting.
        Returns a ValidationResult instance.
        """
        pass

    @abstractmethod
    def generate_transcript(self, audio_source: Any) -> str:
        """
        Transcribes meeting audio to text.
        Returns the raw transcript string.
        """
        pass

    @abstractmethod
    def generate_report(self, transcript: str) -> str:
        """
        Analyzes the transcript and generates the executive meeting report.
        Returns the formatted report string.
        """
        pass

    @abstractmethod
    def translate_error(self, exc: Exception) -> ValidationResult:
        """
        Normalizes provider SDK exceptions into a structured ValidationResult.
        """
        pass

    def upload_audio(self, audio_path: str) -> Any:
        """
        Uploads or prepares audio for provider processing.
        Default implementation returns the local audio path.
        """
        return audio_path

    def wait_until_ready(self, audio_file: Any, timeout_seconds: int = 120) -> Any:
        """
        Waits for remote audio processing to complete if required by the provider.
        Default implementation returns the audio file immediately.
        """
        return audio_file

    def cleanup_audio(self, audio_source: Any) -> None:
        """
        Optional lifecycle cleanup hook for remote audio assets.
        Default implementation is a no-op for providers that do not retain remote assets.
        """
        pass