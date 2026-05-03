import base64
import copy
import hashlib
import json
import os
import re
import sys
import time
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote

JsonDict = dict[str, Any]
JsonList = list[Any]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
except ImportError:
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log


OWNED_BY = "aistudio.google.com"
ORIGIN = "https://aistudio.google.com"
PRIVATE_BASE = os.environ.get(
    "GOOGLE_AI_STUDIO_WEB_PRIVATE_BASE",
    "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService",
).rstrip("/")
DEFAULT_USER_AGENT = os.environ.get(
    "GOOGLE_AI_STUDIO_WEB_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
).strip()
DEFAULT_FRONTEND_API_KEY = os.environ.get(
    "GOOGLE_AI_STUDIO_WEB_DEFAULT_API_KEY", ""
).strip()

MODEL_ALIASES = {
    "google-ai-studio-web": "gemini-3.1-pro-preview",
    "ai-studio-web": "gemini-3.1-pro-preview",
    "ai-studio-web-pro": "gemini-3.1-pro-preview",
    "ai-studio-web-3-pro": "gemini-3.1-pro-preview",
    "ai-studio-web-3-flash": "gemini-3-flash-preview",
    "ai-studio-web-flash": "gemini-2.5-flash",
    "ai-studio-web-lite": "gemini-2.5-flash-lite",
}
DEFAULT_UPSTREAM_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]


def _strip_model_prefix(model: str) -> str:
    value = str(model or "").strip()
    return value[7:] if value.startswith("models/") else value


def _with_model_prefix(model: str) -> str:
    value = _strip_model_prefix(model)
    return value if value.startswith("models/") else f"models/{value}"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _int_env(
    name: str, default: int, minimum: int = 1, maximum: int = 100_000_000
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _configured_models() -> list[str]:
    raw = os.environ.get("GOOGLE_AI_STUDIO_WEB_MODELS", "").strip()
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
                        item.get("id") or item.get("model") or item.get("name") or ""
                    ).strip()
                else:
                    value = ""
                if value:
                    models.append(_strip_model_prefix(value))
    if not models:
        models = list(DEFAULT_UPSTREAM_MODELS)

    exposed = list(MODEL_ALIASES.keys())
    if _bool_env("GOOGLE_AI_STUDIO_WEB_EXPOSE_RAW_MODELS", default=False):
        exposed.extend(models)
        exposed.extend(f"models/{model}" for model in models)

    ordered = []
    seen = set()
    for model in exposed:
        lowered = str(model or "").lower()
        if lowered and lowered not in seen:
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
    value = str(model or "google-ai-studio-web").strip() or "google-ai-studio-web"
    lowered = value.lower()
    if lowered in MODEL_ALIASES:
        return _with_model_prefix(MODEL_ALIASES[lowered])
    return _with_model_prefix(value)


def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
    parsed = SimpleCookie()
    if cookie_header:
        try:
            parsed.load(cookie_header)
        except Exception:
            parsed = SimpleCookie()
    return {
        str(morsel.key): str(morsel.value)
        for morsel in parsed.values()
        if morsel.key and morsel.value
    }


def _cookie_header_from_values(values: dict[str, str]) -> str:
    return "; ".join(
        f"{name}={value}" for name, value in values.items() if name and value
    )


def _credentials_cookie_values(credentials: JsonDict) -> dict[str, str]:
    cookie = str((credentials or {}).get("cookie") or "").strip()
    values = _parse_cookie_header(cookie)
    aliases = {
        "SAPISID": ["sapisid", "SAPISID"],
        "__Secure-1PAPISID": ["secure_1papisid", "__Secure-1PAPISID"],
        "__Secure-3PAPISID": ["secure_3papisid", "__Secure-3PAPISID"],
        "__Secure-1PSID": ["secure_1psid", "__Secure-1PSID"],
        "__Secure-3PSID": ["secure_3psid", "__Secure-3PSID"],
        "__Secure-1PSIDTS": ["secure_1psidts", "__Secure-1PSIDTS"],
        "__Secure-3PSIDTS": ["secure_3psidts", "__Secure-3PSIDTS"],
    }
    for cookie_name, keys in aliases.items():
        if values.get(cookie_name):
            continue
        for key in keys:
            value = str((credentials or {}).get(key) or "").strip()
            if value:
                values[cookie_name] = value
                break
    return values


