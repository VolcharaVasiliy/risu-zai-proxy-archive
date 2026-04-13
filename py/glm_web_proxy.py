import hashlib
import json
import os
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.zai_proxy import debug_log
except ImportError:
    from zai_proxy import debug_log

GLM_API_BASE = "https://chatglm.cn/chatglm"
DEFAULT_ASSISTANT_ID = "65940acff94777010aa6b796"
SIGN_SECRET = "8a1317a7468aa3ad86e997d08f3f31cb"

OWNED_BY = "chatglm.cn"
SUPPORTED_MODELS = [
    "chatglm-web",
    "chatglm-web-thinking",
    "chatglm-web-deepresearch",
]

FAKE_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    "App-Name": "chatglm",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json",
    "Origin": "https://chatglm.cn",
    "Pragma": "no-cache",
    "Priority": "u=1, i",
    "Sec-Ch-Ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
    "X-App-Fr": "browser_extension",
    "X-App-Platform": "pc",
    "X-App-Version": "0.0.1",
    "X-Device-Brand": "",
    "X-Device-Model": "",
    "X-Lang": "zh",
}

_TOKEN_CACHE = {}


def supports_model(model: str) -> bool:
    if re.fullmatch(r"[a-z0-9]{24,}", str(model or "")):
        return True
    return str(model or "").lower() in {value.lower() for value in SUPPORTED_MODELS}


def _text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def _prompt_from_messages(messages) -> str:
    system_parts = []
    conversation_parts = []

    for message in messages or []:
        role = message.get("role")
        text = _text_from_content(message.get("content", ""))
        if not text.strip():
            continue
        if role == "system":
            system_parts.append(text)
            continue
        label = "User"
        if role == "assistant":
            label = "Assistant"
        elif role == "tool":
            label = "Tool"
        conversation_parts.append(f"{label}: {text}")

    prompt_parts = []
    if system_parts:
        prompt_parts.append("System: " + "\n\n".join(system_parts))
    if conversation_parts:
        prompt_parts.append("\n\n".join(conversation_parts))
    return "\n\n".join(prompt_parts).strip()


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _generate_sign():
    now_ms = int(time.time() * 1000)
    timestamp = str(now_ms)
    digits = [int(char) for char in timestamp]
    checksum = (sum(digits) - digits[-2]) % 10
    signed_timestamp = timestamp[:-2] + str(checksum) + timestamp[-1]
    nonce = str(uuid.uuid4())
    sign = _md5(f"{signed_timestamp}-{nonce}-{SIGN_SECRET}")
    return {"timestamp": signed_timestamp, "nonce": nonce, "sign": sign}


def _assistant_id_for(model: str) -> str:
    if re.fullmatch(r"[a-z0-9]{24,}", str(model or "")):
        return model
    return os.environ.get("GLM_ASSISTANT_ID", "").strip() or DEFAULT_ASSISTANT_ID


def _chat_mode_for(model: str, payload: dict) -> str:
    lowered = str(model or "").lower()
    if payload.get("deep_research") or "deepresearch" in lowered:
        return "deep_research"
    if payload.get("reasoning_effort") or "think" in lowered or "zero" in lowered:
        return "zero"
    return ""


