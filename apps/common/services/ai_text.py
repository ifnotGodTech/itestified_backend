import os

import requests


class AITextServiceError(Exception):
    """Raised when a transcription or translation call cannot be completed."""


def _require_openai_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AITextServiceError("Missing required environment variable: OPENAI_API_KEY")
    return api_key


def transcribe_video(*, video_url: str) -> str:
    """Downloads a testimony video and transcribes its audio via OpenAI's
    Whisper API. The only place in this codebase that talks to OpenAI for
    transcription -- tests mock this function itself, not the OpenAI SDK,
    same boundary-mocking approach as create_direct_upload_signature for
    Cloudinary.

    Known gap, not solved here: Whisper's API rejects files over 25MB, and a
    multi-minute testimony video can exceed that. This downloads the video
    as-is with no audio-extraction/compression step. Fine for short clips;
    a longer video fails closed with a clear AITextServiceError rather than
    silently truncating, but the underlying limit isn't worked around yet.
    """
    api_key = _require_openai_api_key()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AITextServiceError("openai package is not installed.") from exc

    try:
        video_response = requests.get(video_url, timeout=120)
        video_response.raise_for_status()
    except requests.RequestException as exc:
        raise AITextServiceError(f"Could not download video for transcription: {exc}") from exc

    client = OpenAI(api_key=api_key)
    try:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=("testimony.mp4", video_response.content),
        )
    except Exception as exc:  # OpenAI SDK's own exception hierarchy, wrapped
        raise AITextServiceError(f"Whisper transcription failed: {exc}") from exc
    return transcription.text.strip()


def translate_text(*, text: str, target_language: str) -> str:
    """Translates text into target_language (an ISO 639-1 code, e.g. "fr")
    via a GPT-class model. Same boundary-mocking rationale as
    transcribe_video above."""
    api_key = _require_openai_api_key()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AITextServiceError("openai package is not installed.") from exc

    client = OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional translator. Translate the user's "
                        f"text into the language with ISO 639-1 code '{target_language}'. "
                        "Return only the translated text, with no commentary or "
                        "quotation marks around it."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
    except Exception as exc:  # OpenAI SDK's own exception hierarchy, wrapped
        raise AITextServiceError(f"Translation failed: {exc}") from exc
    return response.choices[0].message.content.strip()
