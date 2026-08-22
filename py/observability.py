"""Small dependency-free logging and request tracing helpers.

The proxy talks to browser sessions and third-party APIs, so logs must remain
useful without ever copying credentials or full prompts into stdout.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import time
import traceback
import uuid
from contextlib import contextmanager
from typing import Any, Iterator


_REQUEST_ID = contextvars.ContextVar("risu_request_id", default="")
_SECRET_KEY = re.compile(
    r"(?:authorization|cookie|token|secret|password|api[-_]?key|access[-_]?key|"
    r"private[-_]?key|session|csrf|captcha|turnstile|clearance|credential|proof)",
    re.IGNORECASE,
)
_TOKEN_IN_TEXT = re.compile(
    r"(?i)(bearer\s+|(?:api[_-]?key|token|cookie|authorization|secret)\s*[=:]\s*)"
    r"([^\s,;\"']{8,})"
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


def request_id() -> str:
    return _REQUEST_ID.get() or ""


def new_request_id(candidate: str = "") -> str:
    value = str(candidate or "").strip()
    if value and _REQUEST_ID_RE.fullmatch(value):
        return value
    return f"req_{uuid.uuid4().hex}"


@contextmanager
def request_context(candidate: str = "") -> Iterator[str]:
    value = new_request_id(candidate)
    token = _REQUEST_ID.set(value)
    try:
        yield value
    finally:
        _REQUEST_ID.reset(token)


def _enabled(level: str) -> bool:
    configured = os.environ.get("PROXY_LOG_LEVEL", "").strip().lower()
    if not configured:
        debug = os.environ.get("DEBUG_LOGGING", "").strip().lower()
        configured = "debug" if debug in {"1", "true", "yes", "on"} else "off"
    if configured in {"", "off", "none", "0"}:
        return False
    threshold = _LEVELS.get(configured, 10)
    return _LEVELS.get(str(level).lower(), 20) >= threshold


def _fingerprint(value: Any) -> str:
    text = str(value or "")
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return f"<redacted len={len(text)} sha256={digest}>"


def redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(str(key or "")):
        return _fingerprint(value)
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, key) for item in value]
    if isinstance(value, str):
        return _TOKEN_IN_TEXT.sub(lambda match: f"{match.group(1)}{_fingerprint(match.group(2))}", value)
    return value


def header_summary(headers: Any) -> dict[str, Any]:
    """Return safe header diagnostics without copying header values."""
    try:
        items = headers.items()
    except AttributeError:
        return {}
    names = []
    present = {}
    for name, value in items:
        lowered = str(name).lower()
        names.append(lowered)
        if lowered in {"authorization", "cookie", "x-api-key", "x-proxy-api-key"}:
            present[lowered] = bool(str(value or "").strip())
    return {"names": sorted(set(names)), "sensitive_present": present}


def log_event(event: str, level: str = "debug", **fields: Any) -> None:
    if not _enabled(level):
        return
    payload: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "level": str(level).lower(),
        "event": str(event),
    }
    rid = request_id()
    if rid:
        payload["request_id"] = rid
    payload.update(redact(fields))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)


def log_exception(event: str, error: BaseException, level: str = "error", **fields: Any) -> None:
    log_event(
        event,
        level=level,
        error_type=type(error).__name__,
        error=str(error),
        traceback=traceback.format_exc(),
        **fields,
    )


def elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
