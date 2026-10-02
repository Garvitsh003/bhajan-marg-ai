"""A shared deadline for synchronous provider calls in one chat request."""
import time
from contextvars import ContextVar

deadline = ContextVar("chat_deadline", default=None)
request_id = ContextVar("chat_request_id", default="offline")


def remaining_timeout(requested: float) -> float:
    limit = deadline.get()
    remaining = float(requested) if limit is None else min(float(requested), limit - time.monotonic())
    if remaining <= 0:
        raise TimeoutError("Chat request deadline exceeded")
    return remaining
