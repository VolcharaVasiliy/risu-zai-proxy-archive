import base64
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.openai_stream import OpenAIStreamBuilder, openai_chunk
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder, openai_chunk
    from zai_proxy import debug_log


OWNED_BY = "Google AI Studio / Gemini API"
API_BASE = os.environ.get(
    "GOOGLE_AI_STUDIO_API_BASE", "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")
DEFAULT_USER_AGENT = os.environ.get(
    "GOOGLE_AI_STUDIO_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
).strip()

DEFAULT_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]
MODEL_ALIASES = {
    "google-ai-studio": "gemini-2.5-flash",
    "ai-studio": "gemini-2.5-flash",
    "ai-studio-pro": "gemini-2.5-pro",
    "ai-studio-flash": "gemini-2.5-flash",
    "ai-studio-lite": "gemini-2.5-flash-lite",
}
_SCHEMA_DROP_KEYS = {
    "$schema",
    "$id",
    "$defs",
    "definitions",
    "examples",
    "default",
    "additionalProperties",
    "anyOf",
    "oneOf",
    "allOf",
    "not",
    "nullable",
    "patternProperties",
}


def _strip_model_prefix(model: str) -> str:
    value = str(model or "").strip()
    if value.startswith("models/"):
        return value[7:]
    return value


def _configured_models() -> list[str]:
    raw = os.environ.get("GOOGLE_AI_STUDIO_MODELS", "").strip()
    models = []
    if raw:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str):
                    value = item.strip()
                elif isinstance(item, dict):
                    value = str(
                        item.get("id") or item.get("name") or item.get("model") or ""
                    ).strip()
                else:
                    value = ""
                if value:
                    models.append(_strip_model_prefix(value))
    if not models:
        models = list(DEFAULT_MODELS)

    ordered = []
    seen = set()
    for model in [*MODEL_ALIASES.keys(), *models]:
        lowered = model.lower()
        if lowered not in seen:
            ordered.append(model)
            seen.add(lowered)
    return ordered


SUPPORTED_MODELS = _configured_models()


def supports_model(model: str) -> bool:
    lowered = str(model or "").strip().lower()
    if not lowered:
        return False
    if lowered in MODEL_ALIASES:
        return True
    return any(lowered == item.lower() for item in _configured_models())


