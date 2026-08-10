import json
import os
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


OWNED_BY = "chat.arcee.ai"
BASE_URL = (os.environ.get("ARCEE_BASE_URL", "").strip() or "https://api.arcee.ai").rstrip("/")
ORIGIN_URL = (os.environ.get("ARCEE_ORIGIN_URL", "").strip() or "https://chat.arcee.ai").rstrip("/")
CREATE_CHAT_ENDPOINT = f"{BASE_URL}/app/v1/completions/create-chat"
REFRESH_ENDPOINT = f"{BASE_URL}/app/v1/refresh"

DEFAULT_MODEL = "trinity-large-thinking"
SUPPORTED_MODELS = [
    "trinity-nano-6b",
    "trinity-mini",
    "trinity-large-preview",
    "trinity-large-thinking",
]
MODEL_ALIASES = {
    "arcee": "trinity-nano-6b",
    "arcee-nano": "trinity-nano-6b",
    "arcee-mini": "trinity-mini",
    "arcee-preview": "trinity-large-preview",
    "arcee-thinking": "trinity-large-thinking",
}
THINKING_MODELS = {"trinity-large-thinking"}

DEFAULT_TEMPERATURES = {
    "trinity-nano-6b": 0.15,
    "trinity-mini": 0.15,
    "trinity-large-preview": 0.8,
    "trinity-large-thinking": 0.3,
}
DEFAULT_TOOLS = ["web_search", "web_fetch"]

STREAM_INIT_RE = re.compile(r"__STREAM_INIT__(.*?)__STREAM_INIT_END__", re.DOTALL)
METADATA_RE = re.compile(r"__METADATA__(.*?)__METADATA_END__", re.DOTALL)
THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def supports_model(model: str) -> bool:
    lowered = str(model or "").strip().lower()
    if not lowered:
        return False
    if lowered in MODEL_ALIASES:
        return True
    return any(lowered == item.lower() for item in SUPPORTED_MODELS)


def map_model(model: str) -> str:
    lowered = str(model or "").strip().lower()
    if lowered in MODEL_ALIASES:
        return MODEL_ALIASES[lowered]
    for item in SUPPORTED_MODELS:
        if lowered == item.lower():
            return item
    return DEFAULT_MODEL


def _model_fallback_order(requested: str) -> list:
    preferred = [item for item in SUPPORTED_MODELS if item == requested]
    rest = [item for item in SUPPORTED_MODELS if item != requested]
    order = preferred + [requested] if requested not in preferred else preferred + rest
    unique = []
    for item in order:
        if item not in unique:
            unique.append(item)
    return unique


def _headers(token: str, session_id: str, accept: str = "text/plain") -> dict:
    return {
        "Accept": accept,
        "Accept-Language": "ru,en;q=0.9",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Origin": ORIGIN_URL,
        "Referer": f"{ORIGIN_URL}/",
        "Sec-Ch-Ua": '"Not(A:Brand";v="8", "Chromium";v="144", "YaBrowser";v="26.3", "Yowser";v="2.5"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/144.0.0.0 YaBrowser/26.3.0.0 Safari/537.36"
        ),
        "X-Request-Id": str(uuid.uuid4()),
        "X-Session-Id": session_id,
    }


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _prompt_from_messages(messages) -> str:
    system_parts = []
    dialogue = []
    for message in messages or []:
        role = str(message.get("role") or "").strip().lower()
        text = _content_text(message.get("content")).strip()
        if not role or not text:
            continue
        if role == "system":
            system_parts.append(text)
            continue
        dialogue.append((role, text))

    parts = []
    if system_parts:
        parts.append("System:\n" + "\n\n".join(system_parts))

    for index, (role, text) in enumerate(dialogue):
        if index == len(dialogue) - 1 and role == "user":
            parts.append(text)
            continue
        parts.append(f"{role}: {text}")

    return "\n\n".join(parts).strip()


def _title_from_messages(messages, prompt: str) -> str:
    for message in reversed(messages or []):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        text = _content_text(message.get("content")).strip()
        if text:
            return text[:120]
    return (prompt or "New chat")[:120]


