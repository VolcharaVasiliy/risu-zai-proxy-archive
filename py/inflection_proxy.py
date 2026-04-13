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


API_BASE = os.environ.get("INFLECTION_API_BASE", "https://api.inflection.ai/v1").rstrip("/")
OWNED_BY = "Inflection AI (api.inflection.ai)"

# Client-facing model ids (OpenAI-style) -> upstream Inflection `model` field
MODEL_UPSTREAM = {
    "pi-api": "inflection_3_pi",
    "inflection-pi": "inflection_3_pi",
    "inflection_3_pi": "inflection_3_pi",
    "pi-3.1": "Pi-3.1",
    "pi-3-1": "Pi-3.1",
}

SUPPORTED_MODELS = list(MODEL_UPSTREAM.keys())
_MODEL_INDEX = {k.lower(): k for k in SUPPORTED_MODELS}

PASSTHROUGH_FIELDS = [
    "frequency_penalty",
    "logit_bias",
    "logprobs",
    "max_completion_tokens",
    "max_tokens",
    "metadata",
    "n",
    "presence_penalty",
    "response_format",
    "seed",
    "stop",
    "stream_options",
    "temperature",
    "top_p",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "user",
]


def supports_model(model: str) -> bool:
    return str(model or "").lower() in _MODEL_INDEX


def _canonical_model(model: str) -> str:
    return _MODEL_INDEX.get(str(model or "").lower()) or ""


def _token(credentials: dict) -> str:
    t = (credentials or {}).get("token") or ""
    if not str(t).strip():
        raise RuntimeError("Inflection API token is empty")
    return str(t).strip()


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _response_error(response, label: str):
    try:
        body = response.text[:500]
    except Exception:
        body = ""
    raise RuntimeError(f"Inflection {label} failed: HTTP {response.status_code} {body}".strip())


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or raw.startswith(":") or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data:
            yield data


def _request_body(payload: dict, upstream_model: str, stream: bool) -> dict:
    body = {
        "model": upstream_model,
        "messages": payload.get("messages") or [],
        "stream": stream,
    }
    for field in PASSTHROUGH_FIELDS:
        if field in payload and payload[field] is not None:
            body[field] = payload[field]
    return body


def _post(token: str, body: dict, stream: bool):
    response = requests.post(
        f"{API_BASE}/chat/completions",
        headers=_headers(token),
        json=body,
        timeout=120,
        stream=stream,
    )
    if response.status_code != 200:
        _response_error(response, "chat completion")
    return response


def stream_chunks(credentials: dict, payload: dict):
    token = _token(credentials)
    request_model = _canonical_model(str(payload.get("model") or "pi-api"))
    upstream = MODEL_UPSTREAM.get(request_model) or MODEL_UPSTREAM["pi-api"]
    body = _request_body(payload, upstream, True)
    body["stream"] = True
    response = _post(token, body, stream=True)
    debug_log(
        "inflection_chat_started",
        model=request_model,
        upstream_model=upstream,
        api_base=API_BASE,
        stream=True,
    )

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Inflection stream parse failed: {exc}: {data[:200]}") from exc
            if isinstance(parsed, dict) and parsed.get("model"):
                parsed["model"] = request_model
            yield parsed
    finally:
        response.close()


def complete_non_stream(credentials: dict, payload: dict):
    token = _token(credentials)
    request_model = _canonical_model(str(payload.get("model") or "pi-api"))
    upstream = MODEL_UPSTREAM.get(request_model) or MODEL_UPSTREAM["pi-api"]
    body = _request_body(payload, upstream, False)
    body["stream"] = False
    response = _post(token, body, stream=False)
    try:
        result = response.json()
    except Exception as exc:
        raise RuntimeError(f"Inflection non-stream response is not valid JSON: {exc}") from exc
    finally:
        response.close()

    if isinstance(result, dict):
        result["model"] = request_model

    meta = {
        "provider": "inflection",
        "model": request_model,
        "upstream_model": upstream,
        "api_base": API_BASE,
    }
    debug_log("inflection_chat_done", **meta)
    return result, meta
