import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any

from django.db import transaction
from django.utils import timezone

from meeting.models import Meeting
from meeting.services.audio_service import AudioService
from meeting.services.transcript_service import TranscriptService
from meeting.services.provider_factory import ProviderFactory

logger = logging.getLogger(__name__)


class AsyncTaskService:
    """
    Core backend foundation for asynchronous meeting processing.
    Manages a bounded thread pool, in-memory task tracking, database row locks,
    and stage-checkpointed pipeline execution.
    """

    _executor: Optional[ThreadPoolExecutor] = None
    _executor_lock = threading.Lock()
    _active_tasks: Dict[int, str] = {}  # Map of meeting_id -> task_id
    _active_tasks_lock = threading.Lock()
    _max_workers: int = 2

    @classmethod
    def get_executor(cls) -> ThreadPoolExecutor:
        """
        Returns the application-level ThreadPoolExecutor singleton (max_workers=2).
        """
        if cls._executor is None:
            with cls._executor_lock:
                if cls._executor is None:
                    cls._executor = ThreadPoolExecutor(
                        max_workers=cls._max_workers,
                        thread_name_prefix="ai_meeting_worker"
                    )
                    logger.info("Initialized AsyncTaskService ThreadPoolExecutor (max_workers=%d)", cls._max_workers)
        return cls._executor

    @classmethod
    def register_active_task(cls, meeting_id: int, task_id: str) -> None:
        with cls._active_tasks_lock:
            cls._active_tasks[meeting_id] = task_id

    @classmethod
    def unregister_active_task(cls, meeting_id: int, task_id: Optional[str] = None) -> None:
        with cls._active_tasks_lock:
            if meeting_id in cls._active_tasks:
                if task_id is None or cls._active_tasks.get(meeting_id) == task_id:
                    cls._active_tasks.pop(meeting_id, None)

    @classmethod
    def is_task_active(cls, meeting_id: int) -> bool:
        with cls._active_tasks_lock:
            return meeting_id in cls._active_tasks

    @classmethod
    def get_active_task_id(cls, meeting_id: int) -> Optional[str]:
        with cls._active_tasks_lock:
            return cls._active_tasks.get(meeting_id)

    @classmethod
    def acquire_processing_lease(
        cls,
        meeting_id: int,
        user=None,
        allow_retry: bool = False
    ) -> Optional[str]:
        """
        Acquires an exclusive DB row lock using select_for_update() to prevent
        duplicate concurrent thread execution on the same Meeting instance.

        Returns a new unique task_id (UUID string) if the lease is successfully acquired,
        or None if the meeting is already actively processing or not retryable.
        """
        new_task_id = str(uuid.uuid4())

        with transaction.atomic():
            query = Meeting.objects.select_for_update().filter(id=meeting_id)
            if user is not None:
                query = query.filter(user=user)

            meeting = query.first()
            if not meeting:
                logger.warning("Meeting %d not found for lease acquisition.", meeting_id)
                return None

            # If already processing and active in memory, reject duplicate lease
            if meeting.status == "processing" and cls.is_task_active(meeting_id):
                logger.warning("Meeting %d is already actively processing with task %s.", meeting_id, meeting.task_id)
                return None

            # If completed and not allowing retry, reject lease
            if meeting.status == "completed" and not allow_retry:
                logger.warning("Meeting %d is already completed; cannot acquire lease.", meeting_id)
                return None

            # Transition status to processing, set new task_id and queued stage
            meeting.status = "processing"
            meeting.stage = "queued"
            meeting.task_id = new_task_id
            meeting.error_message = None
            meeting.save(update_fields=["status", "stage", "task_id", "error_message", "updated_at"])

            cls.register_active_task(meeting_id, new_task_id)
            logger.info("Acquired processing lease for meeting %d with task_id %s", meeting_id, new_task_id)
            return new_task_id

    @classmethod
    def update_stage(
        cls,
        meeting_id: int,
        stage: str,
        gemini_file_name: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> None:
        """
        Updates the meeting stage and metadata checkpoints in PostgreSQL.
        """
        update_fields = ["stage", "updated_at"]
        updates: Dict[str, Any] = {"stage": stage}

        if gemini_file_name is not None:
            updates["gemini_file_name"] = gemini_file_name
            update_fields.append("gemini_file_name")

        if error_message is not None:
            updates["error_message"] = error_message
            update_fields.append("error_message")

        Meeting.objects.filter(id=meeting_id).update(**updates)
        logger.debug("Meeting %d stage updated to '%s'", meeting_id, stage)

    @classmethod
    def run_pipeline_stepwise(
        cls,
        meeting_id: int,
        task_id: str,
        media_filepath: str
    ) -> bool:
        """
        Executes the staged AI analysis pipeline in a background worker thread.
        Uses checkpointing to resume gracefully from prior stages.
        """
        logger.info("Starting background pipeline for meeting %d (task_id=%s)", meeting_id, task_id)
        meeting = Meeting.objects.filter(id=meeting_id).first()
        if not meeting or meeting.task_id != task_id:
            logger.warning("Task ID mismatch or meeting %d missing. Aborting.", meeting_id)
            cls.unregister_active_task(meeting_id, task_id)
            return False

        provider = None
        gemini_file_obj = None

        try:
            provider = ProviderFactory.get_provider(meeting.user)
            if not provider:
                raise ValueError("AI Provider is not configured for user.")

            # Stage 1: Audio Extraction (Skip if transcript already exists)
            if not meeting.transcript:
                if getattr(provider, "provider", "") == "claude":
                    raise NotImplementedError(
                        "Anthropic Claude does not natively support audio transcription. "
                        "Please select an audio-capable provider (e.g. Gemini) in AI Settings to transcribe media recordings, "
                        "or provide an existing meeting transcript."
                    )

                cls.update_stage(meeting_id, "extracting_audio")
                audio_path = AudioService.extract_audio(media_filepath)
                audio_info = AudioService.get_audio_info(audio_path)

                Meeting.objects.filter(id=meeting_id).update(
                    audio_file=os.path.basename(audio_path),
                    duration=audio_info.get("duration_seconds", 0.0)
                )

                # Stage 2: Upload to Gemini Files API
                cls.update_stage(meeting_id, "uploading_to_ai")
                gemini_file_obj = provider.upload_audio(audio_path)
                gemini_name = getattr(gemini_file_obj, "name", str(gemini_file_obj))
                cls.update_stage(meeting_id, "waiting_for_ai", gemini_file_name=gemini_name)

                # Stage 3: Wait for Remote Indexing
                if hasattr(provider, "wait_until_ready"):
                    gemini_file_obj = provider.wait_until_ready(gemini_file_obj)

                # Stage 4: Transcribe Audio
                cls.update_stage(meeting_id, "transcribing")
                transcript = provider.generate_transcript(gemini_file_obj)
                if not transcript:
                    raise RuntimeError("AI Provider returned an empty transcript.")

                # Save transcript checkpoint immediately
                transcript_path = TranscriptService.save_transcript(transcript, media_path=media_filepath)
                Meeting.objects.filter(id=meeting_id).update(
                    transcript=transcript,
                    transcript_file=os.path.basename(transcript_path),
                    stage="generating_summary"
                )
                meeting.transcript = transcript
                logger.info("Saved transcript checkpoint for meeting %d", meeting_id)
            else:
                logger.info("Meeting %d already has transcript. Resuming at summary stage.", meeting_id)
                cls.update_stage(meeting_id, "generating_summary")

            # Stage 5: Generate Summary Report
            report = provider.generate_report(meeting.transcript)
            if not report:
                raise RuntimeError("AI Provider returned an empty summary report.")

            # Finalize completion
            Meeting.objects.filter(id=meeting_id).update(
                ai_report=report,
                status="completed",
                stage="completed",
                error_message=None
            )
            logger.info("Meeting %d successfully completed by task %s", meeting_id, task_id)
            return True

        except Exception as exc:
            logger.exception("Background pipeline failed for meeting %d: %s", meeting_id, exc)
            err_msg = str(exc)[:300]
            if provider and hasattr(provider, "translate_error"):
                try:
                    translated = provider.translate_error(exc)
                    if translated and translated.message:
                        err_msg = translated.message
                except Exception:
                    pass
            Meeting.objects.filter(id=meeting_id).update(
                status="failed",
                stage="failed",
                error_message=err_msg
            )
            return False

        finally:
            # Guarantee remote Gemini cleanup
            if gemini_file_obj and provider and hasattr(provider, "cleanup_audio"):
                try:
                    provider.cleanup_audio(gemini_file_obj)
                    Meeting.objects.filter(id=meeting_id).update(gemini_file_name=None)
                except Exception as cleanup_err:
                    logger.warning("Remote cleanup error for meeting %d: %s", meeting_id, cleanup_err)

            cls.unregister_active_task(meeting_id, task_id)