def _enabled_tools(payload: dict) -> list[str]:
    provided = payload.get("tools")
    if isinstance(provided, list):
        values = [str(item).strip() for item in provided if str(item or "").strip()]
        if values:
            return values
    return list(DEFAULT_TOOLS)


def _strip_markers(text: str) -> str:
    cleaned = STREAM_INIT_RE.sub("", text or "")
    cleaned = METADATA_RE.sub("", cleaned)
    cleaned = THINK_RE.sub("", cleaned)
    return cleaned.strip()


def _parse_response(raw_text: str) -> dict:
    """Parses the SSE stream returned by create-chat (OpenAI-style chunks)."""
    raw_text = str(raw_text or "")
    reasoning_parts = []
    content_parts = []
    metadata = {}
    init_payload = {}

    for line in raw_text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except Exception:
            continue
        if isinstance(payload, dict):
            choices = payload.get("choices") or []
            for choice in choices:
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning_parts.append(str(delta["reasoning_content"]))
                if delta.get("content"):
                    content_parts.append(str(delta["content"]))
            if payload.get("object") == "chat.completion":
                message = ((payload.get("choices") or [{}])[0]).get("message") or {}
                if message.get("reasoning_content"):
                    reasoning_parts.append(str(message["reasoning_content"]))
                if message.get("content"):
                    content_parts.append(str(message["content"]))
            if payload.get("usage"):
                metadata["usage"] = payload["usage"]
            if payload.get("user_message_id") or payload.get("assistant_message_id"):
                init_payload = payload
            if payload.get("metadata"):
                metadata.update(payload["metadata"])

    content = "".join(content_parts).strip()
    reasoning = "".join(reasoning_parts).strip()
    return {
        "content": content,
        "reasoning": reasoning,
        "metadata": metadata,
        "stream_init": init_payload,
        "raw_text": raw_text,
    }


def _session_id(credentials: dict) -> str:
    value = str((credentials or {}).get("session_id") or "").strip()
    return value or str(uuid.uuid4())


def _request_body(payload: dict, request_model: str, session_id: str) -> dict:
    prompt = _prompt_from_messages(payload.get("messages") or [])
    temperature = payload.get("temperature")
    if temperature is None:
        temperature = DEFAULT_TEMPERATURES.get(request_model, 0.3)
    return {
        "message": prompt,
        "title": _title_from_messages(payload.get("messages") or [], prompt),
        "base_model_name": request_model,
        "chat_id": session_id,
        "enabledTools": _enabled_tools(payload),
        "fileReferences": [],
        "temperature": float(temperature),
        "provider_preference": payload.get("provider_preference"),
    }


_TOKEN_CACHE: dict[str, tuple] = {}


def _jwt_exp(token: str) -> int:
    try:
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        data = json.loads(__import__("base64").urlsafe_b64decode(payload.encode()).decode())
        return int(data.get("exp") or 0)
    except Exception:
        return 0


def _persist_tokens(token: str) -> None:
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["ARCEE_ACCESS_TOKEN"] = token
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _refresh_access_token(token: str) -> str:
    """Calls the /app/v1/refresh endpoint. The refresh endpoint expects the
    current access token as a cookie (not a bearer header)."""
    response = requests.post(
        REFRESH_ENDPOINT,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": ORIGIN_URL,
            "Referer": f"{ORIGIN_URL}/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 YaBrowser/26.3.0.0 Safari/537.36"
            ),
        },
        cookies={"access_token": token},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Arcee token refresh failed: HTTP {response.status_code} {response.text[:200]}")
    data = response.json()
    new_token = str(data.get("access_token") or "").strip()
    if not new_token:
        raise RuntimeError(f"Arcee token refresh returned no access_token: {data}")
    return new_token


