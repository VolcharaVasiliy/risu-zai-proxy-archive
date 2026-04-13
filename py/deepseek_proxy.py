import json
import os
import random
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.deepseek_hash import build_pow_response
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from deepseek_hash import build_pow_response
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


DEEPSEEK_API_BASE = "https://chat.deepseek.com/api"
OWNED_BY = "chat.deepseek.com"

SUPPORTED_MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-search",
]

MODEL_OPTIONS = {
    "deepseek": {"model": "deepseek-chat", "thinking": False, "search": False},
    "deepseek-chat": {"model": "deepseek-chat", "thinking": False, "search": False},
    "deepseek-reasoner": {"model": "deepseek-reasoner", "thinking": True, "search": False},
    "deepseek-search": {"model": "deepseek-search", "thinking": False, "search": True},
}

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://chat.deepseek.com",
    "Referer": "https://chat.deepseek.com/",
    "Sec-Ch-Ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "X-App-Version": "20241129.1",
    "X-Client-Locale": "zh-CN",
    "X-Client-Platform": "web",
    "X-Client-Version": "1.6.1",
}

_ACCESS_CACHE = {}
_SESSION_CACHE = {}


def supports_model(model: str) -> bool:
    return str(model or "").lower() in MODEL_OPTIONS


def _cache_get(cache: dict, key: str):
    item = cache.get(key)
    if not item:
        return None
    if item["expires_at"] <= time.time():
        cache.pop(key, None)
        return None
    return item["value"]


def _cache_set(cache: dict, key: str, value, ttl_seconds: int):
    cache[key] = {"value": value, "expires_at": time.time() + ttl_seconds}


def _random_string(length: int, alphabet: str = "0123456789abcdefghijklmnopqrstuvwxyz") -> str:
    return "".join(random.choice(alphabet) for _ in range(length))


def _cookie() -> str:
    timestamp_ms = int(time.time() * 1000)
    timestamp_s = int(time.time())
    return "; ".join(
        [
            f"intercom-HWWAFSESTIME={timestamp_ms}",
            f"HWWAFSESID={_random_string(18, '0123456789abcdef')}",
            f"_frid={uuid.uuid4().hex}",
            f"_fr_ssid={uuid.uuid4().hex}",
            f"_fr_pvid={uuid.uuid4().hex}",
            f"Hm_lvt_{uuid.uuid4().hex[:16]}={timestamp_s},{timestamp_s},{timestamp_s}",
            f"Hm_lpvt_{uuid.uuid4().hex[:16]}={timestamp_s}",
        ]
    )


def _check_response(response, label: str):
    if response.status_code == 401:
        raise RuntimeError("DeepSeek token invalid or expired")
    if response.status_code != 200:
        raise RuntimeError(f"DeepSeek {label} failed: HTTP {response.status_code}")
    return response.json()


def acquire_access_token(token: str) -> str:
    cached = _cache_get(_ACCESS_CACHE, token)
    if cached:
        return cached

    response = requests.get(
        f"{DEEPSEEK_API_BASE}/v0/users/current",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {token}"},
        timeout=30,
    )
    data = _check_response(response, "token exchange")
    biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data") or {}
    access_token = str(biz_data.get("token") or "").strip()
    if not access_token:
        raise RuntimeError(f"DeepSeek token exchange returned no access token: {data}")
    _cache_set(_ACCESS_CACHE, token, access_token, 3000)
    return access_token


def create_session(access_token: str) -> str:
    cached = _cache_get(_SESSION_CACHE, access_token)
    if cached:
        return cached

    response = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/chat_session/create",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {access_token}", "Cookie": _cookie()},
        json={"character_id": None},
        timeout=30,
    )
    data = _check_response(response, "create session")
    biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data") or {}
    session_id = str(biz_data.get("id") or "").strip()
    if not session_id:
        raise RuntimeError(f"DeepSeek create session returned no session id: {data}")
    _cache_set(_SESSION_CACHE, access_token, session_id, 300)
    return session_id


def get_challenge(access_token: str) -> dict:
    response = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/chat/create_pow_challenge",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {access_token}"},
        json={"target_path": "/api/v0/chat/completion"},
        timeout=30,
    )
    data = _check_response(response, "get challenge")
    biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data") or {}
    challenge = biz_data.get("challenge") or {}
    if not challenge:
        raise RuntimeError(f"DeepSeek challenge response is empty: {data}")
    return challenge


def _text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def _prompt_from_messages(messages) -> str:
    parts = []
    for message in messages or []:
        role = str(message.get("role") or "user").capitalize()
        text = _text_from_content(message.get("content"))
        if not text.strip():
            continue
        parts.append(f"{role}: {text}")
    return "\n\n".join(parts).replace("![](", "! [").strip()


def _flags_for(request_model: str, payload: dict):
    model_key = str(request_model or "").lower()
    defaults = MODEL_OPTIONS.get(model_key) or MODEL_OPTIONS["deepseek-chat"]
    search_enabled = defaults["search"] or bool(payload.get("web_search"))
    thinking_enabled = defaults["thinking"] or bool(payload.get("reasoning_effort"))
    return defaults["model"], search_enabled, thinking_enabled


