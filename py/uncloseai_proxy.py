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


OWNED_BY = "uncloseai.com"

MODEL_TARGETS = {
    "uncloseai-hermes": {
        "api_base": "https://hermes.ai.unturf.com/v1",
        "fallback_model": "adamo1139/Hermes-3-Llama-3.1-8B-FP8-Dynamic",
        "match_prefix": "adamo1139/Hermes-3-Llama-3.1-8B",
    },
    "uncloseai-hermes-8b": {
        "api_base": "https://hermes.ai.unturf.com/v1",
        "fallback_model": "adamo1139/Hermes-3-Llama-3.1-8B-FP8-Dynamic",
        "match_prefix": "adamo1139/Hermes-3-Llama-3.1-8B",
    },
    "uncloseai-qwen-vl": {
        "api_base": "https://qwen-vl.ai.unturf.com/v1",
        "fallback_model": "qwen3-vl:8b",
        "match_prefix": "qwen3-vl:",
    },
    "uncloseai-gpt-oss": {
        "api_base": "https://qwen-vl.ai.unturf.com/v1",
        "fallback_model": "gpt-oss:latest",
        "match_prefix": "gpt-oss:",
    },
    "uncloseai-r1-distill": {
        "api_base": "https://qwen-vl.ai.unturf.com/v1",
        "fallback_model": "deepseek-r1:14b-qwen-distill-q8_0",
        "match_prefix": "deepseek-r1:",
    },
}

SUPPORTED_MODELS = list(MODEL_TARGETS.keys())
_MODEL_INDEX = {model.lower(): model for model in SUPPORTED_MODELS}
_MODEL_CACHE = {}
_MODEL_CACHE_TTL_SECONDS = 300

DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
}

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
    return str(model or "").lower() in _MODEL_INDEX


def _config_for(model: str):
    canonical = _MODEL_INDEX.get(str(model or "").lower())
    if not canonical:
        raise RuntimeError(f"Unsupported UncloseAI model: {model}")
    return canonical, MODEL_TARGETS[canonical]


def _cache_get(key: str):
    entry = _MODEL_CACHE.get(key)
    if not entry:
        return None
    if entry["expires_at"] <= time.time():
        _MODEL_CACHE.pop(key, None)
        return None
    return entry["value"]


def _cache_set(key: str, value):
    _MODEL_CACHE[key] = {"value": value, "expires_at": time.time() + _MODEL_CACHE_TTL_SECONDS}


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or raw.startswith(":") or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if data:
            yield data


def _response_error(response, label: str):
    try:
        body = response.text[:400]
    except Exception:
        body = ""
    raise RuntimeError(f"UncloseAI {label} failed: HTTP {response.status_code} {body}".strip())


def _fetch_models(api_base: str):
    cached = _cache_get(api_base)
    if cached:
        return cached

    response = requests.get(f"{api_base}/models", headers=DEFAULT_HEADERS, timeout=30)
    if response.status_code != 200:
        _response_error(response, "model discovery")

    data = response.json()
    model_ids = [str(item.get("id") or "").strip() for item in (data.get("data") or []) if str(item.get("id") or "").strip()]
    if not model_ids:
        raise RuntimeError(f"UncloseAI model discovery returned no models for {api_base}")

    _cache_set(api_base, model_ids)
    return model_ids


def _resolve_upstream_model(config: dict) -> str:
    api_base = config["api_base"]
    fallback_model = str(config.get("fallback_model") or "").strip()
    match_prefix = str(config.get("match_prefix") or "")

    try:
        model_ids = _fetch_models(api_base)
        for model_id in model_ids:
            if match_prefix and model_id.startswith(match_prefix):
                return model_id
        if model_ids:
            return model_ids[0]
    except Exception as exc:
        if fallback_model:
            debug_log("uncloseai_model_fallback", api_base=api_base, fallback_model=fallback_model, error=str(exc))
            return fallback_model
        raise

    if fallback_model:
        return fallback_model
    raise RuntimeError(f"UncloseAI upstream model could not be resolved for {api_base}")


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


def _request_completion(api_base: str, body: dict, stream: bool):
    response = requests.post(
        f"{api_base}/chat/completions",
        headers=DEFAULT_HEADERS,
        json=body,
        timeout=120,
        stream=stream,
    )
    if response.status_code != 200:
        _response_error(response, "chat completion")
    return response


def stream_chunks(_credentials: dict, payload: dict):
    request_model, config = _config_for(str(payload.get("model") or "uncloseai-hermes"))
    upstream_model = _resolve_upstream_model(config)
    response = _request_completion(config["api_base"], _request_body(payload, upstream_model, True), stream=True)
    debug_log("uncloseai_chat_started", model=request_model, upstream_model=upstream_model, api_base=config["api_base"], stream=True)

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"UncloseAI stream parse failed: {exc}: {data[:200]}") from exc
            if isinstance(parsed, dict) and parsed.get("model"):
                parsed["model"] = request_model
            yield parsed
    finally:
        response.close()


def complete_non_stream(_credentials: dict, payload: dict):
    request_model, config = _config_for(str(payload.get("model") or "uncloseai-hermes"))
    upstream_model = _resolve_upstream_model(config)
    response = _request_completion(config["api_base"], _request_body(payload, upstream_model, False), stream=False)
    try:
        result = response.json()
    except Exception as exc:
        raise RuntimeError(f"UncloseAI non-stream response is not valid JSON: {exc}") from exc
    finally:
        response.close()

    if isinstance(result, dict):
        result["model"] = request_model

    meta = {
        "provider": "uncloseai",
        "model": request_model,
        "upstream_model": upstream_model,
        "api_base": config["api_base"],
    }
    debug_log("uncloseai_chat_done", **meta)
    return result, meta