def _map_model(model: str) -> str:
    lowered = str(model or "").strip().lower()
    if lowered in MODEL_ALIASES:
        return MODEL_ALIASES[lowered]
    for item in _configured_models():
        if lowered == item.lower():
            return _strip_model_prefix(item)
    return MODEL_ALIASES["google-ai-studio"]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int_env(
    name: str, default: int, minimum: int = 0, maximum: int = 100_000_000
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _mime_from_url(url: str, fallback: str = "image/png") -> str:
    guessed = mimetypes.guess_type(str(url or "").split("?", 1)[0])[0]
    return guessed or fallback


def _data_url_part(url: str) -> dict | None:
    match = re.match(
        r"^data:(?P<mime>[^;,]+)?(?:;[^,]*)?;base64,(?P<data>.*)$",
        str(url or ""),
        re.I | re.S,
    )
    if not match:
        return None
    mime = (match.group("mime") or "image/png").strip() or "image/png"
    data = re.sub(r"\s+", "", match.group("data") or "")
    return {"inline_data": {"mime_type": mime, "data": data}}


def _file_data_part(file_data: str, mime_type: str = "image/png") -> dict | None:
    raw = str(file_data or "").strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        return _data_url_part(raw)
    return {
        "inline_data": {
            "mime_type": mime_type or "image/png",
            "data": re.sub(r"\s+", "", raw),
        }
    }


def _download_image_part(url: str, mime_type: str = "") -> dict | None:
    if not _bool_env("GOOGLE_AI_STUDIO_FETCH_IMAGE_URLS", default=True):
        return None
    max_bytes = _int_env(
        "GOOGLE_AI_STUDIO_MAX_IMAGE_BYTES", default=20_000_000, minimum=1024
    )
    response = requests.get(
        str(url), headers={"User-Agent": DEFAULT_USER_AGENT}, timeout=30
    )
    response.raise_for_status()
    content = response.content or b""
    if len(content) > max_bytes:
        raise RuntimeError(
            f"Image URL is too large for Google AI Studio proxy: {len(content)} bytes"
        )
    detected_mime = (
        mime_type
        or response.headers.get("content-type", "").split(";", 1)[0].strip()
        or _mime_from_url(url)
    )
    encoded = base64.b64encode(content).decode("ascii")
    return {"inline_data": {"mime_type": detected_mime, "data": encoded}}


def _image_item_part(item: dict) -> dict | None:
    mime_type = (
        str(item.get("mime_type") or item.get("media_type") or "image/png").strip()
        or "image/png"
    )
    image = item.get("image_url")
    if isinstance(image, dict):
        image = image.get("url")
    image = image or item.get("url") or item.get("file_url")
    file_data = item.get("file_data") or item.get("data")
    if file_data:
        return _file_data_part(str(file_data), mime_type)
    if image:
        image_url = str(image).strip()
        data_part = _data_url_part(image_url)
        if data_part:
            return data_part
        if image_url.startswith(("http://", "https://")):
            return _download_image_part(image_url, mime_type=mime_type)
    return None


def _content_to_parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return [{"text": str(content)}] if content is not None else []

    parts = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type in {"text", "input_text", "output_text"}:
            text = str(item.get("text") or "")
            if text:
                parts.append({"text": text})
            continue
        if item_type in {"image_url", "input_image"}:
            image_part = _image_item_part(item)
            if image_part:
                parts.append(image_part)
            continue
        if item_type in {"input_file", "file"}:
            file_data = item.get("file_data") or item.get("data")
            mime_type = str(item.get("mime_type") or item.get("media_type") or "")
            if file_data and mime_type.startswith("image/"):
                file_part = _file_data_part(str(file_data), mime_type)
                if file_part:
                    parts.append(file_part)
                continue
            file_url = str(item.get("file_url") or item.get("url") or "").strip()
            if file_url and mime_type.startswith("image/"):
                image_part = _image_item_part(item)
                if image_part:
                    parts.append(image_part)
                continue
            if file_data:
                parts.append(
                    {
                        "text": f"[file: {item.get('filename') or item.get('name') or 'file'}] inline data ({len(str(file_data))} chars)"
                    }
                )
                continue
            if file_url:
                parts.append(
                    {
                        "text": f"[file: {item.get('filename') or item.get('name') or 'file'}] {file_url}"
                    }
                )
    return parts


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in _content_to_parts(content):
            if isinstance(part, dict) and part.get("text"):
                texts.append(str(part["text"]))
        return "\n".join(texts)
    if content is None:
        return ""
    return str(content)


def _parse_json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"items": value}
    text = str(value or "").strip()
    if not text:
        return {"content": ""}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {"content": parsed}
    except Exception:
        return {"content": text}


def _parse_tool_arguments(arguments) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"input": parsed}
        except Exception:
            return {"input": text}
    return {"input": arguments}


