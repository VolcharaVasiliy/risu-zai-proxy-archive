import json
import os
import re
import time
from typing import Iterable

import requests

try:
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


OWNED_BY = "console.mistral.ai"
BASE_URL = (os.environ.get("MISTRAL_BASE_URL", "").strip() or "https://console.mistral.ai").rstrip("/")
CONVERSATION_URL = f"{BASE_URL}/api-ui/bora/v1/conversations"
DEFAULT_MODEL = "mistral-medium-2508"
DEFAULT_SUPPORTED_MODELS = [
    "mistral-small-2603",
    "mistral-large-2512",
    "mistral-medium-2508",
    "mistral-small-2506",
    "ministral-14b-2512",
    "ministral-8b-2512",
    "ministral-3b-2512",
    "magistral-medium-2509",
    "magistral-small-2509",
    "devstral-2512",
    "codestral-2508",
    "labs-devstral-small-2512",
    "labs-leanstral-2603",
    "voxtral-mini-2507",
    "voxtral-small-2507",
]
SUPPORTED_MODELS = [
    item.strip()
    for item in (os.environ.get("MISTRAL_MODELS", "").split(",") if os.environ.get("MISTRAL_MODELS") else DEFAULT_SUPPORTED_MODELS)
    if item.strip()
]
MODEL_ALIASES = {
    "mistral": "mistral-medium-2508",
    "mistral-chat": "mistral-medium-2508",
    "mistral-latest": "mistral-medium-2508",
    "mistral-small": "mistral-small-2603",
    "mistral-small-latest": "mistral-small-2603",
    "mistral-medium": "mistral-medium-2508",
    "mistral-medium-latest": "mistral-medium-2508",
    "mistral-large": "mistral-large-2512",
    "mistral-large-latest": "mistral-large-2512",
    "ministral": "ministral-8b-2512",
    "ministral-latest": "ministral-8b-2512",
    "ministral-3b": "ministral-3b-2512",
    "ministral-3b-latest": "ministral-3b-2512",
    "ministral-8b": "ministral-8b-2512",
    "ministral-8b-latest": "ministral-8b-2512",
    "ministral-14b": "ministral-14b-2512",
    "ministral-14b-latest": "ministral-14b-2512",
    "magistral": "magistral-medium-2509",
    "magistral-latest": "magistral-medium-2509",
    "magistral-medium": "magistral-medium-2509",
    "magistral-medium-latest": "magistral-medium-2509",
    "magistral-small": "magistral-small-2509",
    "magistral-small-latest": "magistral-small-2509",
    "devstral": "devstral-2512",
    "devstral-latest": "devstral-2512",
    "devstral-small": "labs-devstral-small-2512",
    "devstral-small-latest": "labs-devstral-small-2512",
    "codestral": "codestral-2508",
    "codestral-latest": "codestral-2508",
    "leanstral": "labs-leanstral-2603",
    "leanstral-latest": "labs-leanstral-2603",
    "voxtral-mini": "voxtral-mini-2507",
    "voxtral-mini-latest": "voxtral-mini-2507",
    "voxtral-small": "voxtral-small-2507",
    "voxtral-small-latest": "voxtral-small-2507",
}


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


def _get_cookie_value(cookie_header: str, cookie_name: str) -> str:
    pattern = rf"(?:^|;\s*){re.escape(cookie_name)}=([^;]*)"
    match = re.search(pattern, str(cookie_header or ""))
    return (match.group(1) if match else "").strip()


def _csrf_from_cookie(cookie_header: str) -> str:
    for part in str(cookie_header or "").split(";"):
        key, sep, value = part.partition("=")
        if sep and key.strip().startswith("csrf_token_"):
            return value.strip()
    return ""


def _headers(cookie: str, csrf_token: str = "") -> dict:
    headers = {
        "Accept": "text/event-stream, application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/build/playground",
        "User-Agent": os.environ.get(
            "MISTRAL_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        ).strip(),
        "internal-source": "playground",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    if cookie:
        headers["Cookie"] = cookie
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
        headers["x-csrf-token"] = csrf_token
        headers["X-XSRF-Token"] = csrf_token
    return headers


def _message_entries(payload: dict) -> tuple[str, list]:
    system_parts = []
    inputs = []
    for message in payload.get("messages") or []:
        role = str(message.get("role") or "").strip().lower()
        content = message.get("content")
        if role == "system":
            if isinstance(content, list):
                system_parts.extend(str(item.get("text") or item.get("content") or "") for item in content if isinstance(item, dict))
            else:
                text = str(content or "").strip()
                if text:
                    system_parts.append(text)
            continue
        if role == "user":
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            inputs.append({"object": "entry", "type": "message.input", "role": "user", "content": text, "prefix": False})
            continue
        if role == "assistant":
            if isinstance(content, list):
                assistant_text = "".join(str(item.get("text") or item.get("content") or "") for item in content if isinstance(item, dict))
            else:
                assistant_text = str(content or "")
            inputs.append(
                {
                    "object": "entry",
                    "type": "message.output",
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_text}],
                }
            )
    return "\n\n".join(system_parts).strip(), inputs


