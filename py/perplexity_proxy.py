import json
import os
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


PERPLEXITY_URL = "https://www.perplexity.ai"
QUERY_ENDPOINT = f"{PERPLEXITY_URL}/rest/sse/perplexity_ask"
OWNED_BY = "www.perplexity.ai"

SUPPORTED_MODELS = [
    "Turbo",
    "PPLX-Pro",
    "GPT-5",
    "Gemini-2.5-Pro",
    "Claude-Sonnet-4",
    "Claude-Opus-4",
    "Nemotron",
]

MODEL_MAP = {
    "auto": "turbo",
    "turbo": "turbo",
    "pplx-pro": "pplx_pro",
    "pplx_pro": "pplx_pro",
    "gpt-5": "gpt5",
    "gpt5": "gpt5",
    "gemini-2.5-pro": "gemini25pro",
    "gemini25pro": "gemini25pro",
    "claude-sonnet-4": "claude4sonnet",
    "claude4sonnet": "claude4sonnet",
    "claude-opus-4": "claude4opus",
    "claude4opus": "claude4opus",
    "nemotron": "nemotron",
}

FAKE_HEADERS = {
    "Accept": "text/event-stream",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": PERPLEXITY_URL,
    "Sec-Ch-Ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
}


def supports_model(model: str) -> bool:
    return str(model or "").lower() in MODEL_MAP


def _map_model(model: str) -> str:
    return MODEL_MAP.get(str(model or "").lower()) or "turbo"


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


def _extract_query(messages) -> str:
    system_prompt = ""
    conversation = []
    for message in messages or []:
        role = str(message.get("role") or "")
        text = _text_from_content(message.get("content"))
        if not text.strip():
            continue
        if role == "system" and not system_prompt:
            system_prompt = text
            continue
        if role == "system":
            continue
        label = "User" if role == "user" else "Assistant"
        conversation.append(f"[{label}]: {text}")
    conversation_text = "\n\n".join(conversation)
    if system_prompt and conversation_text:
        return f"{system_prompt}\n\n---\n\n{conversation_text}"
    return conversation_text or system_prompt


def _filter_citations(text: str) -> str:
    return re.sub(r"\[(?:perplexity[+-])?\d+\]", "", text or "")


def _request_body(query: str, model: str) -> dict:
    frontend_uuid = str(uuid.uuid4())
    frontend_context_uuid = str(uuid.uuid4())
    return {
        "params": {
            "attachments": [],
            "language": "en-US",
            "timezone": "America/Los_Angeles",
            "search_focus": "internet",
            "sources": ["web"],
            "search_recency_filter": None,
            "frontend_uuid": frontend_uuid,
            "mode": "copilot",
            "model_preference": model,
            "is_related_query": False,
            "is_sponsored": False,
            "frontend_context_uuid": frontend_context_uuid,
            "prompt_source": "user",
            "query_source": "home",
            "is_incognito": False,
            "time_from_first_type": 18361,
            "local_search_enabled": False,
            "use_schematized_api": True,
            "send_back_text_in_streaming_api": False,
            "supported_block_use_cases": [
                "answer_modes",
                "media_items",
                "knowledge_cards",
                "inline_entity_cards",
                "place_widgets",
                "finance_widgets",
                "prediction_market_widgets",
                "sports_widgets",
                "flight_status_widgets",
                "news_widgets",
                "shopping_widgets",
                "jobs_widgets",
                "search_result_widgets",
                "inline_images",
                "inline_assets",
                "placeholder_cards",
                "diff_blocks",
                "inline_knowledge_cards",
                "entity_group_v2",
                "refinement_filters",
                "canvas_mode",
                "maps_preview",
                "answer_tabs",
                "price_comparison_widgets",
                "preserve_latex",
                "generic_onboarding_widgets",
                "in_context_suggestions",
                "inline_claims",
            ],
            "client_coordinates": None,
            "mentions": [],
            "dsl_query": query,
            "skip_search_enabled": True,
            "is_nav_suggestions_disabled": False,
            "source": "default",
            "always_search_override": False,
            "override_no_search": False,
            "should_ask_for_mcp_tool_confirmation": True,
            "browser_agent_allow_once_from_toggle": False,
            "force_enable_browser_agent": False,
            "supported_features": ["browser_agent_permission_banner_v1.1"],
            "version": "2.18",
        },
        "query_str": query,
    }


def _session():
    if curl_requests is not None:
        return curl_requests.Session(impersonate="chrome136", timeout=120)
    return requests.Session()