def _messages_to_contents(messages: list) -> tuple[dict | None, list[dict]]:
    system_parts = []
    contents = []
    call_names_by_id = {}

    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        parts = _content_to_parts(message.get("content"))

        if role in {"system", "developer"}:
            system_parts.extend(part for part in parts if part.get("text"))
            continue

        if role == "assistant":
            tool_calls = (
                message.get("tool_calls")
                if isinstance(message.get("tool_calls"), list)
                else []
            )
            model_parts = list(parts)
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = (
                    call.get("function")
                    if isinstance(call.get("function"), dict)
                    else {}
                )
                name = str(function.get("name") or call.get("name") or "").strip()
                if not name:
                    continue
                call_id = str(call.get("id") or call.get("call_id") or "").strip()
                if call_id:
                    call_names_by_id[call_id] = name
                function_call_part = {
                    "name": name,
                    "args": _parse_tool_arguments(
                        function.get("arguments")
                        if "arguments" in function
                        else call.get("arguments")
                    ),
                }
                if call_id:
                    function_call_part["id"] = call_id
                model_parts.append({"functionCall": function_call_part})
            contents.append({"role": "model", "parts": model_parts or [{"text": ""}]})
            continue

        if role in {"tool", "function"}:
            call_id = str(
                message.get("tool_call_id")
                or message.get("call_id")
                or message.get("id")
                or ""
            ).strip()
            name = str(
                message.get("name") or call_names_by_id.get(call_id) or ""
            ).strip()
            if not name:
                name = "tool_result"
            function_response_part = {
                "name": name,
                "response": _parse_json_object(message.get("content")),
            }
            if call_id:
                function_response_part["id"] = call_id
            contents.append(
                {
                    "role": "user",
                    "parts": [{"functionResponse": function_response_part}],
                }
            )
            continue

        if not parts:
            continue
        contents.append({"role": "user", "parts": parts})

    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents


def _generation_config(payload: dict) -> dict:
    config = {}
    if payload.get("temperature") is not None:
        config["temperature"] = payload.get("temperature")
    else:
        config["temperature"] = float(
            os.environ.get("GOOGLE_AI_STUDIO_TEMPERATURE", "1") or "1"
        )
    if payload.get("top_p") is not None:
        config["topP"] = payload.get("top_p")
    else:
        config["topP"] = float(
            os.environ.get("GOOGLE_AI_STUDIO_TOP_P", "0.95") or "0.95"
        )
    max_tokens = (
        payload.get("max_output_tokens")
        or payload.get("max_completion_tokens")
        or payload.get("max_tokens")
        or os.environ.get("GOOGLE_AI_STUDIO_MAX_OUTPUT_TOKENS", "65536")
    )
    if max_tokens:
        config["maxOutputTokens"] = int(max_tokens)
    stop = payload.get("stop")
    if isinstance(stop, str):
        config["stopSequences"] = [stop]
    elif isinstance(stop, list) and stop:
        config["stopSequences"] = [str(item) for item in stop if str(item)]

    response_mime = payload.get("response_mime_type") or os.environ.get(
        "GOOGLE_AI_STUDIO_RESPONSE_MIME_TYPE", ""
    )
    if response_mime:
        config["responseMimeType"] = str(response_mime)

    thinking_budget = payload.get("thinking_budget") or os.environ.get(
        "GOOGLE_AI_STUDIO_THINKING_BUDGET", ""
    )
    if thinking_budget not in {None, ""}:
        config["thinkingConfig"] = {"thinkingBudget": int(thinking_budget)}
    return config


