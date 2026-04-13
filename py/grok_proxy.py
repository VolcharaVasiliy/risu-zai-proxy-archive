import base64
import json
import os
import random
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))

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


BASE_URL = "https://grok.com"
CHAT_ENDPOINT = f"{BASE_URL}/rest/app-chat/conversations/new"
OWNED_BY = "grok.com"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"

SUPPORTED_MODELS = [
    "grok-3",
    "grok-3-mini",
    "grok-3-thinking",
    "grok-4",
    "grok-4-mini",
    "grok-4-thinking",
    "grok-4-heavy",
    "grok-4.1-mini",
    "grok-4.1-fast",
    "grok-4.1-expert",
    "grok-4.1-thinking",
    "grok-4.20-beta",
]

MODEL_MAPPING = {
    "grok-3": {"name": "grok-3", "mode": "MODEL_MODE_GROK_3"},
    "grok-3-mini": {"name": "grok-3", "mode": "MODEL_MODE_GROK_3_MINI_THINKING"},
    "grok-3-thinking": {"name": "grok-3", "mode": "MODEL_MODE_GROK_3_THINKING"},
    "grok-4": {"name": "grok-4", "mode": "MODEL_MODE_GROK_4"},
    "grok-4-mini": {"name": "grok-4-mini", "mode": "MODEL_MODE_GROK_4_MINI_THINKING"},
    "grok-4-thinking": {"name": "grok-4", "mode": "MODEL_MODE_GROK_4_THINKING"},
    "grok-4-heavy": {"name": "grok-4", "mode": "MODEL_MODE_HEAVY"},
    "grok-4.1-mini": {"name": "grok-4-1-thinking-1129", "mode": "MODEL_MODE_GROK_4_1_MINI_THINKING"},
    "grok-4.1-fast": {"name": "grok-4-1-thinking-1129", "mode": "MODEL_MODE_FAST"},
    "grok-4.1-expert": {"name": "grok-4-1-thinking-1129", "mode": "MODEL_MODE_EXPERT"},
    "grok-4.1-thinking": {"name": "grok-4-1-thinking-1129", "mode": "MODEL_MODE_GROK_4_1_THINKING"},
    "grok-4.20-beta": {"name": "grok-420", "mode": "MODEL_MODE_GROK_420"},
}

FILTERED_TAGS = ("rolloutId", "responseId", "isThinking")


def supports_model(model: str) -> bool:
    return str(model or "").strip().lower() in MODEL_MAPPING


def _map_model(model: str) -> dict:
    return MODEL_MAPPING.get(str(model or "").strip().lower()) or MODEL_MAPPING["grok-3"]


def _session(use_curl: bool = True):
    if use_curl and curl_requests is not None:
        return curl_requests.Session(impersonate="chrome136", timeout=120)
    return requests.Session()


def _statsig_id() -> str:
    suffix = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
    message = f"e:TypeError: Cannot read properties of undefined (reading '{suffix}')"
    return base64.b64encode(message.encode("utf-8")).decode("ascii")


def _headers(cookie_header: str) -> dict:
    user_agent = os.environ.get("GROK_USER_AGENT", "").strip() or DEFAULT_USER_AGENT
    return {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Cookie": cookie_header,
        "Origin": BASE_URL,
        "Priority": "u=1, i",
        "Referer": f"{BASE_URL}/",
        "Sec-Ch-Ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "Sec-Ch-Ua-Arch": '"x86"',
        "Sec-Ch-Ua-Bitness": '"64"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": user_agent,
        "x-statsig-id": _statsig_id(),
        "x-xai-request-id": str(uuid.uuid4()),
    }


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
    extracted = []
    for message in messages or []:
        role = str(message.get("role") or "user")
        text = _text_from_content(message.get("content"))
        if text.strip():
            extracted.append({"role": role, "text": text.strip()})

    if not extracted:
        return ""

    last_user_index = -1
    for index in range(len(extracted) - 1, -1, -1):
        if extracted[index]["role"] == "user":
            last_user_index = index
            break

    parts = []
    for index, item in enumerate(extracted):
        role = item["role"]
        text = item["text"]
        if index == last_user_index and role == "user":
            parts.append(text)
            continue
        if role == "system":
            parts.append(f"system: {text}")
        elif role == "assistant":
            parts.append(f"assistant: {text}")
        else:
            parts.append(f"user: {text}")
    return "\n\n".join(parts)


def _request_body(request_model: str, payload: dict) -> dict:
    mapping = _map_model(request_model)
    message = _prompt_from_messages(payload.get("messages") or [])
    if not message:
        raise RuntimeError("Grok prompt is empty")

    return {
        "deviceEnvInfo": {
            "darkModeEnabled": False,
            "devicePixelRatio": 2,
            "screenWidth": 1920,
            "screenHeight": 1080,
            "viewportWidth": 1920,
            "viewportHeight": 947,
        },
        "disableMemory": False,
        "disableNsfwFilter": False,
        "disableSearch": False,
        "disableSelfHarmShortCircuit": False,
        "disableTextFollowUps": False,
        "enableImageGeneration": False,
        "enableImageStreaming": False,
        "enableSideBySide": True,
        "fileAttachments": [],
        "forceConcise": False,
        "forceSideBySide": False,
        "imageAttachments": [],
        "imageGenerationCount": 0,
        "isAsyncChat": False,
        "isReasoning": False,
        "message": message,
        "modelMode": mapping["mode"],
        "modelName": mapping["name"],
        "responseMetadata": {
            "requestModelDetails": {"modelId": mapping["name"]},
            "modelConfigOverride": {},
        },
        "returnImageBytes": False,
        "returnRawGrokInXaiRequest": False,
        "sendFinalMetadata": True,
        "temporary": True,
        "toolOverrides": {},
    }


