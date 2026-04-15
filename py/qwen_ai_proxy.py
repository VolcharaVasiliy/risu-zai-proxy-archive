import json
import os
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

QWEN_AI_BASE = "https://chat.qwen.ai"
OWNED_BY = "chat.qwen.ai"

SUPPORTED_MODELS = [
    "Qwen3.5-Plus",
    "Qwen3-235B-A22B-2507",
    "Qwen3-Max",
    "Qwen3.5-397B-A17B",
    "Qwen3-Coder",
    "Qwen3-VL-235B-A22B",
    "Qwen3-Omni-Flash",
    "Qwen2.5-Max",
]

MODEL_MAP = {
    "Qwen3.5-Plus": "qwen3.5-plus",
    "Qwen3.5-397B-A17B": "qwen3.5-397b-a17b",
    "Qwen3-Max": "qwen3-max",
    "Qwen3-235B-A22B-2507": "qwen3-235b-a22b-2507",
    "Qwen3-Coder": "qwen3-coder-plus",
    "Qwen3-VL-235B-A22B": "qwen3-vl-235b-a22b",
    "Qwen3-Omni-Flash": "qwen3-omni-flash",
    "Qwen2.5-Max": "qwen2.5-max",
    "qwen": "qwen3.5-plus",
    "qwen3": "qwen3.5-plus",
    "qwen3.5": "qwen3.5-plus",
    "qwen3-coder": "qwen3-coder-plus",
    "qwen3-vl": "qwen3-vl-235b-a22b",
    "qwen3-omni": "qwen3-omni-flash",
    "qwen2.5": "qwen2.5-max",
}

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Content-Type": "application/json",
    "source": "web",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "bx-v": "2.5.36",
    "Timezone": "Mon Feb 23 2026 22:06:02 GMT+0800",
    "Version": "0.2.7",
    "Origin": "https://chat.qwen.ai",
}


def supports_model(model: str) -> bool:
    lowered = str(model or "").lower()
    if lowered.endswith("-thinking"):
        lowered = lowered[:-9]
    elif lowered.endswith("-fast"):
        lowered = lowered[:-5]
    for key in MODEL_MAP:
        if key.lower() == lowered:
            return True
    return False


def map_model(model: str) -> str:
    value = str(model or "")
    force_suffix = ""
    if value.endswith("-thinking"):
        force_suffix = "-thinking"
        value = value[:-9]
    elif value.endswith("-fast"):
        force_suffix = "-fast"
        value = value[:-5]

    lowered = value.lower()
    for key, mapped in MODEL_MAP.items():
        if key.lower() == lowered:
            return mapped + force_suffix
    return value + force_suffix


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
    system_parts = []
    user_content = ""
    for message in messages or []:
        role = message.get("role")
        text = _text_from_content(message.get("content", ""))
        if not text.strip():
            continue
        if role == "system":
            system_parts.append(text)
        elif role == "user":
            user_content = text
    if system_parts:
        return f"{chr(10).join(system_parts)}\n\nUser: {user_content}"
    return user_content


def _headers(token: str, cookie: str = "", chat_id: str = ""):
    headers = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {token}",
        "X-Request-Id": str(uuid.uuid4()),
    }
    if chat_id:
        headers["Referer"] = f"{QWEN_AI_BASE}/c/{chat_id}"
    if cookie:
        headers["Cookie"] = cookie
    return headers