def _schema_for_gemini(schema) -> dict:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    for union_key in ("anyOf", "oneOf"):
        union_options = schema.get(union_key)
        if isinstance(union_options, list):
            for option in union_options:
                if not isinstance(option, dict):
                    continue
                if str(option.get("type") or "").strip().lower() == "null":
                    continue
                merged = {
                    key: value
                    for key, value in schema.items()
                    if key not in _SCHEMA_DROP_KEYS
                }
                merged.update(option)
                return _schema_for_gemini(merged)

    all_of_options = schema.get("allOf")
    if isinstance(all_of_options, list):
        merged = {
            key: value for key, value in schema.items() if key not in _SCHEMA_DROP_KEYS
        }
        for option in all_of_options:
            if isinstance(option, dict):
                merged.update(option)
        return _schema_for_gemini(merged)

    cleaned = {}
    for key, value in schema.items():
        if key in _SCHEMA_DROP_KEYS:
            continue
        if key == "type" and isinstance(value, list):
            cleaned[key] = next(
                (str(item) for item in value if str(item).lower() != "null"),
                "string",
            )
        elif isinstance(value, dict):
            cleaned[key] = _schema_for_gemini(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _schema_for_gemini(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    if str(cleaned.get("type") or "").strip().lower() == "null":
        cleaned["type"] = "string"
    if "type" not in cleaned:
        if isinstance(cleaned.get("properties"), dict):
            cleaned["type"] = "object"
        elif "items" in cleaned:
            cleaned["type"] = "array"
    if not cleaned:
        return {"type": "object", "properties": {}}
    return cleaned


def _function_declarations(payload: dict) -> list[dict]:
    declarations = []
    tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if str(tool.get("type") or "function") != "function":
            continue
        function = (
            tool.get("function") if isinstance(tool.get("function"), dict) else tool
        )
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        declaration = {
            "name": name,
            "description": str(function.get("description") or ""),
            "parameters": _schema_for_gemini(
                function.get("parameters") or {"type": "object", "properties": {}}
            ),
        }
        declarations.append(declaration)
    return declarations


def _builtin_tools(payload: dict) -> list[dict]:
    tools = []
    if _bool_env("GOOGLE_AI_STUDIO_GOOGLE_SEARCH", default=False) or payload.get(
        "google_search"
    ):
        tools.append({"googleSearch": {}})
    if _bool_env("GOOGLE_AI_STUDIO_URL_CONTEXT", default=False) or payload.get(
        "url_context"
    ):
        tools.append({"urlContext": {}})
    if _bool_env("GOOGLE_AI_STUDIO_CODE_EXECUTION", default=False) or payload.get(
        "code_execution"
    ):
        tools.append({"codeExecution": {}})
    return tools


def _request_tools(payload: dict) -> list[dict]:
    tools = _builtin_tools(payload)
    declarations = _function_declarations(payload)
    if declarations:
        tools.append({"functionDeclarations": declarations})
    return tools


def _tool_config(payload: dict) -> dict | None:
    if not _function_declarations(payload):
        return None
    tool_choice = payload.get("tool_choice")
    if tool_choice is None or tool_choice == "auto":
        return {"functionCallingConfig": {"mode": "AUTO"}}
    if tool_choice == "none":
        return {"functionCallingConfig": {"mode": "NONE"}}
    if tool_choice == "required":
        return {"functionCallingConfig": {"mode": "ANY"}}
    if isinstance(tool_choice, dict):
        function = (
            tool_choice.get("function")
            if isinstance(tool_choice.get("function"), dict)
            else {}
        )
        name = str(function.get("name") or tool_choice.get("name") or "").strip()
        if name:
            return {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [name],
                }
            }
    return {"functionCallingConfig": {"mode": "AUTO"}}


def _request_body(payload: dict) -> dict:
    system_instruction, contents = _messages_to_contents(payload.get("messages") or [])
    if not contents:
        raise RuntimeError("Google AI Studio prompt is empty after normalization")
    body = {
        "contents": contents,
        "generationConfig": _generation_config(payload),
    }
    if system_instruction:
        body["systemInstruction"] = system_instruction
    tools = _request_tools(payload)
    if tools:
        body["tools"] = tools
    tool_config = _tool_config(payload)
    if tool_config:
        body["toolConfig"] = tool_config
    safety_settings = payload.get("safety_settings")
    if isinstance(safety_settings, list):
        body["safetySettings"] = safety_settings
    return body


def _headers(api_key: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
        "x-goog-api-key": api_key,
    }


def _response_error(response, label: str):
    try:
        body = response.text[:800]
    except Exception:
        body = ""
    raise RuntimeError(
        f"Google AI Studio {label} failed: HTTP {response.status_code} {body}".strip()
    )


def _finish_reason(value: str, has_tool_calls: bool = False) -> str:
    if has_tool_calls:
        return "tool_calls"
    normalized = str(value or "stop").strip().lower()
    if normalized in {"max_tokens", "max_output_tokens"}:
        return "length"
    if normalized in {"safety", "blocked"}:
        return "content_filter"
    if normalized in {"stop", "finished_stop"}:
        return "stop"
    return normalized or "stop"


def _tool_call_delta(tool_call: dict, index: int) -> dict:
    function = (
        tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    )
    return {
        "index": index,
        "id": str(tool_call.get("id") or "") or f"call_{uuid.uuid4().hex}",
        "type": "function",
        "function": {
            "name": str(function.get("name") or ""),
            "arguments": str(function.get("arguments") or "{}"),
        },
    }


def _extract_function_call(part: dict) -> dict | None:
    call = part.get("functionCall") or part.get("function_call")
    if not isinstance(call, dict):
        return None
    name = str(call.get("name") or "").strip()
    if not name:
        return None
    args = call.get("args") if "args" in call else call.get("arguments")
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
        except Exception:
            parsed_args = {"input": args}
    elif isinstance(args, dict):
        parsed_args = args
    elif args is None:
        parsed_args = {}
    else:
        parsed_args = {"input": args}
    call_id = str(call.get("id") or "").strip() or f"call_{uuid.uuid4().hex}"
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                parsed_args, ensure_ascii=False, separators=(",", ":")
            ),
        },
    }


