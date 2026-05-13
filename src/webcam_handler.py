"""
Webcam / short-video timeline support.

Given a list of frames (PIL images) sampled from a webcam capture or
a short uploaded video, run the face emotion classifier on each
frame and return a per-frame timeline of emotion probabilities so
the UI can plot the change over time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from PIL import Image

from .config import FACE_EMOTIONS
from .face_emotion import predict_face_emotion


@dataclass
class TimelinePoint:
    """One frame's emotion estimate."""
    frame_idx: int
    timestamp_s: float
    label: str
    confidence: float
    distribution: dict


def analyse_video_frames(
    frames: Sequence[Image.Image],
    fps: float = 1.0,
) -> List[TimelinePoint]:
    """
    Run face emotion classification on a sequence of frames.

    `fps` is the sampling rate — used only to generate a timestamp
    for each frame in the returned timeline.
    """
    timeline: List[TimelinePoint] = []
    for i, frame in enumerate(frames):
        result = predict_face_emotion(frame)
        timeline.append(
            TimelinePoint(
                frame_idx=i,
                timestamp_s=i / fps if fps > 0 else float(i),
                label=result.label,
                confidence=float(result.confidence),
                distribution=dict(result.distribution),
            )
        )
    return timeline


def sample_video(path: str, max_frames: int = 8) -> List[Image.Image]:
    """
    Uniformly sample up to `max_frames` frames from a video file.

    Uses OpenCV; gracefully returns an empty list if cv2 isn't installed.
    """
    try:
        import cv2
    except ImportError:
        return []

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []

    step = max(1, total // max_frames)
    frames: List[Image.Image] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(rgb))
            if len(frames) >= max_frames:
                break
        idx += 1

    cap.release()
    return frames


def aggregate_timeline_distribution(timeline: List[TimelinePoint]) -> dict:
    """
    Average emotion distributions across the timeline so the fusion
    layer sees a single, stable per-emotion vector for short videos.
    """
    if not timeline:
        return {e: 0.0 for e in FACE_EMOTIONS}

    agg = {e: 0.0 for e in FACE_EMOTIONS}
    for pt in timeline:
        for emotion, prob in pt.distribution.items():
            agg[emotion] = agg.get(emotion, 0.0) + prob
    n = len(timeline)
    return {k: v / n for k, v in agg.items()}
