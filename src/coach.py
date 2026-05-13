"""
Conversation Coach.

Turns the single-moment emotion analyser into a multi-turn coaching tool:
given a sequence of conversation turns (each with face + text predictions
already computed), it detects how the alignment between modalities
evolves and produces *prescriptive* advice for the conversation owner.

The coach output has three parts:
  - observation : one-sentence factual reading of the trajectory
  - reading     : likely emotional interpretation
  - suggestion  : one concrete action to take next

A FLAN-T5 model produces these via a structured instruction prompt; a
deterministic template fallback covers offline / cold-start environments
so the demo always renders something well-formed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional

from .fusion import FusionResult
from .generator import _load_generator   # reuse FLAN-T5 pipeline cache


# ----------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------

@dataclass
class ConversationTurn:
    """One analysed turn of the conversation."""
    index: int
    face_label: str
    face_conf: float
    text: str
    text_label: str
    text_conf: float
    polarity: str                # positive / neutral / negative
    polarity_conf: float
    mismatch: bool
    mismatch_score: float
    # signed scalars in [-1, +1] for the trajectory chart
    face_polarity_score: float
    text_polarity_score: float


@dataclass
class CoachAdvice:
    """Prescriptive output of the coach."""
    observation: str
    reading: str
    suggestion: str
    trajectory: str   # the detected pattern label
    source: str       # "model" or "template"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def polarity_to_scalar(polarity_scores: dict) -> float:
    """
    Reduce a {positive, neutral, negative} probability dict to a single
    scalar in [-1, +1].  +1 = fully positive, -1 = fully negative, 0 =
    neutral / equally split.
    """
    return float(polarity_scores.get("positive", 0.0) - polarity_scores.get("negative", 0.0))


def make_turn(
    index: int,
    face_result,
    text: str,
    text_result,
    fusion: FusionResult,
) -> ConversationTurn:
    """Build a `ConversationTurn` from the per-modality result objects."""
    return ConversationTurn(
        index=index,
        face_label=face_result.label,
        face_conf=float(face_result.confidence),
        text=text,
        text_label=text_result.label,
        text_conf=float(text_result.confidence),
        polarity=fusion.polarity,
        polarity_conf=float(fusion.confidence),
        mismatch=bool(fusion.mismatch),
        mismatch_score=float(fusion.mismatch_score),
        face_polarity_score=polarity_to_scalar(fusion.face_polarity),
        text_polarity_score=polarity_to_scalar(fusion.text_polarity),
    )


# ----------------------------------------------------------------------
# Trajectory detection
# ----------------------------------------------------------------------

TrajectoryLabel = Literal[
    "aligned-stable",
    "drift-into-mismatch",
    "sustained-mismatch",
    "recovering",
    "worsening",
    "mixed",
    "single-turn",
]


def detect_trajectory(turns: List[ConversationTurn]) -> TrajectoryLabel:
    """
    Classify how the alignment between modalities evolves across turns.

    Heuristic over the per-turn mismatch_score series:
      - 1 turn                                        → single-turn
      - all turns below threshold                     → aligned-stable
      - all turns above threshold                     → sustained-mismatch
      - last turn worse than first (crossing thresh)  → drift-into-mismatch
      - last turn better than first (crossing thresh) → recovering
      - monotonically worsening                       → worsening
      - otherwise                                     → mixed
    """
    if not turns:
        return "single-turn"
    if len(turns) == 1:
        return "single-turn"

    threshold = 0.35      # same value used in fusion.MISMATCH_THRESHOLD
    scores = [t.mismatch_score for t in turns]
    flags  = [t.mismatch for t in turns]

    if all(not f for f in flags):
        return "aligned-stable"
    if all(f for f in flags):
        return "sustained-mismatch"

    first_mm = flags[0]
    last_mm  = flags[-1]
    if not first_mm and last_mm:
        return "drift-into-mismatch"
    if first_mm and not last_mm:
        return "recovering"

    # Look at the trend on the score sequence.
    deltas = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
    if all(d >= 0 for d in deltas) and scores[-1] - scores[0] > 0.1:
        return "worsening"

    return "mixed"


# ----------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------

def _trajectory_blurb(label: TrajectoryLabel) -> str:
    """Plain-English description of each trajectory pattern."""
    return {
        "single-turn":          "only one turn so far",
        "aligned-stable":       "all turns so far show the face and the words agreeing",
        "drift-into-mismatch":  "the conversation started aligned and has drifted into incongruence",
        "sustained-mismatch":   "every turn shows the face and the words disagreeing",
        "recovering":           "the conversation started with incongruence and is recovering toward alignment",
        "worsening":            "the gap between face and words is steadily growing",
        "mixed":                "alignment is unstable across turns",
    }[label]


def _format_turn_for_prompt(t: ConversationTurn) -> str:
    flag = "MISMATCH" if t.mismatch else "ALIGNED"
    return (
        f'Turn {t.index}: face="{t.face_label}" ({t.face_conf*100:.0f}%), '
        f'words="{t.text_label}" ({t.text_conf*100:.0f}%), '
        f'fusion={t.polarity} ({t.polarity_conf*100:.0f}%), '
        f'{flag} (score={t.mismatch_score:.2f}). '
        f'Quote: "{t.text.strip()}"'
    )


def _build_prompt(turns: List[ConversationTurn], trajectory: TrajectoryLabel) -> str:
    """Structured instruction-prompt for FLAN-T5."""
    lines = [
        "You are an empathetic but practical conversation coach.",
        "Read the multi-turn conversation log below. Produce exactly three short",
        "sections labelled OBSERVATION, READING, SUGGESTION.",
        "OBSERVATION: a single factual sentence describing how the alignment",
        "between face and words evolved across the turns.",
        "READING: a single sentence about what the speaker is most likely",
        "feeling underneath their words. No medical or diagnostic claims.",
        "SUGGESTION: one concrete, kind, practical thing the listener could",
        "do NEXT in this conversation. Be specific and actionable.",
        "",
        f"Detected trajectory pattern: {trajectory} ({_trajectory_blurb(trajectory)}).",
        "Conversation log:",
    ]
    lines.extend(_format_turn_for_prompt(t) for t in turns)
    lines.append("")
    lines.append("OBSERVATION:")
    return "\n".join(lines)


def _parse_model_output(text: str) -> Optional[CoachAdvice]:
    """
    Robustly split a FLAN-T5 response into the three labelled sections.
    Returns None if the model didn't follow the format (caller falls back
    to template).
    """
    text = (text or "").strip()
    if not text:
        return None

    # The prompt ends with "OBSERVATION:" so the first section is the
    # OBSERVATION body up to "READING:".  Be lenient about whitespace.
    upper = text.upper()
    try:
        r_idx = upper.index("READING:")
        s_idx = upper.index("SUGGESTION:")
    except ValueError:
        # Format wasn't followed — treat the entire output as a single
        # observation; better than dropping the response on the floor.
        return CoachAdvice(
            observation=text,
            reading="",
            suggestion="",
            trajectory="",
            source="model",
        )

    obs = text[:r_idx].strip().rstrip(":").strip()
    rdg = text[r_idx + len("READING:"):s_idx].strip()
    sug = text[s_idx + len("SUGGESTION:"):].strip()
    # Strip the implicit "OBSERVATION:" the prompt left at the start.
    if obs.upper().startswith("OBSERVATION"):
        obs = obs.split(":", 1)[-1].strip()
    return CoachAdvice(
        observation=obs,
        reading=rdg,
        suggestion=sug,
        trajectory="",
        source="model",
    )


# ----------------------------------------------------------------------
# Template fallback
# ----------------------------------------------------------------------

_TEMPLATES: dict[TrajectoryLabel, dict[str, str]] = {
    "single-turn": {
        "observation": "Only one turn has been captured so far, so there is no trajectory to compare against yet.",
        "reading":     "The first turn shows a {polarity} polarity overall; the modalities are {flag}.",
        "suggestion":  "Capture two or three more turns to surface how the alignment evolves over the conversation.",
    },
    "aligned-stable": {
        "observation": "The face and the words have agreed across every turn so far.",
        "reading":     "The speaker is presenting a coherent emotional state — what you see is what you get.",
        "suggestion":  "Stay with the current rhythm. Genuine conversations don't need to be steered; mirror their energy and keep going.",
    },
    "drift-into-mismatch": {
        "observation": "The conversation started with the face and the words aligned, but has drifted into incongruence in recent turns.",
        "reading":     "Something in the recent topic is pulling the speaker's true affect away from what they are willing to say.",
        "suggestion":  "Pause the agenda. Try an open-ended check-in: \"That last point seemed harder — how are you really finding it?\" Avoid stacking new asks until you see the alignment recover.",
    },
    "sustained-mismatch": {
        "observation": "Every turn so far has shown the face and the words disagreeing.",
        "reading":     "The speaker appears to be masking how they actually feel, possibly because the setting doesn't feel safe enough to be candid.",
        "suggestion":  "Lower the stakes before continuing. Acknowledge that this is a hard conversation, share something vulnerable yourself, or offer to revisit at a better time.",
    },
    "recovering": {
        "observation": "The conversation started with incongruence and is now recovering toward alignment.",
        "reading":     "Whatever was unsaid is being processed; the speaker is moving toward expressing what they really feel.",
        "suggestion":  "Don't rush this. Keep doing what you just did — quiet listening or a validating reflection — and let the alignment continue to settle.",
    },
    "worsening": {
        "observation": "The gap between the face and the words has grown turn by turn.",
        "reading":     "The conversation is accumulating tension faster than it is being processed.",
        "suggestion":  "Slow down. Name what you are noticing (gently): \"I want to check — does this still feel okay?\" Make space for the speaker to redirect or stop.",
    },
    "mixed": {
        "observation": "Alignment has fluctuated across turns without a clear directional trend.",
        "reading":     "The speaker's affect is reactive to specific topics rather than to the conversation as a whole.",
        "suggestion":  "Notice which turn types triggered the mismatches and return to those. The signal is in the specific subject matter, not the overall tone.",
    },
}


def _template_advice(
    turns: List[ConversationTurn], trajectory: TrajectoryLabel
) -> CoachAdvice:
    """Deterministic, well-written fallback (no LLM required)."""
    t = _TEMPLATES[trajectory]
    last = turns[-1] if turns else None
    obs = t["observation"]
    rdg = t["reading"]
    sug = t["suggestion"]
    if last is not None and "{polarity}" in rdg:
        rdg = rdg.format(
            polarity=last.polarity,
            flag="aligned" if not last.mismatch else "incongruent",
        )
    return CoachAdvice(
        observation=obs,
        reading=rdg,
        suggestion=sug,
        trajectory=trajectory,
        source="template",
    )


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def generate_coach_advice(turns: List[ConversationTurn]) -> CoachAdvice:
    """
    Produce prescriptive coaching advice over a sequence of turns.

    Tries FLAN-T5 first. If the model is unavailable or returns
    unparseable output, the deterministic template covers the same
    trajectory pattern.
    """
    trajectory = detect_trajectory(turns)

    pipe = _load_generator()
    if pipe is not None and turns:
        try:
            prompt = _build_prompt(turns, trajectory)
            out = pipe(
                prompt,
                max_new_tokens=180,
                do_sample=False,
                num_beams=4,
            )[0]["generated_text"]
            parsed = _parse_model_output(out)
            if parsed and parsed.observation:
                parsed.trajectory = trajectory
                return parsed
        except Exception:
            pass

    return _template_advice(turns, trajectory)
