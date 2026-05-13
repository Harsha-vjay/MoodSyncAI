"""
Attention visualisation for the Vision Transformer.

A pure-PyTorch attention-rollout implementation that highlights which
facial regions most influenced the predicted emotion, without
requiring the optional `pytorch-grad-cam` dependency.

Reference: Abnar & Zuidema (2020) — "Quantifying Attention Flow
in Transformers".
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import torch
from PIL import Image

from .face_emotion import _load_face_model


def _attention_rollout(
    attentions: Tuple[torch.Tensor, ...],
    discard_ratio: float = 0.85,
    head_fusion: str = "mean",
) -> np.ndarray:
    """
    Compute attention rollout — multiply attention matrices across
    layers (after a residual + low-attention prune step) to get a
    single attention map relative to the [CLS] token.
    """
    result = torch.eye(attentions[0].size(-1))
    with torch.no_grad():
        for attn in attentions:
            if head_fusion == "mean":
                attn_heads = attn.mean(dim=1)
            elif head_fusion == "max":
                attn_heads = attn.max(dim=1)[0]
            else:
                attn_heads = attn.mean(dim=1)

            # Drop the lowest `discard_ratio` of attentions per row.
            flat = attn_heads.view(attn_heads.size(0), -1)
            n_drop = int(flat.size(-1) * discard_ratio)
            if n_drop > 0:
                _, idx = flat.topk(n_drop, largest=False)
                flat.scatter_(-1, idx, 0)
            attn_heads = flat.view_as(attn_heads)

            # Add the identity (residual) and renormalise.
            I = torch.eye(attn_heads.size(-1))
            a = (attn_heads + I) / 2
            a = a / a.sum(dim=-1, keepdim=True)
            result = torch.matmul(a[0], result)

    # First row corresponds to the CLS token.
    cls_attn = result[0, 1:]   # drop CLS-on-CLS
    grid = int(np.sqrt(cls_attn.numel()))
    return cls_attn.reshape(grid, grid).cpu().numpy()


def attention_heatmap(image: Image.Image) -> np.ndarray:
    """
    Return a (H, W) heatmap in [0, 1] aligned with the input image.

    Caller can overlay it on the original image with matplotlib or PIL.
    """
    processor, model, device = _load_face_model()
    if image.mode != "RGB":
        image = image.convert("RGB")

    inputs = processor(images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs, output_attentions=True)

    heat = _attention_rollout(outputs.attentions)

    # Normalise & resize to the original image.
    heat = (heat - heat.min()) / (heat.max() - heat.min() + 1e-8)
    heat_img = Image.fromarray((heat * 255).astype(np.uint8)).resize(
        image.size, resample=Image.BICUBIC
    )
    return np.asarray(heat_img, dtype=np.float32) / 255.0


def overlay_heatmap(
    image: Image.Image,
    heatmap: np.ndarray,
    alpha: float = 0.45,
) -> Image.Image:
    """Blend a [0,1] heatmap on top of a PIL image using a viridis-like LUT."""
    import matplotlib.cm as cm

    if image.mode != "RGB":
        image = image.convert("RGB")

    base = np.asarray(image, dtype=np.float32) / 255.0
    cmap = cm.get_cmap("plasma")
    coloured = cmap(heatmap)[..., :3].astype(np.float32)

    blended = (1 - alpha) * base + alpha * coloured
    blended = np.clip(blended * 255, 0, 255).astype(np.uint8)
    return Image.fromarray(blended)
