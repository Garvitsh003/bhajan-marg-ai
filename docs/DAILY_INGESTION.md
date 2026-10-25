# Daily YouTube ingestion

The GitHub Actions workflow checks the configured Bhajan Marg channel surfaces
every day at 03:15 Asia/Kolkata. It inspects recent uploads, skips video IDs
already present in the configured Qdrant Cloud collection, fetches available
caption tracks, creates timestamped chunks, and uploads them using the same
cloud dense/sparse vector names as production retrieval. It does not retrain the
model or rebuild the whole index.

## Required one-time setup

In repository **Settings → Secrets and variables → Actions**, configure:

**Secrets**
- `QDRANT_URL`: Qdrant Cloud cluster URL.
- `QDRANT_API_KEY`: a key scoped as narrowly as possible to the target collection.
- `INGESTION_ALERT_WEBHOOK` (optional): Slack-compatible webhook for failure alerts.

**Variables**
- `QDRANT_COLLECTION`: exact collection used by the deployed API (currently expected to be `bhajan_marg_chunks_cloud_v1`).
- `TRANSCRIPT_USE_AUTHORIZED`: leave unset or `false` until you have confirmed the required rights. Set to the literal `true` only after you have permission to store/process transcripts and display excerpts in this product.
- Optional: `DAILY_SCAN_LATEST` (default 40), `QDRANT_DENSE_MODEL` (default `sentence-transformers/all-minilm-l6-v2`), and `QDRANT_BM25_MODEL` (default `qdrant/bm25`).

Use the same model names and collection as the live API. Do not create a new collection for this workflow.

## Rights and platform terms

Publicly viewable YouTube videos or auto-captions do **not** automatically grant
permission to copy, store, index, or redistribute their transcript text. Get
permission/licensing from the relevant rights holder and check applicable YouTube
terms before enabling this workflow. The authorization variable is a deliberate
fail-closed gate, not a license or legal determination. Until then, leave it
disabled and continue with content you are authorized to use.

The workflow uses available captions only; Whisper/audio-download fallback is
disabled. It does not use browser cookies. Caption availability and YouTube
access can still change, so failures are summarized in Actions and can trigger
the optional webhook.

## Operations

- Use **Actions → Daily YouTube transcript ingestion → Run workflow** for a manual run.
- Check the workflow summary for discovered/indexed/skipped/failed counts.
- A partial failure exits nonzero and is retried on the next scheduled run; successful uploads are idempotent by deterministic chunk IDs.
- The workflow only syncs searchable transcript chunks to Qdrant Cloud; it does not commit raw transcript files into Git.
