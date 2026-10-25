from scripts.run_golden_eval import evaluate_case, expected_video_ids


def test_expected_source_match_passes_when_expected_video_is_returned():
    case = {"id": "g1", "question": "question", "expected_sources": [{"video_id": "abc"}]}
    result = evaluate_case(case, {"answer": "answer", "sources": [{"video_id": "abc"}]}, 200)
    assert result["pass"] is True
    assert result["checks"]["expected_source_match"] is True


def test_expected_source_mismatch_fails():
    case = {"id": "g1", "question": "question", "expected_sources": [{"video_id": "abc"}]}
    result = evaluate_case(case, {"answer": "answer", "sources": [{"video_id": "xyz"}]}, 200)
    assert result["pass"] is False


def test_missing_expected_sources_does_not_claim_source_validation():
    case = {"id": "g1", "question": "question", "expected_sources": []}
    result = evaluate_case(case, {"answer": "answer", "sources": []}, 200)
    assert result["pass"] is True
    assert result["checks"]["expected_source_match"] is None
    assert "answer presence only" in result["note"]


def test_expected_video_ids_ignores_malformed_entries():
    assert expected_video_ids([{"video_id": "abc"}, {}, "bad"]) == {"abc"}