def _extract_candidate_content(candidate: dict) -> tuple[str, str, list[dict]]:
    content = candidate.get("content") if isinstance(candidate, dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else []
    text_parts = []
    reasoning_parts = []
    tool_calls = []
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        function_call = _extract_function_call(part)
        if function_call:
            tool_calls.append(function_call)
            continue
        text = str(part.get("text") or "")
        if not text:
            continue
        if part.get("thought") is True:
            reasoning_parts.append(text)
        else:
            text_parts.append(text)
    return "".join(text_parts).strip(), "".join(reasoning_parts).strip(), tool_calls


def _request_model(payload: dict) -> tuple[str, str]:
    request_model = (
        str(payload.get("model") or "google-ai-studio").strip() or "google-ai-studio"
    )
    return request_model, _map_model(request_model)


def _generation_url(upstream_model: str, stream: bool = False) -> str:
    suffix = "streamGenerateContent?alt=sse" if stream else "generateContent"
    return f"{API_BASE}/models/{quote(upstream_model, safe='')}:{suffix}"


def _post_generate(api_key: str, upstream_model: str, body: dict, stream: bool = False):
    response = requests.post(
        _generation_url(upstream_model, stream=stream),
        headers=_headers(api_key),
        json=body,
        timeout=int(os.environ.get("GOOGLE_AI_STUDIO_TIMEOUT_SEC", "180") or "180"),
        stream=stream,
    )
    if response.status_code != 200:
        _response_error(response, "generation")
    return response


def complete_non_stream(credentials: dict, payload: dict):
    api_key = str((credentials or {}).get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("Google AI Studio API key is empty")
    request_model, upstream_model = _request_model(payload)
    body = _request_body(payload)
    response = _post_generate(api_key, upstream_model, body, stream=False)
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Google AI Studio returned no candidates: {data}")
    content, reasoning, tool_calls = _extract_candidate_content(candidates[0])
    if not content and not reasoning and not tool_calls:
        raise RuntimeError("Google AI Studio returned an empty completion")
    message = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    if tool_calls:
        message["content"] = content or ""
        message["tool_calls"] = tool_calls
    usage = (
        data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
    )
    result = {
        "id": f"google-ai-studio-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": _finish_reason(
                    candidates[0].get("finishReason"), bool(tool_calls)
                ),
            }
        ],
        "usage": {
            "prompt_tokens": int(usage.get("promptTokenCount") or 0),
            "completion_tokens": int(usage.get("candidatesTokenCount") or 0),
            "total_tokens": int(usage.get("totalTokenCount") or 0),
        },
    }
    meta = {
        "provider": "google-ai-studio",
        "model": request_model,
        "upstream_model": upstream_model,
        "content_length": len(content),
        "reasoning_length": len(reasoning),
        "tool_call_count": len(tool_calls),
    }
    debug_log("google_ai_studio_done", **meta)
    return result, meta


