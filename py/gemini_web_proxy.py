import json
import os
import random
import re
import sys
import time
import uuid
from collections import OrderedDict
from http.cookies import SimpleCookie

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))

try:
    from curl_cffi import requests as curl_requests
except Exception:
    curl_requests = None

import requests

try:
    from py.zai_proxy import debug_log
except ImportError:
    from zai_proxy import debug_log


OWNED_BY = "gemini.google.com"
INIT_URL = "https://gemini.google.com/app"
BATCH_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"
GENERATE_URL = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
MODEL_HEADER_KEY = "x-goog-ext-525001261-jspb"
DEFAULT_USER_AGENT = os.environ.get(
    "GEMINI_WEB_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
).strip()
DEFAULT_METADATA = ["", "", "", None, None, None, None, None, None, ""]
FRAME_PREFIX = ")]}'"
FRAME_PATTERN = re.compile(r"(\d+)\n")
CARD_CONTENT_RE = re.compile(r"^http://googleusercontent\.com/card_content/\d+")
ARTIFACTS_RE = re.compile(r"http://googleusercontent\.com/\w+/\d+\n*")

KNOWN_MODELS = [
    {
        "id": "gemini-3-flash",
        "model_id": "fbb127bbb056c959",
        "display_name": "Flash",
        "description": "Default Gemini Web flash model.",
        "capacity": 1,
        "capacity_field": 12,
    },
    {
        "id": "gemini-3-pro",
        "model_id": "9d8ca3786ebdfbea",
        "display_name": "Pro",
        "description": "Default Gemini Web pro model.",
        "capacity": 1,
        "capacity_field": 12,
    },
    {
        "id": "gemini-3-flash-thinking",
        "model_id": "5bf011840784117a",
        "display_name": "Thinking",
        "description": "Default Gemini Web thinking model.",
        "capacity": 1,
        "capacity_field": 12,
    },
]
MODEL_ALIASES = {
    "gemini-web": "gemini-3-flash",
    "gemini-web-fast": "gemini-3-flash",
    "gemini-web-pro": "gemini-3-pro",
    "gemini-web-thinking": "gemini-3-flash-thinking",
}
KNOWN_MODEL_IDS = {entry["model_id"]: entry["id"] for entry in KNOWN_MODELS}


def build_model_header(model_id: str, capacity: int, capacity_field: int) -> dict:
    if capacity_field == 13:
        tail = f"null,{capacity}"
    else:
        tail = str(capacity)
    return {
        MODEL_HEADER_KEY: f'[1,null,null,null,"{model_id}",null,null,0,[4],null,null,{tail}]',
        "x-goog-ext-73010989-jspb": "[0]",
        "x-goog-ext-73010990-jspb": "[0]",
    }


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "gemini-web-model"


def _dedupe_models(entries) -> list:
    ordered = []
    seen = set()
    for entry in entries or []:
        model_id = str((entry or {}).get("id") or "").strip()
        if not model_id:
            continue
        lowered = model_id.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(entry)
    return ordered


def _known_entry_map() -> dict:
    result = {}
    for entry in KNOWN_MODELS:
        model_id = entry["id"].lower()
        result[model_id] = dict(entry)
    return result


def configured_model_entries() -> list:
    raw = os.environ.get("GEMINI_WEB_MODELS", "").strip()
    parsed_entries = []
    known = _known_entry_map()

    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            if raw.lstrip().startswith("[") or raw.lstrip().startswith("{"):
                payload = []
            else:
                payload = [item.strip() for item in raw.split(",") if item.strip()]

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, str):
                    known_entry = known.get(item.strip().lower())
                    if known_entry:
                        parsed_entries.append(known_entry)
                    else:
                        parsed_entries.append({"id": item.strip(), "display_name": item.strip(), "description": ""})
                    continue

                if not isinstance(item, dict):
                    continue

                identifier = str(
                    item.get("id")
                    or item.get("slug")
                    or item.get("model_name")
                    or item.get("display_name")
                    or ""
                ).strip()
                if not identifier:
                    continue

                entry = {
                    "id": identifier,
                    "display_name": str(item.get("display_name") or identifier),
                    "description": str(item.get("description") or ""),
                    "model_id": str(item.get("model_id") or "").strip(),
                    "capacity": int(item.get("capacity") or 1),
                    "capacity_field": int(item.get("capacity_field") or 12),
                    "header": item.get("header") if isinstance(item.get("header"), dict) else None,
                }
                if not entry["header"] and entry["model_id"]:
                    entry["header"] = build_model_header(entry["model_id"], entry["capacity"], entry["capacity_field"])
                parsed_entries.append(entry)

    if not parsed_entries:
        parsed_entries = [dict(entry) for entry in KNOWN_MODELS]

    with_aliases = []
    for alias, target in MODEL_ALIASES.items():
        target_entry = next((entry for entry in parsed_entries if str(entry.get("id") or "").lower() == target.lower()), None)
        if not target_entry:
            target_entry = _known_entry_map().get(target.lower())
        if target_entry:
            alias_entry = dict(target_entry)
            alias_entry["id"] = alias
            alias_entry["display_name"] = alias
            with_aliases.append(alias_entry)

    return _dedupe_models(with_aliases + parsed_entries)