def chat_completion(cookie_header: str, payload: dict):
    request_model = str(payload.get("model") or "Turbo")
    model = _map_model(request_model)
    query = _extract_query(payload.get("messages") or [])
    if not query:
        raise RuntimeError("Perplexity query is empty")

    request_id = str(uuid.uuid4())
    headers = {
        **FAKE_HEADERS,
        "Content-Type": "application/json",
        "Cookie": cookie_header,
        "x-perplexity-request-reason": "perplexity-query-state-provider",
        "x-request-id": request_id,
        "Referer": f"{PERPLEXITY_URL}/",
    }
    body = _request_body(query, model)
    session = _session()

    if curl_requests is not None:
        response = session.post(QUERY_ENDPOINT, headers=headers, json=body, stream=True)
    else:
        response = session.post(QUERY_ENDPOINT, headers=headers, json=body, timeout=120, stream=True)

    if response.status_code == 403:
        raise RuntimeError("Perplexity request was blocked by Cloudflare")
    if response.status_code != 200:
        try:
            body_text = response.text
        except Exception:
            body_text = ""
        raise RuntimeError(f"Perplexity completion failed: HTTP {response.status_code} {body_text[:300]}")

    debug_log("perplexity_chat_started", model=request_model, query_length=len(query))
    return session, response, request_model, request_id


def _iter_sse_data(response):
    for raw in response.iter_lines():
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if raw.startswith("event:"):
            continue
        if not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data:
            yield data


def _extract_block_value(value):
    if isinstance(value, dict) and "chunks" in value:
        return "".join(str(part) for part in (value.get("chunks") or []) if part)
    if isinstance(value, dict) and "answer" in value:
        return str(value.get("answer") or "")
    if isinstance(value, str):
        return value
    return ""


def _suffix_delta(previous: str, current: str) -> str:
    if not current:
        return ""
    if not previous:
        return current
    if current.startswith(previous):
        return current[len(previous) :]
    if len(current) > len(previous):
        return current[len(previous) :]
    return ""


def stream_chunks(cookie_header: str, payload: dict):
    session, response, request_model, request_id = chat_completion(cookie_header, payload)
    builder = OpenAIStreamBuilder(request_id, request_model)
    answer_state = {}
    reasoning_state = {}
    last_answer = ""
    last_reasoning = ""

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            event = json.loads(data)
            if event.get("backend_uuid"):
                builder.set_response_id(str(event["backend_uuid"]))

            for block in event.get("blocks") or []:
                if block.get("intended_usage") == "sources_answer_mode":
                    continue
                diff_block = block.get("diff_block") or {}
                field = diff_block.get("field")
                for patch in diff_block.get("patches") or []:
                    path = str(patch.get("path") or "")
                    if path == "/progress":
                        continue
                    value = _extract_block_value(patch.get("value"))
                    if not value:
                        continue
                    state_key = f"{field}:{path or '/'}"
                    if path.startswith("/goals"):
                        reasoning_state[state_key] = value
                    elif field == "markdown_block":
                        answer_state[state_key] = _filter_citations(value)

            answer_text = "".join(answer_state[key] for key in sorted(answer_state))
            reasoning_text = "".join(reasoning_state[key] for key in sorted(reasoning_state))

            answer_delta = _suffix_delta(last_answer, answer_text)
            reasoning_delta = _suffix_delta(last_reasoning, reasoning_text)
            last_answer = answer_text
            last_reasoning = reasoning_text

            if reasoning_delta:
                yield from builder.reasoning(reasoning_delta)
            if answer_delta:
                yield from builder.content(answer_delta)
    finally:
        response.close()
        session.close()

    debug_log(
        "perplexity_stream_done",
        chat_id=builder.response_id,
        model=request_model,
        content_length=len(last_answer),
        reasoning_length=len(last_reasoning),
    )
    yield builder.finish()


def complete_non_stream(cookie_header: str, payload: dict):
    session, response, request_model, request_id = chat_completion(cookie_header, payload)
    answer_state = {}
    reasoning_state = {}
    response_id = request_id

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break
            event = json.loads(data)
            if event.get("backend_uuid"):
                response_id = str(event["backend_uuid"])
            for block in event.get("blocks") or []:
                if block.get("intended_usage") == "sources_answer_mode":
                    continue
                diff_block = block.get("diff_block") or {}
                field = diff_block.get("field")
                for patch in diff_block.get("patches") or []:
                    path = str(patch.get("path") or "")
                    if path == "/progress":
                        continue
                    value = _extract_block_value(patch.get("value"))
                    if not value:
                        continue
                    state_key = f"{field}:{path or '/'}"
                    if path.startswith("/goals"):
                        reasoning_state[state_key] = value
                    elif field == "markdown_block":
                        answer_state[state_key] = _filter_citations(value)
    finally:
        response.close()
        session.close()

    answer_text = "".join(answer_state[key] for key in sorted(answer_state))
    reasoning_text = "".join(reasoning_state[key] for key in sorted(reasoning_state))
    message = {"role": "assistant", "content": answer_text}
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
        "provider": "perplexity",
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(message["content"]),
    }
    debug_log("perplexity_non_stream_done", **meta)
    return result, meta