def _auth_digest(timestamp: str, cookie_value: str) -> str:
    return hashlib.sha1(
        f"{timestamp} {cookie_value} {ORIGIN}".encode("utf-8")
    ).hexdigest()


def _auth_header(credentials: JsonDict, cookie_values: dict[str, str]) -> str:
    explicit = str((credentials or {}).get("authorization") or "").strip()
    if explicit:
        return explicit
    timestamp = str(int(time.time()))
    pieces = []
    for label, name in (
        ("SAPISIDHASH", "SAPISID"),
        ("SAPISID1PHASH", "__Secure-1PAPISID"),
        ("SAPISID3PHASH", "__Secure-3PAPISID"),
    ):
        value = cookie_values.get(name) or cookie_values.get("SAPISID") or ""
        if not value:
            continue
        pieces.append(f"{label} {timestamp}_{_auth_digest(timestamp, value)}")
    if not pieces:
        raise RuntimeError(
            "Google AI Studio Web cookie is missing SAPISID / __Secure-*PAPISID values"
        )
    return " ".join(pieces)


def _parse_headers_json(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items() if v is not None}
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return {str(k): str(v) for k, v in parsed.items() if v is not None}
    return {}


def _generated_visit_id() -> str:
    encoded = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode("ascii").rstrip("=")
    return f"v1_{encoded}"


def _rpc_headers(
    credentials: JsonDict, cookie_values: dict[str, str], *, include_cookie: bool = True
) -> dict[str, str]:
    captured_headers = _parse_headers_json((credentials or {}).get("headers"))
    headers = {
        "Accept": "*/*",
        "Accept-Language": str(
            (credentials or {}).get("accept_language")
            or os.environ.get("GOOGLE_AI_STUDIO_WEB_ACCEPT_LANGUAGE", "en-US,en;q=0.9")
        ),
        "Content-Type": "application/json+protobuf",
        "Origin": ORIGIN,
        "Referer": ORIGIN + "/",
        "User-Agent": DEFAULT_USER_AGENT,
        "x-goog-authuser": str(
            (credentials or {}).get("authuser")
            or captured_headers.get("x-goog-authuser")
            or "0"
        ),
        "x-user-agent": str(
            (credentials or {}).get("x_user_agent")
            or captured_headers.get("x-user-agent")
            or "grpc-web-javascript/0.1"
        ),
    }
    headers.update(
        {
            key: value
            for key, value in captured_headers.items()
            if key.lower() not in {"content-length", "host", "cookie", "authorization"}
        }
    )
    api_key = str(
        (credentials or {}).get("api_key")
        or captured_headers.get("x-goog-api-key")
        or DEFAULT_FRONTEND_API_KEY
    ).strip()
    if api_key:
        headers["x-goog-api-key"] = api_key
    visit_id = str(
        (credentials or {}).get("visit_id")
        or captured_headers.get("x-aistudio-visit-id")
        or ""
    ).strip()
    if not visit_id and _bool_env(
        "GOOGLE_AI_STUDIO_WEB_GENERATE_VISIT_ID", default=True
    ):
        visit_id = _generated_visit_id()
    if visit_id:
        headers["x-aistudio-visit-id"] = visit_id
    ext_header = str(
        (credentials or {}).get("ext_519733851_bin")
        or captured_headers.get("x-goog-ext-519733851-bin")
        or ""
    ).strip()
    if ext_header:
        headers["x-goog-ext-519733851-bin"] = ext_header
    headers["Authorization"] = _auth_header(credentials, cookie_values)
    if include_cookie:
        headers["Cookie"] = _cookie_header_from_values(cookie_values)
    return headers