def _ensure_fresh_token(token: str) -> str:
    """Returns an access token valid for the next ~50 minutes, refreshing via
    the /app/v1/refresh endpoint when the current one is close to expiry."""
    if not token:
        return ""
    cached = _TOKEN_CACHE.get(token)
    if cached and cached[1] - int(time.time()) > 300:
        return cached[0]
    exp = _jwt_exp(token)
    if exp and exp - int(time.time()) > 300:
        return token
    new_token = _refresh_access_token(token)
    new_exp = _jwt_exp(new_token) or (int(time.time()) + 3600)
    _TOKEN_CACHE[token] = (new_token, new_exp)
    _persist_tokens(new_token)
    debug_log("arcee_token_refreshed", expires_in=new_exp - int(time.time()))
    return new_token


def _run_chat(credentials: dict, payload: dict) -> dict:
    token = _ensure_fresh_token(str((credentials or {}).get("token") or "").strip())
    if not token:
        raise RuntimeError("Arcee access token is required")

    requested_model = map_model(payload.get("model") or "")
    session_id = _session_id(credentials)
    request_body = _request_body(payload, requested_model, session_id)

    model_error = None
    for candidate in _model_fallback_order(requested_model):
        candidate_body = dict(request_body, base_model_name=candidate)
        response = requests.post(
            CREATE_CHAT_ENDPOINT,
            headers=_headers(token, session_id),
            json=candidate_body,
            timeout=120,
        )
        if response.status_code != 200:
            preview = ""
            try:
                preview = response.text[:500]
            except Exception:
                pass
            raise RuntimeError(f"Arcee create-chat failed: HTTP {response.status_code} {preview}".strip())

        parsed = _parse_response(response.text)
        if "not accessible with the current access profile" in parsed.get("raw_text", ""):
            model_error = parsed.get("raw_text", "")[:300]
            continue
        break
    else:
        raise RuntimeError(f"Arcee has no accessible model: {model_error or 'unknown'}")

    metadata = parsed.get("metadata") or {}
    init_payload = parsed.get("stream_init") or {}
    content = str(parsed.get("content") or "").strip()
    if not content:
        raise RuntimeError(f"Arcee returned no content: {parsed.get('raw_text', '')[:500]}")

    debug_log(
        "arcee_chat_done",
        model=candidate,
        chat_id=str(metadata.get("chat_id") or session_id),
        assistant_message_id=str(metadata.get("assistant_message_id") or init_payload.get("assistant_message_id") or ""),
        content_length=len(content),
        reasoning_length=len(parsed.get("reasoning") or ""),
    )

    return {
        "model": candidate,
        "session_id": session_id,
        "content": content,
        "reasoning": str(parsed.get("reasoning") or "").strip(),
        "metadata": metadata,
        "stream_init": init_payload,
    }


def stream_chunks(credentials: dict, payload: dict):
    run = _run_chat(credentials, payload)
    response_id = (
        str((run.get("metadata") or {}).get("assistant_message_id") or "")
        or str((run.get("stream_init") or {}).get("assistant_message_id") or "")
        or str((run.get("metadata") or {}).get("chat_id") or "")
        or str(uuid.uuid4())
    )
    builder = OpenAIStreamBuilder(response_id, run["model"])

    reasoning = run.get("reasoning") or ""
    if reasoning:
        for chunk in builder.reasoning(reasoning):
            yield chunk

    for chunk in builder.content(run["content"]):
        yield chunk

    yield builder.finish("stop")


def complete_non_stream(credentials: dict, payload: dict):
    run = _run_chat(credentials, payload)
    metadata = run.get("metadata") or {}
    response_id = (
        str(metadata.get("assistant_message_id") or "")
        or str((run.get("stream_init") or {}).get("assistant_message_id") or "")
        or str(metadata.get("chat_id") or "")
        or str(uuid.uuid4())
    )
    message = {
        "role": "assistant",
        "content": run["content"],
    }
    if run.get("reasoning"):
        message["reasoning_content"] = run["reasoning"]

    result = {
        "id": response_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": run["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    meta = {
        "provider": "arcee",
        "model": run["model"],
        "chat_id": str(metadata.get("chat_id") or run["session_id"]),
        "assistant_message_id": str(
            metadata.get("assistant_message_id") or (run.get("stream_init") or {}).get("assistant_message_id") or ""
        ),
        "reasoning_length": len(run.get("reasoning") or ""),
    }
    return result, meta
