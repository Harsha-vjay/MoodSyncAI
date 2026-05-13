"""Shared helpers: chart factories, audio utilities, glass styling."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np
import plotly.graph_objects as go

from .config import EMOTION_COLOURS, THEME


# ----------------------------------------------------------------------
# Plotly factories — all charts inherit the Aurora Glass palette
# ----------------------------------------------------------------------

def _glass_layout(height: int = 300) -> dict:
    """Common layout settings so charts feel like the rest of the UI."""
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=THEME.font_body, color=THEME.text_secondary, size=13),
        margin=dict(l=8, r=8, t=12, b=8),
        height=height,
        xaxis=dict(showgrid=False, color=THEME.text_muted),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(255,255,255,0.07)",
            color=THEME.text_muted,
        ),
    )


def emotion_bar_chart(distribution: Dict[str, float], title: str = "") -> go.Figure:
    """Horizontal bar chart of an emotion distribution."""
    items = sorted(distribution.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    values = [v * 100 for _, v in items]
    colours = [EMOTION_COLOURS.get(lbl, THEME.primary) for lbl in labels]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colours, line=dict(width=0)),
            text=[f"{v:.0f}%" for v in values],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_layout(**_glass_layout(height=320), title=title)
    fig.update_xaxes(range=[0, 100], ticksuffix="%")
    return fig


def polarity_donut(scores: Dict[str, float]) -> go.Figure:
    """Donut chart for polarity (positive / neutral / negative)."""
    palette = {
        "positive": THEME.success,
        "neutral":  THEME.text_muted,
        "negative": THEME.danger,
    }
    fig = go.Figure(
        go.Pie(
            labels=[k.capitalize() for k in scores.keys()],
            values=[v * 100 for v in scores.values()],
            hole=0.65,
            marker=dict(colors=[palette[k] for k in scores.keys()]),
            textinfo="label+percent",
        )
    )
    fig.update_layout(
        showlegend=False,
        **_glass_layout(height=300),
    )
    return fig


def timeline_chart(timeline) -> go.Figure:
    """
    Stacked-area chart of emotion probabilities over time for a short
    video / webcam capture.
    """
    if not timeline:
        return go.Figure(layout=_glass_layout(height=260))

    times = [pt.timestamp_s for pt in timeline]
    emotions = list(timeline[0].distribution.keys())
    fig = go.Figure()
    for e in emotions:
        fig.add_trace(
            go.Scatter(
                x=times,
                y=[pt.distribution.get(e, 0) * 100 for pt in timeline],
                mode="lines",
                stackgroup="one",
                name=e,
                line=dict(width=0.5, color=EMOTION_COLOURS.get(e, THEME.primary)),
                fillcolor=EMOTION_COLOURS.get(e, THEME.primary),
                opacity=0.9,
            )
        )
    fig.update_layout(
        **_glass_layout(height=300),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            font=dict(color=THEME.text_secondary)
        ),
    )
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    fig.update_xaxes(title_text="time (s)")
    return fig


# ----------------------------------------------------------------------
# Conversation-coach trajectory chart
# ----------------------------------------------------------------------

def coach_trajectory_chart(turns) -> go.Figure:
    """
    Two-panel chart of a multi-turn conversation:
      - top:    face polarity vs. text polarity per turn (range [-1, +1])
      - bottom: mismatch score per turn (range [0, 1]) with threshold line

    `turns` is a list of `coach.ConversationTurn` (or any objects with the
    same attribute names) so this helper has no import-cycle with coach.
    """
    if not turns:
        return go.Figure(layout=_glass_layout(height=320))

    from plotly.subplots import make_subplots  # local import keeps top tidy

    indices  = [t.index for t in turns]
    face_pol = [t.face_polarity_score for t in turns]
    text_pol = [t.text_polarity_score for t in turns]
    mismatch = [t.mismatch_score for t in turns]

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.4],
        vertical_spacing=0.10,
        subplot_titles=("Polarity per turn (face vs. words)",
                        "Mismatch score per turn"),
    )

    # Top: face & text polarity
    fig.add_trace(
        go.Scatter(
            x=indices, y=face_pol,
            mode="lines+markers", name="Face polarity",
            line=dict(color=THEME.tertiary, width=3),
            marker=dict(size=10, color=THEME.tertiary),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=indices, y=text_pol,
            mode="lines+markers", name="Text polarity",
            line=dict(color=THEME.secondary, width=3),
            marker=dict(size=10, color=THEME.secondary),
        ),
        row=1, col=1,
    )
    # Neutral reference line at zero
    fig.add_hline(
        y=0, line_dash="dot", line_color="rgba(255,255,255,0.25)",
        row=1, col=1,
    )

    # Bottom: mismatch score
    bar_colors = [
        THEME.warning if m >= 0.35 else THEME.success for m in mismatch
    ]
    fig.add_trace(
        go.Bar(
            x=indices, y=mismatch,
            marker=dict(color=bar_colors),
            name="Mismatch score",
            text=[f"{m:.2f}" for m in mismatch],
            textposition="outside",
        ),
        row=2, col=1,
    )
    fig.add_hline(
        y=0.35, line_dash="dash", line_color=THEME.warning,
        annotation_text="mismatch threshold",
        annotation_font_color=THEME.warning,
        annotation_position="top right",
        row=2, col=1,
    )

    # Layout / styling
    fig.update_layout(
        **_glass_layout(height=420),
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.06, xanchor="right", x=1,
            font=dict(color=THEME.text_secondary),
        ),
        barmode="group",
    )
    fig.update_yaxes(
        range=[-1.05, 1.05], tickvals=[-1, -0.5, 0, 0.5, 1],
        title_text="negative ←→ positive",
        gridcolor="rgba(255,255,255,0.07)", color=THEME.text_muted,
        row=1, col=1,
    )
    fig.update_yaxes(
        range=[0, 1.05],
        title_text="‖face − text‖₂ / √2",
        gridcolor="rgba(255,255,255,0.07)", color=THEME.text_muted,
        row=2, col=1,
    )
    fig.update_xaxes(
        title_text="turn", tickmode="linear", dtick=1,
        color=THEME.text_muted, row=2, col=1,
    )
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    return fig


# ----------------------------------------------------------------------
# Token attention helpers
# ----------------------------------------------------------------------

def render_attention_html(tokens: Sequence[str], weights: Sequence[float]) -> str:
    """
    Render a sequence of tokens with background opacity proportional to
    attention weight. Returns an HTML snippet ready for st.markdown.
    """
    if not tokens:
        return ""
    max_w = max(weights) if max(weights) > 0 else 1.0

    spans: List[str] = []
    for tok, w in zip(tokens, weights):
        # Skip special tokens for cleaner display.
        if tok in {"<s>", "</s>", "<pad>", "[CLS]", "[SEP]"}:
            continue
        clean = tok.replace("Ġ", " ").replace("▁", " ")
        opacity = min(1.0, max(0.05, w / max_w))
        spans.append(
            f'<span style="background: rgba(124, 58, 237, {opacity:.2f}); '
            f'padding: 2px 4px; margin: 1px; border-radius: 6px; '
            f'font-family: {THEME.font_mono};">{clean}</span>'
        )
    return "".join(spans)


# ----------------------------------------------------------------------
# Asset paths
# ----------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def load_css() -> str:
    """Load and return the glassmorphic stylesheet."""
    css_file = ASSETS / "style.css"
    if css_file.exists():
        return css_file.read_text(encoding="utf-8")
    return ""
