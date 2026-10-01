# Bhajan Marg AI — full local RAG + growing corpus

This project builds a local chatbot that:

- indexes Bhajan Marg video transcripts with exact time ranges;
- searches the full indexed corpus on **every** user turn, including follow-ups;
- combines dense semantic retrieval + Unicode lexical sparse retrieval;
- reranks candidates with a multilingual cross-encoder;
- grades evidence as `direct`, `related`, or `none`;
- lets the LLM explain the teaching devotionally without pretending to be Premanand Ji;
- shows transcript-derived evidence separately with the exact video/timestamp;
- adds newly uploaded videos every day without rebuilding the whole corpus;
- keeps raw transcript JSON as the canonical source of truth;
- includes an optional, review-first LoRA style-training pipeline.

## 0. Important distinction

The generated explanation is AI-generated. It is **not** a quote from Premanand Ji.

Only the source card's `transcript_excerpt` is copied from the stored transcript.
If that transcript came from YouTube auto-captions or Whisper, it can still have
speech-recognition errors. Always link users to the original timestamp.

Use/collection of YouTube content must comply with the platform's terms and the
rights holder's permissions.

## 1. Requirements

Recommended:
- Python 3.11 or 3.12
- Docker Desktop
- Ollama
- 16 GB RAM is comfortable; lower-memory machines can switch to a smaller LLM
- `ffmpeg` only if Whisper fallback is enabled

macOS:
```bash
brew install python@3.12 ffmpeg
brew install --cask ollama
```

## 2. Setup

```bash
cp .env.example .env

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d

ollama pull qwen3:8b
```

If 8B is too heavy:
```bash
ollama pull qwen3:4b
```
and change `OLLAMA_MODEL=qwen3:4b` in `.env`.

Verify:
```bash
curl http://localhost:6333
curl http://localhost:11434/api/tags
```

## 3. First ingestion

Start small:
```bash
python -m app.cli backfill --limit 10
```

Then:
```bash
python -m app.cli backfill --limit 100
```

After validating retrieval, backfill all videos:
```bash
python -m app.cli backfill --all
```

The process is resumable: already indexed video IDs are skipped.

Check:
```bash
python -m app.cli stats
```

## 4. Run chatbot

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:
http://localhost:8000

API docs:
http://localhost:8000/docs

## 5. How follow-ups work

Every `/api/chat` call:
1. loads recent conversation context;
2. rewrites the current message into a standalone retrieval query;
3. performs a brand-new hybrid search across the entire indexed corpus;
4. reranks the result;
5. grades evidence;
6. generates a fresh explanation.

Conversation history is used to understand the question, **not as evidence**.

## 6. Search architecture

Each chunk stores:
- `dense`: BGE-M3 dense vector
- `lexical`: language-independent hashed Unicode tokens + word bigrams

Qdrant fuses the two candidate lists using RRF. A multilingual cross-encoder
then reranks the fused results.

The lexical representation intentionally does not depend on an English stemmer,
so Devanagari/Hindi exact terms remain useful.

## 7. Daily new videos

When the API server is running, APScheduler checks the latest videos every day.

Defaults:
```env
DAILY_UPDATE_ENABLED=true
DAILY_UPDATE_HOUR=2
DAILY_UPDATE_MINUTE=15
DAILY_SCAN_LATEST=40
TIMEZONE=Asia/Kolkata
```

Manual:
```bash
python -m app.cli update --latest 40
```

The updater checks video IDs and only ingests videos that are not already indexed.

## 8. Transcript storage

Canonical transcript:
```text
data/transcripts/<video_id>.json
```

It contains timestamp-level segments with:
- raw caption text
- de-duplicated searchable text
- start/end milliseconds
- transcript source

Search chunks are separately stored in SQLite and Qdrant.

## 9. Missing captions / Whisper fallback

By default:
```env
WHISPER_FALLBACK=false
```

To use fallback:
```bash
pip install -r requirements-whisper.txt
```

Then:
```env
WHISPER_FALLBACK=true
WHISPER_MODEL=small
```

For a large channel, transcription is compute-heavy. Prefer legitimate existing
captions where available, and enable fallback only where permitted.

## 10. YouTube restrictions

Sometimes YouTube requires authentication/cookies for automated access. You can
optionally set:

```env
YTDLP_COOKIES_FROM_BROWSER=chrome
```

Use your own authorized browser session only.

Keep `yt-dlp` current:
```bash
pip install -U yt-dlp
```

## 11. Evidence levels

`direct`
: transcript material substantially answers the user's question.

`related`
: a teaching is relevant but does not directly answer the exact situation.

`none`
: no sufficiently relevant source. The LLM may give a general explanation, but
the answer explicitly labels it uncited and does not attribute it to Premanand Ji.

Thresholds can be tuned:
```env
STRONG_EVIDENCE_THRESHOLD=0.72
RELATED_EVIDENCE_THRESHOLD=0.45
```

These are heuristic thresholds, not probabilities. Build a human-labelled
evaluation set before production.

## 12. Optional style learning

Daily videos should **not** trigger daily LLM retraining.

Knowledge freshness:
```text
new video -> transcript -> chunks -> embeddings -> instantly searchable
```

Model improvement:
```text
accumulated corpus -> curated examples -> evaluation -> periodic LoRA
```

Build candidate examples:
```bash
python training/build_style_dataset.py --limit 500
```

Manually review the JSONL. Then on an NVIDIA machine:
```bash
pip install -r training/requirements.txt

python training/train_lora.py \
  --model Qwen/Qwen3-4B \
  --data training/data/style_examples.jsonl \
  --output training/output/bhajan-style-lora
```

Never use synthetic training outputs as citation evidence. Citations always come
from canonical transcript files.

## 13. Production upgrades after validation

For a large public deployment:
- run the API behind nginx/Caddy;
- move ingestion to a worker queue;
- store raw transcript JSON in object storage;
- use Qdrant Cloud or a replicated Qdrant deployment;
- add authentication/rate limiting;
- build a labelled retrieval test set;
- add transcript quality scores and manual correction tooling;
- add a second retrieval model specialized on your corpus;
- train the reranker on hard positives/negatives from real user searches;
- version and evaluate every LoRA before deployment.

## 14. Troubleshooting

### `Connection refused localhost:6333`
```bash
docker compose up -d
```

### `Connection refused localhost:11434`
Start Ollama, then:
```bash
ollama serve
```

### no captions
Try updating `yt-dlp`, using authorized browser cookies, or enable Whisper
fallback when appropriate.

### first request is slow
BGE-M3 and the reranker download on first use. Subsequent requests reuse them.

### Apple Silicon memory pressure
Use:
```env
OLLAMA_MODEL=qwen3:4b
RERANKER_ENABLED=false
```
to get the pipeline running, then re-enable reranking for quality tests.
