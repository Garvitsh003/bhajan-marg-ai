import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db
from .config import settings
from .llm import generate_answer, rewrite_query
from .retrieval import retrieve
from .search_backend import ensure_collection

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


app = FastAPI(
    title="Bhajan Marg AI",
    version="1.0.0",
    lifespan=lifespan,
)


raw_origins = os.getenv(
    "CORS_ORIGINS",
    getattr(settings, "cors_origins", "http://localhost:8000"),
)
allow_origins = [x.strip() for x in raw_origins.split(",") if x.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = None


class UpdateRequest(BaseModel):
    latest: int = Field(default=40, ge=1, le=500)
    force: bool = False


@app.get("/")
def ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
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


@app.get("/api/stats")
def corpus_stats():
    return db.stats()


@app.post("/api/chat")
def chat(req: ChatRequest):
    conversation_id = req.conversation_id or str(uuid.uuid4())
    question = req.question.strip()

    history = db.get_messages(conversation_id, limit=8)
    standalone_query = rewrite_query(question, history)

    # Fresh corpus search on EVERY user turn, including follow-ups.
    evidence = retrieve(standalone_query)

    selected_sources = evidence["sources"]
    answer = generate_answer(
        question=question,
        history=history,
        evidence_level=evidence["level"],
        selected_sources=selected_sources,
    )

    db.add_message(conversation_id, "user", question)
    db.add_message(
        conversation_id,
        "assistant",
        answer,
        metadata={
            "standalone_query": standalone_query,
            "evidence_level": evidence["level"],
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
        {k: v for k, v in s.items() if k != "context_text"}
        for s in selected_sources
    ]

    return {
        "conversation_id": conversation_id,
        "standalone_query": standalone_query,
        "evidence_level": evidence["level"],
        "evidence_reason": evidence.get("reason"),
        "answer": answer,
        "sources": public_sources,
    }


def _check_admin(token: str | None):
    if not token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@app.post("/api/admin/update")
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
