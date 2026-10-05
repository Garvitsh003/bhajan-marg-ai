from app import source_localization


def sample_source():
    return {
        "video_id": "abc123",
        "title": "मन को शांत कैसे करें?",
        "url": "https://www.youtube.com/watch?v=abc123&t=5s",
        "timestamp_start_ms": 12500,
        "transcript_excerpt": "नाम जप करते रहो।",
    }


def test_hindi_source_keeps_exact_excerpt_and_prefers_hindi_captions():
    result = source_localization.localize_source(sample_source(), "hi")

    assert result["display_excerpt"] == "नाम जप करते रहो।"
    assert result["exact_transcript_excerpt"] == "नाम जप करते रहो।"
    assert result["is_translation"] is False
    assert "cc_lang_pref=hi" in result["display_url"]
    assert "cc_load_policy=1" in result["display_url"]
    assert "t=12s" in result["display_url"]


def test_english_source_keeps_exact_original_separate(monkeypatch):
    monkeypatch.setattr(
        source_localization,
        "_render_text",
        lambda title, excerpt, language: (
            "How can I calm my mind?",
            "Keep doing naam-jap.",
        ),
    )

    result = source_localization.localize_source(sample_source(), "en")

    assert result["display_excerpt"] == "Keep doing naam-jap."
    assert result["exact_transcript_excerpt"] == "नाम जप करते रहो।"
    assert result["is_translation"] is True
    assert "cc_lang_pref=en" in result["display_url"]
