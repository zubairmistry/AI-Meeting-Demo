import logging
import time
from typing import List, Dict, Any, Optional

from google import genai

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


# Curated fallback catalog for Gemini (used only when live discovery endpoint is unreachable)
FALLBACK_GEMINI_MODELS: List[Dict[str, Any]] = [
    {
        "id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash (Recommended)",
        "quality_score": 90,
        "speed_score": 95,
        "is_recommended": True,
        "context_window": 1048576,
    },
    {
        "id": "gemini-1.5-flash",
        "display_name": "Gemini 1.5 Flash",
        "quality_score": 85,
        "speed_score": 90,
        "is_recommended": False,
        "context_window": 1048576,
    },
    {
        "id": "gemini-2.5-pro",
        "display_name": "Gemini 2.5 Pro",
        "quality_score": 95,
        "speed_score": 75,
        "is_recommended": False,
        "context_window": 2097152,
    },
    {
        "id": "gemini-1.5-pro",
        "display_name": "Gemini 1.5 Pro",
        "quality_score": 90,
        "speed_score": 70,
        "is_recommended": False,
        "context_window": 2097152,
    },
]


class GeminiProvider(BaseAIProvider):

    def __init__(self, settings: Dict[str, Any]):
        self.provider = settings.get("provider", "gemini")
        self.api_key = settings.get("api_key", "")
        self.model_name = settings.get("model_name", "gemini-2.5-flash")

        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    def _ensure_client(self):
        if not self.client and self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        if not self.client:
            raise ValueError("Gemini API key is not configured.")

    def test_connection(self) -> ValidationResult:
        """
        Tests provider reachability and credentials.
        """
        try:
            self._ensure_client()
            response = self.client.models.generate_content(
                model=self.model_name,
                contents="Reply with only one word: Connected"
            )
            return ValidationResult(
                is_valid=True,
                status=ModelStatus.AVAILABLE,
                message=response.text or "Connected",
                model_id=self.model_name,
            )
        except Exception as e:
            return self.translate_error(e)

    def discover_models(self) -> List[ModelDescriptor]:
        """
        Discovers all available Gemini models via live SDK or falls back to static catalog.
        """
        try:
            self._ensure_client()
            models_pager = self.client.models.list()
            descriptors: List[ModelDescriptor] = []

            for m in models_pager:
                raw_name = getattr(m, "name", "")
                if not raw_name:
                    continue

                # Strip 'models/' prefix for normalized ID
                model_id = raw_name.replace("models/", "").strip()
                display_name = getattr(m, "display_name", "") or model_id

                # Filter out specialized non-general generation models
                lower_id = model_id.lower()
                if (
                    lower_id.endswith("-tts")
                    or "imagen" in lower_id
                    or "embedding" in lower_id
                    or "-aqa" in lower_id
                ):
                    continue

                # Multimodal Gemini models natively support audio transcription and text generation
                capabilities = {
                    ProviderCapability.AUDIO_TRANSCRIPTION,
                    ProviderCapability.TEXT_GENERATION,
                    ProviderCapability.NATIVE_AUDIO_INPUT,
                }

                # Quality / speed scoring
                is_rec = "2.5-flash" in lower_id and "preview" not in lower_id
                quality = 95 if "pro" in lower_id else 90
                speed = 75 if "pro" in lower_id else 95

                descriptors.append(
                    ModelDescriptor(
                        id=model_id,
                        display_name=display_name,
                        capabilities=capabilities,
                        source=DiscoverySource.LIVE_API,
                        status=ModelStatus.COMPATIBLE_UNTESTED,
                        quality_score=quality,
                        speed_score=speed,
                        is_recommended=is_rec,
                        context_window=getattr(m, "input_token_limit", 1048576) or 1048576,
                    )
                )

            if descriptors:
                return descriptors

        except Exception as exc:
            logger.warning("Live Gemini model discovery failed: %s. Using catalog fallback.", exc)

        # Fallback catalog
        fallback_descriptors: List[ModelDescriptor] = []
        for item in FALLBACK_GEMINI_MODELS:
            fallback_descriptors.append(
                ModelDescriptor(
                    id=item["id"],
                    display_name=item["display_name"],
                    capabilities={
                        ProviderCapability.AUDIO_TRANSCRIPTION,
                        ProviderCapability.TEXT_GENERATION,
                        ProviderCapability.NATIVE_AUDIO_INPUT,
                    },
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
        Filters models strictly to those satisfying meeting application requirements.
        """
        required = {
            ProviderCapability.AUDIO_TRANSCRIPTION,
            ProviderCapability.TEXT_GENERATION,
        }
        return [m for m in models if required.issubset(m.capabilities)]

    def validate_model_access(self, model_id: str) -> ValidationResult:
        """
        Performs a live lightweight 1-token probe to confirm model access.
        """
        try:
            self._ensure_client()
            response = self.client.models.generate_content(
                model=model_id,
                contents="ping",
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
        """
        Quick pre-flight check on the currently configured model.
        """
        return self.validate_model_access(self.model_name)

    def translate_error(self, exc: Exception) -> ValidationResult:
        """
        Normalizes provider SDK exceptions into a structured ValidationResult.
        """
        err_str = str(exc)
        code = getattr(exc, "code", None)

        if code == 401 or "UNAUTHENTICATED" in err_str or "API_KEY_INVALID" in err_str:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message="Invalid API key. Please check your credentials in AI Settings.",
                model_id=self.model_name,
            )
        if code == 403 or "PERMISSION_DENIED" in err_str:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.ACCESS_DENIED,
                message=f"Access denied for model '{self.model_name}'. Please check project permissions.",
                model_id=self.model_name,
            )
        if code == 404 or "NOT_FOUND" in err_str:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message=f"Model '{self.model_name}' is not available for your account tier. Please select another model in AI Settings.",
                model_id=self.model_name,
            )
        if code == 429 or "RESOURCE_EXHAUSTED" in err_str:
            if "quota" in err_str.lower():
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.QUOTA_EXCEEDED,
                    message="AI account quota exhausted. Please check billing or use another key.",
                    model_id=self.model_name,
                )
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.RATE_LIMITED,
                message="AI request rate limit reached. Please wait a moment and try again.",
                model_id=self.model_name,
            )
        if code in (500, 503) or "UNAVAILABLE" in err_str or "HIGH_DEMAND" in err_str:
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.TEMPORARILY_UNAVAILABLE,
                message=f"Model '{self.model_name}' is currently experiencing high demand. Please try again shortly or switch models.",
                model_id=self.model_name,
            )

        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNKNOWN,
            message=f"AI provider error: {err_str[:120]}",
            model_id=self.model_name,
        )

    def upload_audio(self, audio_path):
        self._ensure_client()
        print("=" * 60)
        print("Uploading Audio To Gemini...")
        print("=" * 60)

        audio_file = self.client.files.upload(
            file=audio_path
        )

        print("Upload Successful")
        print("File Name :", audio_file.name)
        print("File URI  :", audio_file.uri)
        print("=" * 60)

        return audio_file

    def wait_until_ready(self, audio_file, timeout_seconds=120):
        self._ensure_client()
        print("Waiting for Gemini Processing...")
        start_time = time.time()

        while True:
            audio_file = self.client.files.get(
                name=audio_file.name
            )

            state_name = getattr(audio_file.state, "name", str(audio_file.state))
            print("Current State :", state_name)

            if state_name == "ACTIVE":
                break

            if state_name == "FAILED":
                raise RuntimeError("Gemini audio file processing failed on the server.")

            if time.time() - start_time > timeout_seconds:
                raise TimeoutError(f"Gemini audio file processing timed out after {timeout_seconds} seconds.")

            time.sleep(2)

        print("=" * 60)
        print("Gemini Processing Completed")
        print("=" * 60)

        return audio_file

    def generate_transcript(self, audio_file):
        self._ensure_client()
        print("=" * 60)
        print("Generating Transcript...")
        print("=" * 60)

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[
                audio_file,
                """
Generate the complete transcript of this meeting.

Instructions:
- Transcribe everything accurately.
- Do not summarize.
- Maintain the original sequence.
- Return only the transcript.
"""
            ]
        )

        return response.text

    def generate_report(self, transcript):
        self._ensure_client()
        prompt = MEETING_REPORT_PROMPT.format(
            transcript=transcript
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )

        return response.text

    def cleanup_audio(self, audio_source: Any) -> None:
        """
        Safely deletes the uploaded audio file from the remote Gemini Files API.
        Never interrupts the meeting workflow if deletion fails.
        """
        if audio_source is None:
            return

        file_name = getattr(audio_source, "name", None)
        if not file_name:
            return

        try:
            self._ensure_client()
            logger.info("Cleaning up remote Gemini audio asset: %s", file_name)
            self.client.files.delete(name=file_name)
            logger.info("Successfully deleted remote Gemini audio file: %s", file_name)
        except Exception as exc:
            # Shield cleanup exceptions so they never disrupt user workflow
            logger.warning("Could not delete remote Gemini audio file '%s': %s", file_name, exc)

    def get_file(self, file_name: str) -> Any:
        """
        Retrieves an existing remote file object by name from Gemini Files API.
        Returns the file object if found and active/processing, or None if expired/deleted/inaccessible.
        """
        if not file_name:
            return None
        try:
            self._ensure_client()
            remote_file = self.client.files.get(name=file_name)
            state_val = getattr(remote_file, "state", None)
            state_name = getattr(state_val, "name", str(state_val))
            if state_name == "FAILED":
                logger.warning("Remote Gemini file '%s' is in FAILED state.", file_name)
                return None
            return remote_file
        except Exception as exc:
            logger.warning("Could not retrieve remote Gemini file '%s': %s", file_name, exc)
            return None
