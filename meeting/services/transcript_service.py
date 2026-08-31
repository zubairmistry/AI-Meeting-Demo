import os


class TranscriptService:

    @staticmethod
    def save_transcript(transcript_text, output_path=None, media_path=None):
        """
        Saves the transcript text to a .txt file on disk using UTF-8 encoding.
        If output_path is omitted, derives it from media_path with .txt extension.
        """
        if not output_path and media_path:
            output_path = os.path.splitext(media_path)[0] + ".txt"

        if not output_path:
            raise ValueError("Either output_path or media_path must be provided to save transcript.")

        with open(output_path, "w", encoding="utf-8") as file:
            file.write(transcript_text)

        return output_path

    @staticmethod
    def read_transcript(transcript_path):
        """
        Reads and returns the transcript text from disk.
        """
        if not transcript_path or not os.path.exists(transcript_path):
            return ""

        with open(transcript_path, "r", encoding="utf-8") as file:
            return file.read()
