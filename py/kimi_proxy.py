import base64
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


KIMI_API_BASE = "https://www.kimi.com"
OWNED_BY = "www.kimi.com"

SUPPORTED_MODELS = [
    "kimi",
    "kimi-thinking",
    "kimi-search",
    "kimi-thinking-search",
]

MODEL_FLAGS = {
    "kimi": {"thinking": False, "search": False},
    "kimi-thinking": {"thinking": True, "search": False},
    "kimi-search": {"thinking": False, "search": True},
    "kimi-thinking-search": {"thinking": True, "search": True},
    "k2": {"thinking": False, "search": False},
    "kimi-k2": {"thinking": False, "search": False},
}

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": KIMI_API_BASE,
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Priority": "u=1, i",
}


def supports_model(model: str) -> bool:
    return str(model or "").lower() in MODEL_FLAGS


def _decode_jwt_payload(token: str):
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return {}


def _is_kimi_access_token(token: str) -> bool:
    payload = _decode_jwt_payload(token)
    return payload.get("app_id") == "kimi" and payload.get("typ") == "access"


def _access_token(token: str) -> str:
    if not token:
        raise RuntimeError("Kimi token is empty")
    return token


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
    lines = []
    for message in messages or []:
        role = str(message.get("role") or "user")
        text = _text_from_content(message.get("content"))
        if not text.strip():
            continue
        lines.append(f"{role}: {text}")
    return "\n\n".join(lines).strip()


def _build_frame(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return bytes([0]) + struct.pack(">I", len(body)) + body


def _flags_for(request_model: str):
    lowered = str(request_model or "").lower()
    flags = MODEL_FLAGS.get(lowered) or MODEL_FLAGS["kimi"]
    return flags["thinking"], flags["search"]


def chat_completion(token: str, payload: dict):
    access_token = _access_token(token)
    request_model = str(payload.get("model") or "kimi")
    enable_thinking, enable_search = _flags_for(request_model)
    prompt = _prompt_from_messages(payload.get("messages") or [])
    body = {
        "scenario": "SCENARIO_K2D5",
        "chat_id": "",
        "tools": [{"type": "TOOL_TYPE_SEARCH", "search": {}}] if enable_search else [],
        "message": {
            "parent_id": "",
            "role": "user",
            "blocks": [{"message_id": "", "text": {"content": prompt}}],
            "scenario": "SCENARIO_K2D5",
        },
        "options": {"thinking": enable_thinking},
    }

    response = requests.post(
        f"{KIMI_API_BASE}/apiv2/kimi.gateway.chat.v1.ChatService/Chat",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {access_token}", "Content-Type": "application/connect+json"},
        data=_build_frame(body),
        timeout=120,
        stream=True,
    )
    if response.status_code == 401:
        raise RuntimeError("Kimi token invalid or expired")
    if response.status_code != 200:
        raise RuntimeError(f"Kimi completion failed: HTTP {response.status_code}")

    debug_log("kimi_chat_started", model=request_model, prompt_length=len(prompt), thinking=enable_thinking, search=enable_search)
    return response, request_model


def _iter_frames(response):
    buffer = b""
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        buffer += chunk
        offset = 0
        while offset + 5 <= len(buffer):
            flag = buffer[offset]
            length = struct.unpack(">I", buffer[offset + 1 : offset + 5])[0]
            frame_end = offset + 5 + length
            if frame_end > len(buffer):
                break
            payload = buffer[offset + 5 : frame_end]
            offset = frame_end
            if flag & 0x80:
                continue
            if payload:
                yield json.loads(payload.decode("utf-8"))
        buffer = buffer[offset:]


def _delta_from_op(previous: str, op: str, content: str):
    if not content:
        return previous, ""
    if op == "append":
        return previous + content, content
    if content.startswith(previous):
        return content, content[len(previous) :]
    return content, content if not previous else ""


def stream_chunks(token: str, payload: dict):
    response, request_model = chat_completion(token, payload)
    builder = OpenAIStreamBuilder("kimi", request_model)
    block_state = {}
    total_content = 0

    try:
        for event in _iter_frames(response):
            if event.get("error"):
                raise RuntimeError(f"Kimi API error: {event['error']}")

            if event.get("chat_id"):
                builder.set_response_id(str(event["chat_id"]))

            block = event.get("block") or {}
            text_block = block.get("text") or {}
            content = str(text_block.get("content") or "")
            block_id = str(block.get("message_id") or block.get("id") or "default")
            previous = block_state.get(block_id, "")
            updated, delta = _delta_from_op(previous, str(event.get("op") or ""), content)
            block_state[block_id] = updated

            if delta:
                total_content += len(delta)
                yield from builder.content(delta)

            if event.get("done") is not None:
                break
    finally:
        response.close()

    debug_log("kimi_stream_done", chat_id=builder.response_id, model=request_model, content_length=total_content)
    yield builder.finish()


def complete_non_stream(token: str, payload: dict):
    response, request_model = chat_completion(token, payload)
    content_parts = []
    conversation_id = "kimi"

    try:
        for event in _iter_frames(response):
            if event.get("error"):
                raise RuntimeError(f"Kimi API error: {event['error']}")
            if event.get("chat_id"):
                conversation_id = str(event["chat_id"])
            block = event.get("block") or {}
            text_block = block.get("text") or {}
            content = str(text_block.get("content") or "")
            if content and event.get("op") in {"set", "append"}:
                content_parts.append(content)
            if event.get("done") is not None:
                break
    finally:
        response.close()

    message = {"role": "assistant", "content": "".join(content_parts)}
    result = {
        "id": conversation_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    meta = {
        "chat_id": conversation_id,
        "model": request_model,
        "provider": "kimi",
        "content_length": len(message["content"]),
        "reasoning_length": 0,
        "empty_content": not bool(message["content"]),
    }
    debug_log("kimi_non_stream_done", **meta)
    return result, meta