def create_chat(token: str, cookie: str, model_id: str, title: str = "OpenAI_API_Chat") -> str:
    response = requests.post(
        f"{QWEN_AI_BASE}/api/v2/chats/new",
        headers=_headers(token, cookie),
        json={
            "title": title,
            "models": [model_id],
            "chat_mode": "normal",
            "chat_type": "t2t",
            "timestamp": int(time.time() * 1000),
            "project_id": "",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    chat_id = data.get("data", {}).get("id")
    if not chat_id:
        raise RuntimeError(f"Qwen AI create chat failed: {data}")
    return chat_id


def chat_completion(token: str, cookie: str, payload: dict):
    request_model = payload.get("model", "Qwen3-Max")
    model_id = map_model(request_model)
    prompt = _prompt_from_messages(payload.get("messages") or [])
    chat_id = create_chat(token, cookie, model_id)

    lowered = str(request_model or "").lower()
    should_enable_thinking = bool(payload.get("enable_thinking") or payload.get("reasoning_effort"))
    if request_model.endswith("-thinking") or "think" in lowered or "r1" in lowered:
        should_enable_thinking = True
    if request_model.endswith("-fast"):
        should_enable_thinking = False

    now_s = int(time.time())
    fid = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    body = {
        "stream": True,
        "version": "2.1",
        "incremental_output": True,
        "chat_id": chat_id,
        "chat_mode": "normal",
        "model": model_id.replace("-thinking", "").replace("-fast", ""),
        "parent_id": None,
        "messages": [
            {
                "fid": fid,
                "parentId": None,
                "childrenIds": [child_id],
                "role": "user",
                "content": prompt,
                "user_action": "chat",
                "files": [],
                "timestamp": now_s,
                "models": [model_id.replace("-thinking", "").replace("-fast", "")],
                "chat_type": "t2t",
                "feature_config": {
                    "thinking_enabled": should_enable_thinking,
                    "output_schema": "phase",
                    "research_mode": "normal",
                    "auto_thinking": should_enable_thinking,
                    "thinking_format": "summary",
                    "auto_search": False,
                },
                "extra": {"meta": {"subChatType": "t2t"}},
                "sub_chat_type": "t2t",
                "parent_id": None,
            }
        ],
        "timestamp": now_s + 1,
    }

    response = requests.post(
        f"{QWEN_AI_BASE}/api/v2/chat/completions?chat_id={chat_id}",
        headers={**_headers(token, cookie, chat_id), "x-accel-buffering": "no"},
        json=body,
        timeout=120,
        stream=True,
    )
    response.raise_for_status()
    debug_log("qwen_ai_chat_started", model=request_model, chat_id=chat_id, prompt_length=len(prompt), thinking=should_enable_thinking)
    return response, chat_id, request_model


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data:
            yield data


def stream_chunks(token: str, cookie: str, payload: dict):
    response, chat_id, request_model = chat_completion(token, cookie, payload)
    builder = OpenAIStreamBuilder(chat_id, request_model)
    reasoning_text = ""
    summary_text = ""
    answer_text = ""

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            parsed = json.loads(data)
            created_info = parsed.get("response.created") or {}
            if created_info.get("response_id"):
                builder.set_response_id(str(created_info["response_id"]))

            choices = parsed.get("choices") or []
            if not choices:
                continue

            delta = choices[0].get("delta") or {}
            phase = delta.get("phase")
            status = delta.get("status")
            content = delta.get("content") or ""

            if phase == "think" and status != "finished":
                reasoning_text += content
                if content:
                    yield from builder.reasoning(content)
            elif phase == "thinking_summary" and not reasoning_text:
                extra = delta.get("extra") or {}
                summary_parts = ((extra.get("summary_thought") or {}).get("content")) or []
                if isinstance(summary_parts, list):
                    new_summary = "\n".join(str(part) for part in summary_parts if part)
                    if len(new_summary) > len(summary_text):
                        summary_delta = new_summary[len(summary_text) :]
                        summary_text = new_summary
                        if summary_delta:
                            yield from builder.reasoning(summary_delta)
            elif phase == "answer":
                if content:
                    answer_text += content
                    yield from builder.content(content)
            elif phase is None and content:
                answer_text += content
                yield from builder.content(content)
    finally:
        response.close()

    debug_log(
        "qwen_ai_stream_done",
        chat_id=builder.response_id,
        model=request_model,
        content_length=len(answer_text),
        reasoning_length=len(reasoning_text or summary_text),
    )
    yield builder.finish()


def complete_non_stream(token: str, cookie: str, payload: dict):
    response, chat_id, request_model = chat_completion(token, cookie, payload)
    response_id = ""
    reasoning_text = ""
    summary_text = ""
    answer_text = ""

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            parsed = json.loads(data)
            created_info = parsed.get("response.created") or {}
            if not response_id and created_info.get("response_id"):
                response_id = created_info["response_id"]

            choices = parsed.get("choices") or []
            if not choices:
                continue

            delta = choices[0].get("delta") or {}
            phase = delta.get("phase")
            status = delta.get("status")
            content = delta.get("content") or ""

            if phase == "think" and status != "finished":
                reasoning_text += content
            elif phase == "thinking_summary":
                extra = delta.get("extra") or {}
                summary_parts = ((extra.get("summary_thought") or {}).get("content")) or []
                if isinstance(summary_parts, list):
                    new_summary = "\n".join(str(part) for part in summary_parts if part)
                    if len(new_summary) > len(summary_text):
                        summary_text = new_summary
            elif phase == "answer":
                if content:
                    answer_text += content
            elif phase is None and content:
                answer_text += content
    finally:
        response.close()

    message = {
        "role": "assistant",
        "content": answer_text,
    }
    final_reasoning = reasoning_text or summary_text
    if final_reasoning:
        message["reasoning_content"] = final_reasoning

    result = {
        "id": response_id or chat_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    meta = {
        "chat_id": result["id"],
        "model": request_model,
        "provider": "qwen-ai",
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(message["content"]),
    }
    debug_log("qwen_ai_non_stream_done", **meta)
    return result, meta
