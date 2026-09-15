"""
meeting/services/model_validation_service.py

Provider-agnostic live model access validation and pre-flight health check service.
Does NOT import any provider-specific SDKs.
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import List, Dict, Optional

from django.conf import settings

from meeting.providers.base_provider import (
    BaseAIProvider,
    ModelDescriptor,
    ModelStatus,
    ValidationResult,
)
from meeting.services.model_discovery_service import ModelDiscoveryService
from meeting.services.audio_service import AudioService

logger = logging.getLogger(__name__)


class ModelValidationService:
    """
    Service for selectively validating live model access and performing
    pre-flight configuration health checks across AI providers.
    """

    @classmethod
    def validate_model(
        cls,
        provider: BaseAIProvider,
        model_id: str,
    ) -> ValidationResult:
        """
        Validates live access for a single model ID via the provider.
        """
        if not isinstance(provider, BaseAIProvider):
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNKNOWN,
                message=f"Invalid provider: expected BaseAIProvider, got {type(provider).__name__}",
                model_id=model_id or "",
            )

        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Model ID cannot be empty.",
                model_id="",
            )

        clean_model_id = model_id.strip()
        try:
            return provider.validate_model_access(clean_model_id)
        except Exception as exc:
            logger.warning("Unhandled exception during model validation for '%s': %s", clean_model_id, exc)
            return provider.translate_error(exc)

    @classmethod
    def validate_models(
        cls,
        provider: BaseAIProvider,
        model_ids: List[str],
    ) -> Dict[str, ValidationResult]:
        """
        Selectively validates a specific list of model IDs.
        Returns a dictionary mapping model_id to ValidationResult.
        """
        results: Dict[str, ValidationResult] = {}
        for mid in model_ids:
            if mid and isinstance(mid, str):
                results[mid] = cls.validate_model(provider, mid)
        return results

    @classmethod
    def validate_discovered_models(
        cls,
        provider: BaseAIProvider,
        models: List[ModelDescriptor],
        selected_model_id: Optional[str] = None,
    ) -> List[ModelDescriptor]:
        """
        Selectively validates discovered models.
        By default, validates ONLY the selected_model_id (or configured model if selected_model_id is None).
        
        All other compatible models remain in their current status (e.g. COMPATIBLE_UNTESTED).
        Preserves all ModelDescriptor metadata, quality scores, and DiscoverySource.
        """
        if not isinstance(provider, BaseAIProvider):
            logger.error("validate_discovered_models requires a BaseAIProvider instance.")
            return models

        # Ensure only application-compatible models are processed
        if hasattr(provider, "filter_compatible_models"):
            compatible_models = provider.filter_compatible_models(models)
        else:
            compatible_models = ModelDiscoveryService.filter_compatible_models(models)

        target_model_id = selected_model_id
        if not target_model_id:
            # Fall back to provider's configured model if available
            target_model_id = getattr(provider, "model_name", None)

        if not target_model_id and compatible_models:
            # If no model specified or configured, pick the recommended one
            recommended = ModelDiscoveryService.get_recommended_model(compatible_models)
            if recommended:
                target_model_id = recommended.id

        if not target_model_id:
            return compatible_models

        compatible_ids = {m.id for m in compatible_models}
        if target_model_id not in compatible_ids:
            logger.debug("Target model '%s' is not among compatible models. Skipping live probe.", target_model_id)
            return compatible_models

        # Validate ONLY the target model
        validation_result = cls.validate_model(provider, target_model_id)

        for m in compatible_models:
            if m.id == target_model_id:
                if validation_result.is_valid:
                    m.status = ModelStatus.AVAILABLE
                else:
                    m.status = validation_result.status
                m.status_message = validation_result.message

        return compatible_models

    @classmethod
    def preflight_check(
        cls,
        provider: BaseAIProvider,
    ) -> ValidationResult:
        """
        Performs a lightweight pre-flight health check to verify that the configured
        provider, credentials, and active model are currently usable for meeting processing.
        """
        if not isinstance(provider, BaseAIProvider):
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNKNOWN,
                message=f"Invalid provider: expected BaseAIProvider, got {type(provider).__name__}",
            )

        try:
            return provider.quick_preflight_check()
        except Exception as exc:
            logger.warning("Pre-flight check failed with exception: %s", exc)
            return provider.translate_error(exc)

    @classmethod
    def get_sample_video_path(cls) -> Path:
        """
        Returns the absolute Path to the built-in sample meeting video.
        """
        base_dir = getattr(settings, "BASE_DIR", None)
        if base_dir:
            return Path(base_dir) / "meeting" / "resources" / "sample_meeting.mp4"
        return Path(__file__).resolve().parent.parent / "resources" / "sample_meeting.mp4"

    @classmethod
    def validate_model_e2e(
        cls,
        provider: BaseAIProvider,
        model_id: str,
        sample_video_path: Optional[Path] = None,
    ) -> ValidationResult:
        """
        Performs a real end-to-end meeting processing validation for the specified model:
        1. Access verification probe via provider.validate_model_access(model_id).
        2. Resolves built-in sample meeting video (10-15s).
        3. Extracts 16kHz mono WAV audio via AudioService.extract_audio().
        4. Uploads audio via provider.upload_audio() and waits until ready.
        5. Generates transcript via provider.generate_transcript() and verifies non-empty output.
        6. Cleans up remote uploaded audio via provider.cleanup_audio().
        7. Generates executive meeting report via provider.generate_report() and verifies non-empty output.
        8. Cleans up local temporary audio file and directories.

        For text-generation providers without native audio support (e.g. Claude):
        Executes access probe followed by sample transcript report generation verification.

        Guarantees:
        - The selected model is set on the provider instance.
        - No persistent Meeting database record is created.
        - Dashboard KPI metrics and user meeting history remain completely untouched.
        - All temporary local and remote assets are cleaned up in finally blocks.
        """
        if not isinstance(provider, BaseAIProvider):
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNKNOWN,
                message=f"Invalid provider: expected BaseAIProvider, got {type(provider).__name__}",
                model_id=model_id or "",
                stage="access_validation_failed",
            )

        if not model_id or not isinstance(model_id, str) or not model_id.strip():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Model ID cannot be empty.",
                model_id="",
                stage="access_validation_failed",
            )

        clean_model_id = model_id.strip()
        # Ensure the provider is explicitly configured to use the targeted model
        provider.model_name = clean_model_id

        # 1. Access verification probe
        access_result = cls.validate_model(provider, clean_model_id)
        if not access_result.is_valid:
            access_result.stage = "access_validation_failed"
            return access_result

        # Capability-aware branch: text-generation reasoning providers (e.g. Claude)
        is_text_only = getattr(provider, "provider", "") == "claude"
        if is_text_only:
            sample_transcript = (
                "Speaker 1: Welcome to the quarterly planning meeting. "
                "Speaker 2: We need to finalize the product roadmap and launch dates."
            )
            try:
                report = provider.generate_report(sample_transcript)
            except Exception as exc:
                logger.warning("Report generation failed during E2E validation for model '%s': %s", clean_model_id, exc)
                err_res = provider.translate_error(exc)
                err_res.stage = "report_generation_failed"
                err_res.model_id = clean_model_id
                return err_res

            if not report or not str(report).strip():
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.UNAVAILABLE,
                    message=f"Model '{clean_model_id}' returned an empty executive summary for the sample meeting.",
                    model_id=clean_model_id,
                    stage="empty_report",
                )

            return ValidationResult(
                is_valid=True,
                status=ModelStatus.AVAILABLE,
                message=f"Model '{clean_model_id}' is verified: successfully passed text reasoning and report generation validation.",
                model_id=clean_model_id,
                stage="validation_success",
            )

        # 2. Resolve sample video path
        target_sample_path = sample_video_path or cls.get_sample_video_path()
        if not target_sample_path or not os.path.exists(str(target_sample_path)):
            logger.warning("Sample meeting video not found at path: %s", target_sample_path)
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Sample meeting video file is missing or unreadable.",
                model_id=clean_model_id,
                stage="sample_video_missing",
            )

        # 3. Audio extraction
        temp_dir = tempfile.mkdtemp(prefix="meeting_e2e_val_")
        temp_wav_path = os.path.join(temp_dir, "sample_audio.wav")
        audio_source = None

        try:
            try:
                extracted_wav = AudioService.extract_audio(str(target_sample_path), temp_wav_path)
            except Exception as exc:
                logger.warning("Audio extraction failed for sample video '%s': %s", target_sample_path, exc)
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.UNAVAILABLE,
                    message="Failed to extract audio from sample meeting recording.",
                    model_id=clean_model_id,
                    stage="audio_extraction_failed",
                )

            # 4. Upload audio & wait until ready
            try:
                audio_source = provider.upload_audio(extracted_wav)
            except Exception as exc:
                logger.warning("Audio upload failed during E2E validation for model '%s': %s", clean_model_id, exc)
                err_res = provider.translate_error(exc)
                err_res.stage = "audio_upload_failed"
                err_res.model_id = clean_model_id
                return err_res

            try:
                audio_source = provider.wait_until_ready(audio_source)
            except Exception as exc:
                logger.warning("Audio processing wait failed during E2E validation for model '%s': %s", clean_model_id, exc)
                err_res = provider.translate_error(exc)
                err_res.stage = "audio_processing_failed"
                err_res.model_id = clean_model_id
                return err_res

            # 5. Generate transcript
            try:
                transcript = provider.generate_transcript(audio_source)
            except Exception as exc:
                logger.warning("Transcript generation failed during E2E validation for model '%s': %s", clean_model_id, exc)
                err_res = provider.translate_error(exc)
                err_res.stage = "transcription_failed"
                err_res.model_id = clean_model_id
                return err_res

            if not transcript or not str(transcript).strip():
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.UNAVAILABLE,
                    message=f"Model '{clean_model_id}' returned an empty or invalid transcript for the sample meeting.",
                    model_id=clean_model_id,
                    stage="empty_transcript",
                )

            # 6. Cleanup remote audio
            if audio_source is not None and hasattr(provider, "cleanup_audio"):
                try:
                    provider.cleanup_audio(audio_source)
                    audio_source = None
                except Exception as exc:
                    logger.warning("Remote audio cleanup notice during validation: %s", exc)

            # 7. Generate executive report
            try:
                report = provider.generate_report(transcript)
            except Exception as exc:
                logger.warning("Report generation failed during E2E validation for model '%s': %s", clean_model_id, exc)
                err_res = provider.translate_error(exc)
                err_res.stage = "report_generation_failed"
                err_res.model_id = clean_model_id
                return err_res

            if not report or not str(report).strip():
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.UNAVAILABLE,
                    message=f"Model '{clean_model_id}' returned an empty executive summary for the sample meeting.",
                    model_id=clean_model_id,
                    stage="empty_report",
                )

            # All stages completed successfully!
            return ValidationResult(
                is_valid=True,
                status=ModelStatus.AVAILABLE,
                message=f"Model '{clean_model_id}' is verified: successfully passed end-to-end meeting validation (transcription & executive summary).",
                model_id=clean_model_id,
                stage="validation_success",
            )

        finally:
            # Remote audio cleanup fallback if exception occurred before cleanup
            if audio_source is not None and hasattr(provider, "cleanup_audio"):
                try:
                    provider.cleanup_audio(audio_source)
                except Exception:
                    pass

            # Local temporary file and directory cleanup
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    @classmethod
    def validate_model_with_fallback(
        cls,
        provider: BaseAIProvider,
        selected_model_id: str,
        candidate_models: Optional[List[str]] = None,
        sample_video_path: Optional[Path] = None,
    ) -> ValidationResult:
        """
        Orchestrates multi-candidate live E2E model validation with automatic fallback:
        1. Queries authoritative discovered compatible models for the provider via ModelDiscoveryService.
        2. Places the user-selected model FIRST in the attempt order.
        3. Appends the remaining discovered compatible models, strictly preserving their original discovery ranking.
        4. Rejects/ignores any unknown or incompatible model IDs passed from the client.
        5. Deduplicates candidates so each model is attempted at most once.
        6. Executes Task 1 E2E validation sequentially on each candidate.
        7. If a provider-level credential failure (401 / ACCESS_DENIED) occurs on the initial probe, short-circuits immediately.
        8. Stops immediately once a working model is found and returns full attempt details.
        9. If all candidates fail, returns a structured failure with stage="all_models_failed".
        """
        if not isinstance(provider, BaseAIProvider):
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNKNOWN,
                message=f"Invalid provider: expected BaseAIProvider, got {type(provider).__name__}",
                model_id=selected_model_id or "",
                stage="access_validation_failed",
            )

        if not selected_model_id or not isinstance(selected_model_id, str) or not selected_model_id.strip():
            return ValidationResult(
                is_valid=False,
                status=ModelStatus.UNAVAILABLE,
                message="Selected model ID cannot be empty.",
                model_id="",
                stage="access_validation_failed",
            )

        clean_selected_id = selected_model_id.strip()

        # 1. Authoritative discovery of compatible models for current provider/credentials
        discovered_descriptors = ModelDiscoveryService.discover_and_filter(provider)
        discovered_ids = [m.id for m in discovered_descriptors]

        # 2. Build candidate list: selected model FIRST, then other valid discovered compatible models
        raw_candidates = [clean_selected_id]
        if candidate_models is not None:
            # When candidate_models is passed, validate each against authoritative discovered_ids
            valid_additional = [cid for cid in candidate_models if cid in discovered_ids and cid != clean_selected_id]
            raw_candidates.extend(valid_additional)
        else:
            # When candidate_models is not provided, use all discovered compatible models as the fallback pool
            valid_additional = [cid for cid in discovered_ids if cid != clean_selected_id]
            raw_candidates.extend(valid_additional)

        # 3. Deduplicate while preserving order
        seen = set()
        ordered_candidates: List[str] = []
        for cid in raw_candidates:
            if cid and cid not in seen:
                seen.add(cid)
                ordered_candidates.append(cid)

        attempted_models = []
        last_res = None

        for idx, candidate_id in enumerate(ordered_candidates):
            is_first_attempt = (idx == 0)

            # Execute real E2E validation for this candidate
            res = cls.validate_model_e2e(
                provider,
                candidate_id,
                sample_video_path=sample_video_path,
            )
            last_res = res

            attempt_record = {
                "model_id": candidate_id,
                "success": res.is_valid,
                "status": res.status.value if isinstance(res.status, ModelStatus) else str(res.status),
                "stage": getattr(res, "stage", "unknown") or "unknown",
                "message": res.message,
            }
            attempted_models.append(attempt_record)

            if res.is_valid:
                # SUCCESS!
                # fallback_used is True ONLY if an alternate model was actually attempted and verified
                fallback_used = (not is_first_attempt)

                if fallback_used:
                    first_attempt_info = attempted_models[0]
                    first_fail_msg = first_attempt_info.get("message") or "validation failed"
                    success_msg = (
                        f"Selected model '{clean_selected_id}' was unavailable ({first_fail_msg}). "
                        f"Fallback model '{candidate_id}' was automatically tested, verified, and selected."
                    )
                else:
                    success_msg = res.message

                return ValidationResult(
                    is_valid=True,
                    status=ModelStatus.AVAILABLE,
                    message=success_msg,
                    model_id=candidate_id,
                    stage="validation_success",
                    details={
                        "selected_model": clean_selected_id,
                        "verified_model": candidate_id,
                        "fallback_used": fallback_used,
                        "attempted_models": attempted_models,
                    },
                )

            # Candidate failed. Check for credential-level failure on first attempt to fast-fail.
            if is_first_attempt and res.status == ModelStatus.ACCESS_DENIED:
                return ValidationResult(
                    is_valid=False,
                    status=ModelStatus.ACCESS_DENIED,
                    message=res.message,
                    model_id=clean_selected_id,
                    stage=getattr(res, "stage", "access_validation_failed"),
                    details={
                        "selected_model": clean_selected_id,
                        "verified_model": None,
                        "fallback_used": False,
                        "attempted_models": attempted_models,
                    },
                )

        # All candidates failed
        fallback_used = (len(attempted_models) > 1)
        if not fallback_used and last_res:
            return ValidationResult(
                is_valid=False,
                status=last_res.status,
                message=last_res.message,
                model_id=clean_selected_id,
                stage=getattr(last_res, "stage", "validation_failed"),
                details={
                    "selected_model": clean_selected_id,
                    "verified_model": None,
                    "fallback_used": False,
                    "attempted_models": attempted_models,
                },
            )

        summary_msg = (
            f"No discovered model passed the end-to-end meeting validation for this API key. "
            f"({len(attempted_models)} model(s) tested)."
        )

        return ValidationResult(
            is_valid=False,
            status=ModelStatus.UNAVAILABLE,
            message=summary_msg,
            model_id=clean_selected_id,
            stage="all_models_failed",
            details={
                "selected_model": clean_selected_id,
                "verified_model": None,
                "fallback_used": fallback_used,
                "attempted_models": attempted_models,
            },
        )
