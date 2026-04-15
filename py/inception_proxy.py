import json
import os
import time
import uuid
from typing import Iterable

sys_path_added = False
try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

import requests

try:
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


OWNED_BY = "chat.inceptionlabs.ai"
BASE_URL = (os.environ.get("INCEPTION_BASE_URL", "").strip() or "https://chat.inceptionlabs.ai").rstrip("/")
CHAT_ENDPOINT = f"{BASE_URL}/api/chat"
SESSION_ENDPOINT = f"{BASE_URL}/api/session"
DEFAULT_MODEL = "mercury-2"
SUPPORTED_MODELS = ["mercury-2", "mercury-coder"]
MODEL_ALIASES = {
    "mercury": "mercury-2",
    "mercury-2": "mercury-2",
    "mercury-coder": "mercury-coder",
    "inception": "mercury-2",
    "inception-chat": "mercury-2",
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


def _session(use_curl: bool = True):
    if use_curl and curl_requests is not None:
        return curl_requests.Session(impersonate=os.environ.get("INCEPTION_IMPERSONATE", "chrome136"), timeout=120)
    return requests.Session()


def _edge_base_url() -> str:
    return (os.environ.get("INCEPTION_EDGE_URL", "").strip() or "").rstrip("/")


def _edge_chat_endpoint() -> str:
    edge_base_url = _edge_base_url()
    return f"{edge_base_url}/v1/chat/completions" if edge_base_url else ""


def _prefer_edge_transport() -> bool:
    if not _edge_chat_endpoint():
        return False

    if os.environ.get("VERCEL", "").strip().lower() in {"1", "true"}:
        return True

    force_edge = os.environ.get("INCEPTION_FORCE_EDGE", "").strip().lower()
    if force_edge in {"1", "true", "yes", "on"}:
        return True

    return curl_requests is None


def _header_value(value: str) -> str:
    return str(value or "").strip()


def _headers(cookie: str, session_token: str) -> dict:
    user_agent = os.environ.get(
        "INCEPTION_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    ).strip()
    headers = {
        "Accept": "*/*",
        "Accept-Language": os.environ.get("INCEPTION_ACCEPT_LANGUAGE", "ru,en;q=0.9").strip() or "ru,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "Priority": os.environ.get("INCEPTION_PRIORITY", "u=1, i").strip() or "u=1, i",
        "sec-ch-ua": os.environ.get(
            "INCEPTION_SEC_CH_UA",
            '"Not(A:Brand";v="8", "Chromium";v="144", "YaBrowser";v="26.3", "Yowser";v="2.5"',
        ).strip(),
        "sec-ch-ua-mobile": os.environ.get("INCEPTION_SEC_CH_UA_MOBILE", "?0").strip() or "?0",
        "sec-ch-ua-platform": os.environ.get("INCEPTION_SEC_CH_UA_PLATFORM", '"Windows"').strip() or '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": user_agent,
    }
    if session_token:
        headers["x-session-token"] = session_token
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _refresh_session_token(session, cookie: str, session_token: str) -> str:
    headers = _headers(cookie, "")
    response = session.get(
        SESSION_ENDPOINT,
        headers=headers,
        timeout=120,
        stream=False,
        allow_redirects=False,
    )

    if response.status_code != 200:
        body_text = ""
        try:
            body_text = response.text[:300]
        except Exception:
            pass
        response.close()
        raise RuntimeError(f"Inception session refresh failed: HTTP {response.status_code} {body_text}".strip())

    refreshed_token = ""
    try:
        payload = response.json()
        refreshed_token = str(payload.get("token") or "").strip()
    except Exception:
        refreshed_token = ""
    finally:
        response.close()

    if not refreshed_token:
        raise RuntimeError("Inception session refresh failed: token missing in response")

    return refreshed_token


def _edge_headers(cookie: str, session_token: str) -> dict:
    headers = {
        "Accept": "*/*",
        "Content-Type": "application/json",
    }
    if cookie:
        headers["x-inception-cookie"] = cookie
    if session_token:
        headers["x-inception-session-token"] = session_token
    return headers


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("content"):
                    parts.append(str(item["content"]))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def _message_entries(payload: dict) -> list:
    entries = []
    for message in payload.get("messages") or []:
        role = str(message.get("role") or "").strip().lower()
        if not role:
            continue
        text = _content_text(message.get("content")).strip()
        if not text:
            continue
        entries.append(
            {
                "id": str(message.get("id") or uuid.uuid4().hex[:16]),
                "role": role,
                "parts": [{"type": "text", "text": text}],
            }
        )
    return entries


def _request_body(payload: dict) -> tuple[dict, str]:
    model = map_model(payload.get("model") or "")
    messages = _message_entries(payload)
    if not messages:
        raise RuntimeError("Inception request requires at least one message")

    request_id = f"inc-{uuid.uuid4().hex[:16]}"
    reasoning_effort = (
        str(
            payload.get("reasoning_effort")
            or payload.get("reasoningEffort")
            or os.environ.get("INCEPTION_REASONING_EFFORT", "medium")
        )
        .strip()
        .lower()
    )
    web_search_enabled = payload.get("web_search")
    if web_search_enabled is None:
        web_search_enabled = payload.get("webSearchEnabled")
    if web_search_enabled is None:
        web_search_enabled = os.environ.get("INCEPTION_WEB_SEARCH", "").strip().lower() in {"1", "true", "yes", "on"}

    body = {
        "reasoningEffort": reasoning_effort if reasoning_effort in {"low", "medium", "high"} else "medium",
        "webSearchEnabled": bool(web_search_enabled),
        "voiceMode": bool(payload.get("voiceMode") or False),
        "id": request_id,
        "messages": messages,
        "trigger": "submit-message",
    }
    return body, model


def _iter_sse(text: str) -> Iterable[tuple[str, dict | str]]:
    for raw_block in str(text or "").split("\n\n"):
        block = raw_block.strip()
        if not block:
            continue
        data_lines = []
        event_name = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
                continue
            data_lines.append(line)
        data = "\n".join(data_lines).strip()
        if not data:
            continue
        if data == "[DONE]":
            yield event_name, "[DONE]"
            continue
        try:
            yield event_name, json.loads(data)
        except Exception:
            yield event_name, data


def chat_completion(credentials: dict, payload: dict):
    if _prefer_edge_transport():
        edge_chat_endpoint = _edge_chat_endpoint()
        cookie = _header_value((credentials or {}).get("cookie") or "")
        session_token = _header_value((credentials or {}).get("session_token") or "")
        if not session_token and cookie:
            for part in cookie.split(";"):
                key, sep, value = part.partition("=")
                if sep and key.strip() == "session":
                    session_token = value.strip()
                    break
        if not session_token:
            raise RuntimeError("Inception session token is required")

        body = dict(payload or {})
        body["stream"] = False
        response = requests.post(
            edge_chat_endpoint,
            headers=_edge_headers(cookie, session_token),
            json=body,
            timeout=120,
            stream=False,
            allow_redirects=False,
        )

        if response.status_code != 200:
            body_text = ""
            try:
                body_text = response.text[:300]
            except Exception:
                pass
            response.close()
            raise RuntimeError(f"Inception edge proxy failed: HTTP {response.status_code} {body_text}".strip())

        debug_log("inception_chat_started", model=map_model(payload.get("model") or ""), transport="cloudflare-edge")
        return response

    cookie = _header_value((credentials or {}).get("cookie") or "")
    session_token = _header_value((credentials or {}).get("session_token") or "")
    if not session_token and cookie:
        for part in cookie.split(";"):
            key, sep, value = part.partition("=")
            if sep and key.strip() == "session":
                session_token = value.strip()
                break
    if not session_token:
        raise RuntimeError("Inception session token is required")

    if not cookie:
        cookie = f"session={session_token}"

    body, request_model = _request_body(payload)
    used_transport = "curl_cffi" if curl_requests is not None else "requests"

    session = _session(use_curl=True)
    refreshed_session_token = session_token
    if curl_requests is not None:
        refreshed_session_token = _refresh_session_token(session, cookie, session_token)

    response = session.post(
        CHAT_ENDPOINT,
        headers=_headers(cookie, refreshed_session_token),
        json=body,
        timeout=120,
        stream=False,
        allow_redirects=False,
    )

    if response.status_code == 401 and curl_requests is not None:
        response.close()
        refreshed_session_token = _refresh_session_token(session, cookie, refreshed_session_token)
        response = session.post(
            CHAT_ENDPOINT,
            headers=_headers(cookie, refreshed_session_token),
            json=body,
            timeout=120,
            stream=False,
            allow_redirects=False,
        )

    if response.status_code in {401, 403, 429} and curl_requests is None:
        body_text = ""
        try:
            body_text = response.text[:300]
        except Exception:
            pass
        response.close()
        session.close()
        raise RuntimeError(f"Inception authentication failed: HTTP {response.status_code} {body_text}".strip())

    if response.status_code != 200:
        body_text = ""
        try:
            body_text = response.text[:300]
        except Exception:
            pass
        response.close()
        session.close()
        raise RuntimeError(f"Inception completion failed: HTTP {response.status_code} {body_text}".strip())

    debug_log("inception_chat_started", model=request_model, transport=used_transport)
    return session, response, request_model, body["id"]


def stream_chunks(credentials: dict, payload: dict):
    if _prefer_edge_transport():
        response = chat_completion(credentials, payload)
        try:
            content_type = str(response.headers.get("content-type", "")).lower()
            raw_text = response.text or ""
            if "text/event-stream" in content_type:
                for _event_name, item in _iter_sse(raw_text):
                    if item == "[DONE]":
                        continue
                    if isinstance(item, dict):
                        yield item
            else:
                try:
                    parsed = response.json()
                except Exception:
                    parsed = None
                if isinstance(parsed, dict) and parsed.get("choices"):
                    yield parsed
        finally:
            response.close()
        return

    session, response, request_model, request_id = chat_completion(credentials, payload)
    builder = OpenAIStreamBuilder(request_id, request_model)
    content_parts = []
    reasoning_parts = []

    try:
        content_type = str(response.headers.get("content-type", "")).lower()
        raw_text = response.text or ""
        if "text/event-stream" in content_type:
            for event_name, item in _iter_sse(raw_text):
                if item == "[DONE]":
                    continue
                if not isinstance(item, dict):
                    continue
                event_type = str(item.get("type") or event_name or "").strip().lower()
                if event_type == "reasoning-start" or event_type == "reasoning-end" or event_type == "text-start" or event_type == "text-end":
                    continue
                if event_type == "text-delta":
                    delta = str(item.get("delta") or "")
                    if delta:
                        content_parts.append(delta)
                        for chunk in builder.content(delta):
                            yield chunk
                    continue
                if event_type == "reasoning-delta":
                    delta = str(item.get("delta") or "")
                    if delta:
                        reasoning_parts.append(delta)
                        for chunk in builder.reasoning(delta):
                            yield chunk
                    continue
        else:
            try:
                parsed = response.json()
            except Exception:
                parsed = None
            text = ""
            if isinstance(parsed, dict):
                text = str(parsed.get("text") or parsed.get("content") or "")
            else:
                text = str(raw_text or "")
            if text:
                content_parts.append(text)
                for chunk in builder.content(text):
                    yield chunk
        yield builder.finish()
        debug_log(
            "inception_stream_done",
            model=request_model,
            chat_id=request_id,
            content_length=sum(len(part) for part in content_parts),
            reasoning_length=sum(len(part) for part in reasoning_parts),
        )
    finally:
        response.close()
        session.close()


def complete_non_stream(credentials: dict, payload: dict):
    if _prefer_edge_transport():
        response = chat_completion(credentials, payload)
        try:
            result = response.json()
        finally:
            response.close()
        return result, {"provider": "inception", "transport": "cloudflare-edge"}

    content_parts = []
    reasoning_parts = []
    for chunk in stream_chunks(credentials, payload):
        if chunk.get("choices"):
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta:
                content_parts.append(delta["content"])
            if "reasoning_content" in delta:
                reasoning_parts.append(delta["reasoning_content"])
    full_content = "".join(content_parts)
    full_reasoning = "".join(reasoning_parts)
    result = {
        "id": f"inc-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": map_model(payload.get("model") or ""),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_content,
                    **({"reasoning_content": full_reasoning} if full_reasoning else {}),
                },
                "finish_reason": "stop",
            }
        ],
    }
    return result, {"provider": "inception"}
