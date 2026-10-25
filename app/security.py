"""Shared rate-limit configuration for public and authentication endpoints."""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Memory storage is sufficient for a single instance. Configure a shared Redis
# URL before scaling to multiple workers or instances.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,
)
