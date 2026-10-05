# Katha V0 — local selected corpus only

This stage intentionally does **not** mix Katha sources into the Premanand Ji
guidance corpus or production retrieval.

## Local storage boundary

```text
data/
├── bhajan.db                      # existing Premanand Ji local registry
├── transcripts/                   # existing Premanand Ji transcripts
└── katha/
    ├── indresh_ji/
    │   ├── catalog.json
    │   ├── videos/
    │   │   └── <video_id>/metadata.json
    │   ├── transcripts/
    │   │   └── <video_id>.json
    │   ├── segments/
    │   ├── summaries/
    │   ├── taxonomy/
    │   └── tmp/
    └── rajendra_das_ji/
        ├── catalog.json
        ├── videos/
        │   └── <video_id>/metadata.json
        ├── transcripts/
        │   └── <video_id>.json
        ├── segments/
        ├── summaries/
        ├── taxonomy/
        └── tmp/
```

No Katha command writes into `data/transcripts/`, `data/bhajan.db`, or the
Premanand Qdrant collection.

The canonical media remains the original YouTube source. V0 stores metadata,
timestamps/captions when requested, and later derived Katha segmentation. It
does not permanently download/rehost full video or audio.

## Add one selected video

```bash
python -m app.katha_cli add \
  --speaker indresh_ji \
  --url "YOUTUBE_URL" \
  --series "Shrimad Bhagwat Katha" \
  --event "Vrindavan 2026" \
  --day "6" \
  --location "Vrindavan" \
  --katha-type "Bhagwat Katha"
```

Add `--with-captions` only when you want to save the available YouTube
captions locally for Katha V0 experiments.

## Add a curated small batch

Create a file containing one URL per line:

```text
# data is local/gitignored
https://www.youtube.com/watch?v=...
https://www.youtube.com/watch?v=...
```

Then:

```bash
python -m app.katha_cli add-file \
  --speaker rajendra_das_ji \
  --file ./rajendra_selected.txt \
  --series "Bhaktmaal Katha" \
  --katha-type "Bhaktmaal" \
  --with-captions
```

## Inspect

```bash
python -m app.katha_cli stats
python -m app.katha_cli list --speaker indresh_ji
python -m app.katha_cli list --speaker rajendra_das_ji
```

## V0 rules

1. Premanand Ji remains the default guidance/Q&A corpus.
2. Indresh Ji and Rajendra Das Ji remain separate Katha corpora.
3. Indresh Ji and Rajendra Das Ji also remain separate from each other.
4. Do not expose Katha V0 in normal user chat retrieval yet.
5. First prove metadata quality, series/event grouping, transcript quality and
   prasang segmentation on a small representative set.
6. Katha statements are stored as `source_kind=katha_interpretation`; they are
   not silently promoted to canonical scripture.
7. Future vector indexing must use separate collections/namespaces for each
   corpus before a source router can combine them.
