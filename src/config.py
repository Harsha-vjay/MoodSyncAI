"""
Central configuration for MoodSyncAI.

Holds model identifiers, label mappings, fusion weights, and the
Aurora Glass colour palette used across the app, presentation, report
and architecture diagram so the visual identity stays consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


# ----------------------------------------------------------------------
# Model identifiers (HuggingFace Hub)
# ----------------------------------------------------------------------

# Vision Transformer fine-tuned on FER-2013 facial expression classes.
FACE_MODEL_ID: str = "trpakov/vit-face-expression"

# RoBERTa fine-tuned for fine-grained emotion classification.
TEXT_MODEL_ID: str = "j-hartmann/emotion-english-distilroberta-base"

# Whisper for audio transcription (small footprint).
AUDIO_MODEL_ID: str = "openai/whisper-base"

# Generative model for natural-language emotional summary.
GEN_MODEL_ID: str = "google/flan-t5-base"


# ----------------------------------------------------------------------
# Emotion label mappings
# ----------------------------------------------------------------------

# Canonical 7-class facial emotion set (FER-2013).
FACE_EMOTIONS: List[str] = [
    "angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"
]

# Fine-grained emotion classes for text (matches j-hartmann model).
TEXT_EMOTIONS: List[str] = [
    "anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"
]

# Coarse polarity buckets used by the fusion layer.
POLARITY: Dict[str, str] = {
    # face
    "happy": "positive",
    "surprise": "positive",
    "neutral": "neutral",
    "sad": "negative",
    "angry": "negative",
    "fear": "negative",
    "disgust": "negative",
    # text (j-hartmann)
    "joy": "positive",
    "sadness": "negative",
    "anger": "negative",
}


# ----------------------------------------------------------------------
# Fusion configuration
# ----------------------------------------------------------------------

@dataclass
class FusionConfig:
    """Hyperparameters for the learned fusion head."""
    face_dim: int = 7
    text_dim: int = 7
    hidden_dim: int = 64
    num_classes: int = 3        # positive / neutral / negative
    dropout: float = 0.2
    # Fallback weights for the simple weighted-average baseline.
    face_weight: float = 0.55
    text_weight: float = 0.45


FUSION = FusionConfig()


# ----------------------------------------------------------------------
# Aurora Glass theme — single source of truth for all artefacts
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class AuroraTheme:
    """
    Colour and typography tokens.

    These same values are mirrored in assets/style.css and reused by the
    presentation builder and the docx report generator so every
    deliverable carries the same identity.
    """
    # Backdrop gradient
    bg_start: str = "#0F0C29"
    bg_mid:   str = "#302B63"
    bg_end:   str = "#24243E"

    # Glass surface
    glass_fill:   str = "rgba(255, 255, 255, 0.06)"
    glass_border: str = "rgba(255, 255, 255, 0.18)"

    # Accents
    primary:   str = "#7C3AED"   # violet
    secondary: str = "#06B6D4"   # cyan
    tertiary:  str = "#F472B6"   # pink

    # Status
    success: str = "#10B981"
    warning: str = "#F59E0B"
    danger:  str = "#EF4444"

    # Text
    text_primary:   str = "#F8FAFC"
    text_secondary: str = "#CBD5E1"
    text_muted:     str = "#94A3B8"

    # Typography
    font_heading: str = "Space Grotesk"
    font_body:    str = "Inter"
    font_mono:    str = "JetBrains Mono"

    # Shape
    radius_lg: str = "20px"
    radius_md: str = "14px"
    blur:      str = "24px"


THEME = AuroraTheme()


# Convenience: per-emotion colour for charts.
EMOTION_COLOURS: Dict[str, str] = {
    "happy":    "#10B981",
    "joy":      "#10B981",
    "surprise": "#06B6D4",
    "neutral":  "#94A3B8",
    "sad":      "#7C3AED",
    "sadness":  "#7C3AED",
    "fear":     "#F472B6",
    "angry":    "#EF4444",
    "anger":    "#EF4444",
    "disgust":  "#F59E0B",
}