def _bootstrap(
    session: requests.Session, credentials: JsonDict, cookie_values: dict[str, str]
):
    if not _bool_env("GOOGLE_AI_STUDIO_WEB_BOOTSTRAP", default=True):
        return None
    path = (
        str(
            (credentials or {}).get("bootstrap_path")
            or os.environ.get("GOOGLE_AI_STUDIO_WEB_BOOTSTRAP_PATH", "/")
        ).strip()
        or "/"
    )
    url = (
        path
        if path.startswith("http")
        else ORIGIN + (path if path.startswith("/") else f"/{path}")
    )
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": os.environ.get(
            "GOOGLE_AI_STUDIO_WEB_ACCEPT_LANGUAGE", "en-US,en;q=0.9"
        ),
        "Cookie": _cookie_header_from_values(cookie_values),
        "Referer": ORIGIN + "/",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    try:
        response = session.get(
            url,
            headers=headers,
            timeout=_int_env("GOOGLE_AI_STUDIO_WEB_BOOTSTRAP_TIMEOUT_SEC", 30, 5, 120),
        )
        debug_log(
            "google_ai_studio_web_bootstrap",
            status=response.status_code,
            length=len(response.text or ""),
        )
        return response
    except Exception as exc:
        debug_log("google_ai_studio_web_bootstrap_error", error=type(exc).__name__)
        return None


def _new_session(credentials: JsonDict):
    session = requests.Session()
    cookie_values = _credentials_cookie_values(credentials)
    for name, value in cookie_values.items():
        session.cookies.set(name, value, domain=".google.com", path="/")
    return session, cookie_values


def _rpc_url(name: str) -> str:
    return f"{PRIVATE_BASE}/{quote(name, safe='')}"


def _post_rpc(
    session: requests.Session,
    credentials: JsonDict,
    cookie_values: dict[str, str],
    name: str,
    body_text: str,
):
    response = session.post(
        _rpc_url(name),
        headers=_rpc_headers(credentials, cookie_values),
        data=str(body_text or "").encode("utf-8"),
        timeout=_int_env("GOOGLE_AI_STUDIO_WEB_TIMEOUT_SEC", 180, 10, 600),
    )
    if response.status_code != 200:
        _raise_response_error(response, name)
    return response


def _response_preview(response) -> str:
    try:
        return (response.text or "")[:800]
    except Exception:
        return ""


