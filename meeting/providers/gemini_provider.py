import time

from google import genai

from meeting.prompts.meeting_report_prompt import MEETING_REPORT_PROMPT


class GeminiProvider:

    def __init__(self, settings):

        self.provider = settings["provider"]
        self.api_key = settings["api_key"]
        self.model_name = settings["model_name"]

        self.client = genai.Client(
            api_key=self.api_key
        )

    def test_connection(self):

        response = self.client.models.generate_content(
            model=self.model_name,
            contents="Reply with only one word: Connected"
        )

        return response.text

    def upload_audio(self, audio_path):

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

        prompt = MEETING_REPORT_PROMPT.format(
            transcript=transcript
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )

        return response.text