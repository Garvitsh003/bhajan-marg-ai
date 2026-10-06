# V1.5.1 — Corpus Intelligence & High-Recall Retrieval

Katha is out of scope. This release applies only to the existing Premanand Ji / Bhajan Marg transcript corpus.

## Design

The system separates retrieval understanding from answer evidence:

1. Existing transcripts remain the source of truth.
2. Offline corpus understanding reads every saved transcript and produces retrieval-only metadata.
3. Semantic sections are expanded into a 10-second addressable temporal map without calling an LLM once per 10 seconds.
4. Transcript chunks retain exact text/timestamps and receive optional `search_text` + semantic metadata.
5. User questions are parsed into language, domain, situation, intent, emotion, constraints, concepts and retrieval phrases.
6. Retrieval searches the original query plus bounded semantic/language variants.
7. A wide recall recovery pass is triggered when the normal result is weak.
8. Reranking sees title, semantic metadata and transcript evidence.
9. The evidence judge remains authoritative for direct/related/none.
10. Answers continue to use exact transcript evidence and exact timestamps.

## Offline corpus build

Build semantic artifacts from already-saved transcripts:

```bash
python -m scripts.build_corpus_intelligence
```

Start with a small sample:

```bash
python -m scripts.build_corpus_intelligence --limit 10
```

Build one known video:

```bash
python -m scripts.build_corpus_intelligence --video-id 5vzzUFSo_E4 --force
```

Artifacts are written under `data/corpus_intelligence/` and are ignored by git.

## Rebuild the local search index

After corpus artifacts exist:

```bash
python -m scripts.reindex_v151 --require-intelligence
```

This does not download YouTube media. It reads saved transcripts, rebuilds chunks, attaches semantic metadata, and reindexes Qdrant.

## Cloud

Run the local rebuild first, then the existing Qdrant Cloud migration/sync path. V1.5.1 migration scripts use `search_text` instead of raw transcript text when creating Cloud vectors, while preserving raw `text` as the evidence field.

## Important boundary

Generated corpus metadata is never quoted as Premanand Ji's teaching. It only helps locate evidence. The raw transcript and exact source timestamp remain the final authority.
