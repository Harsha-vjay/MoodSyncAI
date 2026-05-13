"""
Facial emotion classification with a Vision Transformer.

Wraps the HuggingFace pipeline for `trpakov/vit-face-expression`, a
ViT-base model fine-tuned on FER-2013, and exposes a single
`predict()` method that returns a probability distribution over
the 7 canonical emotions.

A `predict_with_features()` method is also provided that returns the
penultimate CLS embedding so the learned-fusion head can consume a
richer signal than just probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Tuple

import numpy as np
import torch
from PIL import Image
from transformers import (
    AutoImageProcessor,
    AutoModelForImageClassification,
)

from .config import FACE_EMOTIONS, FACE_MODEL_ID


@dataclass
class FaceResult:
    """Structured output for a single face inference."""
    label: str
    confidence: float
    distribution: Dict[str, float]
    logits: np.ndarray            # raw model logits (7,)
    cls_embedding: np.ndarray     # CLS hidden state (768,)


@lru_cache(maxsize=1)
def _load_face_model() -> Tuple[AutoImageProcessor, AutoModelForImageClassification, torch.device]:
    """Load and cache the ViT model + processor.  CPU-friendly."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor = AutoImageProcessor.from_pretrained(FACE_MODEL_ID)
    model = AutoModelForImageClassification.from_pretrained(FACE_MODEL_ID)
    model.to(device).eval()
    return processor, model, device


def _normalise_label(label: str) -> str:
    """Map any model-specific label to our canonical emotion vocab."""
    label = label.lower().strip()
    aliases = {
        "happiness": "happy",
        "anger":     "angry",
        "sadness":   "sad",
        "neutrality":"neutral",
    }
    return aliases.get(label, label)


def predict_face_emotion(image: Image.Image) -> FaceResult:
    """
    Run ViT inference on a PIL image and return a `FaceResult`.

    The CLS embedding is also returned (768-dim) so the learned-fusion
    head can use it instead of the 7-dim probability vector when
    higher-fidelity fusion is desired.
    """
    processor, model, device = _load_face_model()

    # Always use RGB to match the processor's expectation.
    if image.mode != "RGB":
        image = image.convert("RGB")

    inputs = processor(images=image, return_tensors="pt").to(device)

    with torch.no_grad():
        outputs = model(**inputs, output_hidden_states=True)

    logits = outputs.logits[0].cpu().numpy()
    probs = torch.softmax(outputs.logits, dim=-1)[0].cpu().numpy()

    # Pull CLS token from the last hidden state — first patch position.
    cls = outputs.hidden_states[-1][0, 0, :].cpu().numpy()

    id2label = model.config.id2label
    distribution = {
        _normalise_label(id2label[i]): float(probs[i])
        for i in range(len(probs))
    }

    # Re-order to canonical FER-2013 order so downstream code is stable.
    distribution = {
        label: distribution.get(label, 0.0) for label in FACE_EMOTIONS
    }

    top_label = max(distribution, key=distribution.get)
    return FaceResult(
        label=top_label,
        confidence=distribution[top_label],
        distribution=distribution,
        logits=logits,
        cls_embedding=cls,
    )