SUPPORTED_MODELS = [entry["id"] for entry in configured_model_entries()]


def supports_model(model: str) -> bool:
    lowered = str(model or "").strip().lower()
    if not lowered:
        return False
    if lowered in MODEL_ALIASES:
        return True
    return any(lowered == str(entry.get("id") or "").strip().lower() for entry in configured_model_entries())


def _model_entry_for(request_model: str):
    lowered = str(request_model or "").strip().lower()
    if lowered in MODEL_ALIASES:
        lowered = MODEL_ALIASES[lowered].lower()
    for entry in configured_model_entries():
        if lowered == str(entry.get("id") or "").strip().lower():
            return dict(entry)
    return None


def _proxy_disabled() -> bool:
    return os.environ.get("GEMINI_WEB_NO_SYSTEM_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}


def _normalized_proxy_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        return f"http://{text}"
    return text


def _proxy_from_env() -> str:
    for name in ["GEMINI_WEB_PROXY", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"]:
        value = _normalized_proxy_url(os.environ.get(name, ""))
        if value:
            return value
    return ""


def _proxy_from_windows_internet_settings() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except Exception:
        return ""

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    except Exception:
        return ""

    if not enabled or not server:
        return ""

    if "=" not in server:
        return _normalized_proxy_url(server)

    parts = {}
    for item in server.split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        parts[name.strip().lower()] = value.strip()
    for key in ["https", "http", "socks", "socks5"]:
        value = _normalized_proxy_url(parts.get(key, ""))
        if value:
            return value
    return ""


def _proxy_url() -> str:
    if _proxy_disabled():
        return ""
    explicit = _proxy_from_env()
    if explicit:
        return explicit
    return _proxy_from_windows_internet_settings()


def _new_session(use_curl: bool = True):
    proxy_url = _proxy_url()
    if use_curl and curl_requests is not None:
        return curl_requests.Session(
            impersonate=os.environ.get("GEMINI_WEB_IMPERSONATE", "chrome136"),
            proxy=proxy_url or None,
            timeout=120,
            verify=not _skip_tls_verify(),
        )
    session = requests.Session()
    session.verify = not _skip_tls_verify()
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


def _skip_tls_verify() -> bool:
    return os.environ.get("GEMINI_WEB_SKIP_TLS_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}


def _transport_name(use_curl: bool) -> str:
    return "curl_cffi" if use_curl and curl_requests is not None else "requests"


def _base_headers() -> dict:
    return {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "User-Agent": DEFAULT_USER_AGENT,
    }


def _morsel_value(parsed: SimpleCookie, name: str) -> str:
    morsel = parsed.get(name)
    if not morsel:
        return ""
    return str(morsel.value or "").strip()


def _set_cookie_values(session, credentials: dict):
    cookie_header = str((credentials or {}).get("cookie") or "").strip()
    parsed = SimpleCookie()
    if cookie_header:
        try:
            parsed.load(cookie_header)
        except Exception:
            parsed = SimpleCookie()

    secure_1psid = str((credentials or {}).get("secure_1psid") or _morsel_value(parsed, "__Secure-1PSID") or "").strip()
    secure_1psidts = str((credentials or {}).get("secure_1psidts") or _morsel_value(parsed, "__Secure-1PSIDTS") or "").strip()

    if secure_1psid:
        session.cookies.set("__Secure-1PSID", secure_1psid, domain=".google.com", path="/")
    if secure_1psidts:
        session.cookies.set("__Secure-1PSIDTS", secure_1psidts, domain=".google.com", path="/")

    for morsel in parsed.values():
        name = str(morsel.key or "").strip()
        value = str(morsel.value or "").strip()
        if name and value:
            session.cookies.set(name, value, domain=".google.com", path="/")


def _perform_request(session, method: str, url: str, *, use_curl: bool, **kwargs):
    response = session.request(method, url, **kwargs)
    if response.status_code == 403 and use_curl and curl_requests is not None:
        response.close()
        session.close()
        session = _new_session(use_curl=False)
        response = session.request(method, url, **kwargs)
        return session, response, False
    return session, response, use_curl


def _bootstrap(credentials: dict):
    session = _new_session(use_curl=True)
    use_curl = True
    _set_cookie_values(session, credentials)
    try:
        try:
            session, _warm, use_curl = _perform_request(
                session,
                "GET",
                "https://www.google.com",
                use_curl=use_curl,
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=20,
                allow_redirects=True,
            )
            _warm.close()
        except Exception:
            pass

        session, response, use_curl = _perform_request(
            session,
            "GET",
            INIT_URL,
            use_curl=use_curl,
            headers=_base_headers(),
            timeout=30,
            allow_redirects=True,
        )
        if response.status_code != 200:
            preview = response.text[:300] if hasattr(response, "text") else ""
            raise RuntimeError(f"Gemini Web init failed: HTTP {response.status_code} {preview}")

        text = response.text
        access_token = _capture_value(text, "SNlM0e")
        if not access_token:
            raise RuntimeError("Gemini Web init page does not contain SNlM0e; cookies may be missing or expired")

        state = {
            "access_token": access_token,
            "build_label": _capture_value(text, "cfb2h"),
            "session_id": _capture_value(text, "FdrFJe"),
            "language": _capture_value(text, "TuX5cc") or "en",
            "push_id": _capture_value(text, "qKIAYe"),
            "use_curl": use_curl,
        }
        debug_log("gemini_web_bootstrap", transport=_transport_name(use_curl), language=state["language"])
        return session, state
    except Exception:
        session.close()
        raise


def _capture_value(text: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}":\s*"(.*?)"', str(text or ""))
    return match.group(1) if match else ""


def _request_params(state: dict, *, source_path: str = "") -> dict:
    params = {
        "hl": str(state.get("language") or "en"),
        "_reqid": random.randint(10000, 99999),
        "rt": "c",
    }
    if source_path:
        params["source-path"] = source_path
    if state.get("build_label"):
        params["bl"] = state["build_label"]
    if state.get("session_id"):
        params["f.sid"] = state["session_id"]
    return params


def _serialize_rpc(rpcid: str, payload: str, identifier: str = "generic") -> list:
    return [rpcid, payload, None, identifier]


def _batch_execute(session, state: dict, rpcid: str, payload: str) -> str:
    headers = {
        **_base_headers(),
        MODEL_HEADER_KEY: "[1,null,null,null,null,null,null,null,[4]]",
        "x-goog-ext-73010989-jspb": "[0]",
        "X-Same-Domain": "1",
    }
    response = session.post(
        BATCH_URL,
        params=_request_params(state, source_path="/app"),
        headers=headers,
        data={
            "at": state["access_token"],
            "f.req": json.dumps([[_serialize_rpc(rpcid, payload)]]),
        },
        timeout=30,
    )
    if response.status_code != 200:
        preview = response.text[:300] if hasattr(response, "text") else ""
        raise RuntimeError(f"Gemini Web batch execute failed: HTTP {response.status_code} {preview}")
    return response.text


def _get_char_count_for_utf16_units(text: str, start_idx: int, units_needed: int) -> tuple:
    count = 0
    units = 0
    while units < units_needed and start_idx + count < len(text):
        char = text[start_idx + count]
        char_units = 2 if ord(char) > 0xFFFF else 1
        if units + char_units > units_needed:
            break
        units += char_units
        count += 1
    return count, units


def _parse_response_frames(text: str) -> tuple:
    parsed = []
    cursor = 0
    total_len = len(text)

    while cursor < total_len:
        while cursor < total_len and text[cursor].isspace():
            cursor += 1
        if cursor >= total_len:
            break

        match = FRAME_PATTERN.match(text, pos=cursor)
        if not match:
            break

        length_text = match.group(1)
        length_units = int(length_text)
        start = match.start() + len(length_text)
        char_count, units_found = _get_char_count_for_utf16_units(text, start, length_units)
        if units_found < length_units:
            break

        end = start + char_count
        chunk = text[start:end].strip()
        cursor = end
        if not chunk:
            continue

        try:
            decoded = json.loads(chunk)
        except Exception:
            continue

        if isinstance(decoded, list):
            parsed.extend(decoded)
        else:
            parsed.append(decoded)

    return parsed, text[cursor:]


def _extract_json_frames(text: str) -> list:
    content = str(text or "")
    if content.startswith(FRAME_PREFIX):
        content = content[len(FRAME_PREFIX) :].lstrip()
    frames, remainder = _parse_response_frames(content)
    if frames:
        return frames
    stripped = (content + remainder).strip()
    if not stripped:
        return []
    decoded = json.loads(stripped)
    return decoded if isinstance(decoded, list) else [decoded]


def _nested_value(data, path, default=None):
    current = data
    for key in path:
        if isinstance(key, int):
            if not isinstance(current, list) or key < -len(current) or key >= len(current):
                return default
            current = current[key]
            continue
        if isinstance(key, str):
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
            continue
        return default
    return default if current is None else current


def _compute_capacity(tier_flags, capability_flags) -> tuple:
    tier_flags = tier_flags if isinstance(tier_flags, list) else []
    capability_flags = capability_flags if isinstance(capability_flags, list) else []

    if 21 in tier_flags:
        return 1, 13
    if 22 in tier_flags:
        return 2, 13
    if 115 in capability_flags:
        return 4, 12
    if 16 in tier_flags or 106 in capability_flags:
        return 3, 12
    if 8 in tier_flags or (106 not in capability_flags and 19 in capability_flags):
        return 2, 12
    return 1, 12


def _model_id_to_name(model_id: str, display_name: str) -> str:
    if model_id in KNOWN_MODEL_IDS:
        return KNOWN_MODEL_IDS[model_id]
    display_slug = _slugify(display_name)
    if display_slug.startswith("gemini-"):
        return display_slug
    return f"gemini-web-{display_slug or model_id}"


def discover_models(credentials: dict) -> list:
    session, state = _bootstrap(credentials)
    try:
        response_text = _batch_execute(session, state, "otAQ7b", "[]")
        response_json = _extract_json_frames(response_text)
        discovered = []
        for part in response_json:
            body_text = _nested_value(part, [2], "")
            if not body_text:
                continue
            body = json.loads(body_text)
            models_list = _nested_value(body, [15], [])
            if not isinstance(models_list, list):
                continue
            capacity, capacity_field = _compute_capacity(_nested_value(body, [16], []), _nested_value(body, [17], []))
            for model_data in models_list:
                if not isinstance(model_data, list):
                    continue
                model_id = str(_nested_value(model_data, [0], "") or "").strip()
                display_name = str(_nested_value(model_data, [1], "") or "").strip()
                description = str(_nested_value(model_data, [2], "") or "").strip()
                if not model_id:
                    continue
                discovered.append(
                    {
                        "id": _model_id_to_name(model_id, display_name or model_id),
                        "model_id": model_id,
                        "display_name": display_name or model_id,
                        "description": description,
                        "capacity": capacity,
                        "capacity_field": capacity_field,
                        "header": build_model_header(model_id, capacity, capacity_field),
                    }
                )
        return _dedupe_models(discovered)
    finally:
        session.close()


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
    conversation_parts = []
    for message in messages or []:
        role = str((message or {}).get("role") or "user").strip().lower()
        text = _text_from_content((message or {}).get("content"))
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

    parts = []
    if system_parts:
        parts.append("System:\n" + "\n\n".join(system_parts))
    if conversation_parts:
        parts.append("\n\n".join(conversation_parts))
    return "\n\n".join(parts).strip()


def _resolve_model_entry(credentials: dict, request_model: str):
    entry = _model_entry_for(request_model)
    if entry and entry.get("header"):
        return entry

    if entry and entry.get("model_id"):
        entry["header"] = build_model_header(entry["model_id"], int(entry.get("capacity") or 1), int(entry.get("capacity_field") or 12))
        return entry

    if not credentials:
        return entry

    for live_entry in discover_models(credentials):
        if str(live_entry.get("id") or "").lower() == str(request_model or "").strip().lower():
            return live_entry
    return entry


def _request_body(prompt: str, language: str, temporary: bool) -> tuple:
    request_id = str(uuid.uuid4()).upper()
    inner = [None] * 69
    inner[0] = [prompt, 0, None, None, None, None, 0]
    inner[1] = [language]
    inner[2] = list(DEFAULT_METADATA)
    inner[6] = [1]
    inner[7] = 1
    inner[10] = 1
    inner[11] = 0
    inner[17] = [[0]]
    inner[18] = 0
    inner[27] = 1
    inner[30] = [4]
    inner[41] = [1]
    if temporary:
        inner[45] = 1
    inner[53] = 0
    inner[59] = request_id
    inner[61] = []
    inner[68] = 2
    return request_id, inner


def _error_from_code(code: int, request_model: str) -> str:
    mapping = {
        1013: "Gemini Web returned temporary error 1013",
        1037: f"Gemini Web usage limit exceeded for model '{request_model}'",
        1050: f"Gemini Web rejected model '{request_model}' as inconsistent",
        1052: f"Gemini Web model '{request_model}' is unavailable or the model header is invalid",
        1060: "Gemini Web rejected this account, region, or IP (status 1060)",
    }
    return mapping.get(int(code), f"Gemini Web returned API error code {code}")


def _parse_generation_payload(text: str, request_model: str) -> tuple:
    frames = _extract_json_frames(text)
    cid = ""
    rid = ""
    candidates = OrderedDict()

    for part in frames:
        error_code = _nested_value(part, [5, 2, 0, 1, 0])
        if error_code:
            raise RuntimeError(_error_from_code(int(error_code), request_model))

        inner_text = _nested_value(part, [2], "")
        if not inner_text:
            continue

        try:
            inner = json.loads(inner_text)
        except Exception:
            continue

        metadata = _nested_value(inner, [1], [])
        if isinstance(metadata, list):
            cid = str(_nested_value(metadata, [0], cid) or cid)
            rid = str(_nested_value(metadata, [1], rid) or rid)

        for index, candidate_data in enumerate(_nested_value(inner, [4], []) or []):
            if not isinstance(candidate_data, list):
                continue
            rcid = str(_nested_value(candidate_data, [0], "") or f"idx-{index}")
            content = str(_nested_value(candidate_data, [1, 0], "") or "")
            if CARD_CONTENT_RE.match(content):
                content = str(_nested_value(candidate_data, [22, 0], "") or content)
            content = ARTIFACTS_RE.sub("", content).strip()
            thoughts = str(_nested_value(candidate_data, [37, 0, 0], "") or "").strip()
            candidates[rcid] = {"content": content, "thoughts": thoughts}

    if not candidates:
        raise RuntimeError("Gemini Web returned no reply candidates")

    first_candidate = next(iter(candidates.values()))
    return cid, rid, first_candidate["content"], first_candidate["thoughts"]


def complete_non_stream(credentials: dict, payload: dict):
    request_model = str(payload.get("model") or "gemini-web").strip() or "gemini-web"
    prompt = _prompt_from_messages(payload.get("messages") or [])
    if not prompt:
        raise RuntimeError("Gemini Web prompt is empty after normalization")

    model_entry = _resolve_model_entry(credentials, request_model)
    if not model_entry or not model_entry.get("header"):
        raise RuntimeError(f"Gemini Web model '{request_model}' is not configured")

    session, state = _bootstrap(credentials)
    try:
        request_uuid, inner_body = _request_body(
            prompt=prompt,
            language=str(state.get("language") or "en"),
            temporary=bool(payload.get("history_disabled", True)),
        )
        headers = {
            **_base_headers(),
            **model_entry["header"],
            "X-Same-Domain": "1",
            "x-goog-ext-525005358-jspb": f'["{request_uuid}",1]',
        }
        response = session.post(
            GENERATE_URL,
            params=_request_params(state),
            headers=headers,
            data={
                "at": state["access_token"],
                "f.req": json.dumps([None, json.dumps(inner_body)]),
            },
            timeout=int(os.environ.get("GEMINI_WEB_TIMEOUT_SEC", "180") or "180"),
        )
        if response.status_code != 200:
            preview = response.text[:500] if hasattr(response, "text") else ""
            raise RuntimeError(f"Gemini Web generation failed: HTTP {response.status_code} {preview}")

        cid, rid, content, thoughts = _parse_generation_payload(response.text, request_model)
        if not content and not thoughts:
            raise RuntimeError("Gemini Web returned an empty completion")

        message = {"role": "assistant", "content": content}
        if thoughts:
            message["reasoning_content"] = thoughts

        result = {
            "id": cid or rid or f"gemini-web-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request_model,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        meta = {
            "provider": "gemini-web",
            "chat_id": result["id"],
            "model": request_model,
            "transport": _transport_name(bool(state.get("use_curl"))),
            "content_length": len(content),
            "reasoning_length": len(thoughts),
            "empty_content": not bool(content),
        }
        debug_log("gemini_web_non_stream_done", **meta)
        return result, meta
    finally:
        session.close()
