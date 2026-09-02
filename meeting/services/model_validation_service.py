"""
meeting/services/model_validation_service.py

Provider-agnostic live model access validation and pre-flight health check service.
Does NOT import any provider-specific SDKs.
"""

import logging
from typing import List, Dict, Optional

from meeting.providers.base_provider import (
    BaseAIProvider,
    ModelDescriptor,
    ModelStatus,
    ValidationResult,
)
from meeting.services.model_discovery_service import ModelDiscoveryService

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
