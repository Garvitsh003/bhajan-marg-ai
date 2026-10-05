from __future__ import annotations

import hashlib
import html
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from psycopg.types.json import Jsonb

from .config import settings
from .product_db import configured as database_configured
from .product_db import connection
from .quality import attach_feedback, attach_message, version_snapshot
from .source_localization import localize_source
from .cloud_llm import gemini_transcribe_audio

log = logging.getLogger(__name__)
router = APIRouter()
_passwords = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_COOKIE = "bm_session"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _secret() -> str:
    value = os.getenv("AUTH_SECRET", "").strip()
    if len(value) < 32:
        raise HTTPException(
            status_code=503,
            detail="AUTH_SECRET is not configured with at least 32 characters.",
        )
    return value


def _frontend_url() -> str:
    return os.getenv("V1_FRONTEND_URL", "https://bhajan-marg-ai-web.vercel.app").rstrip("/")


def _public_base_url() -> str:
    return os.getenv("V1_PUBLIC_BASE_URL", _frontend_url()).rstrip("/")


def _session_days() -> int:
    try:
        return max(1, min(int(os.getenv("V1_SESSION_DAYS", "14")), 90))
    except ValueError:
        return 14


def _cookie_secure() -> bool:
    return _env_bool("V1_COOKIE_SECURE", True)


def _safe_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row.get("name") or "User",
        "email": row.get("email") or "",
        "avatar_url": row.get("avatar_url"),
        "preferred_language": row.get("preferred_language") or "auto",
        "theme": row.get("theme") or "system",
        "email_verified": bool(row.get("email_verified")),
        "created_at": row.get("created_at"),
        "last_active": row.get("last_active"),
    }