def _filter_token(token: str) -> str:
    filtered = str(token or "")
    if not filtered:
        return ""

    filtered = re.sub(r"<xai:tool_usage_card[^>]*>.*?</xai:tool_usage_card>", "", filtered, flags=re.DOTALL)
    filtered = re.sub(r"<xai:tool_usage_card[^>]*/>", "", filtered, flags=re.DOTALL)

    for tag in FILTERED_TAGS:
        filtered = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", filtered, flags=re.DOTALL)
        filtered = re.sub(rf"<{tag}[^>]*/>", "", filtered, flags=re.DOTALL)

    return filtered


def _iter_sse_data(response):
    for raw in response.iter_lines():
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        line = raw.strip()
        if not line:
            continue
        if line.startswith("data:"):
            data = line[5:].strip()
        else:
            data = line
        if data:
            yield data


def chat_completion(cookie_header: str, payload: dict):
    request_model = str(payload.get("model") or "grok-3")
    request_body = _request_body(request_model, payload)
    used_transport = "curl_cffi" if curl_requests is not None else "requests"

    def _post(use_curl: bool):
        session = _session(use_curl=use_curl)
        response = session.post(
            CHAT_ENDPOINT,
            headers=_headers(cookie_header),
            json=request_body,
            stream=True,
            allow_redirects=False,
        )
        return session, response

    session, response = _post(use_curl=True)

    if response.status_code == 403 and curl_requests is not None:
        response.close()
        session.close()
        session, response = _post(use_curl=False)
        used_transport = "requests"

    if response.status_code in {401, 403}:
        body_text = ""
        try:
            body_text = response.text[:300]
        except Exception:
            pass
        response.close()
        session.close()
        raise RuntimeError(f"Grok authentication failed: HTTP {response.status_code} {body_text}".strip())

    if response.status_code != 200:
        body_text = ""
        try:
            body_text = response.text[:300]
        except Exception:
            pass
        response.close()
        session.close()
        raise RuntimeError(f"Grok completion failed: HTTP {response.status_code} {body_text}".strip())

    debug_log("grok_chat_started", model=request_model, transport=used_transport)
    return session, response, request_model


def stream_chunks(cookie_header: str, payload: dict):
    session, response, request_model = chat_completion(cookie_header, payload)
    builder = OpenAIStreamBuilder(str(uuid.uuid4()), request_model)
    answer_text = ""
    reasoning_text = ""
    saw_done = False

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            parsed = json.loads(data)
            resp = ((parsed.get("result") or {}).get("response") or {})

            response_id = str(resp.get("responseId") or "").strip()
            if response_id:
                builder.set_response_id(response_id)

            if resp.get("isDone"):
                saw_done = True
                break

            token = _filter_token(resp.get("token"))
            if not token:
                continue

            if resp.get("isThinking") or resp.get("messageStepId"):
                reasoning_text += token
                yield from builder.reasoning(token)
            else:
                answer_text += token
                yield from builder.content(token)
    finally:
        response.close()
        session.close()

    debug_log(
        "grok_stream_done",
        chat_id=builder.response_id,
        model=request_model,
        content_length=len(answer_text),
        reasoning_length=len(reasoning_text),
        saw_done=saw_done,
    )
    yield builder.finish()


def complete_non_stream(cookie_header: str, payload: dict):
    session, response, request_model = chat_completion(cookie_header, payload)
    response_id = ""
    answer_parts = []
    reasoning_parts = []
    fallback_message = ""
    saw_done = False

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            parsed = json.loads(data)
            resp = ((parsed.get("result") or {}).get("response") or {})

            if resp.get("responseId"):
                response_id = str(resp["responseId"])
            if resp.get("message"):
                fallback_message = str(resp["message"])
            if resp.get("isDone"):
                saw_done = True
                break

            token = _filter_token(resp.get("token"))
            if not token:
                continue

            if resp.get("isThinking") or resp.get("messageStepId"):
                reasoning_parts.append(token)
            else:
                answer_parts.append(token)
    finally:
        response.close()
        session.close()

    answer_text = "".join(answer_parts) or _filter_token(fallback_message)
    reasoning_text = "".join(reasoning_parts)

    message = {"role": "assistant", "content": answer_text}
    if reasoning_text:
        message["reasoning_content"] = reasoning_text

    result = {
        "id": response_id or str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    meta = {
        "chat_id": result["id"],
        "model": request_model,
        "provider": "grok",
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(message["content"]),
        "saw_done": saw_done,
    }
    debug_log("grok_non_stream_done", **meta)
    return result, meta
