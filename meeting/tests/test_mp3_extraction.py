import os
from unittest.mock import patch, MagicMock
from django.test import TestCase

from meeting.services.audio_service import AudioService


class MP3ExtractionTests(TestCase):
    """
    Unit tests verifying production MP3 extraction (32kbps mono 16kHz libmp3lame),
    backward-compatible WAV support, duration inspection, and error handling.
    """

    @patch("subprocess.run")
    def test_extract_audio_defaults_to_mp3_with_libmp3lame(self, mock_run):
        """
        Verifies AudioService.extract_audio outputs an .mp3 file using libmp3lame, 32kbps, 16kHz, mono.
        """
        input_video = "test_video.mp4"
        output_path = AudioService.extract_audio(input_video)

        self.assertTrue(output_path.endswith(".mp3"))
        self.assertEqual(output_path, "test_video.mp3")

        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIn("-acodec", cmd_args)
        self.assertIn("libmp3lame", cmd_args)
        self.assertIn("-b:a", cmd_args)
        self.assertIn("32k", cmd_args)
        self.assertIn("-ar", cmd_args)
        self.assertIn("16000", cmd_args)
        self.assertIn("-ac", cmd_args)
        self.assertIn("1", cmd_args)
        self.assertEqual(cmd_args[-1], "test_video.mp3")

    @patch("subprocess.run")
    def test_extract_audio_backward_compatible_with_explicit_wav(self, mock_run):
        """
        Verifies AudioService.extract_audio uses pcm_s16le when .wav is explicitly passed as output_path.
        """
        input_video = "test_video.mp4"
        custom_wav = "custom_output.wav"
        output_path = AudioService.extract_audio(input_video, output_path=custom_wav)

        self.assertEqual(output_path, "custom_output.wav")
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIn("-acodec", cmd_args)
        self.assertIn("pcm_s16le", cmd_args)
        self.assertIn("16000", cmd_args)
        self.assertIn("1", cmd_args)
        self.assertEqual(cmd_args[-1], "custom_output.wav")

    def test_extract_audio_returns_existing_mp3_directly(self):
        """
        Verifies AudioService.extract_audio returns an existing .mp3 file directly without conversion.
        """
        input_mp3 = "already_extracted.mp3"
        with patch("subprocess.run") as mock_run:
            result = AudioService.extract_audio(input_mp3)
            self.assertEqual(result, "already_extracted.mp3")
            mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_get_audio_info_for_mp3_parses_duration(self, mock_run):
        """
        Verifies get_audio_info parses duration from FFmpeg output for MP3 files.
        """
        mock_process = MagicMock()
        mock_process.stderr = "  Duration: 00:02:15.50, start: 0.000000, bitrate: 32 kb/s"
        mock_run.return_value = mock_process

        info = AudioService.get_audio_info("test_clip.mp3")
        self.assertEqual(info["duration_seconds"], 135.5)
        self.assertEqual(info["sample_rate"], 16000)
        self.assertEqual(info["channels"], 1)

    @patch("subprocess.run", side_effect=Exception("FFmpeg encoding error"))
    def test_extract_audio_handles_ffmpeg_failure(self, mock_run):
        """
        Verifies that FFmpeg failures bubble up appropriately as exceptions for caller handling.
        """
        with self.assertRaises(Exception):
            AudioService.extract_audio("corrupted_video.mp4")
