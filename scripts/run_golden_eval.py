"""Run a bounded, source-grounded regression check against saved golden cases.

This measures retrieval/source match and answer presence, not full semantic
correctness. Human review remains necessary for spiritual/contextual accuracy.
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


def expected_video_ids(expected_sources):
    return {
        str(item.get("video_id")).strip()
        for item in (expected_sources or [])
        if isinstance(item, dict) and item.get("video_id")
    }


def evaluate_case(case, response_json, http_status):
    answer = str(response_json.get("answer") or "").strip()
    sources = response_json.get("sources") or []
    found_video_ids = {
        str(item.get("video_id")).strip()
        for item in sources
        if isinstance(item, dict) and item.get("video_id")
    }
    expected = expected_video_ids(case.get("expected_sources"))
    source_match = bool(expected.intersection(found_video_ids)) if expected else None
    checks = {
        "http_ok": http_status == 200,
        "answer_present": bool(answer),
        "expected_source_match": source_match,
    }
    required = [checks["http_ok"], checks["answer_present"]]
    if expected:
        required.append(source_match)
    return {
        "id": str(case.get("id", "")),
        "question": case.get("question", ""),
        "pass": all(required),
        "checks": checks,
        "expected_video_ids": sorted(expected),
        "returned_video_ids": sorted(found_video_ids),
        "evidence_level": response_json.get("evidence_level"),
        "answer_status": response_json.get("answer_status"),
        "elapsed_ms": response_json.get("elapsed_ms"),
        "request_id": response_json.get("request_id"),
        "note": None if expected else "No expected source IDs configured; answer presence only was checked.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BH_API_BASE_URL") or "https://bhajan-marg-ai.onrender.com")
    parser.add_argument("--admin-token", default=os.getenv("BH_ADMIN_TOKEN", ""))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--delay-seconds", type=float, default=6.2)
    parser.add_argument("--output", type=Path, default=Path("golden-eval-results.json"))
    args = parser.parse_args()

    if not args.admin_token:
        parser.error("Provide --admin-token or set BH_ADMIN_TOKEN.")
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100.")
    if args.delay_seconds < 6:
        parser.error("--delay-seconds must be at least 6 to respect the current chat rate limit.")

    base_url = args.base_url.rstrip("/")
    headers = {"X-Admin-Token": args.admin_token}
    cases_response = requests.get(
        f"{base_url}/api/admin/golden-cases",
        params={"limit": min(args.limit, 1000)},
        headers=headers,
        timeout=30,
    )
    cases_response.raise_for_status()
    cases = cases_response.json()[:args.limit]
    if not cases:
        raise SystemExit("No active golden cases found. Add reviewed cases in the quality dashboard first.")

    try:
        version_response = requests.get(
            f"{base_url}/api/admin/mastery-dashboard",
            headers=headers,
            timeout=30,
        )
        version_response.raise_for_status()
        versions = version_response.json().get("versions", {})
    except requests.RequestException:
        versions = {}

    results = []
    for index, case in enumerate(cases):
        language = case.get("language")
        if language not in {"auto", "hi", "hinglish", "en"}:
            language = "auto"
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json={"question": case.get("question", ""), "preferred_language": language},
                timeout=240,
            )
            try:
                body = response.json()
            except ValueError:
                body = {}
            row = evaluate_case(case, body, response.status_code)
            row["http_status"] = response.status_code
        except requests.RequestException as exc:
            row = {
                "id": str(case.get("id", "")),
                "question": case.get("question", ""),
                "pass": False,
                "checks": {"http_ok": False, "answer_present": False, "expected_source_match": None},
                "error": type(exc).__name__,
            }
        results.append(row)
        print(f"{index + 1}/{len(cases)} {row['id']} {'PASS' if row['pass'] else 'FAIL'}", flush=True)
        if index + 1 < len(cases):
            time.sleep(args.delay_seconds)

    passed = sum(1 for item in results if item["pass"])
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "scope": "Answer presence and expected-source retrieval checks; not a semantic truthfulness or devotional correctness score.",
        "versions": versions,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": round(passed / len(results), 4),
        },
        "results": results,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {args.output}")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
