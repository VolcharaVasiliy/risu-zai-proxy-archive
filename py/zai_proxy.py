import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from urllib.parse import urlencode

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

BASE = "https://chat.z.ai"
X_FE_VERSION = "prod-fe-1.0.241"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
SECRET = b"key-@@@@)))()((9))-xxxx&&&%%%%%"
OWNED_BY = "z.ai"

SUPPORTED_MODELS = [
    "glm-5",
    "glm-5.1",
    "glm-4.7",
    "glm-4.6v",
    "glm-4.6",
    "glm-4.5v",
    "glm-4.5-air",
    "GLM-5-Turbo",
]

MODEL_MAPPING = {
    "glm-5": "glm-5",
    "glm-5.1": "GLM-5.1",
    "glm-5-turbo": "GLM-5-Turbo",
    "glm-4.7": "glm-4.7",
    "glm-4.6v": "glm-4.6v",
    "glm-4.6": "glm-4.6",
    "glm-4.5v": "glm-4.5v",
    "glm-4.5-air": "glm-4.5-air",
    "GLM-5": "glm-5",
    "GLM-5.1": "GLM-5.1",
    "GLM-5-Turbo": "GLM-5-Turbo",
    "GLM-4.7": "glm-4.7",
    "GLM-4.6V": "glm-4.6v",
    "GLM-4.6": "glm-4.6",
    "GLM-4.5V": "glm-4.5v",
    "GLM-4.5-Air": "glm-4.5-air",
}


def supports_model(model: str) -> bool:
    return str(model or "") in MODEL_MAPPING or str(model or "").lower() in MODEL_MAPPING


def debug_enabled() -> bool:
    return os.environ.get("DEBUG_LOGGING", "").strip().lower() in {"1", "true", "yes", "on"}


def debug_log(message: str, **fields):
    if not debug_enabled():
        return

    payload = {"message": message, **fields}
    print(f"[zai-proxy] {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", flush=True)


def env_int(name: str, default: int, minimum: int = 0, maximum: int = 10) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def empty_retry_count() -> int:
    return env_int("ZAI_EMPTY_RETRY_COUNT", default=1, minimum=0, maximum=3)


def empty_retry_delay_seconds() -> float:
    return env_int("ZAI_EMPTY_RETRY_DELAY_MS", default=250, minimum=0, maximum=5000) / 1000.0


def decode_payload(token: str) -> dict:
    mid = token.split(".")[1]
    mid += "=" * ((4 - len(mid) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(mid.encode()).decode())


def extract_user_id(token: str) -> str:
    try:
        payload = decode_payload(token)
        return str(payload.get("id") or payload.get("user_id") or payload.get("uid") or payload.get("sub") or "guest")
    except Exception:
        return "guest"


def normalize_messages(messages):
    result = []
    for message in messages or []:
      role = message.get("role")
      if role == "system":
          # Skip system for Z.ai
          continue
      if role == "assistant":
          # Skip assistant
          continue
      if role == "user":
          result.append({"role": role, "content": message.get("content", "")})
    return result


def latest_user_text(messages) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
        return ""
    return ""


def signature_for(message: str, request_id: str, timestamp_ms: int, user_id: str) -> str:
    window_index = timestamp_ms // (5 * 60 * 1000)
    derived_key_hex = hmac.new(SECRET, str(window_index).encode(), hashlib.sha256).hexdigest().encode()
    message_b64 = base64.b64encode(message.encode()).decode()
    canonical = f"requestId,{request_id},timestamp,{timestamp_ms},user_id,{user_id}|{message_b64}|{timestamp_ms}"
    return hmac.new(derived_key_hex, canonical.encode(), hashlib.sha256).hexdigest()


def map_model(name: str) -> str:
    return MODEL_MAPPING.get(name) or MODEL_MAPPING.get(str(name).lower()) or name or "glm-5"


def build_common_headers(token: str):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-FE-Version": X_FE_VERSION,
        "Cookie": f"token={token}",
        "Origin": BASE,
        "Referer": f"{BASE}/",
        "User-Agent": UA,
        "Accept": "*/*",
    }


