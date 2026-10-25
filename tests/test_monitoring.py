from app.monitoring import scrub_sentry_event


def test_sentry_scrubber_removes_sensitive_request_data():
    event = {
        "user": {"email": "private@example.com", "id": "123"},
        "contexts": {"user": {"email": "private@example.com"}},
        "request": {
            "url": "https://example.test/reset?reset_token=secret",
            "query_string": "reset_token=secret",
            "data": {"question": "private reflection"},
            "cookies": {"bm_session": "secret"},
            "headers": {"Authorization": "Bearer secret", "Cookie": "secret"},
            "method": "POST",
        },
    }
    scrubbed = scrub_sentry_event(event)
    assert "user" not in scrubbed
    assert "user" not in scrubbed["contexts"]
    assert scrubbed["request"]["url"] == "https://example.test/reset"
    assert "query_string" not in scrubbed["request"]
    assert "data" not in scrubbed["request"]
    assert "cookies" not in scrubbed["request"]
    assert scrubbed["request"]["headers"] == {}
    assert scrubbed["request"]["method"] == "POST"


def test_sentry_scrubber_removes_sensitive_breadcrumb_fields():
    event = {"breadcrumbs": {"values": [{"data": {
        "url": "https://example.test/path?token=secret",
        "password": "secret",
        "status_code": 503,
    }}]}}
    scrubbed = scrub_sentry_event(event)
    data = scrubbed["breadcrumbs"]["values"][0]["data"]
    assert data == {"url": "https://example.test/path", "status_code": 503}
