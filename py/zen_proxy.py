import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.zai_proxy import debug_log
except ImportError:
    from zai_proxy import debug_log


OWNED_BY = "opencode-zen"

# Models mirror the codex-zen catalog (data/catalog.json): OpenCode Zen free
# gateway slugs with reasoning levels and tool shims.
SUPPORTED_MODELS = [
    "big-pickle",
    "deepseek-v4-flash-free",
    "mimo-v2.5-free",
    "hy3-free",
    "laguna-s-2.1-free",
    "nemotron-3-ultra-free",
    "nemotron-3.5-lightning-free",
]

DEFAULT_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    # OpenCode Zen rejects the default python-requests UA with 403; a browser
    # UA is required (matches how the official codex-zen gateway talks to it).
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

VALID_EFFORT = {"low", "medium", "high", "xhigh", "max", "minimal"}

ZEN_HOST = os.environ.get("ZEN_HOST", "opencode.ai").strip() or "opencode.ai"
ZEN_BASE = os.environ.get("ZEN_BASE", "/zen/v1").strip() or "/zen/v1"
ZEN_TIMEOUT = int(os.environ.get("ZEN_TIMEOUT", "120") or "120")

PASSTHROUGH_FIELDS = [
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "max_completion_tokens",
    "max_tokens",
    "metadata",
    "modalities",
    "n",
    "parallel_tool_calls",
    "presence_penalty",
    "reasoning_effort",
    "response_format",
    "seed",
    "stop",
    "temperature",
    "tool_choice",
    "tools",
    "top_logprobs",
    "top_p",
    "user",
]


def supports_model(model: str) -> bool:
    return str(model or "").strip().lower() in {m.lower() for m in SUPPORTED_MODELS}


def _canonical_model(model: str) -> str:
    lowered = str(model or "").strip().lower()
    for m in SUPPORTED_MODELS:
        if m.lower() == lowered:
            return m
    raise RuntimeError(f"Unsupported OpenCode Zen model: {model}")


def _normalize_effort(value):
    if not value:
        return None
    text = str(value).strip().lower()
    return text if text in VALID_EFFORT else "medium"


def _request_body(payload: dict, stream: bool) -> dict:
    model = _canonical_model(payload.get("model"))
    messages = payload.get("messages") or []
    body = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    for field in PASSTHROUGH_FIELDS:
        if field in payload and payload[field] is not None:
            body[field] = payload[field]
    # Responses API alias: max_output_tokens -> max_tokens
    if body.get("max_output_tokens") is not None and body.get("max_tokens") is None:
        body["max_tokens"] = body["max_output_tokens"]
    # Responses API alias: reasoning.effort -> reasoning_effort
    reasoning = payload.get("reasoning")
    if body.get("reasoning_effort") is None and isinstance(reasoning, dict) and reasoning.get("effort"):
        body["reasoning_effort"] = _normalize_effort(reasoning["effort"])
    return body


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or raw.startswith(":") or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data and data != "[DONE]":
            yield data


def _request(payload: dict, stream: bool):
    url = f"https://{ZEN_HOST}{ZEN_BASE}/chat/completions"
    body_dict = _request_body(payload, stream)
    body = json.dumps(body_dict).encode("utf-8")
    headers = dict(DEFAULT_HEADERS)
    headers["content-length"] = str(len(body))
    response = requests.post(
        url, headers=headers, data=body, timeout=ZEN_TIMEOUT, stream=stream
    )
    if response.status_code != 200:
        text = ""
        try:
            text = response.text[:400]
        except Exception:
            pass
        raise RuntimeError(
            f"OpenCode Zen request failed: HTTP {response.status_code} {text}".strip()
        )
    return response


def stream_chunks(_credentials: dict, payload: dict):
    model = _canonical_model(payload.get("model"))
    response = _request(payload, stream=True)
    debug_log("zen_chat_started", model=model, stream=True)
    try:
        for data in _iter_sse_data(response):
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"OpenCode Zen stream parse failed: {exc}: {data[:200]}") from exc
            if isinstance(parsed, dict) and parsed.get("model"):
                parsed["model"] = model
            yield parsed
    finally:
        response.close()


def complete_non_stream(_credentials: dict, payload: dict):
    model = _canonical_model(payload.get("model"))
    response = _request(payload, stream=False)
    try:
        result = response.json()
    except Exception as exc:
        raise RuntimeError(f"OpenCode Zen response is not valid JSON: {exc}") from exc
    finally:
        response.close()

    if isinstance(result, dict):
        result["model"] = model

    meta = {
        "provider": "opencode-zen",
        "model": model,
    }
    debug_log("zen_chat_done", **meta)
    return result, meta