def create_chat(token: str, model: str, messages: list, chat_id: str = None):
    if not chat_id:
        chat_id = str(uuid.uuid4())
    now_s = int(time.time())
    message_dict = {}
    parent_id = None
    current_id = None
    for i, msg in enumerate(messages):
        message_id = str(uuid.uuid4())
        message_dict[message_id] = {
            "id": message_id,
            "parentId": parent_id,
            "childrenIds": [],
            "role": msg["role"],
            "content": msg["content"],
            "timestamp": now_s + i,  # slight offset
            "models": [model],
        }
        if parent_id:
            message_dict[parent_id]["childrenIds"].append(message_id)
        parent_id = message_id
        current_id = message_id

    body = {
        "chat": {
            "id": chat_id,
            "title": "New Chat",
            "models": [model],
            "params": {},
            "history": {
                "messages": message_dict,
                "currentId": current_id,
            },
            "tags": [],
            "flags": [],
            "features": [{"type": "tool_selector", "server": "tool_selector_h", "status": "hidden"}],
            "mcp_servers": [],
            "enable_thinking": False,
            "auto_web_search": False,
            "message_version": 1,
            "extra": {},
            "timestamp": int(time.time() * 1000),
        }
    }
    response = requests.post(f"{BASE}/api/v1/chats/new", headers=build_common_headers(token), json=body, timeout=30)
    response.raise_for_status()
    actual_chat_id = response.json()["id"]
    debug_log("create_chat", model=model, message_count=len(messages), chat_id=actual_chat_id)
    return actual_chat_id, current_id


def build_query(token: str, chat_id: str, request_id: str, timestamp_ms: int, user_id: str):
    now = dt.datetime.utcnow()
    query = {
        "timestamp": str(timestamp_ms),
        "requestId": request_id,
        "user_id": user_id,
        "version": "0.0.1",
        "platform": "web",
        "token": token,
        "user_agent": UA,
        "language": "zh-CN",
        "languages": "zh-CN,zh",
        "timezone": "Asia/Shanghai",
        "cookie_enabled": "true",
        "screen_width": "1512",
        "screen_height": "982",
        "screen_resolution": "1512x982",
        "viewport_height": "945",
        "viewport_width": "923",
        "viewport_size": "923x945",
        "color_depth": "30",
        "pixel_ratio": "2",
        "current_url": f"{BASE}/c/{chat_id}",
        "pathname": f"/c/{chat_id}",
        "search": "",
        "hash": "",
        "host": "chat.z.ai",
        "hostname": "chat.z.ai",
        "protocol": "https:",
        "referrer": "",
        "title": "Z.ai - Free AI Chatbot & Agent powered by GLM-5 & GLM-4.7",
        "timezone_offset": "-480",
        "local_time": now.isoformat() + "Z",
        "utc_time": now.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "is_mobile": "false",
        "is_touch": "false",
        "max_touch_points": "0",
        "browser_name": "Chrome",
        "os_name": "Windows",
        "signature_timestamp": str(timestamp_ms),
    }
    return urlencode(query)


def build_features(request_model: str, web_search=False, reasoning_effort=None):
    lowered = str(request_model or "").lower()
    return {
        "image_generation": False,
        "web_search": False,
        "auto_web_search": bool(web_search) or "search" in lowered,
        "preview_mode": True,
        "flags": [],
        "enable_thinking": bool(reasoning_effort) or "think" in lowered or "r1" in lowered,
    }


