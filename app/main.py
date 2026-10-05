import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db
from .config import settings
from .llm import generate_answer_result, rewrite_query
from .language import render_answer_language
from .budget import deadline, request_id
from .retrieval import retrieve
from .search_backend import ensure_collection
from .quality import record_chat_case
from .v1_api import router as v1_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    ensure_collection()

    scheduler_started = False

    if (
        getattr(settings, "app_mode", "local").lower() != "cloud"
        and settings.daily_update_enabled
    ):
        from .scheduler import start_scheduler
        start_scheduler()
        scheduler_started = True

    yield

    if scheduler_started:
        from .scheduler import stop_scheduler
        stop_scheduler()


api = FastAPI(
    title="Bhajan Marg AI",
    version="1.0.0",
    lifespan=lifespan,
)
api.include_router(v1_router)
api.mount('/assets', StaticFiles(directory=Path(__file__).parent / 'static'), name='assets')


raw_origins = os.getenv(
    "CORS_ORIGINS",
    getattr(settings, "cors_origins", "http://localhost:8000"),
)
allow_origins = [x.strip() for x in raw_origins.split(",") if x.strip()]

class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = None
    history: list[HistoryMessage] | None = Field(default=None, max_length=20)
    preferred_language: Literal["auto", "hi", "hinglish", "en"] = "auto"

    @field_validator('question')
    @classmethod
    def nonblank_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Question must not be blank')
        return value


class UpdateRequest(BaseModel):
    latest: int = Field(default=40, ge=1, le=500)
    force: bool = False


@api.get("/")
def ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@api.get("/api/health")
def health():
    return {
        "ok": True,
        "mode": settings.app_mode,
        "llm_provider": settings.llm_provider,
        "model": (
            settings.gemini_model
            if settings.llm_provider == "gemini"
            else settings.ollama_model
        ),
    }


@api.get("/api/stats")
def corpus_stats():
    return db.stats()


@api.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    trace_id = str(uuid.uuid4())
    trace_token = request_id.set(trace_id)
    deadline_token = deadline.set(time.monotonic() + settings.chat_timeout_seconds)
    started = time.monotonic()
    try:
        return _chat(req, trace_id, started)
    except Exception as exc:
        logging.getLogger(__name__).error(
            'request=%s chat_failed error_type=%s elapsed_ms=%d',
            trace_id, type(exc).__name__, (time.monotonic()-started)*1000)
        timeout = isinstance(exc, TimeoutError) or 'timeout' in type(exc).__name__.lower()
        return JSONResponse(status_code=504 if timeout else 503,
            headers={'X-Request-ID':trace_id}, content={'error':{
                'code':'UPSTREAM_TIMEOUT' if timeout else 'CHAT_UNAVAILABLE',
                'message':'उत्तर तैयार नहीं हो पाया। कुछ देर बाद दोबारा प्रयास करें।',
                'request_id':trace_id}})
    finally:
        deadline.reset(deadline_token)
        request_id.reset(trace_token)


def _chat(req: ChatRequest, trace_id: str, started: float):
    conversation_id = req.conversation_id or str(uuid.uuid4())
    question = req.question.strip()

    if req.history:
        history = [
            {"role": item.role, "content": item.content.strip(), "metadata": {}}
            for item in req.history[-8:]
            if item.content.strip()
        ]
    else:
        history = db.get_messages(conversation_id, limit=8)

    log = logging.getLogger(__name__)
    log.info('request=%s phase=rewrite', trace_id)
    standalone_query = rewrite_query(question, history)

    # Fresh corpus search on EVERY user turn, including follow-ups.
    log.info('request=%s phase=retrieval', trace_id)
    evidence = retrieve(standalone_query)

    selected_sources = evidence["sources"]
    log.info('request=%s phase=answer', trace_id)
    generated = generate_answer_result(
        question=question,
        history=history,
        evidence_level=evidence["level"],
        selected_sources=selected_sources,
    )
    answer, response_language = render_answer_language(
        answer=generated["answer"],
        question=question,
        preference=req.preferred_language,
        quotes=generated.get("quotes", []),
    )

    db.add_message(conversation_id, "user", question)
    db.add_message(
        conversation_id,
        "assistant",
        answer,
        metadata={
            "standalone_query": standalone_query,
            "evidence_level": evidence["level"],
            "response_language": response_language,
            "sources": [
                {
                    "video_id": s["video_id"],
                    "start_ms": s["start_ms"],
                    "url": s["url"],
                }
                for s in selected_sources
            ],
        },
    )

    # Do not expose expanded context twice.
    public_sources = [
        {k: v for k, v in s.items() if k not in ("context_text", 'caption_segments')}
        for s in selected_sources
    ]
    for quote in generated['quotes']:
        if quote.get('url'):
            card = public_sources[quote['source_index']]
            card.setdefault('answer_start', quote['start'])
            card.setdefault('answer_url', quote['url'])

    result = {
        "conversation_id": conversation_id,
        "standalone_query": standalone_query,
        "evidence_level": evidence["level"],
        "evidence_reason": evidence.get("reason"),
        "answer": answer,
        "response_language": response_language,
        "sources": public_sources,
        'request_id':trace_id,
        'elapsed_ms':round((time.monotonic()-started)*1000),
        **{key:generated[key] for key in (
            'answer_status','extraction_status','interpretation_status','quotes','claims')},
    }

    # V1.5 quality observability is intentionally non-blocking. A database
    # outage must never turn a grounded answer into a failed chat response.
    try:
        case_id = record_chat_case(
            request_id=trace_id,
            question=question,
            standalone_query=standalone_query,
            response_language=response_language,
            answer=answer,
            evidence=evidence,
            generated=generated,
            sources_shown=public_sources,
            elapsed_ms=result["elapsed_ms"],
        )
        if case_id:
            result["quality_case_id"] = case_id
    except Exception:
        log.exception("request=%s quality_case_write_failed", trace_id)

    log.info('request=%s completed status=%s elapsed_ms=%d',
             trace_id, generated['answer_status'], result['elapsed_ms'])
    return JSONResponse(result, headers={'X-Request-ID':trace_id})


def _check_admin(token: str | None):
    if not token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@api.post("/api/admin/update")
def update(
    req: UpdateRequest,
    background_tasks: BackgroundTasks,
    x_admin_token: str | None = Header(default=None),
):
    _check_admin(x_admin_token)

    if getattr(settings, "app_mode", "local").lower() == "cloud":
        raise HTTPException(
            status_code=503,
            detail="Cloud web service is read-only. Run ingestion locally and sync Qdrant Cloud.",
        )

    from .ingest import run_ingestion

    background_tasks.add_task(
        run_ingestion,
        limit=req.latest,
        force=req.force,
        mode="manual-update",
    )
    return {"accepted": True, "latest": req.latest, "force": req.force}


# CORS must also cover unhandled 500 responses, not just successful routes.
app = CORSMiddleware(api, allow_origins=allow_origins or ['*'],
    allow_credentials=False, allow_methods=['*'], allow_headers=['*'],
    expose_headers=['X-Request-ID'])
