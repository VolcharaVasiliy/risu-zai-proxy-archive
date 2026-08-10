import base64
import json
import os
import struct
import sys
import threading
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
KIMI_AUTH_BASE = "https://auth.kimi.com/api"
OWNED_BY = "www.kimi.com"

REFRESH_ENDPOINT = f"{KIMI_AUTH_BASE}/account.gateway.v1.AuthService/RefreshToken"

_token_lock = threading.Lock()
_token_cache = {}  # key: refresh_token hash -> {"access": str, "refresh": str, "exp": int}

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
    "k2.5": {"thinking": False, "search": False},
    "kimi-k2.5": {"thinking": False, "search": False},
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


def _jwt_exp(token: str):
    payload = _decode_jwt_payload(token)
    try:
        return int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return 0


def _persist_tokens(access_token: str, refresh_token: str) -> None:
    """Writes refreshed tokens back to credentials.json so a server restart
    keeps working without rescanning."""
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["KIMI_TOKEN"] = access_token
        data["KIMI_REFRESH_TOKEN"] = refresh_token
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _refresh_access_token(refresh_token: str):
    """Calls the auth service RefreshToken endpoint. Returns
    (access_token, refresh_token) or raises RuntimeError."""
    if not refresh_token:
        raise RuntimeError("Kimi refresh token is empty")
    headers = {
        **FAKE_HEADERS,
        "Content-Type": "application/json",
        "connect-protocol-version": "1",
        "x-msh-platform": "web",
        "x-msh-version": "2.0.0",
    }
    claims = _decode_jwt_payload(refresh_token)
    device_id = str(claims.get("device_id") or "").strip()
    session_id = str(claims.get("ssid") or "").strip()
    traffic_id = str(claims.get("sub") or "").strip()
    if device_id:
        headers["x-msh-device-id"] = device_id
    if session_id:
        headers["x-msh-session-id"] = session_id
    if traffic_id:
        headers["x-traffic-id"] = traffic_id
    response = requests.post(
        REFRESH_ENDPOINT,
        headers=headers,
        json={"refreshToken": refresh_token},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Kimi token refresh failed: HTTP {response.status_code}")
    data = response.json()
    new_access = str(data.get("accessToken") or "").strip()
    new_refresh = str(data.get("refreshToken") or "").strip()
    if not new_access:
        raise RuntimeError("Kimi token refresh returned no accessToken")
    return new_access, new_refresh or refresh_token


def _ensure_fresh_token(access_token: str, refresh_token: str) -> str:
    """Returns an access token valid for the next ~10 minutes, refreshing
    via the refresh token when needed. Refreshed tokens are cached in memory
    and persisted to credentials.json."""
    if not refresh_token:
        return access_token
    with _token_lock:
        cached = _token_cache.get(refresh_token)
        if cached and cached["access"] and cached["exp"] - int(time.time()) > 120:
            return cached["access"]
    exp = _jwt_exp(access_token)
    if exp and exp - int(time.time()) > 300:
        return access_token
    new_access, new_refresh = _refresh_access_token(refresh_token)
    with _token_lock:
        _token_cache[refresh_token] = {
            "access": new_access,
            "refresh": new_refresh,
            "exp": _jwt_exp(new_access),
        }
    _persist_tokens(new_access, new_refresh)
    debug_log("kimi_token_refreshed", refresh_exp=_jwt_exp(new_refresh))
    return new_access


def _with_fresh_token(token: str, refresh_token: str) -> str:
    return _ensure_fresh_token(token, refresh_token)


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


def chat_completion(token: str, payload: dict, refresh_token: str = ""):
    access_token = _ensure_fresh_token(_access_token(token), refresh_token or "")
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

    # Kimi gateway now binds requests to the JWT via x-msh-* context headers
    # (device_id, ssid, sub). Missing them makes even fresh tokens rejected
    # with "invalid user token". All values are derived from the token itself.
    claims = _decode_jwt_payload(access_token)
    device_id = str(claims.get("device_id") or "").strip()
    session_id = str(claims.get("ssid") or "").strip()
    traffic_id = str(claims.get("sub") or "").strip()
    headers = {
        **FAKE_HEADERS,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/connect+json",
        "connect-protocol-version": "1",
        "x-msh-platform": "web",
        "x-msh-version": "2.0.0",
    }
    if device_id:
        headers["x-msh-device-id"] = device_id
    if session_id:
        headers["x-msh-session-id"] = session_id
    if traffic_id:
        headers["x-traffic-id"] = traffic_id
    shield = (os.environ.get("KIMI_MSH_SHIELD_DATA") or "").strip()
    if shield:
        headers["x-msh-shield-data"] = shield

    response = requests.post(
        f"{KIMI_API_BASE}/apiv2/kimi.gateway.chat.v1.ChatService/Chat",
        headers=headers,
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


def stream_chunks(token: str, payload: dict, refresh_token: str = ""):
    response, request_model = chat_completion(token, payload, refresh_token)
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


def complete_non_stream(token: str, payload: dict, refresh_token: str = ""):
    response, request_model = chat_completion(token, payload, refresh_token)
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
