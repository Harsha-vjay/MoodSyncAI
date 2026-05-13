"""
Audio → text transcription using OpenAI Whisper (HuggingFace).

Used for the 3rd modality (Optional extended feature #2).  The
returned transcript is fed into the text-sentiment pipeline so the
fusion layer can combine all three signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import numpy as np
import torch

from .config import AUDIO_MODEL_ID


@dataclass
class TranscriptionResult:
    """Output of a Whisper transcription pass."""
    text: str
    language: Optional[str] = None
    duration_s: Optional[float] = None


@lru_cache(maxsize=1)
def _load_whisper():
    """Lazy-load the Whisper pipeline (CPU is fine for the base model)."""
    from transformers import pipeline   # local import to keep startup fast
    device = 0 if torch.cuda.is_available() else -1
    return pipeline(
        "automatic-speech-recognition",
        model=AUDIO_MODEL_ID,
        device=device,
        chunk_length_s=30,
    )


def transcribe_audio(
    audio: np.ndarray | str,
    sample_rate: int = 16000,
) -> TranscriptionResult:
    """
    Transcribe an audio array (float32, mono, 16kHz) or a file path.

    Falls back to silence-tolerant behaviour when the array is empty.
    """
    if isinstance(audio, np.ndarray) and audio.size == 0:
        return TranscriptionResult(text="")

    pipe = _load_whisper()

    if isinstance(audio, np.ndarray):
        # Whisper expects mono float32.
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)
        out = pipe({"array": audio, "sampling_rate": sample_rate})
    else:
        out = pipe(audio)

    text = out.get("text", "").strip()
    return TranscriptionResult(text=text)