def acquire_access_token(refresh_token: str) -> str:
    cached = _TOKEN_CACHE.get(refresh_token)
    if cached and cached["expires_at"] > time.time():
        return cached["access_token"]

    sign = _generate_sign()
    response = requests.post(
        f"{GLM_API_BASE}/user-api/user/refresh",
        headers={
            "Authorization": f"Bearer {refresh_token}",
            **FAKE_HEADERS,
            "X-Device-Id": str(uuid.uuid4()),
            "X-Nonce": sign["nonce"],
            "X-Request-Id": str(uuid.uuid4()),
            "X-Sign": sign["sign"],
            "X-Timestamp": sign["timestamp"],
        },
        json={},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if (data.get("code") not in {0, None} and data.get("status") not in {0, None}) or not data.get("result", {}).get("access_token"):
        raise RuntimeError(f"GLM token refresh failed: {data.get('message') or data}")

    access_token = data["result"]["access_token"]
    _TOKEN_CACHE[refresh_token] = {
        "access_token": access_token,
        "expires_at": time.time() + 3500,
    }
    return access_token


def chat_completion(refresh_token: str, payload: dict):
    access_token = acquire_access_token(refresh_token)
    request_model = payload.get("model", "chatglm-web")
    prompt = _prompt_from_messages(payload.get("messages") or [])
    if not prompt:
        prompt = "User: "

    sign = _generate_sign()
    body = {
        "assistant_id": _assistant_id_for(request_model),
        "conversation_id": "",
        "project_id": "",
        "chat_type": "user_chat",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
        "meta_data": {
            "channel": "",
            "chat_mode": _chat_mode_for(request_model, payload) or None,
            "draft_id": "",
            "if_plus_model": True,
            "input_question_type": "xxxx",
            "is_networking": bool(payload.get("web_search")),
            "is_test": False,
            "platform": "pc",
            "quote_log_id": "",
            "cogview": {"rm_label_watermark": False},
        },
    }
    response = requests.post(
        f"{GLM_API_BASE}/backend-api/assistant/stream",
        headers={
            "Authorization": f"Bearer {access_token}",
            **FAKE_HEADERS,
            "X-Device-Id": str(uuid.uuid4()),
            "X-Request-Id": str(uuid.uuid4()),
            "X-Sign": sign["sign"],
            "X-Timestamp": sign["timestamp"],
            "X-Nonce": sign["nonce"],
        },
        json=body,
        timeout=120,
        stream=True,
    )
    response.raise_for_status()
    debug_log("glm_chat_started", model=request_model, prompt_length=len(prompt))
    return response, request_model


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data:
            yield data


def _append_part(cache, part):
    logic_id = part.get("logic_id") or str(len(cache))
    cache[logic_id] = part


def _extract_part_text(part):
    content = part.get("content")
    if not isinstance(content, list):
        return "", ""

    part_text = []
    part_reasoning = []
    for value in content:
        if not isinstance(value, dict):
            continue
        item_type = value.get("type")
        if item_type == "text" and value.get("text"):
            part_text.append(str(value["text"]))
        elif item_type == "think" and value.get("think"):
            part_reasoning.append(str(value["think"]))
        elif item_type == "image" and isinstance(value.get("image"), list):
            for image in value["image"]:
                image_url = image.get("image_url")
                if image_url and re.match(r"^https?://", image_url):
                    part_text.append(f"![image]({image_url})")
        elif item_type == "code" and value.get("code"):
            part_text.append(f"```python\n{value['code']}\n```")
        elif item_type == "execution_output" and isinstance(value.get("content"), str):
            part_text.append(value["content"])
    return "\n".join(part_text).strip(), "\n".join(part_reasoning).strip()


def complete_non_stream(refresh_token: str, payload: dict):
    response, request_model = chat_completion(refresh_token, payload)
    cached_parts = {}
    conversation_id = ""

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break
            result = json.loads(data)
            if not conversation_id and result.get("conversation_id"):
                conversation_id = result["conversation_id"]

            for part in result.get("parts") or []:
                _append_part(cached_parts, part)

            if result.get("status") == "finish":
                break
    finally:
        response.close()

    text_blocks = []
    reasoning_blocks = []
    for part in cached_parts.values():
        text, reasoning = _extract_part_text(part)
        if text:
            text_blocks.append(text)
        if reasoning:
            reasoning_blocks.append(reasoning)

    message = {
        "role": "assistant",
        "content": "\n".join(block for block in text_blocks if block).strip(),
    }
    if reasoning_blocks:
        message["reasoning_content"] = "\n".join(block for block in reasoning_blocks if block).strip()

    result = {
        "id": conversation_id or f"glm-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    meta = {
        "chat_id": result["id"],
        "model": request_model,
        "provider": "glm-web",
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(message["content"]),
    }
    debug_log("glm_non_stream_done", **meta)
    return result, meta
