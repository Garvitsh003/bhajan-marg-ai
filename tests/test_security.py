import pytest
from fastapi import HTTPException

from app.config import settings
from app.v1_api import _require_admin


def test_admin_auth_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    with pytest.raises(HTTPException) as exc:
        _require_admin("anything")
    assert exc.value.status_code == 503


def test_admin_auth_accepts_only_exact_configured_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "a-long-random-admin-token")
    assert _require_admin("a-long-random-admin-token") is None
    with pytest.raises(HTTPException) as exc:
        _require_admin("a-long-random-admin-tokeN")
    assert exc.value.status_code == 401
