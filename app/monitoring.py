"""Optional error monitoring with conservative PII scrubbing."""
import logging
import os
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)


def _without_query(value):
    if not isinstance(value, str):
        return value
    parts = urlsplit(value)
    if not parts.scheme and not parts.netloc:
        return value.split("?", 1)[0]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def scrub_sentry_event(event, hint=None):
    """Remove request bodies, cookies, headers, query strings and user identity."""
    event.pop("user", None)
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        contexts.pop("user", None)

    request = event.get("request")
    if isinstance(request, dict):
        for key in ("data", "cookies", "query_string", "env"):
            request.pop(key, None)
        request["headers"] = {}
        if "url" in request:
            request["url"] = _without_query(request["url"])

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        for crumb in breadcrumbs.get("values", []):
            data = crumb.get("data") if isinstance(crumb, dict) else None
            if not isinstance(data, dict):
                continue
            for key in list(data):
                lowered = key.lower()
                if any(token in lowered for token in ("authorization", "cookie", "password", "token", "email", "body")):
                    data.pop(key, None)
                elif key.lower() in {"url", "from", "to"}:
                    data[key] = _without_query(data[key])
    return event


def init_monitoring():
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        log.info("Error monitoring disabled; set SENTRY_DSN to enable it.")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("APP_MODE", "production")),
            release=os.getenv("SENTRY_RELEASE") or None,
            send_default_pii=False,
            traces_sample_rate=0.0,
            before_send=scrub_sentry_event,
        )
        log.info("Sentry error monitoring enabled with request-data scrubbing.")
        return True
    except Exception:
        log.exception("Sentry initialization failed; application will continue without monitoring.")
        return False
