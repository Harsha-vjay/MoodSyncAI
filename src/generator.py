"""
Generative summary of the combined emotional state.

Uses FLAN-T5-base (instruction-tuned T5) to produce a short,
plain-language explanation of the fusion result.  When the model is
unavailable (offline, etc.) a deterministic template fallback is used
so the demo remains functional in any environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional

from .config import GEN_MODEL_ID
from .fusion import FusionResult


@dataclass
class GenerationResult:
    """Output of the generative summariser."""
    summary: str
    source: str   # "model" or "template"


# ----------------------------------------------------------------------
# Model loading (lazy)
# ----------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_generator():
    """Load FLAN-T5; returns None on failure so the caller can fall back."""
    try:
        from transformers import pipeline
        return pipeline("text2text-generation", model=GEN_MODEL_ID)
    except Exception:
        return None


# ----------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------

def _build_prompt(
    face_label: str,
    face_conf: float,
    text_label: str,
    text_conf: float,
    fusion: FusionResult,
    transcript: Optional[str] = None,
) -> str:
    """
    Build an instruction-style prompt for FLAN-T5.

    The prompt explicitly asks for an empathic, professional one-paragraph
    summary so it doesn't drift into list output.
    """
    state = "MISMATCH" if fusion.mismatch else "ALIGNED"
    lines = [
        "You are an empathetic communication coach.",
        "Summarise the emotional state of a person from the multi-modal signals below in 2 short sentences.",
        "Be specific about whether the face and the words agree or disagree, and why this might matter.",
        "Avoid making medical or diagnostic claims.",
        "",
        f"Facial emotion: {face_label} ({face_conf*100:.0f}% confidence)",
        f"Spoken/written sentiment: {text_label} ({text_conf*100:.0f}% confidence)",
        f"Fusion polarity: {fusion.polarity} ({fusion.confidence*100:.0f}%)",
        f"Modality agreement: {state} (mismatch score = {fusion.mismatch_score:.2f})",
    ]
    if transcript:
        lines.append(f'Quote: "{transcript.strip()}"')
    lines.append("")
    lines.append("Summary:")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Template fallback
# ----------------------------------------------------------------------

def _template_summary(
    face_label: str,
    text_label: str,
    fusion: FusionResult,
) -> str:
    """Deterministic, well-written fallback in case the model is offline."""
    if fusion.mismatch:
        return (
            f"Despite expressing {text_label} sentiment in their words, the speaker's facial "
            f"cues indicate {face_label}. This incongruence suggests their verbal message may "
            f"not fully reflect what they are feeling, and is worth noting in the context of "
            f"the conversation."
        )
    if fusion.polarity == "positive":
        return (
            f"The person appears genuinely positive — their words and expression both "
            f"convey a {fusion.polarity} state. The signals align, suggesting their message "
            f"can be taken at face value."
        )
    if fusion.polarity == "negative":
        return (
            f"The person appears to be in a {fusion.polarity} emotional state. Both their "
            f"facial expression ({face_label}) and language ({text_label}) point in the same "
            f"direction, which strengthens the read."
        )
    return (
        f"The person's affect appears neutral. Neither their face ({face_label}) nor their "
        f"language ({text_label}) shows a strong emotional charge in either direction."
    )


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def generate_summary(
    face_label: str,
    face_conf: float,
    text_label: str,
    text_conf: float,
    fusion: FusionResult,
    transcript: Optional[str] = None,
    max_new_tokens: int = 90,
) -> GenerationResult:
    """
    Produce a natural-language summary of the multi-modal emotional state.

    Tries FLAN-T5 first; falls back to a hand-written template if the
    model isn't available or returns empty output.
    """
    pipe = _load_generator()
    if pipe is not None:
        try:
            prompt = _build_prompt(
                face_label, face_conf, text_label, text_conf, fusion, transcript
            )
            out = pipe(
                prompt,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=4,
            )[0]["generated_text"].strip()
            if out:
                return GenerationResult(summary=out, source="model")
        except Exception:
            pass   # any runtime error → fall through to template

    return GenerationResult(
        summary=_template_summary(face_label, text_label, fusion),
        source="template",
    )