def _set_session_cookie(response: Response, user_id: uuid.UUID, request: Request) -> None:
    sid = uuid.uuid4()
    now = _now()
    expires = now + timedelta(days=_session_days())
    ip = request.client.host if request.client else ""
    ip_hash = hashlib.sha256((_secret() + "|" + ip).encode()).hexdigest() if ip else None

    with connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions(id,user_id,expires_at,user_agent,ip_hash)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (sid, user_id, expires, request.headers.get("user-agent"), ip_hash),
        )

    token = jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(sid),
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "type": "session",
        },
        _secret(),
        algorithm="HS256",
    )
    response.set_cookie(
        _COOKIE,
        token,
        max_age=_session_days() * 86400,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def _decode_session(request: Request, required: bool = True) -> dict[str, Any] | None:
    token = request.cookies.get(_COOKIE)
    if not token:
        if required:
            raise HTTPException(status_code=401, detail="Sign in required")
        return None
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
        if payload.get("type") != "session":
            raise ValueError("wrong token type")
        uid = uuid.UUID(payload["sub"])
        sid = uuid.UUID(payload["sid"])
    except Exception:
        if required:
            raise HTTPException(status_code=401, detail="Session expired")
        return None

    with connection() as conn:
        row = conn.execute(
            """
            SELECT u.*, s.id AS session_id
            FROM auth_sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.id=%s AND s.user_id=%s
              AND s.revoked_at IS NULL AND s.expires_at > NOW()
            """,
            (sid, uid),
        ).fetchone()
        if not row:
            if required:
                raise HTTPException(status_code=401, detail="Session expired")
            return None
        conn.execute("UPDATE users SET last_active=NOW() WHERE id=%s", (uid,))
        return row


def _password_hash(password: str) -> str:
    return _passwords.hash(password)


def _verify_password(stored: str | None, password: str) -> bool:
    if not stored:
        return False
    try:
        ok = _passwords.verify(stored, password)
        return bool(ok)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _clean_title(value: str | None, fallback: str = "New chat") -> str:
    title = " ".join((value or "").split()).strip()
    return (title or fallback)[:160]


def _check_conversation(conn, conversation_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=%s AND user_id=%s",
        (conversation_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


class RegisterRequest(BaseModel):
    name: str = Field(default="", max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ForgotRequest(BaseModel):
    email: EmailStr


class ResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    password: str = Field(min_length=8, max_length=200)


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    preferred_language: Literal["auto", "hi", "hinglish", "en"] | None = None
    theme: Literal["system", "light", "dark"] | None = None


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", max_length=160)
    preferred_language: Literal["auto", "hi", "hinglish", "en"] = "auto"


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    preferred_language: Literal["auto", "hi", "hinglish", "en"] | None = None


class SourceInput(BaseModel):
    source_index: int | None = None
    video_id: str | None = None
    video_title: str | None = None
    title: str | None = None
    url: str | None = None
    answer_url: str | None = None
    timestamp_start_ms: int | None = None
    timestamp_end_ms: int | None = None
    answer_start_ms: int | None = None
    answer_end_ms: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    answer_start: str | None = None
    answer_end: str | None = None
    start: str | None = None
    end: str | None = None
    transcript_chunk_id: str | None = None
    chunk_id: str | None = None
    point_id: str | None = None
    transcript_excerpt: str | None = None
    text: str | None = None
    relevance: float | None = None

    model_config = {"extra": "allow"}


class MessageCreate(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100000)
    standalone_query: str | None = None
    evidence_level: str | None = None
    evidence_reason: str | None = None
    answer_status: str | None = None
    extraction_status: str | None = None
    interpretation_status: str | None = None
    response_language: str | None = None
    request_id: str | None = None
    elapsed_ms: int | None = None
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    question_snapshot: str | None = None
    sources: list[SourceInput] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    guest_id: str | None = Field(default=None, max_length=128)
    client_feedback_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    request_id: str | None = Field(default=None, max_length=128)
    question: str = Field(default="", max_length=20000)
    answer: str = Field(default="", max_length=100000)
    retrieved_sources: list[dict[str, Any]] = Field(default_factory=list)
    rating: Literal[-1, 1]
    reason: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=5000)
    voice_transcript: str | None = Field(default=None, max_length=10000)
    client_metadata: dict[str, Any] = Field(default_factory=dict)


class SourceLocalizeRequest(BaseModel):
    target_language: Literal["hi", "hinglish", "en"]
    source: SourceInput


class QualityCasePatch(BaseModel):
    review_status: Literal["unreviewed", "needs_review", "reviewed", "resolved"] | None = None
    failure_category: Literal[
        "corpus", "transcript", "chunking", "query_understanding",
        "retrieval", "reranking", "generation", "citation",
        "conversation_context", "language", "other"
    ] | None = None
    review_notes: str | None = Field(default=None, max_length=20000)
    expected_sources: list[dict[str, Any]] | None = None


class GoldenCaseCreate(BaseModel):
    expected_topic: str | None = Field(default=None, max_length=500)
    expected_sources: list[dict[str, Any]] = Field(default_factory=list)
    acceptable_answer: list[str] = Field(default_factory=list)
    unacceptable_behavior: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=20000)


class AnalyticsRequest(BaseModel):
    guest_id: str | None = Field(default=None, max_length=128)
    conversation_id: uuid.UUID | None = None
    event_name: str = Field(min_length=1, max_length=100)
    properties: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/v1/status")
def v1_status():
    return {
        "ok": True,
        "database_configured": database_configured(),
        "google_enabled": bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET")),
        "password_reset_email_enabled": bool(os.getenv("RESEND_API_KEY")),
    }


@router.post("/api/auth/register")
def register(body: RegisterRequest, request: Request, response: Response):
    email = _normalize_email(body.email)
    name = _clean_title(body.name, email.split("@")[0])
    uid = uuid.uuid4()
    with connection() as conn:
        exists = conn.execute("SELECT id FROM users WHERE email=%s", (email,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        conn.execute(
            """
            INSERT INTO users(id,name,email,password_hash,email_verified)
            VALUES (%s,%s,%s,%s,FALSE)
            """,
            (uid, name, email, _password_hash(body.password)),
        )
        user = conn.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    _set_session_cookie(response, uid, request)
    return {"ok": True, "user": _safe_user(user)}


@router.post("/api/auth/login")
def login(body: LoginRequest, request: Request, response: Response):
    email = _normalize_email(body.email)
    with connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    if not user or not _verify_password(user.get("password_hash"), body.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    _set_session_cookie(response, user["id"], request)
    return {"ok": True, "user": _safe_user(user)}


@router.get("/api/auth/me")
def me(request: Request):
    user = _decode_session(request, required=False)
    return {"authenticated": bool(user), "user": _safe_user(user) if user else None}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    user = _decode_session(request, required=False)
    if user:
        with connection() as conn:
            conn.execute("UPDATE auth_sessions SET revoked_at=NOW() WHERE id=%s", (user["session_id"],))
    response.delete_cookie(_COOKIE, path="/", secure=_cookie_secure(), httponly=True, samesite="lax")
    return {"ok": True}


@router.get("/api/auth/google/start")
def google_start():
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id or not os.getenv("GOOGLE_CLIENT_SECRET", "").strip():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")

    redirect_uri = _public_base_url() + "/api/auth/google/callback"
    now = _now()
    state = jwt.encode(
        {
            "type": "google_state",
            "nonce": secrets.token_urlsafe(16),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        },
        _secret(),
        algorithm="HS256",
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), status_code=302)


@router.get("/api/auth/google/callback")
def google_callback(code: str, state: str, request: Request):
    try:
        state_payload = jwt.decode(state, _secret(), algorithms=["HS256"])
        if state_payload.get("type") != "google_state":
            raise ValueError("invalid state")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Google sign-in state") from exc

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = _public_base_url() + "/api/auth/google/callback"

    try:
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        info_response = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        info_response.raise_for_status()
        info = info_response.json()
    except Exception as exc:
        log.exception("Google OAuth exchange failed")
        return RedirectResponse(_frontend_url() + "/?auth_error=google", status_code=302)

    email = _normalize_email(info.get("email", ""))
    sub = str(info.get("sub", "")).strip()
    if not email or not sub:
        return RedirectResponse(_frontend_url() + "/?auth_error=google_profile", status_code=302)

    with connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE google_sub=%s", (sub,)).fetchone()
        if not user:
            user = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
        if user:
            conn.execute(
                """
                UPDATE users
                SET google_sub=COALESCE(google_sub,%s),
                    avatar_url=COALESCE(%s,avatar_url),
                    email_verified=TRUE,
                    last_active=NOW(), updated_at=NOW()
                WHERE id=%s
                """,
                (sub, info.get("picture"), user["id"]),
            )
            uid = user["id"]
        else:
            uid = uuid.uuid4()
            name = _clean_title(info.get("name"), email.split("@")[0])
            conn.execute(
                """
                INSERT INTO users(id,name,email,google_sub,avatar_url,email_verified)
                VALUES (%s,%s,%s,%s,%s,TRUE)
                """,
                (uid, name, email, sub, info.get("picture")),
            )

    redirect = RedirectResponse(_frontend_url() + "/?auth=google", status_code=302)
    _set_session_cookie(redirect, uid, request)
    return redirect


def _send_reset_email(email: str, name: str, reset_url: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not api_key or not sender:
        return False
    safe_name = html.escape(name or "there")
    safe_url = html.escape(reset_url, quote=True)
    payload = {
        "from": sender,
        "to": [email],
        "subject": "Reset your Bhajan Marg AI password",
        "text": f"Reset your Bhajan Marg AI password: {reset_url}\n\nThis link expires in 30 minutes.",
        "html": (
            f"<p>Namaste {safe_name},</p>"
            f"<p><a href=\"{safe_url}\">Reset your Bhajan Marg AI password</a>.</p>"
            "<p>This link expires in 30 minutes. If you did not request it, ignore this email.</p>"
        ),
    }
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception:
        log.exception("Password reset email failed")
        return False


@router.post("/api/auth/forgot-password")
def forgot_password(body: ForgotRequest):
    email = _normalize_email(body.email)
    debug_url = None
    with connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
        if user:
            raw = secrets.token_urlsafe(40)
            token_hash = hashlib.sha256(raw.encode()).hexdigest()
            conn.execute(
                """
                INSERT INTO password_reset_tokens(id,user_id,token_hash,expires_at)
                VALUES (%s,%s,%s,%s)
                """,
                (uuid.uuid4(), user["id"], token_hash, _now() + timedelta(minutes=30)),
            )
            reset_url = _frontend_url() + "/?reset_token=" + raw
            sent = _send_reset_email(email, user.get("name") or "", reset_url)
            if _env_bool("V1_DEV_MODE") and not sent:
                debug_url = reset_url

    result = {"ok": True, "message": "If that account exists, a reset link has been sent."}
    if debug_url:
        result["debug_reset_url"] = debug_url
    return result


@router.post("/api/auth/reset-password")
def reset_password(body: ResetRequest):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    with connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM password_reset_tokens
            WHERE token_hash=%s AND used_at IS NULL AND expires_at > NOW()
            FOR UPDATE
            """,
            (token_hash,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="This reset link is invalid or expired")
        conn.execute("UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s", (_password_hash(body.password), row["user_id"]))
        conn.execute("UPDATE password_reset_tokens SET used_at=NOW() WHERE id=%s", (row["id"],))
        conn.execute("UPDATE auth_sessions SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL", (row["user_id"],))
    return {"ok": True}


@router.patch("/api/profile")
def update_profile(body: ProfilePatch, request: Request):
    user = _decode_session(request)
    fields = body.model_dump(exclude_none=True)
    if "name" in fields:
        fields["name"] = _clean_title(fields["name"], user["name"])
    if fields:
        columns = [f"{key}=%s" for key in fields]
        values = list(fields.values())
        values.append(user["id"])
        with connection() as conn:
            conn.execute(
                f"UPDATE users SET {', '.join(columns)}, updated_at=NOW(), last_active=NOW() WHERE id=%s",
                values,
            )
            updated = conn.execute("SELECT * FROM users WHERE id=%s", (user["id"],)).fetchone()
    else:
        updated = user
    return {"ok": True, "user": _safe_user(updated)}


@router.get("/api/conversations")
def list_conversations(request: Request):
    user = _decode_session(request)
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id,title,preferred_language,created_at,updated_at,last_message_at
            FROM conversations WHERE user_id=%s
            ORDER BY last_message_at DESC LIMIT 50
            """,
            (user["id"],),
        ).fetchall()
    return rows


@router.post("/api/conversations")
def create_conversation(body: ConversationCreate, request: Request):
    user = _decode_session(request)
    cid = uuid.uuid4()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO conversations(id,user_id,title,preferred_language)
            VALUES (%s,%s,%s,%s)
            """,
            (cid, user["id"], _clean_title(body.title), body.preferred_language),
        )
        row = conn.execute(
            "SELECT id,title,preferred_language,created_at,updated_at,last_message_at FROM conversations WHERE id=%s",
            (cid,),
        ).fetchone()
    return row


@router.patch("/api/conversations/{conversation_id}")
def patch_conversation(conversation_id: uuid.UUID, body: ConversationPatch, request: Request):
    user = _decode_session(request)
    with connection() as conn:
        _check_conversation(conn, conversation_id, user["id"])
        fields = body.model_dump(exclude_none=True)
        if "title" in fields:
            fields["title"] = _clean_title(fields["title"])
        if fields:
            columns = [f"{key}=%s" for key in fields]
            values = list(fields.values()) + [conversation_id, user["id"]]
            conn.execute(
                f"UPDATE conversations SET {', '.join(columns)}, updated_at=NOW() WHERE id=%s AND user_id=%s",
                values,
            )
        row = conn.execute(
            "SELECT id,title,preferred_language,created_at,updated_at,last_message_at FROM conversations WHERE id=%s",
            (conversation_id,),
        ).fetchone()
    return row


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: uuid.UUID, request: Request):
    user = _decode_session(request)
    with connection() as conn:
        _check_conversation(conn, conversation_id, user["id"])
        conn.execute("DELETE FROM conversations WHERE id=%s AND user_id=%s", (conversation_id, user["id"]))
    return {"ok": True}


def _source_public(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row.get("source_payload") or {})
    payload.update({
        "source_index": row.get("source_index"),
        "video_id": row.get("video_id"),
        "video_title": row.get("video_title"),
        "title": row.get("video_title"),
        "url": row.get("url"),
        "answer_url": row.get("answer_url"),
        "timestamp_start_ms": row.get("timestamp_start_ms"),
        "timestamp_end_ms": row.get("timestamp_end_ms"),
        "timestamp_start": row.get("timestamp_start"),
        "timestamp_end": row.get("timestamp_end"),
        "transcript_chunk_id": row.get("transcript_chunk_id"),
        "transcript_excerpt": row.get("transcript_excerpt"),
        "relevance": row.get("relevance"),
    })
    return payload


@router.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: uuid.UUID, request: Request):
    user = _decode_session(request)
    with connection() as conn:
        _check_conversation(conn, conversation_id, user["id"])
        messages = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=%s ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        ids = [row["id"] for row in messages]
        sources_by_message: dict[uuid.UUID, list[dict[str, Any]]] = {mid: [] for mid in ids}
        if ids:
            source_rows = conn.execute(
                "SELECT * FROM message_sources WHERE message_id = ANY(%s) ORDER BY message_id, source_index",
                (ids,),
            ).fetchall()
            for source in source_rows:
                sources_by_message.setdefault(source["message_id"], []).append(_source_public(source))
        for message in messages:
            message["message_sources"] = sources_by_message.get(message["id"], [])
    return messages


@router.post("/api/conversations/{conversation_id}/messages")
def create_message(conversation_id: uuid.UUID, body: MessageCreate, request: Request):
    user = _decode_session(request)
    mid = uuid.uuid4()
    with connection() as conn:
        _check_conversation(conn, conversation_id, user["id"])
        conn.execute(
            """
            INSERT INTO messages(
                id,conversation_id,role,content,standalone_query,evidence_level,evidence_reason,
                answer_status,extraction_status,interpretation_status,response_language,request_id,
                elapsed_ms,quotes,claims,question_snapshot
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                mid, conversation_id, body.role, body.content, body.standalone_query,
                body.evidence_level, body.evidence_reason, body.answer_status,
                body.extraction_status, body.interpretation_status, body.response_language,
                body.request_id, body.elapsed_ms, Jsonb(body.quotes), Jsonb(body.claims),
                body.question_snapshot,
            ),
        )
        source_public: list[dict[str, Any]] = []
        if body.role == "assistant":
            for index, source in enumerate(body.sources):
                raw = source.model_dump(exclude_none=True)
                sid = uuid.uuid4()
                video_title = source.video_title or source.title
                start_ms = source.timestamp_start_ms if source.timestamp_start_ms is not None else source.answer_start_ms if source.answer_start_ms is not None else source.start_ms
                end_ms = source.timestamp_end_ms if source.timestamp_end_ms is not None else source.answer_end_ms if source.answer_end_ms is not None else source.end_ms
                start_text = source.timestamp_start or source.answer_start or source.start
                end_text = source.timestamp_end or source.answer_end or source.end
                chunk_id = source.transcript_chunk_id or source.chunk_id or source.point_id
                excerpt = source.transcript_excerpt or source.text
                conn.execute(
                    """
                    INSERT INTO message_sources(
                        id,message_id,source_index,video_id,video_title,url,answer_url,
                        timestamp_start_ms,timestamp_end_ms,timestamp_start,timestamp_end,
                        transcript_chunk_id,transcript_excerpt,relevance,source_payload
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        sid, mid, source.source_index if source.source_index is not None else index,
                        source.video_id, video_title, source.url, source.answer_url,
                        start_ms, end_ms, start_text, end_text, chunk_id, excerpt,
                        source.relevance, Jsonb(raw),
                    ),
                )
                source_public.append(raw)

        conn.execute(
            "UPDATE conversations SET updated_at=NOW(), last_message_at=NOW() WHERE id=%s",
            (conversation_id,),
        )
        row = conn.execute("SELECT * FROM messages WHERE id=%s", (mid,)).fetchone()
        row["message_sources"] = source_public

    if body.role == "assistant" and body.request_id:
        try:
            attach_message(
                request_id=body.request_id,
                message_id=mid,
                conversation_id=conversation_id,
                user_id=user["id"],
            )
        except Exception:
            log.exception("Failed linking assistant message to quality case")

    return row


@router.post("/api/feedback/voice-transcribe")
async def transcribe_feedback_voice(
    audio: UploadFile = File(...),
    language: str = Form(default="auto"),
):
    allowed = {"auto", "hi", "hinglish", "en"}
    lang = language if language in allowed else "auto"

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Voice feedback audio is empty")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Voice feedback audio is too large")

    try:
        transcript = gemini_transcribe_audio(
            raw,
            mime_type=audio.content_type or "audio/webm",
            language=lang,
        )
    except Exception as exc:
        log.exception("Voice feedback transcription failed")
        raise HTTPException(status_code=503, detail="Voice transcription unavailable") from exc

    return {"ok": True, "transcript": transcript, "language": lang}


@router.post("/api/feedback")
def save_feedback(body: FeedbackRequest, request: Request):
    user = _decode_session(request, required=False)
    fid = uuid.uuid4()
    guest_id = body.guest_id if not user else None

    with connection() as conn:
        if body.client_feedback_id:
            existing = conn.execute(
                "SELECT id FROM feedback WHERE client_feedback_id=%s",
                (body.client_feedback_id,),
            ).fetchone()
            if existing:
                return {"ok": True, "id": str(existing["id"]), "persisted": True, "duplicate": True}

        conn.execute(
            """
            INSERT INTO feedback(
                id,user_id,guest_id,client_feedback_id,conversation_id,message_id,request_id,question,answer,
                retrieved_sources,rating,reason,comment,voice_transcript,client_metadata
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                fid, user["id"] if user else None, guest_id, body.client_feedback_id,
                body.conversation_id, body.message_id, body.request_id, body.question, body.answer,
                Jsonb(body.retrieved_sources), body.rating, body.reason, body.comment,
                body.voice_transcript, Jsonb(body.client_metadata),
            ),
        )

    try:
        attach_feedback(
            request_id=body.request_id,
            feedback_id=fid,
            user_id=user["id"] if user else None,
            guest_id=guest_id,
            rating=body.rating,
            reason=body.reason,
            comment=body.comment,
            voice_transcript=body.voice_transcript,
        )
    except Exception:
        log.exception("Failed linking feedback to quality case")

    return {"ok": True, "id": str(fid), "persisted": True}


@router.post("/api/source-localize")
def source_localize(body: SourceLocalizeRequest):
    source = body.source.model_dump(exclude_none=True)
    return localize_source(source, body.target_language)


@router.post("/api/analytics")
def save_analytics(body: AnalyticsRequest, request: Request):
    user = _decode_session(request, required=False)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO analytics_events(user_id,guest_id,conversation_id,event_name,properties)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (
                user["id"] if user else None,
                body.guest_id if not user else None,
                body.conversation_id,
                body.event_name,
                Jsonb(body.properties),
            ),
        )
    return {"ok": True}


def _require_admin(token: str | None) -> None:
    configured = str(settings.admin_token or "").strip()

    # Fail closed if production ADMIN_TOKEN was never configured.
    if not configured or configured == "change-me":
        raise HTTPException(
            status_code=503,
            detail="Admin API is not configured",
        )

    if not token or not secrets.compare_digest(token, configured):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin token",
        )


@router.get("/api/admin/quality-cases")
def list_quality_cases(
    status: str | None = None,
    language: str | None = None,
    rating: int | None = None,
    failure_category: str | None = None,
    limit: int = 100,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin(x_admin_token)
    limit = max(1, min(limit, 500))

    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("review_status=%s")
        params.append(status)
    if language:
        clauses.append("response_language=%s")
        params.append(language)
    if rating in (-1, 1):
        clauses.append("feedback_rating=%s")
        params.append(rating)
    if failure_category:
        clauses.append("failure_category=%s")
        params.append(failure_category)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,request_id,question,standalone_query,response_language,
                evidence_level,evidence_reason,answer_status,feedback_rating,
                feedback_reason,feedback_comment,voice_transcript,
                review_status,failure_category,review_notes,
                created_at,updated_at
            FROM quality_cases
            {where}
            ORDER BY
                CASE WHEN review_status='needs_review' THEN 0 ELSE 1 END,
                created_at DESC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    return rows


@router.get("/api/admin/quality-cases/{case_id}")
def get_quality_case(
    case_id: uuid.UUID,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin(x_admin_token)
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM quality_cases WHERE id=%s",
            (case_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Quality case not found")
    return row


@router.patch("/api/admin/quality-cases/{case_id}")
def review_quality_case(
    case_id: uuid.UUID,
    body: QualityCasePatch,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin(x_admin_token)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=422, detail="No changes supplied")

    allowed = {"review_status", "failure_category", "review_notes", "expected_sources"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    columns = []
    values: list[Any] = []
    for key, value in fields.items():
        columns.append(f"{key}=%s")
        values.append(Jsonb(value) if key == "expected_sources" else value)
    columns.append("updated_at=NOW()")
    values.append(case_id)

    with connection() as conn:
        row = conn.execute(
            f"UPDATE quality_cases SET {', '.join(columns)} WHERE id=%s RETURNING *",
            tuple(values),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Quality case not found")
    return row


@router.post("/api/admin/quality-cases/{case_id}/golden")
def add_quality_case_to_golden(
    case_id: uuid.UUID,
    body: GoldenCaseCreate,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin(x_admin_token)
    gid = uuid.uuid4()

    with connection() as conn:
        case = conn.execute(
            "SELECT * FROM quality_cases WHERE id=%s",
            (case_id,),
        ).fetchone()
        if not case:
            raise HTTPException(status_code=404, detail="Quality case not found")

        conn.execute(
            """
            INSERT INTO golden_cases(
                id,quality_case_id,question,language,expected_topic,
                expected_sources,acceptable_answer,unacceptable_behavior,notes
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                gid, case_id, case["question"], case.get("response_language"),
                body.expected_topic,
                Jsonb(body.expected_sources or case.get("expected_sources") or []),
                Jsonb(body.acceptable_answer),
                Jsonb(body.unacceptable_behavior),
                body.notes,
            ),
        )
        conn.execute(
            """
            UPDATE quality_cases
            SET review_status='reviewed', updated_at=NOW()
            WHERE id=%s
            """,
            (case_id,),
        )

    return {"ok": True, "id": str(gid)}


@router.get("/api/admin/golden-cases")
def list_golden_cases(
    limit: int = 250,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin(x_admin_token)
    limit = max(1, min(limit, 1000))
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM golden_cases
            WHERE active=TRUE
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return rows


@router.get("/api/admin/mastery-dashboard")
def mastery_dashboard(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    with connection() as conn:
        scalar = lambda sql, params=(): conn.execute(sql, params).fetchone()["value"]
        result = {
            "versions": version_snapshot(),
            "quality_cases": scalar("SELECT COUNT(*) AS value FROM quality_cases"),
            "needs_review": scalar(
                "SELECT COUNT(*) AS value FROM quality_cases WHERE review_status='needs_review'"
            ),
            "resolved": scalar(
                "SELECT COUNT(*) AS value FROM quality_cases WHERE review_status='resolved'"
            ),
            "golden_cases": scalar(
                "SELECT COUNT(*) AS value FROM golden_cases WHERE active=TRUE"
            ),
            "helpful": scalar(
                "SELECT COUNT(*) AS value FROM quality_cases WHERE feedback_rating=1"
            ),
            "not_helpful": scalar(
                "SELECT COUNT(*) AS value FROM quality_cases WHERE feedback_rating=-1"
            ),
        }
        result["failure_taxonomy"] = conn.execute(
            """
            SELECT COALESCE(failure_category,'unclassified') AS category, COUNT(*) AS count
            FROM quality_cases
            WHERE feedback_rating=-1 OR review_status IN ('needs_review','reviewed','resolved')
            GROUP BY COALESCE(failure_category,'unclassified')
            ORDER BY count DESC
            """
        ).fetchall()
        result["language_usage"] = conn.execute(
            """
            SELECT COALESCE(response_language,'unknown') AS language, COUNT(*) AS count
            FROM quality_cases
            GROUP BY COALESCE(response_language,'unknown')
            ORDER BY count DESC
            """
        ).fetchall()
    return result


@router.get("/api/admin/v1-analytics")
def analytics_summary(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    with connection() as conn:
        scalar = lambda sql, params=(): conn.execute(sql, params).fetchone()["value"]
        result: dict[str, Any] = {
            "users": scalar("SELECT COUNT(*) AS value FROM users"),
            "dau": scalar("SELECT COUNT(*) AS value FROM users WHERE last_active >= NOW()-INTERVAL '24 hours'"),
            "conversations": scalar("SELECT COUNT(*) AS value FROM conversations"),
            "messages": scalar("SELECT COUNT(*) AS value FROM messages"),
            "questions": scalar("SELECT COUNT(*) AS value FROM messages WHERE role='user'"),
            "returning_users": scalar("SELECT COUNT(*) AS value FROM (SELECT user_id FROM conversations GROUP BY user_id HAVING COUNT(*)>1) x"),
            "helpful": scalar("SELECT COUNT(*) AS value FROM feedback WHERE rating=1"),
            "not_helpful": scalar("SELECT COUNT(*) AS value FROM feedback WHERE rating=-1"),
            "no_source_answers": scalar("SELECT COUNT(*) AS value FROM messages WHERE role='assistant' AND evidence_level='none'"),
            "avg_response_ms": scalar("SELECT COALESCE(ROUND(AVG(elapsed_ms)),0)::bigint AS value FROM messages WHERE role='assistant' AND elapsed_ms IS NOT NULL"),
        }
        result["avg_messages_per_conversation"] = conn.execute(
            "SELECT COALESCE(ROUND(AVG(c),2),0) AS value FROM (SELECT COUNT(*) c FROM messages GROUP BY conversation_id) x"
        ).fetchone()["value"]
        result["language_usage"] = conn.execute(
            "SELECT preferred_language AS language, COUNT(*) AS count FROM conversations GROUP BY preferred_language ORDER BY count DESC"
        ).fetchall()
        result["most_referenced_videos"] = conn.execute(
            """
            SELECT video_id, MAX(video_title) AS video_title, COUNT(*) AS "references"
            FROM message_sources WHERE video_id IS NOT NULL
            GROUP BY video_id ORDER BY "references" DESC LIMIT 15
            """
        ).fetchall()
        result["most_asked_questions"] = conn.execute(
            """
            SELECT content AS question, COUNT(*) AS asks
            FROM messages WHERE role='user'
            GROUP BY content ORDER BY asks DESC, MAX(created_at) DESC LIMIT 15
            """
        ).fetchall()
        result["feedback_reasons"] = conn.execute(
            "SELECT COALESCE(reason,'unspecified') AS reason, COUNT(*) AS count FROM feedback WHERE rating=-1 GROUP BY reason ORDER BY count DESC"
        ).fetchall()
    return result
