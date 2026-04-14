import json
import os
import time
import uuid
from typing import Iterable

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


OWNED_BY = "longcat.chat"
BASE_URL = (os.environ.get("LONGCAT_BASE_URL", "").strip() or "https://longcat.chat").rstrip("/")
SESSION_CREATE_ENDPOINT = f"{BASE_URL}/api/v1/session-create?yodaReady=h5&csecplatform=4&csecversion=4.2.0"
CHAT_ENDPOINT = f"{BASE_URL}/api/v1/chat-completion-V2?yodaReady=h5&csecplatform=4&csecversion=4.2.0"
DEFAULT_MODEL = "LongCat-Flash-Chat"
DEFAULT_THINKING_MODEL = "LongCat-Flash-Thinking-2601"
SUPPORTED_MODELS = [
    "LongCat-Flash-Chat",
    "LongCat-Flash-Thinking",
    "LongCat-Flash-Thinking-2601",
]
MODEL_ALIASES = {
    "longcat": "LongCat-Flash-Chat",
    "longcat-chat": "LongCat-Flash-Chat",
    "longcat-flash-chat": "LongCat-Flash-Chat",
    "longcat-thinking": "LongCat-Flash-Thinking-2601",
    "longcat-flash-thinking": "LongCat-Flash-Thinking-2601",
    "longcat-flash-thinking-2601": "LongCat-Flash-Thinking-2601",
}
THINKING_MODELS = {"LongCat-Flash-Thinking", "LongCat-Flash-Thinking-2601"}


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


def is_thinking_model(model: str) -> bool:
    return map_model(model) in THINKING_MODELS


def _session():
    if curl_requests is not None:
        return curl_requests.Session(impersonate=os.environ.get("LONGCAT_IMPERSONATE", "chrome136"), timeout=120)
    return requests.Session()


def _cookie_header(value: str) -> str:
    return str(value or "").strip()


def _headers(cookie: str, referer: str) -> dict:
    user_agent = os.environ.get(
        "LONGCAT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    ).strip()
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": referer,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": user_agent,
        "X-Requested-With": "XMLHttpRequest",
    }
    if cookie:
        headers["Cookie"] = cookie
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


def _iter_sse(text: str) -> Iterable[dict]:
    for raw_block in str(text or "").split("\n\n"):
        block = raw_block.strip()
        if not block:
            continue
        data_lines = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            else:
                data_lines.append(line)
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except Exception:
            continue


def _extract_event_text(item: dict) -> str:
    event = item.get("event") or {}
    if not isinstance(event, dict):
        return ""
    for key in ("content", "delta", "text", "message", "finalContentX"):
        value = event.get(key)
        if value:
            return str(value)
    return ""


def _delta_from_cumulative(previous: str, current: str) -> str:
    previous = str(previous or "")
    current = str(current or "")
    if not current:
        return ""
    if current.startswith(previous):
        return current[len(previous) :]
    return current


def _event_type(item: dict) -> str:
    event = item.get("event") or {}
    if isinstance(event, dict):
        return str(event.get("type") or "").strip().lower()
    return ""


def _is_reasoning_event(item: dict) -> bool:
    event_type = _event_type(item)
    if event_type in {"reason", "think"}:
        return True
    if event_type == "summary":
        event = item.get("event") or {}
        heavy_stage = str((event or {}).get("heavyStage") or "").strip().lower()
        if heavy_stage.startswith("heavy_"):
            return True
    return False


def _is_content_event(item: dict) -> bool:
    return _event_type(item) == "content"


def _create_conversation(session, cookie: str) -> tuple[str, dict]:
    response = session.post(
        SESSION_CREATE_ENDPOINT,
        headers=_headers(cookie, f"{BASE_URL}/"),
        json={},
        timeout=120,
        allow_redirects=False,
    )
    if response.status_code != 200:
        preview = ""
        try:
            preview = response.text[:300]
        except Exception:
            pass
        response.close()
        raise RuntimeError(f"LongCat session creation failed: HTTP {response.status_code} {preview}".strip())

    try:
        payload = response.json()
    except Exception as exc:
        response.close()
        raise RuntimeError(f"LongCat session creation returned invalid JSON: {exc}") from exc
    finally:
        response.close()

    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise RuntimeError("LongCat session creation returned an invalid payload")

    conversation_id = str(data.get("conversationId") or "").strip()
    if not conversation_id:
        raise RuntimeError("LongCat session creation did not return a conversation id")
    return conversation_id, data


