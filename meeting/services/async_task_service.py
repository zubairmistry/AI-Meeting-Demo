import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Optional, Dict, Any, List

from django.db import transaction
from django.utils import timezone

from meeting.models import Meeting
from meeting.providers.base_provider import BaseAIProvider, ModelStatus
from meeting.services.audio_service import AudioService
from meeting.services.transcript_service import TranscriptService
from meeting.services.provider_factory import ProviderFactory
from meeting.services.model_discovery_service import ModelDiscoveryService

logger = logging.getLogger(__name__)


class TaskHeartbeat:
    """
    Lightweight background heartbeat thread that periodically updates
    the Meeting row's updated_at timestamp in the database while an
    asynchronous pipeline is executing.
    Ensures multi-worker Gunicorn processes and server restarts can
    reliably distinguish actively running tasks from dead/orphaned processes.
    """

    def __init__(self, meeting_id: int, interval: float = 10.0):
        self.meeting_id = meeting_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _run(self) -> None:
        from django.db import connection
        try:
            while not self._stop_event.wait(self.interval):
                try:
                    Meeting.objects.filter(
                        id=self.meeting_id,
                        status="processing"
                    ).update(updated_at=timezone.now())
                except Exception as exc:
                    logger.debug("Heartbeat error on meeting %d: %s", self.meeting_id, exc)
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat_meeting_{self.meeting_id}",
            daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


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
    def safe_sleep(cls, seconds: float) -> None:
        """
        Sleep helper that can be patched in tests to avoid test execution slowdowns.
        """
        time.sleep(seconds)

    @classmethod
    def is_transient_capacity_error(cls, provider: BaseAIProvider, exc: Exception) -> bool:
        """
        Determines if an exception from the AI provider is a transient capacity/overload
        condition suitable for model fallback (503, 500, 529, 429 rate limit, high demand).
        Auth/permission (401, 403), quota exhaustion, and client errors return False.
        """
        if isinstance(exc, (NotImplementedError, ValueError, TypeError)):
            return False

        err_res = None
        if hasattr(provider, "translate_error"):
            try:
                err_res = provider.translate_error(exc)
            except Exception:
                pass

        if err_res:
            # Explicitly allow TEMPORARILY_UNAVAILABLE and RATE_LIMITED (transient)
            if err_res.status in (ModelStatus.TEMPORARILY_UNAVAILABLE, ModelStatus.RATE_LIMITED):
                return True
            # Explicitly reject ACCESS_DENIED, QUOTA_EXCEEDED
            if err_res.status in (ModelStatus.ACCESS_DENIED, ModelStatus.QUOTA_EXCEEDED):
                return False

        err_str = str(exc).lower()
        non_transient_keywords = [
            "unauthenticated",
            "invalid api key",
            "api_key_invalid",
            "permission_denied",
            "access denied",
            "quota",
            "credit balance",
        ]
        for nk in non_transient_keywords:
            if nk in err_str:
                return False

        transient_keywords = [
            "high demand",
            "high_demand",
            "temporarily unavailable",
            "temporarily_unavailable",
            "overloaded",
            "resource_exhausted",
            "rate limit",
            "rate_limit",
            "503",
            "529",
            "500",
            "service unavailable",
            "capacity",
        ]
        for tk in transient_keywords:
            if tk in err_str:
                return True

        return False

    @classmethod
    def get_fallback_candidates(cls, provider: BaseAIProvider, selected_model_id: str) -> List[str]:
        """
        Discovers compatible fallback candidates for the provider, placing the selected
        model first, followed by discovered ranked compatible models (deduplicated).
        Limits fallback pool to at most 3 total models (selected + 2 fallback models).
        Only enables multi-model discovery for Gemini provider.
        """
        if getattr(provider, "provider", "") != "gemini":
            return [selected_model_id] if selected_model_id else []

        discovered_ids = []
        try:
            discovered_descriptors = ModelDiscoveryService.discover_and_filter(provider)
            discovered_ids = [m.id for m in discovered_descriptors if getattr(m, "id", None)]
        except Exception as exc:
            logger.warning("Could not discover fallback models: %s", exc)

        raw_candidates = [selected_model_id] + [cid for cid in discovered_ids if cid != selected_model_id]
        seen = set()
        ordered = []
        for cid in raw_candidates:
            if cid and cid not in seen:
                seen.add(cid)
                ordered.append(cid)

        return ordered[:3] if ordered else ([selected_model_id] if selected_model_id else [])

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

            # If already processing with an assigned task:
            # - Reject if active in current worker memory
            # - Reject if active in another worker (updated_at within STALE_INACTIVE_TIMEOUT)
            # - Reject if stale and allow_retry is False
            if meeting.status == "processing" and meeting.task_id:
                elapsed = (timezone.now() - meeting.updated_at).total_seconds()
                is_active = cls.is_task_active(meeting_id) or (elapsed <= cls.STALE_INACTIVE_TIMEOUT)
                if is_active or not allow_retry:
                    logger.warning(
                        "Meeting %d is already processing with task %s (is_active=%s, elapsed=%.1fs).",
                        meeting_id,
                        meeting.task_id,
                        is_active,
                        elapsed,
                    )
                    return None

            # If completed and not allowing retry, reject lease
            if meeting.status == "completed" and not allow_retry:
                logger.warning("Meeting %d is already completed; cannot acquire lease.", meeting_id)
                return None

            # If failed and not allowing retry, reject lease
            if meeting.status == "failed" and not allow_retry:
                logger.warning("Meeting %d has failed; cannot acquire lease without allow_retry.", meeting_id)
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

    STALE_INACTIVE_TIMEOUT: float = 60.0  # Inactivity threshold in seconds before an unregistered task is reaped

    @classmethod
    def check_and_reap_stale_task(cls, meeting_or_id: Any) -> bool:
        """
        Detects if a meeting in 'processing' status has been orphaned (no active in-memory
        worker thread and inactivity period > 60 seconds). If stale, marks status='failed'
        and stage='failed' with an informative recovery message.

        An active in-memory worker (is_task_active == True) is NEVER marked stale.

        Returns True if the meeting was reaped as stale, False otherwise.
        """
        meeting_id = meeting_or_id.id if isinstance(meeting_or_id, Meeting) else meeting_or_id
        if not meeting_id:
            return False

        # If task is active in memory, it is NEVER stale
        if cls.is_task_active(meeting_id):
            return False

        now = timezone.now()
        reaped = False

        with transaction.atomic():
            meeting = Meeting.objects.select_for_update().filter(id=meeting_id).first()
            if not meeting:
                return False

            if meeting.status == "processing" and not cls.is_task_active(meeting_id):
                elapsed = (now - meeting.updated_at).total_seconds()
                if elapsed > cls.STALE_INACTIVE_TIMEOUT:
                    meeting.status = "failed"
                    meeting.stage = "failed"
                    meeting.error_message = (
                        "Meeting processing was interrupted (server restart or unexpected termination). "
                        "You can retry this meeting."
                    )
                    meeting.save(update_fields=["status", "stage", "error_message", "updated_at"])
                    reaped = True
                    logger.warning(
                        "Reaped stale meeting %d (inactive for %.1fs without active worker)",
                        meeting_id,
                        elapsed,
                    )

        if reaped and isinstance(meeting_or_id, Meeting):
            meeting_or_id.refresh_from_db()

        return reaped

    @classmethod
    def check_and_reap_stale_tasks_for_user(cls, user) -> int:
        """
        Reaps any stale processing meetings for a user on-demand.
        Returns the count of reaped meetings.
        """
        if not user or not user.is_authenticated:
            return 0

        processing_ids = list(
            Meeting.objects.filter(user=user, status="processing").values_list("id", flat=True)
        )
        reaped_count = 0
        for mid in processing_ids:
            if cls.check_and_reap_stale_task(mid):
                reaped_count += 1
        return reaped_count

    @classmethod
    def get_existing_original_media_path(cls, meeting: Meeting, media_filepath: str) -> Optional[str]:
        """
        Locates an existing original media recording file for the meeting.
        """
        candidate_paths: List[str] = []
        if media_filepath:
            candidate_paths.append(media_filepath)
        if meeting.original_file:
            orig_name = str(meeting.original_file)
            if os.path.isabs(orig_name):
                candidate_paths.append(orig_name)
            else:
                try:
                    candidate_paths.append(meeting.original_file.path)
                except Exception:
                    pass
                try:
                    from django.conf import settings
                    candidate_paths.append(os.path.join(settings.MEDIA_ROOT, "meetings", "original", orig_name))
                    candidate_paths.append(os.path.join(settings.MEDIA_ROOT, orig_name))
                except Exception:
                    pass

        for path in candidate_paths:
            if path and os.path.exists(path) and os.path.isfile(path):
                try:
                    if os.path.getsize(path) > 0:
                        return os.path.abspath(path)
                except OSError:
                    continue

        return None

    @classmethod
    def get_existing_audio_path(cls, meeting: Meeting, media_filepath: str) -> Optional[str]:
        """
        Locates an existing, non-empty, valid extracted audio file for the meeting.
        Checks meeting.audio_file, media directory relative paths, and media_filepath base paths.
        Returns the absolute path if valid, or None if extraction is required.
        """
        candidate_paths: List[str] = []

        if meeting.audio_file:
            audio_name = str(meeting.audio_file)
            if os.path.isabs(audio_name):
                candidate_paths.append(audio_name)
            else:
                if media_filepath:
                    candidate_paths.append(os.path.join(os.path.dirname(media_filepath), audio_name))
                try:
                    candidate_paths.append(meeting.audio_file.path)
                except Exception:
                    pass
                try:
                    from django.conf import settings
                    candidate_paths.append(os.path.join(settings.MEDIA_ROOT, "meetings", "audio", audio_name))
                    candidate_paths.append(os.path.join(settings.MEDIA_ROOT, audio_name))
                except Exception:
                    pass

        if media_filepath:
            base, ext = os.path.splitext(media_filepath)
            if ext.lower() == ".mp3":
                candidate_paths.append(media_filepath)
            else:
                candidate_paths.append(f"{base}.mp3")
                candidate_paths.append(f"{base}_extracted.mp3")

        for path in candidate_paths:
            if path and os.path.exists(path) and os.path.isfile(path):
                try:
                    if os.path.getsize(path) > 0:
                        return os.path.abspath(path)
                except OSError:
                    continue

        return None

    @classmethod
    def run_pipeline_stepwise(
        cls,
        meeting_id: int,
        task_id: str,
        media_filepath: str
    ) -> bool:
        """
        Executes the staged AI analysis pipeline in a background worker thread.
        Uses deterministic checkpointing to resume gracefully and skip completed stages.
        """
        logger.info("Starting background pipeline for meeting %d (task_id=%s)", meeting_id, task_id)
        meeting = Meeting.objects.filter(id=meeting_id).first()
        if not meeting or meeting.task_id != task_id:
            logger.warning("Task ID mismatch or meeting %d missing. Aborting.", meeting_id)
            cls.unregister_active_task(meeting_id, task_id)
            return False

        # Idempotent shortcut: if meeting already has valid transcript and ai_report, finalize immediately
        if (
            meeting.transcript and meeting.transcript.strip()
            and meeting.ai_report and meeting.ai_report.strip()
        ):
            logger.info("Meeting %d already has valid transcript and report. Marking completed.", meeting_id)
            Meeting.objects.filter(id=meeting_id).update(
                status="completed",
                stage="completed",
                error_message=None
            )
            cls.unregister_active_task(meeting_id, task_id)
            return True

        heartbeat = TaskHeartbeat(meeting_id, interval=10.0)
        heartbeat.start()

        provider = None
        gemini_file_obj = None
        pipeline_completed = False

        try:
            provider = ProviderFactory.get_provider(meeting.user)
            if not provider:
                raise ValueError("AI Provider is not configured for user.")

            selected_model = getattr(provider, "model_name", "") or getattr(meeting, "model_name", "")
            candidates = cls.get_fallback_candidates(provider, selected_model)
            successful_model = selected_model

            # Stage 1 - 4: Audio Extraction, Upload, Indexing, and Transcription
            # (Skip if valid transcript is already persisted)
            if not (meeting.transcript and meeting.transcript.strip()):
                if getattr(provider, "provider", "") == "claude":
                    raise NotImplementedError(
                        "Anthropic Claude does not natively support audio transcription. "
                        "Please select an audio-capable provider (e.g. Gemini) in AI Settings to transcribe media recordings, "
                        "or provide an existing meeting transcript."
                    )

                # Checkpoint check: can we reuse an existing remote Gemini file?
                if meeting.gemini_file_name and hasattr(provider, "get_file"):
                    try:
                        gemini_file_obj = provider.get_file(meeting.gemini_file_name)
                        if gemini_file_obj:
                            logger.info(
                                "Reusing existing remote Gemini file '%s' for meeting %d (skipping upload)",
                                meeting.gemini_file_name, meeting_id
                            )
                    except Exception as exc:
                        logger.warning("Could not reuse remote Gemini file '%s': %s", meeting.gemini_file_name, exc)
                        gemini_file_obj = None

                # If no remote Gemini file, check local audio extraction and upload
                if not gemini_file_obj:
                    # Check if extracted audio already exists
                    audio_path = cls.get_existing_audio_path(meeting, media_filepath)
                    if not audio_path:
                        orig_media_path = cls.get_existing_original_media_path(meeting, media_filepath)
                        if not orig_media_path and media_filepath and not os.path.isabs(media_filepath):
                            # Allow relative/mock test media_filepath
                            orig_media_path = media_filepath
                        if not orig_media_path:
                            raise FileNotFoundError(
                                "Media file is no longer available on the server (ephemeral storage reset). "
                                "Please re-upload your meeting recording."
                            )
                        cls.update_stage(meeting_id, "extracting_audio")
                        audio_path = AudioService.extract_audio(orig_media_path)
                        audio_info = AudioService.get_audio_info(audio_path)
                        Meeting.objects.filter(id=meeting_id).update(
                            audio_file=os.path.basename(audio_path),
                            duration=audio_info.get("duration_seconds", 0.0)
                        )
                    else:
                        logger.info(
                            "Reusing existing extracted audio file '%s' for meeting %d (skipping FFmpeg)",
                            audio_path, meeting_id
                        )

                    # Stage 2: Upload to Gemini Files API
                    cls.update_stage(meeting_id, "uploading_to_ai")
                    gemini_file_obj = provider.upload_audio(audio_path)
                    gemini_name = getattr(gemini_file_obj, "name", str(gemini_file_obj))
                    cls.update_stage(meeting_id, "waiting_for_ai", gemini_file_name=gemini_name)

                # Stage 3: Wait for Remote Indexing (Skip if already ACTIVE)
                state_val = getattr(gemini_file_obj, "state", None)
                state_name = getattr(state_val, "name", str(state_val))
                if state_name != "ACTIVE" and hasattr(provider, "wait_until_ready"):
                    cls.update_stage(
                        meeting_id,
                        "waiting_for_ai",
                        gemini_file_name=getattr(gemini_file_obj, "name", str(gemini_file_obj))
                    )
                    gemini_file_obj = provider.wait_until_ready(gemini_file_obj)

                # Stage 4: Transcribe Audio with runtime model fallback
                cls.update_stage(meeting_id, "transcribing")
                transcript = None
                last_exc = None

                for idx, candidate_model in enumerate(candidates):
                    provider.model_name = candidate_model
                    max_attempts = 2 if idx == 0 else 1
                    model_succeeded = False

                    for attempt in range(max_attempts):
                        try:
                            logger.info(
                                "Attempting transcription for meeting %d with model %s (candidate %d/%d, attempt %d/%d)",
                                meeting_id, candidate_model, idx + 1, len(candidates), attempt + 1, max_attempts
                            )
                            transcript = provider.generate_transcript(gemini_file_obj)
                            if transcript and transcript.strip():
                                successful_model = candidate_model
                                model_succeeded = True
                                if candidate_model != selected_model:
                                    logger.info(
                                        "Meeting %d fallback to %s succeeded for transcription",
                                        meeting_id, candidate_model
                                    )
                                    Meeting.objects.filter(id=meeting_id).update(model_name=successful_model)
                                break
                            else:
                                raise RuntimeError(f"Model {candidate_model} returned an empty transcript.")
                        except Exception as exc:
                            last_exc = exc
                            is_transient = cls.is_transient_capacity_error(provider, exc)
                            logger.warning(
                                "Transcription error on meeting %d with model %s (attempt %d/%d, transient=%s): %s",
                                meeting_id, candidate_model, attempt + 1, max_attempts, is_transient, exc
                            )
                            if not is_transient:
                                raise exc
                            if attempt + 1 < max_attempts:
                                cls.safe_sleep(2.0)

                    if model_succeeded:
                        break

                if not transcript or not transcript.strip():
                    if last_exc:
                        raise last_exc
                    raise RuntimeError("AI Provider returned an empty transcript after trying all candidate models.")

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
                logger.info(
                    "Meeting %d already has valid transcript (%d chars). Resuming at summary stage.",
                    meeting_id, len(meeting.transcript)
                )
                cls.update_stage(meeting_id, "generating_summary")

            # Stage 5: Generate Summary Report with runtime model fallback
            # (Skip if valid report is already persisted)
            if not (meeting.ai_report and meeting.ai_report.strip()):
                report_candidates = [successful_model] + [c for c in candidates if c != successful_model]
                report = None
                last_report_exc = None

                for idx, candidate_model in enumerate(report_candidates):
                    provider.model_name = candidate_model
                    max_attempts = 2 if idx == 0 else 1
                    report_succeeded = False

                    for attempt in range(max_attempts):
                        try:
                            logger.info(
                                "Attempting report generation for meeting %d with model %s (candidate %d/%d, attempt %d/%d)",
                                meeting_id, candidate_model, idx + 1, len(report_candidates), attempt + 1, max_attempts
                            )
                            report = provider.generate_report(meeting.transcript)
                            if report and report.strip():
                                successful_model = candidate_model
                                report_succeeded = True
                                if candidate_model != selected_model:
                                    logger.info(
                                        "Meeting %d fallback to %s succeeded for report generation",
                                        meeting_id, candidate_model
                                    )
                                    Meeting.objects.filter(id=meeting_id).update(model_name=successful_model)
                                break
                            else:
                                raise RuntimeError(f"Model {candidate_model} returned an empty summary report.")
                        except Exception as exc:
                            last_report_exc = exc
                            is_transient = cls.is_transient_capacity_error(provider, exc)
                            logger.warning(
                                "Report generation error on meeting %d with model %s (attempt %d/%d, transient=%s): %s",
                                meeting_id, candidate_model, attempt + 1, max_attempts, is_transient, exc
                            )
                            if not is_transient:
                                raise exc
                            if attempt + 1 < max_attempts:
                                cls.safe_sleep(2.0)

                    if report_succeeded:
                        break

                if not report or not report.strip():
                    if last_report_exc:
                        raise last_report_exc
                    raise RuntimeError("AI Provider returned an empty summary report after trying all candidate models.")

                # Finalize completion
                Meeting.objects.filter(id=meeting_id).update(
                    ai_report=report,
                    status="completed",
                    stage="completed",
                    error_message=None
                )
                meeting.ai_report = report
            else:
                Meeting.objects.filter(id=meeting_id).update(
                    status="completed",
                    stage="completed",
                    error_message=None
                )

            pipeline_completed = True
            logger.info("Meeting %d successfully completed by task %s (model=%s)", meeting_id, task_id, successful_model)
            return True

        except Exception as exc:
            logger.exception("Background pipeline failed for meeting %d: %s", meeting_id, exc)
            err_msg = str(exc)[:300]
            if provider and hasattr(provider, "translate_error"):
                try:
                    translated = provider.translate_error(exc)
                    if translated and hasattr(translated, "message") and isinstance(translated.message, str) and translated.message:
                        err_msg = translated.message[:300]
                except Exception:
                    pass
            Meeting.objects.filter(id=meeting_id).update(
                status="failed",
                stage="failed",
                error_message=str(err_msg)
            )
            return False

        finally:
            heartbeat.stop()
            # Clean up remote Gemini audio file ONLY on successful completion.
            # On incomplete/interrupted runs, preserve the remote Gemini reference
            # in meeting.gemini_file_name so that subsequent resume/retry can reuse it.
            if pipeline_completed and gemini_file_obj and provider and hasattr(provider, "cleanup_audio"):
                try:
                    provider.cleanup_audio(gemini_file_obj)
                    Meeting.objects.filter(id=meeting_id).update(gemini_file_name=None)
                except Exception as cleanup_err:
                    logger.warning("Remote cleanup error for meeting %d: %s", meeting_id, cleanup_err)

            cls.unregister_active_task(meeting_id, task_id)
