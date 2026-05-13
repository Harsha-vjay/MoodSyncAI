"""
MoodSyncAI — Multi-Modal Sentiment & Emotion Analyser
=====================================================

Main Streamlit application. Wires together:

* `face_emotion`     — ViT-based facial emotion classifier
* `text_sentiment`   — DistilRoBERTa text emotion classifier
* `audio_transcriber`— Whisper for the optional audio modality
* `webcam_handler`   — short-video / webcam timeline support
* `fusion`           — learned fusion MLP + simple weighted-average baseline
* `generator`        — FLAN-T5 generative summary
* `gradcam`          — attention-rollout visualisation for the ViT
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st
from PIL import Image

# Local imports
from src.config import THEME
from src.face_emotion import predict_face_emotion
from src.text_sentiment import predict_text_sentiment
from src.fusion import fuse, MISMATCH_THRESHOLD
from src.generator import generate_summary
from src.gradcam import attention_heatmap, overlay_heatmap
from src.audio_transcriber import transcribe_audio
from src.webcam_handler import (
    analyse_video_frames,
    sample_video,
    aggregate_timeline_distribution,
)
from src.utils import (
    emotion_bar_chart,
    polarity_donut,
    timeline_chart,
    coach_trajectory_chart,
    render_attention_html,
    load_css,
)
from src.coach import generate_coach_advice, make_turn


# ----------------------------------------------------------------------
# Page setup
# ----------------------------------------------------------------------

st.set_page_config(
    page_title="MoodSyncAI — Multi-Modal Sentiment Analyser",
    page_icon="🌌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject the glassmorphic stylesheet.
st.markdown(f"<style>{load_css()}</style>", unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Hero
# ----------------------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <div class="eyebrow">Data Analytics-3 · Deep Learning &amp; GenAI</div>
        <h1>MoodSyncAI</h1>
        <p>A multi-modal sentiment &amp; emotion analyser that fuses facial expression,
        text and (optionally) speech to surface the moments where what people <i>say</i>
        and what they <i>feel</i> drift apart.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------------
# Sidebar — settings
# ----------------------------------------------------------------------

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    fusion_method = st.radio(
        "Fusion strategy",
        options=["learned", "weighted"],
        format_func=lambda x: "Learned MLP (recommended)" if x == "learned" else "Weighted average",
        index=0,
    )
    show_attention = st.checkbox("Show attention visualisation", value=True)
    show_gen = st.checkbox("Generate language summary", value=True)
    st.markdown("---")
    st.markdown("### 📚 About")
    st.markdown(
        """
        **Models used**
        - ViT facial expression (FER-2013)
        - DistilRoBERTa emotion
        - Whisper-base ASR
        - FLAN-T5 generative
        - Custom fusion MLP

        **Built by:** Harsha
        **Course:** DA3 SoSe 2025
        """
    )


# ----------------------------------------------------------------------
# Helpers — render result blocks
# ----------------------------------------------------------------------

def render_face_card(face_result, image_for_attention: Image.Image | None = None) -> None:
    with st.container(border=True):
        st.markdown("### 👤 Visual Emotion")
        cols = st.columns([1.1, 1])
        with cols[0]:
            st.markdown(
                f'<div class="metric-label">Top label</div>'
                f'<div class="metric-ring">{face_result.label.title()}</div>'
                f'<div class="metric-label" style="margin-top:-4px;">'
                f'{face_result.confidence*100:.1f}% confidence</div>',
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.plotly_chart(
                emotion_bar_chart(face_result.distribution),
                use_container_width=True,
                config={"displayModeBar": False},
            )

        if show_attention and image_for_attention is not None:
            with st.expander("Attention heatmap — which facial regions drove the prediction?"):
                try:
                    heat = attention_heatmap(image_for_attention)
                    overlay = overlay_heatmap(image_for_attention, heat)
                    col_a, col_b = st.columns(2)
                    col_a.image(image_for_attention, caption="Original", use_column_width=True)
                    col_b.image(overlay, caption="Attention rollout", use_column_width=True)
                except Exception as exc:
                    st.info(f"Attention visualisation unavailable: {exc}")


def render_text_card(text_result) -> None:
    with st.container(border=True):
        st.markdown("### 💬 Textual Sentiment")
        cols = st.columns([1.1, 1])
        with cols[0]:
            st.markdown(
                f'<div class="metric-label">Top label</div>'
                f'<div class="metric-ring">{text_result.label.title()}</div>'
                f'<div class="metric-label" style="margin-top:-4px;">'
                f'{text_result.confidence*100:.1f}% confidence</div>',
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.plotly_chart(
                emotion_bar_chart(text_result.distribution),
                use_container_width=True,
                config={"displayModeBar": False},
            )

        if show_attention and text_result.tokens:
            with st.expander("Token attention — which words mattered most?"):
                html = render_attention_html(text_result.tokens, text_result.token_attentions)
                st.markdown(
                    f'<div style="line-height:2.1; padding: 0.4rem 0;">{html}</div>',
                    unsafe_allow_html=True,
                )


def render_fusion_card(fusion_result) -> None:
    with st.container(border=True):
        st.markdown("### 🔀 Fusion Result")
        cols = st.columns([1.1, 1])
        with cols[0]:
            badge_class = "badge-mismatch" if fusion_result.mismatch else "badge-match"
            badge_text = "⚠ Mismatch detected" if fusion_result.mismatch else "✓ Modalities aligned"
            st.markdown(
                f'<span class="badge {badge_class}">{badge_text}</span>'
                f'<div class="metric-label" style="margin-top:1.2rem;">Polarity</div>'
                f'<div class="metric-ring">{fusion_result.polarity.title()}</div>'
                f'<div class="metric-label" style="margin-top:-4px;">'
                f'{fusion_result.confidence*100:.1f}% · '
                f'{fusion_result.method} fusion · '
                f'mismatch score {fusion_result.mismatch_score:.2f}</div>',
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.plotly_chart(
                polarity_donut(fusion_result.polarity_scores),
                use_container_width=True,
                config={"displayModeBar": False},
            )


def render_summary_card(summary_text: str, source: str) -> None:
    with st.container(border=True):
        st.markdown("### 🧠 Generative Summary")
        st.markdown(
            f'<p style="font-size: 1.05rem; line-height: 1.6; color: #F8FAFC;">'
            f'{summary_text}</p>'
            f'<div class="metric-label" style="margin-top:0.4rem;">'
            f'Source: {source}</div>',
            unsafe_allow_html=True,
        )


# ----------------------------------------------------------------------
# Tabs — three input modes
# ----------------------------------------------------------------------

tab_image, tab_video, tab_audio, tab_coach = st.tabs([
    "📷  Image + Text",
    "🎥  Webcam / Video",
    "🎙️  Audio + Image",
    "🧭  Conversation Coach",
])


# ============================================================
# TAB 1 — IMAGE + TEXT (the core assignment workflow)
# ============================================================

with tab_image:
    col_left, col_right = st.columns([1, 1])

    with col_left:
        with st.container(border=True):
            st.markdown("### 1 · Upload a face")
            uploaded_image = st.file_uploader(
                "Drop a photo here (PNG / JPG)",
                type=["png", "jpg", "jpeg"],
                key="face_upload",
            )
            if uploaded_image is not None:
                face_image = Image.open(uploaded_image)
                st.image(face_image, use_column_width=True)
            else:
                face_image = None

    with col_right:
        with st.container(border=True):
            st.markdown("### 2 · What did they say?")
            text_input = st.text_area(
                "Type the sentence",
                value="No, I think the project is going really well.",
                height=140,
                key="text_input",
            )
            analyse_btn = st.button("✨  Analyse", use_container_width=True, key="analyse_image")

    if analyse_btn:
        if face_image is None:
            st.error("Please upload an image first.")
        elif not text_input.strip():
            st.error("Please type the sentence the person said.")
        else:
            with st.spinner("Analysing facial expression…"):
                face_res = predict_face_emotion(face_image)
            with st.spinner("Analysing text sentiment…"):
                text_res = predict_text_sentiment(text_input)
            with st.spinner("Fusing modalities…"):
                fused = fuse(face_res.distribution, text_res.distribution, method=fusion_method)
            if show_gen:
                with st.spinner("Generating summary…"):
                    summary = generate_summary(
                        face_label=face_res.label, face_conf=face_res.confidence,
                        text_label=text_res.label, text_conf=text_res.confidence,
                        fusion=fused, transcript=text_input,
                    )

            cols = st.columns(2)
            with cols[0]:
                render_face_card(face_res, image_for_attention=face_image)
            with cols[1]:
                render_text_card(text_res)
            render_fusion_card(fused)
            if show_gen:
                render_summary_card(summary.summary, summary.source)


# ============================================================
# TAB 2 — VIDEO TIMELINE
# ============================================================

def _render_frame_timeline(frames, caption_text: str, fps: float) -> None:
    """Shared rendering: run ViT on frames → timeline chart → fusion → summary."""
    with st.spinner(f"Running ViT on {len(frames)} frames…"):
        timeline = analyse_video_frames(frames, fps=fps)

    with st.container(border=True):
        st.markdown("### Emotion over time")
        st.plotly_chart(
            timeline_chart(timeline),
            use_container_width=True,
            config={"displayModeBar": False},
        )

        cols = st.columns(min(len(frames), 4))
        for col, pt, frame in zip(cols * ((len(frames) // 4) + 1), timeline, frames):
            col.image(
                frame,
                caption=f"t={pt.timestamp_s:.1f}s · {pt.label} ({pt.confidence*100:.0f}%)",
                use_column_width=True,
            )

    agg_face = aggregate_timeline_distribution(timeline)
    text_res = predict_text_sentiment(caption_text or "")
    fused = fuse(agg_face, text_res.distribution, method=fusion_method)
    render_fusion_card(fused)
    if show_gen:
        summary = generate_summary(
            face_label=max(agg_face, key=agg_face.get),
            face_conf=max(agg_face.values()),
            text_label=text_res.label, text_conf=text_res.confidence,
            fusion=fused, transcript=caption_text,
        )
        render_summary_card(summary.summary, summary.source)


with tab_video:
    # Session state for the webcam timeline
    st.session_state.setdefault("webcam_snapshots", [])
    st.session_state.setdefault("webcam_capture_key", 0)

    with st.container(border=True):
        st.markdown("### Capture or upload a face over time")
        st.markdown(
            "Build an emotion timeline two ways: take a sequence of webcam "
            "snapshots directly in the browser, or upload a short pre-recorded "
            "clip. Either way, the ViT runs on every frame and the aggregate "
            "distribution is fused with the optional caption."
        )
        video_mode = st.radio(
            "Input mode",
            options=["📸 Webcam snapshots", "🎞 Upload video"],
            horizontal=True,
            key="video_mode",
            label_visibility="collapsed",
        )

    # ------------------------------------------------------------
    # MODE A — Webcam snapshots
    # ------------------------------------------------------------
    if video_mode == "📸 Webcam snapshots":
        with st.container(border=True):
            st.markdown("### 1 · Capture webcam frames")
            st.markdown(
                "Click **Take Photo**, then **➕ Add to timeline**. Repeat to "
                "build a sequence (e.g. across 10–20 seconds of changing "
                "expression). The capture widget resets after each add."
            )

            # Dynamic key forces the widget to reset after each add.
            cam_image = st.camera_input(
                "Webcam",
                key=f"webcam_capture_{st.session_state.webcam_capture_key}",
                label_visibility="collapsed",
            )

            col_add, col_clear = st.columns([1, 1])
            with col_add:
                add_disabled = cam_image is None
                if st.button(
                    "➕ Add to timeline",
                    use_container_width=True,
                    disabled=add_disabled,
                    key="add_snapshot",
                ):
                    st.session_state.webcam_snapshots.append(
                        Image.open(cam_image).convert("RGB")
                    )
                    st.session_state.webcam_capture_key += 1
                    st.rerun()
            with col_clear:
                if st.button(
                    "🗑 Clear all",
                    use_container_width=True,
                    disabled=len(st.session_state.webcam_snapshots) == 0,
                    key="clear_snapshots",
                ):
                    st.session_state.webcam_snapshots = []
                    st.session_state.webcam_capture_key += 1
                    st.rerun()

            n = len(st.session_state.webcam_snapshots)
            st.markdown(
                f'<div class="metric-label" style="margin-top:0.6rem;">'
                f'{n} snapshot{"s" if n != 1 else ""} captured · '
                f'aim for 3–8 to see a meaningful timeline</div>',
                unsafe_allow_html=True,
            )

            if st.session_state.webcam_snapshots:
                thumb_cols = st.columns(min(n, 6))
                for i, snap in enumerate(st.session_state.webcam_snapshots):
                    thumb_cols[i % 6].image(
                        snap,
                        caption=f"#{i + 1}",
                        use_column_width=True,
                    )

        with st.container(border=True):
            st.markdown("### 2 · Caption (optional)")
            webcam_caption = st.text_input(
                "What did you say while the snapshots were taken?",
                value="",
                key="webcam_caption",
            )
            analyse_webcam_btn = st.button(
                "🎞  Analyse webcam timeline",
                use_container_width=True,
                key="analyse_webcam",
                disabled=len(st.session_state.webcam_snapshots) < 1,
            )

        if analyse_webcam_btn:
            # fps=1 → snapshot index doubles as the timestamp axis (in "seconds")
            _render_frame_timeline(
                st.session_state.webcam_snapshots,
                webcam_caption,
                fps=1.0,
            )

    # ------------------------------------------------------------
    # MODE B — Video upload
    # ------------------------------------------------------------
    else:
        with st.container(border=True):
            st.markdown("### 1 · Upload a short clip")
            video_file = st.file_uploader(
                "Upload a short video (MP4 / MOV / WEBM)",
                type=["mp4", "mov", "webm", "avi"],
                key="video_upload",
            )
            video_caption = st.text_input(
                "Optional caption / spoken transcript",
                value="",
                key="video_caption",
            )
            analyse_video_btn = st.button(
                "🎞  Analyse video",
                use_container_width=True,
                key="analyse_video",
                disabled=video_file is None,
            )

        if analyse_video_btn and video_file is not None:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp.write(video_file.read())
                video_path = tmp.name

            with st.spinner("Sampling frames…"):
                frames = sample_video(video_path, max_frames=8)

            if not frames:
                st.error("Could not read frames from the uploaded video.")
            else:
                _render_frame_timeline(frames, video_caption, fps=1.0)


# ============================================================
# TAB 3 — AUDIO + IMAGE (third modality via Whisper)
# ============================================================

with tab_audio:
    col_a, col_b = st.columns([1, 1])

    with col_a:
        with st.container(border=True):
            st.markdown("### 1 · Upload a face")
            audio_face = st.file_uploader(
                "Photo (PNG / JPG)",
                type=["png", "jpg", "jpeg"],
                key="audio_face_upload",
            )
            face_image_audio = Image.open(audio_face) if audio_face else None
            if face_image_audio:
                st.image(face_image_audio, use_column_width=True)

    with col_b:
        with st.container(border=True):
            st.markdown("### 2 · Upload an audio clip")
            audio_file = st.file_uploader(
                "Audio (WAV / MP3 / M4A)",
                type=["wav", "mp3", "m4a", "ogg", "flac"],
                key="audio_upload",
            )
            analyse_audio_btn = st.button(
                "🎙  Transcribe + analyse",
                use_container_width=True,
                key="analyse_audio",
            )

    if analyse_audio_btn:
        if face_image_audio is None or audio_file is None:
            st.error("Please upload both a photo and an audio clip.")
        else:
            with st.spinner("Transcribing audio with Whisper…"):
                with tempfile.NamedTemporaryFile(
                    suffix=Path(audio_file.name).suffix or ".wav", delete=False
                ) as tmp:
                    tmp.write(audio_file.read())
                    audio_path = tmp.name
                trans = transcribe_audio(audio_path)
                transcript = trans.text or ""

            with st.container(border=True):
                st.markdown("### 📝 Whisper transcript")
                st.markdown(
                    f"<p style='font-style: italic;'>“{transcript or '(silence)'}”</p>",
                    unsafe_allow_html=True,
                )

            with st.spinner("Analysing facial expression…"):
                face_res = predict_face_emotion(face_image_audio)
            with st.spinner("Analysing text sentiment…"):
                text_res = predict_text_sentiment(transcript)
            with st.spinner("Fusing modalities…"):
                fused = fuse(face_res.distribution, text_res.distribution, method=fusion_method)
            if show_gen:
                with st.spinner("Generating summary…"):
                    summary = generate_summary(
                        face_label=face_res.label, face_conf=face_res.confidence,
                        text_label=text_res.label, text_conf=text_res.confidence,
                        fusion=fused, transcript=transcript,
                    )

            cols = st.columns(2)
            with cols[0]:
                render_face_card(face_res, image_for_attention=face_image_audio)
            with cols[1]:
                render_text_card(text_res)
            render_fusion_card(fused)
            if show_gen:
                render_summary_card(summary.summary, summary.source)


# ============================================================
# TAB 4 — CONVERSATION COACH (multi-turn, prescriptive)
# ============================================================

with tab_coach:
    st.session_state.setdefault("coach_turns", [])
    st.session_state.setdefault("coach_thumbs", [])
    st.session_state.setdefault("coach_capture_key", 0)

    with st.container(border=True):
        st.markdown("### 🧭 Conversation Coach")
        st.markdown(
            "Capture a conversation as a series of **turns**, each one a "
            "(face + sentence) pair. The coach charts how the alignment "
            "between modalities evolves across the conversation and then "
            "tells you **what to do next** — not just what is happening."
        )

    # --- Add a new turn ---------------------------------------------
    col_face, col_text = st.columns([1, 1])
    with col_face:
        with st.container(border=True):
            st.markdown("### 1 · Face for this turn")
            coach_source = st.radio(
                "Source",
                options=["📤 Upload photo", "📸 Webcam"],
                horizontal=True,
                key="coach_face_source",
                label_visibility="collapsed",
            )
            coach_face_image = None
            if coach_source == "📤 Upload photo":
                up = st.file_uploader(
                    "Photo (PNG / JPG)",
                    type=["png", "jpg", "jpeg"],
                    key="coach_face_upload",
                )
                if up is not None:
                    coach_face_image = Image.open(up).convert("RGB")
            else:
                cam = st.camera_input(
                    "Webcam",
                    key=f"coach_cam_{st.session_state.coach_capture_key}",
                    label_visibility="collapsed",
                )
                if cam is not None:
                    coach_face_image = Image.open(cam).convert("RGB")
            if coach_face_image is not None:
                st.image(coach_face_image, use_column_width=True)

    with col_text:
        with st.container(border=True):
            st.markdown("### 2 · What did they say?")
            coach_text = st.text_area(
                "Their words this turn",
                value="",
                height=140,
                key="coach_text",
                placeholder="e.g. \"No, I think the project is going really well.\"",
            )
            add_turn_btn = st.button(
                f"➕ Add turn #{len(st.session_state.coach_turns) + 1}",
                use_container_width=True,
                disabled=(coach_face_image is None or not coach_text.strip()),
                key="coach_add_turn",
            )
            clear_turns_btn = st.button(
                "🗑 Clear conversation",
                use_container_width=True,
                disabled=len(st.session_state.coach_turns) == 0,
                key="coach_clear",
            )

    if add_turn_btn and coach_face_image is not None and coach_text.strip():
        with st.spinner("Analysing turn…"):
            face_res = predict_face_emotion(coach_face_image)
            text_res = predict_text_sentiment(coach_text)
            fused = fuse(
                face_res.distribution,
                text_res.distribution,
                method=fusion_method,
            )
            new_turn = make_turn(
                index=len(st.session_state.coach_turns) + 1,
                face_result=face_res,
                text=coach_text,
                text_result=text_res,
                fusion=fused,
            )
            st.session_state.coach_turns.append(new_turn)
            # Cache a thumbnail so we don't have to re-store the full image
            thumb = coach_face_image.copy()
            thumb.thumbnail((160, 160))
            st.session_state.coach_thumbs.append(thumb)
            st.session_state.coach_capture_key += 1
        st.rerun()

    if clear_turns_btn:
        st.session_state.coach_turns = []
        st.session_state.coach_thumbs = []
        st.session_state.coach_capture_key += 1
        st.rerun()

    # --- Conversation log -------------------------------------------
    turns = st.session_state.coach_turns
    if turns:
        with st.container(border=True):
            st.markdown(f"### 📜 Conversation log · {len(turns)} turn(s)")
            for t, thumb in zip(turns, st.session_state.coach_thumbs):
                tcol_a, tcol_b = st.columns([1, 4])
                tcol_a.image(thumb, use_column_width=True)
                badge = "⚠ MISMATCH" if t.mismatch else "✓ ALIGNED"
                badge_cls = "badge-mismatch" if t.mismatch else "badge-match"
                tcol_b.markdown(
                    f'<div class="metric-label">Turn {t.index}</div>'
                    f'<p style="margin: 0.2rem 0 0.5rem 0; font-size: 1rem; '
                    f'color:#F8FAFC;">“{t.text}”</p>'
                    f'<span class="badge {badge_cls}">{badge}</span>'
                    f'<span style="margin-left:0.6rem; color:#94A3B8; '
                    f'font-family: Space Grotesk;">'
                    f'face: <b style="color:#F8FAFC;">{t.face_label}</b> '
                    f'({t.face_conf*100:.0f}%) · '
                    f'words: <b style="color:#F8FAFC;">{t.text_label}</b> '
                    f'({t.text_conf*100:.0f}%) · '
                    f'mismatch <b style="color:#F8FAFC;">'
                    f'{t.mismatch_score:.2f}</b></span>',
                    unsafe_allow_html=True,
                )
                st.markdown("<hr class='divider-soft'/>",
                            unsafe_allow_html=True)

    # --- Trajectory chart + coach advice ----------------------------
    if turns:
        with st.container(border=True):
            st.markdown("### 📈 Emotional trajectory")
            st.plotly_chart(
                coach_trajectory_chart(turns),
                use_container_width=True,
                config={"displayModeBar": False},
            )

        if st.button(
            "🧠 Ask the coach",
            use_container_width=True,
            key="coach_ask",
        ):
            with st.spinner("The coach is thinking…"):
                advice = generate_coach_advice(turns)

            with st.container(border=True):
                st.markdown("### 🧭 Coach")
                st.markdown(
                    f'<div class="metric-label">Trajectory · '
                    f'{advice.trajectory.replace("-", " ")}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<p style="margin: 0.6rem 0 0.2rem 0; font-size: 0.95rem; '
                    f'color:#94A3B8; text-transform:uppercase; letter-spacing:0.08em;">'
                    f'Observation</p>'
                    f'<p style="font-size: 1.05rem; line-height: 1.55; color:#F8FAFC;">'
                    f'{advice.observation}</p>',
                    unsafe_allow_html=True,
                )
                if advice.reading:
                    st.markdown(
                        f'<p style="margin: 0.8rem 0 0.2rem 0; font-size: 0.95rem; '
                        f'color:#94A3B8; text-transform:uppercase; letter-spacing:0.08em;">'
                        f'Reading</p>'
                        f'<p style="font-size: 1.05rem; line-height: 1.55; color:#F8FAFC;">'
                        f'{advice.reading}</p>',
                        unsafe_allow_html=True,
                    )
                if advice.suggestion:
                    st.markdown(
                        f'<p style="margin: 0.8rem 0 0.2rem 0; font-size: 0.95rem; '
                        f'color:#FCD34D; text-transform:uppercase; letter-spacing:0.08em;">'
                        f'Suggestion</p>'
                        f'<p style="font-size: 1.05rem; line-height: 1.55; color:#F8FAFC;">'
                        f'<b>{advice.suggestion}</b></p>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f'<div class="metric-label" style="margin-top:0.6rem;">'
                    f'Source: {advice.source}</div>',
                    unsafe_allow_html=True,
                )


# ----------------------------------------------------------------------
# Footer
# ----------------------------------------------------------------------

st.markdown(
    """
    <div style="text-align:center; margin-top:3rem; opacity:0.6;
                font-family: 'Space Grotesk', sans-serif; font-size: 0.85rem;">
        MoodSyncAI · DA3 Final Project · 2025 · Built with Streamlit ·
        ViT · DistilRoBERTa · Whisper · FLAN-T5
    </div>
    """,
    unsafe_allow_html=True,
)
