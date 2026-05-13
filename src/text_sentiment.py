"""
Text emotion classification with a DistilRoBERTa transformer.

Uses `j-hartmann/emotion-english-distilroberta-base` — a 6-class
emotion model (anger / disgust / fear / joy / neutral / sadness /
surprise).  We keep the raw 7-class distribution and also pool the
[CLS] embedding for the learned-fusion head.

A helper for token-level attention is included so the UI can
visualise which tokens drove the prediction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Tuple

import numpy as np
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
)

from .config import TEXT_EMOTIONS, TEXT_MODEL_ID


@dataclass
class TextResult:
    """Structured output for a single text inference."""
    label: str
    confidence: float
    distribution: Dict[str, float]
    tokens: List[str] = field(default_factory=list)
    token_attentions: List[float] = field(default_factory=list)
    cls_embedding: np.ndarray = field(default_factory=lambda: np.zeros(768))


@lru_cache(maxsize=1)
def _load_text_model():
    """Load and cache the tokenizer + model on CPU/GPU."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(TEXT_MODEL_ID)
    model = AutoModelForSequenceClassification.from_pretrained(
        TEXT_MODEL_ID, output_attentions=True
    )
    model.to(device).eval()
    return tokenizer, model, device


def _aggregate_attention(attentions: torch.Tensor) -> np.ndarray:
    """
    Reduce per-layer multi-head attention to a single per-token weight.

    Strategy: average across layers → average across heads → take the
    [CLS] row, which represents how strongly each token influenced
    the pooled classification representation.
    """
    # attentions: tuple of (batch, heads, seq, seq) per layer
    stacked = torch.stack(attentions, dim=0).mean(dim=(0, 2))  # (B, S, S)
    cls_attn = stacked[0, 0, :].cpu().numpy()                  # (S,)
    # Drop CLS-on-CLS to avoid drowning out content tokens.
    cls_attn[0] = 0.0
    if cls_attn.sum() > 0:
        cls_attn = cls_attn / cls_attn.sum()
    return cls_attn


def predict_text_sentiment(text: str) -> TextResult:
    """
    Classify the emotion of a free-text string.

    Returns top label + confidence, full distribution, the token list,
    and per-token attention weights for visualisation.
    """
    if not text or not text.strip():
        # Graceful default — caller can decide what to show.
        return TextResult(
            label="neutral",
            confidence=1.0,
            distribution={lbl: 0.0 for lbl in TEXT_EMOTIONS} | {"neutral": 1.0},
        )

    tokenizer, model, device = _load_text_model()
    enc = tokenizer(
        text, return_tensors="pt", truncation=True, max_length=128
    ).to(device)

    with torch.no_grad():
        outputs = model(**enc, output_hidden_states=True)

    probs = torch.softmax(outputs.logits, dim=-1)[0].cpu().numpy()
    id2label = model.config.id2label
    distribution = {id2label[i].lower(): float(probs[i]) for i in range(len(probs))}

    # Ensure all canonical labels exist.
    for lbl in TEXT_EMOTIONS:
        distribution.setdefault(lbl, 0.0)

    # Token attention.
    tokens = tokenizer.convert_ids_to_tokens(enc["input_ids"][0])
    attn_weights = _aggregate_attention(outputs.attentions)

    # CLS embedding for the fusion head.
    cls = outputs.hidden_states[-1][0, 0, :].cpu().numpy()

    top_label = max(distribution, key=distribution.get)
    return TextResult(
        label=top_label,
        confidence=distribution[top_label],
        distribution=distribution,
        tokens=tokens,
        token_attentions=attn_weights.tolist(),
        cls_embedding=cls,
    )
