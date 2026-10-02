# Bhajan Marg AI — benchmark-driven tuning

This source-only update addresses the prior 20-question benchmark. It has NOT been deployed, and the live 20-question suite has not been rerun against this version. Preserve your original project, environment, database and transcript files.

## Confirmed findings and changes

- Caption deduplication counted Unicode tokens but sliced whitespace words. A hyphenated phrase such as `क्या-क्या` could delete the following `भगवान`. The fix slices by original character offsets instead. Repair uses saved raw captions, never guessed replacement words.
- Standalone questions no longer incur a rewrite call or acquire the previous topic when rewriting fails. Genuine follow-ups still resolve against the preceding user question and trigger fresh retrieval.
- Answer generation uses only the excerpts shown on source cards. It selects exact contiguous sentences with explicit source references; invented, stitched or incomplete selections are rejected. The old hidden secondary search is no longer in the answer path.
- AI explanation/practice claims receive a separate model support check against cited quotations. This is a model check, not a factual guarantee. If checks fail, only the verified transcript text is shown. Auto-caption recognition errors remain possible.
- Extraction failure is explicitly `source_only`, rather than an empty answer under a direct-evidence badge. Future/guarantee and divine-intent questions carry specific limits when applicable.
- Provider timeouts now apply, calls share a request deadline, Qdrant requests have a timeout, and API failures return safe structured errors with a request ID. CORS wraps error responses. These changes address plausible failure paths; production logs are still needed to establish every original “Failed to fetch” cause. The budget bounds outbound calls, not a hard process termination timer.
- Both frontends restore failed questions, prevent duplicate submits, tolerate blocked local storage, and support a fresh conversation. Reindexed source cards can link to the first selected answer cue rather than the chunk introduction.

## Validation completed

- 46 Python regression tests passed, including the 20 standalone benchmark questions, caption repair, quote fidelity, claim filtering, API errors/CORS and follow-up retrieval.
- Node frontend checks cover error recovery, duplicate prevention, unsafe source URLs, blocked storage, new conversation and matching frontend copies.
- Repair dry-run over 100 original saved transcripts: 1,149 changed caption segments and 1,484 rebuilt chunks. This count is not a claim that all changed segments had been semantically wrong.
- Providers were stubbed for regression tests. No live Gemini/Qdrant calls, production database writes, index rebuild or deployment were performed. Strict sentence selection may return more source-only answers for poor captions; measure this during staging.

## Apply and validate

1. Unzip into a separate review directory, then merge these source files into your existing project. This package omits secrets, `.git`, virtual environments, transcripts and SQLite data; do not remove those from the original project. `app/synthesis.py` remains for compatibility but is unused by the answer path.
2. In your existing environment, install and run:

   ```sh
   pip install -r requirements-dev.txt
   python -m pytest -q
   node tests/test_frontend.cjs
   ```

3. Keep existing provider keys, backend URL and hosting configuration. New optional settings default to `LLM_TIMEOUT_SECONDS=35`, `CHAT_TIMEOUT_SECONDS=180`, `QDRANT_TIMEOUT_SECONDS=30`, `VALIDATE_ANSWER_CLAIMS=true`. Disabling claim validation suppresses explanations; it does not allow unchecked prose. The frontend timeout is 240 seconds. Confirm the hosting request timeout accommodates the backend budget.
4. The code fix cannot restore words already missing from Qdrant. On the ingestion machine with your original transcripts and Qdrant environment, first run:

   ```sh
   python scripts/repair_caption_index.py --transcripts data/transcripts
   ```

   Then build a NEW collection (this writes data and uses Qdrant inference):

   ```sh
   python scripts/repair_caption_index.py --transcripts data/transcripts --collection bhajan_marg_chunks_cloud_v2 --apply
   ```

   The script refuses an existing collection, keeps original transcripts, writes corrected copies to `data/repaired_transcripts`, and verifies chunk count. It uses the project's current 384-dimensional dense model configuration; do not change embedding dimensions without updating the collection schema. After a partial failure, inspect the new collection and rerun with another new name. Retain the old collection for rollback.
5. Deploy the backend and `web/` frontend to staging. Set staging `QDRANT_COLLECTION` to the new collection. Both `web/app.js` and `web/index.html` are required; keep `web/config.js` pointed at the intended backend. Backend entry point remains `app.main:app`.
6. Run the benchmark against the backend API URL (not the static Vercel frontend):

   ```sh
   python scripts/run_benchmark.py --base-url https://YOUR-BACKEND --output benchmark-independent.json
   python scripts/run_benchmark.py --base-url https://YOUR-BACKEND --sequential --output benchmark-sequential.json
   ```

   Each run makes 20 chat requests, stores conversation messages and may incur provider costs. Results are saved after every question; there are no automatic retries. Review response delivery, source-only frequency, query contamination, complete/conditional quotations, faithful explanations, answer timestamps and the four adversarial cases. For the faith example, inspect QytmBqULXAs near 8:27 and confirm the recovered `भगवान`.
7. Promote after reviewing staging results. Roll back source deployment and `QDRANT_COLLECTION` together if needed. This package does not change production automatically.
