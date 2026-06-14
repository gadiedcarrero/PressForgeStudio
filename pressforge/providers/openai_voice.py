"""VoiceProvider con OpenAI TTS.

`gpt-4o-mini-tts` acepta `instructions` para controlar el tono (narrador
dramático). Los modelos `tts-1`/`tts-1-hd` lo ignoran sin error.
"""
from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ._openai_client import client


class OpenAIVoiceProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def synthesize(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs = dict(
            model=self.settings.voice_model,
            voice=self.settings.voice_name,
            input=text,
            response_format="mp3",
        )
        if self.settings.voice_model.startswith("gpt-4o") and self.settings.voice_instructions:
            kwargs["instructions"] = self.settings.voice_instructions

        with client().audio.speech.with_streaming_response.create(**kwargs) as response:
            response.stream_to_file(out_path)
        return out_path