def openai_stream_chunks(response, model: str, chat_id: str):
    created = int(time.time())
    sent_role = False
    answer_chunks = 0
    thinking_chunks = 0
    total_answer_chars = 0
    saw_done = False
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "):
            continue
        data = raw[6:]
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        if obj.get("type") != "chat:completion":
            continue
        item = obj.get("data") or {}
        if item.get("phase") == "thinking" and item.get("delta_content"):
            thinking_chunks += 1
            if not sent_role:
                yield {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"role": "assistant", "reasoning_content": ""}, "finish_reason": None}]}
                sent_role = True
            yield {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"reasoning_content": item["delta_content"]}, "finish_reason": None}]}
        elif item.get("phase") == "answer" and item.get("delta_content"):
            answer_chunks += 1
            total_answer_chars += len(item["delta_content"])
            if not sent_role:
                yield {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}
                sent_role = True
            yield {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"content": item["delta_content"]}, "finish_reason": None}]}
        elif item.get("phase") == "done" and item.get("done"):
            saw_done = True
            debug_log("stream_done", chat_id=chat_id, model=model, answer_chunks=answer_chunks, thinking_chunks=thinking_chunks, total_answer_chars=total_answer_chars)
            yield {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            return

    debug_log("stream_ended_without_done", chat_id=chat_id, model=model, answer_chunks=answer_chunks, thinking_chunks=thinking_chunks, total_answer_chars=total_answer_chars, saw_done=saw_done)
    yield {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}


def chat_completion(token: str, payload: dict):
    request_model = payload.get("model", "glm-5")
    model = map_model(request_model)
    messages = normalize_messages(payload.get("messages") or [])
    prompt = latest_user_text(messages)
    # Auto-generate conversation_id from first user message for automatic context
    conversation_id = None
    if messages:
        import hashlib
        conversation_id = hashlib.md5(messages[0]["content"].encode()).hexdigest()[:16]
    if conversation_id:
        chat_id = conversation_id
        if len(messages) == 1:
            # First message: create chat
            chat_id, _ = create_chat(token, model, messages)
            body_messages = messages
        else:
            # Continuation: use existing chat
            body_messages = [messages[-1]]
    else:
        chat_id, _ = create_chat(token, model, messages)
        body_messages = messages
    request_id = str(uuid.uuid4())
    timestamp_ms = int(time.time() * 1000)
    user_id = extract_user_id(token)
    signature = signature_for(prompt, request_id, timestamp_ms, user_id)
    now = dt.datetime.utcnow()

    body = {
        "stream": True,
        "model": model,
        "messages": [msg["content"] for msg in body_messages],
        "signature_prompt": prompt,
        "params": {},
        "extra": {},
        "features": build_features(request_model, payload.get("web_search"), payload.get("reasoning_effort")),
        "variables": {
            "{{USER_NAME}}": "User",
            "{{USER_LOCATION}}": "Unknown",
            "{{CURRENT_DATETIME}}": now.strftime("%Y-%m-%d %H:%M:%S"),
            "{{CURRENT_DATE}}": now.strftime("%Y-%m-%d"),
            "{{CURRENT_TIME}}": now.strftime("%H:%M:%S"),
            "{{CURRENT_WEEKDAY}}": now.strftime("%A"),
            "{{CURRENT_TIMEZONE}}": "UTC",
            "{{USER_LANGUAGE}}": "en-US",
        },
        "chat_id": chat_id,
        "id": request_id,
        "current_user_message_id": payload.get("current_user_message_id") or (chat_id if not payload.get("chat_id") else None),
        "current_user_message_parent_id": None,
        "background_tasks": {"title_generation": True, "tags_generation": True},
    }

    headers = build_common_headers(token)
    headers.update(
        {
            "Accept-Encoding": "identity",
            "Accept-Language": "zh-CN",
            "X-Signature": signature,
            "Referer": f"{BASE}/c/{chat_id}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Priority": "u=1, i",
        }
    )

    response = requests.post(
        f"{BASE}/api/v2/chat/completions?{build_query(token, chat_id, request_id, timestamp_ms, user_id)}",
        headers=headers,
        json=body,
        timeout=120,
        stream=True,
    )
    response.raise_for_status()
    debug_log("chat_completion_started", chat_id=chat_id, request_id=request_id, model=model, prompt_length=len(prompt), stream_requested=bool(payload.get("stream", True)))
    return response, chat_id, model


def collect_non_stream(response, model: str, chat_id: str):
    created = int(time.time())
    content_parts = []
    reasoning_parts = []
    answer_chunks = 0
    thinking_chunks = 0
    saw_done = False

    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "):
            continue
        data = raw[6:]
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        if obj.get("type") != "chat:completion":
            continue
        item = obj.get("data") or {}
        if item.get("phase") == "thinking" and item.get("delta_content"):
            thinking_chunks += 1
            reasoning_parts.append(item["delta_content"])
        elif item.get("phase") == "answer" and item.get("delta_content"):
            answer_chunks += 1
            content_parts.append(item["delta_content"])
        elif item.get("phase") == "done" and item.get("done"):
            saw_done = True

    message = {"role": "assistant", "content": "".join(content_parts)}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)

    debug_log(
        "collect_non_stream_done",
        chat_id=chat_id,
        model=model,
        answer_chunks=answer_chunks,
        thinking_chunks=thinking_chunks,
        content_length=len(message["content"]),
        reasoning_length=len(message.get("reasoning_content", "")),
        saw_done=saw_done,
        empty_content=not bool(message["content"]),
    )

    result = {
        "id": chat_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    meta = {
        "chat_id": chat_id,
        "model": model,
        "provider": "zai",
        "answer_chunks": answer_chunks,
        "thinking_chunks": thinking_chunks,
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "saw_done": saw_done,
        "empty_content": not bool(message["content"]),
    }

    return result, meta


def complete_non_stream(token: str, payload: dict):
    max_retries = empty_retry_count()
    attempts = max_retries + 1
    last_result = None
    last_meta = None

    for attempt in range(1, attempts + 1):
        upstream, chat_id, model = chat_completion(token, payload)
        try:
            result, meta = collect_non_stream(upstream, model, chat_id)
        finally:
            upstream.close()

        last_result = result
        last_meta = meta

        if not meta["empty_content"]:
            if attempt > 1:
                debug_log("non_stream_retry_recovered", attempt=attempt, attempts=attempts, **meta)
            return result, meta

        if attempt < attempts:
            debug_log("non_stream_empty_retry", attempt=attempt, attempts=attempts, **meta)
            delay = empty_retry_delay_seconds()
            if delay > 0:
                time.sleep(delay)
            continue

    debug_log("non_stream_empty_exhausted", attempts=attempts, **(last_meta or {}))
    raise RuntimeError("Upstream returned an empty completion")
