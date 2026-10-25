# Golden retrieval evaluation

Use the existing quality dashboard to review cases and add representative
questions to the Golden Set, including bad-answer feedback, wrong-source cases,
language variants, and questions where the correct behavior is to abstain.

Run against a deployed API:

```bash
BH_ADMIN_TOKEN=... BH_API_BASE_URL=https://bhajan-marg-ai.onrender.com \
  python scripts/run_golden_eval.py --limit 20 --output golden-eval-results.json
```

The runner fetches active golden cases and the current version snapshot, then
calls `/api/chat` sequentially. It enforces at least six seconds between chat
calls to stay under the current 10/minute per-IP limit. Do not run several copies
in parallel against the same deployment.

Current automatic checks are intentionally narrow:
- HTTP response succeeds.
- Answer is non-empty.
- If expected video IDs are configured, at least one expected source is returned.

The pass rate is a **retrieval/answer-presence regression metric**, not proof that
the answer is true, spiritually appropriate, or fully grounded. Expected-source
coverage is not checked for cases with no expected source IDs. Review failures
and inspect excerpts/timestamps manually before changing retrieval settings.
Record results with corpus/retrieval/prompt versions so regressions can be
compared after a tuning change.