def _iter_sse_json(response):
    pending = []
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            if pending:
                text = "\n".join(pending).strip()
                pending = []
                if text:
                    yield json.loads(text)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                break
            if data:
                pending.append(data)
    if pending:
        text = "\n".join(pending).strip()
        if text:
            yield json.loads(text)


def stream_chunks(credentials: dict, payload: dict):
    api_key = str((credentials or {}).get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("Google AI Studio API key is empty")
    request_model, upstream_model = _request_model(payload)
    body = _request_body(payload)
    response = _post_generate(api_key, upstream_model, body, stream=True)
    response_id = f"google-ai-studio-{uuid.uuid4().hex}"
    builder = OpenAIStreamBuilder(response_id, request_model)
    tool_calls = []
    finish_reason = "stop"

    try:
        for event in _iter_sse_json(response):
            candidates = event.get("candidates") if isinstance(event, dict) else []
            if not candidates:
                continue
            candidate = candidates[0] if isinstance(candidates[0], dict) else {}
            finish_reason = _finish_reason(candidate.get("finishReason"), False)
            content, reasoning, calls = _extract_candidate_content(candidate)
            for chunk in builder.reasoning(reasoning):
                yield chunk
            for chunk in builder.content(content):
                yield chunk
            if calls:
                tool_calls.extend(calls)
    finally:
        response.close()

    if tool_calls:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk
        yield openai_chunk(
            response_id,
            request_model,
            builder.created,
            {
                "tool_calls": [
                    _tool_call_delta(tool_call, index)
                    for index, tool_call in enumerate(tool_calls)
                ]
            },
        )
        finish_reason = "tool_calls"
    elif not builder.role_sent:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk

    yield builder.finish(finish_reason=finish_reason)
    debug_log(
        "google_ai_studio_stream_done",
        provider="google-ai-studio",
        model=request_model,
        upstream_model=upstream_model,
        tool_call_count=len(tool_calls),
    )


def describe_image_item(
    credentials: dict,
    item: dict,
    context_text: str = "",
    index: int = 1,
) -> str:
    api_key = str((credentials or {}).get("api_key") or "").strip()
    if not api_key:
        return ""
    image_part = _image_item_part(item if isinstance(item, dict) else {})
    if not image_part:
        return ""

    model = (
        os.environ.get(
            "MULTIMODAL_CAPTION_MODEL",
            os.environ.get("GOOGLE_AI_STUDIO_CAPTION_MODEL", "gemini-2.5-flash-lite"),
        ).strip()
        or "gemini-2.5-flash-lite"
    )
    prompt_template = os.environ.get(
        "MULTIMODAL_CAPTION_PROMPT",
        "Describe image {index} for another language model. Include visible objects, people, text, UI elements, layout, colors, and any details needed to answer the user's request. Be factual and concise.",
    )
    prompt = prompt_template.format(index=index)
    if context_text:
        prompt = f"Conversation context:\n{context_text}\n\n{prompt}"

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}, image_part]}],
        "generationConfig": {
            "temperature": float(
                os.environ.get("MULTIMODAL_CAPTION_TEMPERATURE", "0.2") or "0.2"
            ),
            "maxOutputTokens": _int_env(
                "MULTIMODAL_CAPTION_MAX_OUTPUT_TOKENS",
                default=1024,
                minimum=64,
                maximum=8192,
            ),
        },
    }
    response = _post_generate(api_key, _strip_model_prefix(model), body, stream=False)
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    content, reasoning, _tool_calls = _extract_candidate_content(candidates[0])
    return (content or reasoning).strip()