def _raise_response_error(response, label: str):
    preview = _response_preview(response)
    hint = ""
    if response.status_code == 401:
        hint = " Cookie/SAPISID auth was rejected; refresh GOOGLE_AI_STUDIO_WEB_COOKIE from a live AI Studio browser session."
    elif response.status_code == 403:
        hint = " AI Studio web GenerateContent is protected by a browser capability/attestation blob; refresh GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE from a matching live request."
    raise RuntimeError(
        f"Google AI Studio Web {label} failed: HTTP {response.status_code} {preview}{hint}".strip()
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            if item_type in {"text", "input_text", "output_text"}:
                text = str(item.get("text") or "")
                if text:
                    parts.append(text)
                continue
            if item_type in {"image_url", "input_image"}:
                image = item.get("image_url")
                if isinstance(image, dict):
                    image = image.get("url")
                image = image or item.get("file_url") or item.get("file_id")
                parts.append(f"[image: {image}]" if image else "[image]")
                continue
            if item_type in {"input_file", "file"}:
                filename = item.get("filename") or item.get("name") or "file"
                file_ref = (
                    item.get("file_url")
                    or item.get("file_id")
                    or item.get("file_data")
                    or ""
                )
                parts.append(f"[file: {filename}] {str(file_ref)[:200]}".strip())
                continue
        return "\n".join(part for part in parts if part)
    return str(content)


def _private_contents(messages: JsonList) -> JsonList:
    contents = []
    system_parts = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip().lower()
        text = _content_text(message.get("content")).strip()
        if not text:
            continue
        if role in {"system", "developer"}:
            system_parts.append(text)
            continue
        if system_parts:
            text = "System:\n" + "\n\n".join(system_parts) + "\n\n" + text
            system_parts = []
        private_role = "model" if role == "assistant" else "user"
        if role in {"tool", "function"}:
            private_role = "user"
            text = f"Tool result:\n{text}"
        contents.append([[[None, text]], private_role])
    if system_parts:
        contents.insert(0, [[[None, "System:\n" + "\n\n".join(system_parts)]], "user"])
    return contents


def _prompt_texts(contents: JsonList) -> set[str]:
    texts = set()
    for item in contents or []:
        try:
            text = item[0][0][1]
        except Exception:
            text = ""
        if text:
            texts.add(str(text))
    return texts


def _count_tokens_body(payload: JsonDict, upstream_model: str) -> str:
    contents = _private_contents(payload.get("messages") or [])
    if not contents:
        raise RuntimeError("Google AI Studio Web prompt is empty after normalization")
    body = [upstream_model, contents]
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _parse_count_tokens_response(data: Any) -> int:
    if isinstance(data, list) and data and isinstance(data[0], int):
        return int(data[0])
    found = []

    def walk(value):
        if isinstance(value, int):
            found.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(data)
    return int(found[0]) if found else 0


def count_tokens(credentials: JsonDict, payload: JsonDict) -> int:
    upstream_model = _map_model(payload.get("model") or "google-ai-studio-web")
    session, cookie_values = _new_session(credentials)
    try:
        _bootstrap(session, credentials, cookie_values)
        response = _post_rpc(
            session,
            credentials,
            cookie_values,
            "CountTokens",
            _count_tokens_body(payload, upstream_model),
        )
        return _parse_count_tokens_response(response.json())
    finally:
        session.close()


def _raw_template_value(credentials: JsonDict):
    for key in ("generate_template", "generate_body", "template", "generate_fetch"):
        value = (credentials or {}).get(key)
        if value:
            return value
    for name in (
        "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE",
        "GOOGLE_AI_STUDIO_WEB_GENERATE_BODY",
        "GOOGLE_AI_STUDIO_WEB_TEMPLATE",
        "GOOGLE_AI_STUDIO_WEB_GENERATE_FETCH",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    template_file = str(
        (credentials or {}).get("generate_template_file")
        or os.environ.get("GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE_FILE", "")
    ).strip()
    if template_file:
        path = Path(template_file)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _parse_json_maybe_nested(value: str):
    parsed = json.loads(value)
    if isinstance(parsed, str):
        stripped = parsed.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            return json.loads(stripped)
    return parsed


def _extract_template_from_fetch(text: str):
    match = re.search(r'"body"\s*:\s*("(?:\\.|[^"\\])*")', text, re.S)
    if match:
        body_text = json.loads(match.group(1))
        return _parse_json_maybe_nested(body_text)
    return None


def _generate_template(credentials: JsonDict) -> JsonList:
    raw_value = _raw_template_value(credentials)
    if isinstance(raw_value, (list, dict)):
        raw = json.dumps(raw_value, ensure_ascii=False, separators=(",", ":"))
    else:
        raw = str(raw_value or "").strip()
    if not raw:
        raise RuntimeError(
            "Google AI Studio Web GenerateContent requires "
            "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE or "
            "x-google-ai-studio-web-generate-template. CountTokens can work with "
            "cookies alone, but generation needs the browser-captured "
            "capability/attestation body."
        )
    try:
        parsed = _parse_json_maybe_nested(raw)
    except Exception:
        parsed = _extract_template_from_fetch(raw)
    if isinstance(parsed, dict):
        for key in ("body", "template", "generate_body", "generate_template"):
            if key in parsed:
                value = parsed[key]
                if isinstance(value, list):
                    parsed = value
                elif isinstance(value, str):
                    parsed = _parse_json_maybe_nested(value)
                break
    if not isinstance(parsed, list) or len(parsed) < 5:
        raise RuntimeError(
            "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE is not a valid AI Studio GenerateContent array body"
        )
    if not isinstance(parsed[4], str) or not parsed[4].strip():
        raise RuntimeError(
            "AI Studio GenerateContent template is missing slot 4 capability blob"
        )
    return parsed


def _maybe_override_config(body: JsonList, payload: JsonDict):
    if not _bool_env("GOOGLE_AI_STUDIO_WEB_OVERRIDE_TEMPLATE_CONFIG", default=False):
        return
    config = body[3] if len(body) > 3 and isinstance(body[3], list) else None
    if not config:
        return
    max_tokens = (
        payload.get("max_output_tokens")
        or payload.get("max_completion_tokens")
        or payload.get("max_tokens")
    )
    if max_tokens is not None and len(config) > 3:
        try:
            config[3] = int(max_tokens)
        except Exception:
            pass
    top_p = payload.get("top_p")
    if top_p is not None and len(config) > 5:
        try:
            config[5] = float(top_p)
        except Exception:
            pass


def _generate_body(
    credentials: JsonDict, payload: JsonDict, upstream_model: str
) -> tuple[str, set[str]]:
    template = _generate_template(credentials)
    body = copy.deepcopy(template)
    contents = _private_contents(payload.get("messages") or [])
    if not contents:
        raise RuntimeError("Google AI Studio Web prompt is empty after normalization")
    if not _bool_env("GOOGLE_AI_STUDIO_WEB_EXACT_TEMPLATE", default=False):
        body[0] = upstream_model
        body[1] = contents
        _maybe_override_config(body, payload)
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")), _prompt_texts(
        contents
    )


def _extract_strings(value: Any, out: list[str]):
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for item in value:
            _extract_strings(item, out)
    elif isinstance(value, dict):
        for item in value.values():
            _extract_strings(item, out)


def _extract_generated_text(data: Any, prompt_texts: set[str]) -> str:
    strings = []
    _extract_strings(data, strings)
    seen = set()
    useful = []
    for value in strings:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        lowered = text.lower()
        if text in prompt_texts or lowered in {"user", "model", "assistant"}:
            continue
        if lowered.startswith("models/") or lowered.startswith("http"):
            continue
        if len(text) > 1000 and text.startswith("!"):
            continue
        if "type.googleapis.com/google.rpc" in text:
            continue
        useful.append(text)
    if not useful:
        return ""
    if len(useful) == 1:
        return useful[0]
    # The private protobuf-json response is not stable; prefer later text leaves but keep short lists readable.
    return "\n".join(useful[-3:]).strip()


def complete_non_stream(
    credentials: JsonDict, payload: JsonDict
) -> tuple[JsonDict, JsonDict]:
    request_model = (
        str(payload.get("model") or "google-ai-studio-web").strip()
        or "google-ai-studio-web"
    )
    upstream_model = _map_model(request_model)
    session, cookie_values = _new_session(credentials)
    prompt_tokens = 0
    try:
        _bootstrap(session, credentials, cookie_values)
        if _bool_env("GOOGLE_AI_STUDIO_WEB_COUNT_TOKENS_FOR_USAGE", default=True):
            try:
                token_response = _post_rpc(
                    session,
                    credentials,
                    cookie_values,
                    "CountTokens",
                    _count_tokens_body(payload, upstream_model),
                )
                prompt_tokens = _parse_count_tokens_response(token_response.json())
            except Exception as exc:
                debug_log(
                    "google_ai_studio_web_count_tokens_error", error=type(exc).__name__
                )
        body_text, prompt_texts = _generate_body(credentials, payload, upstream_model)
        response = _post_rpc(
            session, credentials, cookie_values, "GenerateContent", body_text
        )
        data = response.json()
        content = _extract_generated_text(data, prompt_texts)
        if not content:
            raise RuntimeError(
                f"Google AI Studio Web returned no extractable text: {str(data)[:800]}"
            )
        response_id = f"aistudio-web-{uuid.uuid4()}"
        result = {
            "id": response_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": 0,
                "total_tokens": int(prompt_tokens or 0),
            },
        }
        return result, {
            "provider": "google-ai-studio-web",
            "model": request_model,
            "upstream_model": upstream_model,
            "content_length": len(content),
            "prompt_tokens": int(prompt_tokens or 0),
            "experimental": True,
        }
    finally:
        session.close()


def stream_chunks(credentials: JsonDict, payload: JsonDict):
    result, _meta = complete_non_stream(credentials, payload)
    created_value = result.get("created")
    try:
        created = int(created_value) if created_value is not None else int(time.time())
    except Exception:
        created = int(time.time())
    response_id = str(result.get("id") or f"aistudio-web-{uuid.uuid4()}")
    model = str(result.get("model") or payload.get("model") or "google-ai-studio-web")
    choices_value = result.get("choices")
    choices = choices_value if isinstance(choices_value, list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message_value = first_choice.get("message")
    message = message_value if isinstance(message_value, dict) else {}
    builder = OpenAIStreamBuilder(response_id, model)
    builder.created = created
    content = str(message.get("content") or "")
    if content:
        for chunk in builder.content(content):
            yield chunk
    else:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk
    yield builder.finish(finish_reason="stop")