def _completion_args(payload: dict) -> dict:
    return {
        "temperature": float(payload.get("temperature") or 0.7),
        "max_tokens": int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 2048),
        "top_p": float(payload.get("top_p") or 1),
    }


def _extract_text(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        parts = [_extract_text(item) for item in node]
        return "".join(part for part in parts if part)
    if isinstance(node, dict):
        for key in ("text", "content", "delta", "message", "output"):
            if key in node:
                text = _extract_text(node.get(key))
                if text:
                    return text
        if "choices" in node and isinstance(node["choices"], list):
            return _extract_text(node["choices"])
    return ""


def _iter_sse_events(response: requests.Response) -> Iterable[tuple[str, str]]:
    event_name = ""
    data_lines = []
    for raw_line in response.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = str(raw_line).rstrip("\r\n")
        if not line:
            if event_name or data_lines:
                yield event_name, "\n".join(data_lines).strip()
                event_name = ""
                data_lines = []
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        data_lines.append(line)
    if event_name or data_lines:
        yield event_name, "\n".join(data_lines).strip()


def stream_chunks(credentials: dict, payload: dict):
    cookie = str((credentials or {}).get("cookie") or "").strip()
    csrf_token = str((credentials or {}).get("csrf_token") or "").strip() or _csrf_from_cookie(cookie)
    if not cookie:
        raise RuntimeError("Mistral cookie header is required")

    model = map_model(payload.get("model") or "")
    instructions, inputs = _message_entries(payload)
    if not inputs:
        raise RuntimeError("Mistral request requires at least one message")

    body = {
        "model": model,
        "instructions": instructions,
        "completion_args": _completion_args(payload),
        "stream": True,
        "inputs": inputs,
    }

    debug_log("mistral_chat_started", model=model, stream=True)

    response = requests.post(
        CONVERSATION_URL,
        headers=_headers(cookie, csrf_token),
        json=body,
        timeout=120,
        stream=True,
        allow_redirects=False,
    )

    if response.status_code in {401, 403}:
        preview = response.text[:300] if hasattr(response, "text") else ""
        response.close()
        raise RuntimeError(f"Mistral authentication failed: HTTP {response.status_code} {preview}".strip())

    if response.status_code in {301, 302, 303, 307, 308}:
        location = response.headers.get("Location") or response.headers.get("location") or ""
        response.close()
        raise RuntimeError(f"Mistral request redirected: HTTP {response.status_code} {location}".strip())

    if response.status_code != 200:
        preview = response.text[:500] if hasattr(response, "text") else ""
        response.close()
        raise RuntimeError(f"Mistral completion failed: HTTP {response.status_code} {preview}".strip())

    builder = OpenAIStreamBuilder(f"mistral-{int(time.time())}", model)
    seen_text = False

    try:
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            for event_name, data in _iter_sse_events(response):
                if not data or data in {"[DONE]", "done"}:
                    continue
                try:
                    parsed = json.loads(data)
                except Exception:
                    text = data if event_name == "message.output.delta" else ""
                else:
                    text = _extract_text(parsed)
                    if not text and isinstance(parsed, dict):
                        text = _extract_text(parsed.get("delta") or parsed.get("message") or parsed.get("content"))
                    if not text and event_name == "message.output.delta":
                        text = str(parsed.get("content") or "").strip()
                if text and event_name != "conversation.response.started":
                    seen_text = True
                    for chunk in builder.content(text):
                        yield chunk
        else:
            raw = response.text or ""
            try:
                parsed = response.json()
            except Exception:
                parsed = None
            text = _extract_text(parsed) if parsed is not None else raw
            if text:
                seen_text = True
                for chunk in builder.content(text):
                    yield chunk
        if not seen_text:
            debug_log("mistral_empty_response", model=model, content_type=content_type if 'content_type' in locals() else "")
        yield builder.finish()
    finally:
        response.close()


def complete_non_stream(credentials: dict, payload: dict):
    content_parts = []
    for chunk in stream_chunks(credentials, payload):
        if chunk.get("choices"):
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta:
                content_parts.append(delta["content"])
    full_content = "".join(content_parts)
    result = {
        "id": f"mistral-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": map_model(payload.get("model") or ""),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": full_content},
                "finish_reason": "stop",
            }
        ],
    }
    return result, {"provider": "mistral"}