def _request_body(payload: dict, conversation_id: str, request_model: str) -> dict:
    return {
        "conversationId": conversation_id,
        "content": _prompt_from_messages(payload.get("messages") or []),
        "agentId": "1",
        "files": [],
        "creationParam": {},
        "reasonEnabled": 1 if is_thinking_model(request_model) else 0,
        "searchEnabled": 0,
        "parentMessageId": 0,
        "location": [],
    }


def chat_completion(credentials: dict, payload: dict):
    cookie = _cookie_header((credentials or {}).get("cookie") or "")
    if not cookie:
        raise RuntimeError("LongCat cookie header is required")

    request_model = map_model(payload.get("model") or "")
    used_transport = "curl_cffi" if curl_requests is not None else "requests"
    session = _session()
    conversation_id, session_data = _create_conversation(session, cookie)
    response = session.post(
        CHAT_ENDPOINT,
        headers=_headers(cookie, f"{BASE_URL}/c/{conversation_id}"),
        json=_request_body(payload, conversation_id, request_model),
        timeout=120,
        stream=False,
        allow_redirects=False,
    )

    if response.status_code in {401, 403, 429} and curl_requests is None:
        preview = ""
        try:
            preview = response.text[:300]
        except Exception:
            pass
        response.close()
        session.close()
        raise RuntimeError(f"LongCat authentication failed: HTTP {response.status_code} {preview}".strip())

    if response.status_code != 200:
        preview = ""
        try:
            preview = response.text[:500]
        except Exception:
            pass
        response.close()
        session.close()
        raise RuntimeError(f"LongCat completion failed: HTTP {response.status_code} {preview}".strip())

    debug_log("longcat_chat_started", model=request_model, transport=used_transport, conversation_id=conversation_id)
    return session, response, request_model, conversation_id, session_data


def stream_chunks(credentials: dict, payload: dict):
    session, response, request_model, conversation_id, session_data = chat_completion(credentials, payload)
    builder = OpenAIStreamBuilder(conversation_id, request_model)
    builder.created = int(time.time())
    content_parts = []
    reasoning_parts = []
    last_reasoning_text = ""
    fallback_content_parts = []

    try:
        content_type = str(response.headers.get("content-type", "")).lower()
        raw_text = response.text or ""
        if "text/event-stream" in content_type:
            for item in _iter_sse(raw_text):
                if _is_reasoning_event(item):
                    text = _extract_event_text(item)
                    if text:
                        delta = _delta_from_cumulative(last_reasoning_text, text)
                        last_reasoning_text = text
                        if delta:
                            reasoning_parts.append(delta)
                            for chunk in builder.reasoning(delta):
                                yield chunk
                    continue

                event = item.get("event") or {}
                if isinstance(event, dict) and event.get("type") == "finish":
                    final_text = str(event.get("finalContentX") or event.get("content") or "".join(fallback_content_parts) or "").strip()
                    if final_text:
                        content_parts.append(final_text)
                        for chunk in builder.content(final_text):
                            yield chunk
                    continue
                if _is_content_event(item):
                    text = _extract_event_text(item)
                    if text:
                        delta = _delta_from_cumulative("", text)
                        if delta:
                            fallback_content_parts.append(delta)
                    continue
        else:
            try:
                parsed = response.json()
            except Exception:
                parsed = None
            text = ""
            if isinstance(parsed, dict):
                text = str(parsed.get("data", {}).get("finalContentX") or parsed.get("data", {}).get("content") or parsed.get("content") or "")
            else:
                text = str(raw_text or "")
            if text:
                content_parts.append(text)
                for chunk in builder.content(text):
                    yield chunk
        yield builder.finish()
        debug_log(
            "longcat_stream_done",
            model=request_model,
            conversation_id=conversation_id,
            content_length=len("".join(content_parts or fallback_content_parts)),
            reasoning_length=sum(len(part) for part in reasoning_parts),
            capabilities=",".join(session_data.get("capabilities") or []),
        )
    finally:
        response.close()
        session.close()


def complete_non_stream(credentials: dict, payload: dict):
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
        "id": f"longcat-{int(time.time())}",
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
    return result, {"provider": "longcat"}
