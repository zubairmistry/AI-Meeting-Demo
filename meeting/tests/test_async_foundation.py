import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User

from meeting.models import Meeting
from meeting.services.async_task_service import AsyncTaskService


class AsyncFoundationTests(TestCase):
    """
    Unit tests for Step 1 async backend foundation:
    - Model field additions (stage, error_message, task_id, gemini_file_name)
    - Task identity separation
    - Concurrency and lease acquisition (select_for_update)
    - Checkpointed pipeline execution and idempotency
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="test_async_user",
            email="test_async@example.com",
            password="securepassword123"
        )
        self.meeting = Meeting.objects.create(
            user=self.user,
            meeting_name="Test Async Meeting",
            original_file="test_video.mp4",
            audio_file="test_audio.wav",
            transcript_file="test_transcript.txt",
            provider="gemini",
            model_name="gemini-2.5-flash",
            meeting_type="",
            transcript="",
            ai_report="",
            duration=30.0,
            file_size=1024000,
            status="processing"
        )
        # Clean in-memory task registry
        AsyncTaskService.unregister_active_task(self.meeting.id)

    def tearDown(self):
        AsyncTaskService.unregister_active_task(self.meeting.id)

    def test_meeting_model_fields_and_defaults(self):
        """
        Verifies new fields exist on Meeting model with appropriate defaults.
        """
        meeting = Meeting.objects.get(id=self.meeting.id)
        self.assertEqual(meeting.stage, "queued")
        self.assertIsNone(meeting.error_message)
        self.assertIsNone(meeting.task_id)
        self.assertIsNone(meeting.gemini_file_name)

    def test_task_identity_separation(self):
        """
        Verifies meeting_id, task_id, and gemini_file_name are stored and handled separately.
        """
        test_task_uuid = str(uuid.uuid4())
        test_gemini_name = "files/test_asset_98765"

        self.meeting.task_id = test_task_uuid
        self.meeting.gemini_file_name = test_gemini_name
        self.meeting.save()

        refreshed = Meeting.objects.get(id=self.meeting.id)
        self.assertIsInstance(refreshed.id, int)
        self.assertEqual(refreshed.task_id, test_task_uuid)
        self.assertEqual(refreshed.gemini_file_name, test_gemini_name)
        self.assertNotEqual(refreshed.task_id, refreshed.gemini_file_name)

    def test_acquire_processing_lease_success(self):
        """
        Verifies acquiring lease sets unique task_id, updates stage to 'queued',
        and registers the task in memory.
        """
        self.meeting.status = "failed"
        self.meeting.save()

        task_id = AsyncTaskService.acquire_processing_lease(self.meeting.id, user=self.user, allow_retry=True)
        self.assertIsNotNone(task_id)

        refreshed = Meeting.objects.get(id=self.meeting.id)
        self.assertEqual(refreshed.status, "processing")
        self.assertEqual(refreshed.stage, "queued")
        self.assertEqual(refreshed.task_id, task_id)
        self.assertTrue(AsyncTaskService.is_task_active(self.meeting.id))
        self.assertEqual(AsyncTaskService.get_active_task_id(self.meeting.id), task_id)

    def test_acquire_processing_lease_rejects_duplicate_active_task(self):
        """
        Verifies lease acquisition fails if the meeting is already processing and registered active.
        """
        task_id = AsyncTaskService.acquire_processing_lease(self.meeting.id, user=self.user)
        self.assertIsNotNone(task_id)

        # Attempting second lease on active task must return None
        duplicate_lease = AsyncTaskService.acquire_processing_lease(self.meeting.id, user=self.user)
        self.assertIsNone(duplicate_lease)

    def test_acquire_processing_lease_rejects_completed_without_retry(self):
        """
        Verifies completed meetings cannot acquire a lease unless allow_retry is True.
        """
        self.meeting.status = "completed"
        self.meeting.save()

        lease = AsyncTaskService.acquire_processing_lease(self.meeting.id, user=self.user, allow_retry=False)
        self.assertIsNone(lease)

    def test_update_stage_checkpoints_metadata(self):
        """
        Verifies update_stage correctly updates stage, gemini_file_name, and error_message.
        """
        AsyncTaskService.update_stage(
            self.meeting.id,
            stage="uploading_to_ai",
            gemini_file_name="files/remote_abc_123"
        )
        refreshed = Meeting.objects.get(id=self.meeting.id)
        self.assertEqual(refreshed.stage, "uploading_to_ai")
        self.assertEqual(refreshed.gemini_file_name, "files/remote_abc_123")

    @patch("meeting.services.async_task_service.ProviderFactory.get_provider")
    def test_pipeline_stepwise_skips_transcription_if_transcript_exists(self, mock_get_provider):
        """
        Verifies that if Meeting.transcript is already populated in DB,
        audio extraction and transcription are skipped, proceeding directly to summary.
        """
        mock_provider = MagicMock()
        mock_provider.generate_report.return_value = "### Test Summary Report"
        mock_get_provider.return_value = mock_provider

        # Pre-populate transcript
        self.meeting.transcript = "Pre-existing transcript from previous checkpoint."
        task_id = str(uuid.uuid4())
        self.meeting.task_id = task_id
        self.meeting.save()
        AsyncTaskService.register_active_task(self.meeting.id, task_id)

        success = AsyncTaskService.run_pipeline_stepwise(
            meeting_id=self.meeting.id,
            task_id=task_id,
            media_filepath="dummy_path.mp4"
        )

        self.assertTrue(success)
        mock_provider.upload_audio.assert_not_called()
        mock_provider.generate_transcript.assert_not_called()
        mock_provider.generate_report.assert_called_once_with("Pre-existing transcript from previous checkpoint.")

        refreshed = Meeting.objects.get(id=self.meeting.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.stage, "completed")
        self.assertEqual(refreshed.ai_report, "### Test Summary Report")
        self.assertFalse(AsyncTaskService.is_task_active(self.meeting.id))
