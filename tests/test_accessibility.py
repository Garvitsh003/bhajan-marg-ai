from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_language_selector_has_accessible_name():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="languageSelect" aria-label="Answer language"' in html


def test_chat_status_is_a_polite_live_region():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="status" class="status" role="status" aria-live="polite"' in html


def test_frontend_tags_message_language_and_source_links():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert 'row.lang = message.response_language === "hi" ? "hi"' in js
    assert 'card.setAttribute?.(' in js
    assert "Open original source video." in js