def chat_completion(token: str, payload: dict):
    access_token = acquire_access_token(token)
    session_id = create_session(access_token)
    challenge = get_challenge(access_token)
    pow_response = build_pow_response(challenge)
    request_model = str(payload.get("model") or "deepseek-chat")
    _, search_enabled, thinking_enabled = _flags_for(request_model, payload)
    prompt = _prompt_from_messages(payload.get("messages") or [])

    response = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/chat/completion",
        headers={
            **FAKE_HEADERS,
            "Authorization": f"Bearer {access_token}",
            "Cookie": _cookie(),
            "X-Ds-Pow-Response": pow_response,
        },
        json={
            "chat_session_id": session_id,
            "parent_message_id": None,
            "prompt": prompt,
            "ref_file_ids": [],
            "search_enabled": search_enabled,
            "thinking_enabled": thinking_enabled,
        },
        timeout=120,
        stream=True,
    )
    if response.status_code != 200:
        try:
            body = response.text
        except Exception:
            body = ""
        raise RuntimeError(f"DeepSeek completion failed: HTTP {response.status_code} {body[:300]}")

    debug_log(
        "deepseek_chat_started",
        model=request_model,
        session_id=session_id,
        prompt_length=len(prompt),
        search=search_enabled,
        thinking=thinking_enabled,
    )
    return response, session_id, request_model


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data:
            yield data


def _append_fragments(fragments, answer_parts: list, reasoning_parts: list):
    last_path = ""
    for fragment in fragments or []:
        fragment_type = str(fragment.get("type") or "").upper()
        content = str(fragment.get("content") or "")
        if not content:
            continue
        if fragment_type == "THINK":
            reasoning_parts.append(content)
            last_path = "thinking"
        elif fragment_type in {"ANSWER", "RESPONSE"}:
            answer_parts.append(content)
            last_path = "content"
    return last_path


def _append_delta(path: str, value, answer_parts: list, reasoning_parts: list):
    text = str(value or "")
    if not text:
        return path
    if text == "FINISHED":
        return path
    if path == "thinking":
        reasoning_parts.append(text)
        return "thinking"
    answer_parts.append(text)
    return "content"


def _iter_event_deltas(event: dict, current_path: str):
    value = event.get("v")
    deltas = []

    if isinstance(value, dict) and isinstance((value.get("response") or {}).get("fragments"), list):
        for fragment in (value.get("response") or {}).get("fragments") or []:
            fragment_type = str(fragment.get("type") or "").upper()
            content = str(fragment.get("content") or "")
            if not content:
                continue
            if fragment_type == "THINK":
                deltas.append(("reasoning", content))
                current_path = "thinking"
            elif fragment_type in {"ANSWER", "RESPONSE"}:
                deltas.append(("content", content))
                current_path = "content"
        return current_path, deltas

    if event.get("p") == "response/fragments" and isinstance(value, list):
        for fragment in value:
            fragment_type = str(fragment.get("type") or "").upper()
            content = str(fragment.get("content") or "")
            if not content:
                continue
            if fragment_type == "THINK":
                deltas.append(("reasoning", content))
                current_path = "thinking"
            elif fragment_type in {"ANSWER", "RESPONSE"}:
                deltas.append(("content", content))
                current_path = "content"
        return current_path, deltas

    path = str(event.get("p") or "")
    if "THINK" in path.upper() or "thinking" in path.lower():
        current_path = "thinking"
    elif "/content" in path or "RESPONSE" in path.upper():
        current_path = "content"

    text = str(value or "")
    if text and text != "FINISHED":
        deltas.append(("reasoning" if current_path == "thinking" else "content", text))

    return current_path, deltas


def stream_chunks(token: str, payload: dict):
    response, session_id, request_model = chat_completion(token, payload)
    builder = OpenAIStreamBuilder(session_id, request_model)
    current_path = "content"
    answer_chars = 0
    reasoning_chars = 0

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            event = json.loads(data)
            builder.set_response_id(str(event.get("response_message_id") or builder.response_id))
            current_path, deltas = _iter_event_deltas(event, current_path)
            for kind, text in deltas:
                if kind == "reasoning":
                    reasoning_chars += len(text)
                    yield from builder.reasoning(text)
                else:
                    answer_chars += len(text)
                    yield from builder.content(text)
    finally:
        response.close()

    debug_log(
        "deepseek_stream_done",
        chat_id=builder.response_id,
        model=request_model,
        content_length=answer_chars,
        reasoning_length=reasoning_chars,
    )
    yield builder.finish()


def complete_non_stream(token: str, payload: dict):
    response, session_id, request_model = chat_completion(token, payload)
    response_id = session_id
    answer_parts = []
    reasoning_parts = []
    current_path = "content"

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            event = json.loads(data)
            response_id = str(event.get("response_message_id") or response_id)
            value = event.get("v")
            if isinstance(value, dict) and isinstance((value.get("response") or {}).get("fragments"), list):
                current_path = _append_fragments((value.get("response") or {}).get("fragments"), answer_parts, reasoning_parts) or current_path
                continue

            if event.get("p") == "response/fragments" and isinstance(value, list):
                current_path = _append_fragments(value, answer_parts, reasoning_parts) or current_path
                continue

            path = str(event.get("p") or "")
            if "THINK" in path.upper() or "thinking" in path.lower():
                current_path = "thinking"
            elif "/content" in path or "RESPONSE" in path.upper():
                current_path = "content"

            if isinstance(value, str):
                current_path = _append_delta(current_path, value, answer_parts, reasoning_parts)
    finally:
        response.close()

    message = {"role": "assistant", "content": "".join(answer_parts)}
    reasoning_text = "".join(reasoning_parts)
    if reasoning_text:
        message["reasoning_content"] = reasoning_text

    result = {
        "id": response_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    meta = {
        "chat_id": response_id,
        "model": request_model,
        "provider": "deepseek",
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(message["content"]),
    }
    debug_log("deepseek_non_stream_done", **meta)
    return result, meta
