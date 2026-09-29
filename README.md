# MoodSyncAI · Multi-Modal Sentiment & Emotion Analyser

> A Streamlit application that fuses **facial expression**, **text** and (optionally) **speech** to detect when what people *say* differs from what they *feel*.

Final project for **Data Analytics-3: Deep Learning & GenAI** (SoSe 2025).
Course: Prof. Dr. Gayan de Silva.

---

## What it does

Upload a photo of a person, type the sentence they said, and MoodSyncAI returns:

1. **Visual emotion** - top label, confidence and a full distribution across 7 classes (ViT on FER-2013).
2. **Textual sentiment** - top label and full distribution from a fine-tuned DistilRoBERTa.
3. **Fusion result** - a learned MLP combines both modalities and flags **mismatch** when face and words disagree.
4. **Generative summary** - FLAN-T5 explains the combined emotional state in plain language ("This person appears distressed despite calm language…").

The app also supports two extra modalities and a standout coaching mode:

* **🎥 Webcam / short video** - capture a sequence of snapshots live from your browser webcam, *or* upload a short clip; either way the ViT runs on every frame and a timeline chart shows how emotions shift over time.
* **🎙️ Audio** - Whisper transcribes speech and feeds the transcript into the text channel for full tri-modal fusion.
* **🧭 Conversation Coach** - beyond single-moment analysis: capture a sequence of conversation turns, plot how the alignment between modalities evolves across the whole conversation, and get **prescriptive** advice ("the alignment is drifting into mismatch at turn 3, pause and ask an open-ended question") instead of just a description. This turns MoodSyncAI from a descriptive tool into an actionable conversation companion.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Streamlit · Aurora-Glass UI                  │
└──────────────────────────────────────────────────────────────────┘
        │ image                  │ text                 │ audio
        ▼                        ▼                      ▼
┌───────────────┐       ┌────────────────┐     ┌────────────────┐
│ ViT Face      │       │ DistilRoBERTa  │     │ Whisper-base   │
│ Emotion (7)   │       │ Emotion (7)    │     │ ASR transcript │
└──────┬────────┘       └───────┬────────┘     └───────┬────────┘
       │ probs + CLS           │ probs + tokens        │ text
       ▼                        ▼                      ▼
                ┌──────────────────────────────┐
                │   Fusion MLP (learned)       │
                │   or Weighted Average        │
                │   → polarity + mismatch flag │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │   FLAN-T5 generative summary │
                └──────────────────────────────┘
```

A high-resolution diagram is in `assets/architecture.png`.

---

## Models

| Component  | Model                                     | Purpose                                |
| ---------- | ----------------------------------------- | -------------------------------------- |
| Vision     | `trpakov/vit-face-expression`             | 7-class facial emotion (FER-2013)      |
| Text       | `j-hartmann/emotion-english-distilroberta-base` | 7-class text emotion             |
| Audio      | `openai/whisper-base`                     | Speech → text                          |
| Generation | `google/flan-t5-base`                     | Plain-language emotional summary       |
| Fusion     | Custom 2-layer MLP                        | Concatenates probability vectors → 3-way polarity head |

---

## Quick start

```bash
# 1. Clone the repo
git https://github.com/Harsha-vjay/MoodSyncAI
cd MoodSyncAI

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
streamlit run app.py
```

The first run downloads ~1.5 GB of model weights from HuggingFace; subsequent runs are instant.

---

## Project structure

```
MoodSyncAI/
├── app.py                       # Streamlit entry point
├── requirements.txt
├── README.md
├── .streamlit/config.toml       # Theme tokens (dark base)
├── assets/
│   ├── style.css                # stylesheet
│   ├── architecture.png         # Architecture diagram
│   └── fusion_head.pt           # Cached fusion MLP weights
├── src/
│   ├── config.py                # Theme + model identifiers
│   ├── face_emotion.py          # ViT wrapper
│   ├── text_sentiment.py        # DistilRoBERTa wrapper
│   ├── audio_transcriber.py     # Whisper wrapper
│   ├── webcam_handler.py        # Frame sampling + timeline
│   ├── fusion.py                # Learned + weighted fusion
│   ├── generator.py             # FLAN-T5 summariser
│   ├── gradcam.py               # Attention rollout heatmaps
│   ├── coach.py                 # Conversation Coach: trajectory + advice
│   └── utils.py                 # Plotly helpers, CSS loader
└── docs/
    ├── MoodSyncAI_Documentation.docx
    └── MoodSyncAI_Presentation.pptx
```

---

## Settings (sidebar)

| Setting                         | Effect                                                   |
| ------------------------------- | -------------------------------------------------------- |
| Fusion strategy                 | Learned MLP vs. weighted average baseline                |
| Show attention visualisation    | Toggles ViT attention rollout + token attention overlays |
| Generate language summary       | Switches FLAN-T5 on/off (template fallback always works) |

---

## Deployment

### Hugging Face Spaces

1. Create a new Space → SDK: **Streamlit**.
2. Upload the repository (or push via `git`).
3. Make sure `requirements.txt` is at the root, Spaces installs it automatically.
4. Set hardware to **CPU basic** (works) or **CPU upgrade** (faster).
5. The app boots at `https://huggingface.co/spaces/<your-name>/moodsync-ai`.

### Streamlit Cloud

1. Push to a public GitHub repo.
2. Visit [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Point it at `app.py` on the `main` branch.
4. Wait for the first build (~5–8 min for model downloads).

---

## Extended features implemented

| Feature                                           | Status |
| ------------------------------------------------- | ------ |
| Webcam (live in-browser capture) + video timeline | ✅     |
| Audio input (Whisper)                             | ✅     |
| Attention visualisation (ViT rollout + tokens)    | ✅     |
| Learned fusion (MLP) instead of weighted average  | ✅     |
| Deployment-ready (HF Spaces / Streamlit Cloud)    | ✅     |
| **Conversation Coach (multi-turn prescriptive advice)** | ✅ **(beyond brief)** |

---

## Reproducing the demo

The example flow from the assignment brief works out of the box:

* Upload a face photo.
* Type **"No, I think the project is going really well."**
* Click **Analyse**.
* If the photo shows a sad/fearful expression you'll see:
  * **Visual Emotion:** Sad / Fearful (~68 %)
  * **Textual Sentiment:** Joy / Positive (~80 %)
  * **Fusion:** **Mismatch detected** (amber badge)
  * **Summary:** "*Despite expressing positive sentiment verbally, the speaker's facial cues indicate stress or discomfort…*"

---

## Limitations & ethical notes

* The face model is trained on FER-2013, which is biased toward Western, posed expressions. Predictions on other demographics are noisier.
* The system is a **conversation aid**, not a clinical or surveillance tool. The summary explicitly avoids medical / diagnostic claims.
* Audio is processed locally; nothing is uploaded beyond the user's own machine when running locally.

---

## Author

**Harsha** - Data Analytics-3, SoSe 2025
Instructor: Prof. Dr. Gayan de Silva.

---

## License

MIT - see `LICENSE`.
