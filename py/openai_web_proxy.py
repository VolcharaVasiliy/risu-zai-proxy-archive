import base64
import hashlib
import json
import os
import random
import re
import sys
import time
import uuid
from html.parser import HTMLParser

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


OWNED_BY = "chatgpt.com"
BASE_URL = (os.environ.get("OPENAI_WEB_BASE_URL", "").strip() or "https://chatgpt.com").rstrip("/")
DEFAULT_USER_AGENT = os.environ.get(
    "OPENAI_WEB_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
).strip()
MODEL_ALIASES = {"chatgpt": "auto", "chatgpt-auto": "auto", "openai-web": "auto"}
TOKEN_CACHE = {}
CACHED_SCRIPTS = []
CACHED_DPL = ""
CACHED_DPL_TIME = 0
CORES = [8, 16, 24, 32]
NAV_KEYS = ["webdriver-false", "vendor-Google Inc.", "hardwareConcurrency-16", "cookieEnabled-true"]
DOC_KEYS = ["location", "_reactListening"]
WIN_KEYS = ["window", "document", "navigator", "location", "origin", "localStorage", "sessionStorage", "fetch"]


class ScriptSrcParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        global CACHED_SCRIPTS, CACHED_DPL, CACHED_DPL_TIME
        if tag != "script":
            return
        src = str(dict(attrs).get("src") or "").strip()
        if not src:
            return
        CACHED_SCRIPTS.append(src)
        dpl = re.search(r"[?&]dpl=([a-zA-Z0-9._-]+)", src)
        if dpl:
            CACHED_DPL = dpl.group(1)
            CACHED_DPL_TIME = int(time.time())


def configured_models():
    raw = os.environ.get("OPENAI_WEB_MODELS", "").strip()
    found = []
    if raw:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str) and item.strip():
                    found.append(item.strip())
                elif isinstance(item, dict):
                    value = str(item.get("slug") or item.get("id") or "").strip()
                    if value:
                        found.append(value)
    if not found:
        found = ["chatgpt-auto"]
    ordered = []
    seen = set()
    for item in ["chatgpt", "chatgpt-auto", *found]:
        lowered = item.lower()
        if lowered not in seen:
            ordered.append(item)
            seen.add(lowered)
    return ordered


SUPPORTED_MODELS = configured_models()


def supports_model(model: str) -> bool:
    lowered = str(model or "").strip().lower()
    if not lowered:
        return False
    if lowered in MODEL_ALIASES:
        return True
    return any(lowered == item.lower() for item in configured_models())


def map_model(model: str) -> str:
    lowered = str(model or "").strip().lower()
    if lowered in MODEL_ALIASES:
        return MODEL_ALIASES[lowered]
    for item in configured_models():
        if lowered == item.lower():
            return item
    return "auto"


def session(use_curl: bool = True):
    if use_curl and curl_requests is not None:
        return curl_requests.Session(impersonate=os.environ.get("OPENAI_WEB_IMPERSONATE", "chrome136"), timeout=120)
    return requests.Session()


def transport_name(use_curl: bool) -> str:
    return "curl_cffi" if use_curl and curl_requests is not None else "requests"


def jwt_exp(token: str) -> int:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return 0
    middle = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(middle.encode("utf-8")).decode("utf-8"))
        return int(payload.get("exp") or 0)
    except Exception:
        return 0


def base_headers(access_token: str = "", account_id: str = "", device_id: str = "") -> dict:
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Oai-Language": "en-US",
        "Priority": "u=1, i",
        "Referer": f"{BASE_URL}/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": DEFAULT_USER_AGENT,
        "Sec-Ch-Ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if account_id:
        headers["Chatgpt-Account-Id"] = account_id
    if device_id:
        headers["Oai-Device-Id"] = device_id
    return headers


def cookie_headers(cookie_header: str) -> dict:
    headers = base_headers(device_id=str(uuid.uuid4()))
    headers["Cookie"] = cookie_header
    return headers


def perform_request(sess, method: str, url: str, *, use_curl: bool, **kwargs):
    response = sess.request(method, url, **kwargs)
    if response.status_code == 403 and use_curl and curl_requests is not None:
        response.close()
        sess.close()
        sess = session(use_curl=False)
        response = sess.request(method, url, **kwargs)
        return sess, response, False
    return sess, response, use_curl


def session_from_cookie(cookie_header: str) -> dict:
    cookie_header = str(cookie_header or "").strip()
    if not cookie_header:
        raise RuntimeError("OpenAI Web cookie header is empty")
    sess = session(use_curl=True)
    use_curl = True
    try:
        sess, response, use_curl = perform_request(
            sess,
            "GET",
            f"{BASE_URL}/api/auth/session",
            headers=cookie_headers(cookie_header),
            use_curl=use_curl,
            allow_redirects=True,
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI Web session fetch failed: HTTP {response.status_code}")
        payload = response.json()
        if not str(payload.get("accessToken") or "").strip():
            raise RuntimeError("OpenAI Web session response does not contain accessToken")
        debug_log("openai_web_session_from_cookie", transport=transport_name(use_curl), has_user=bool(payload.get("user")))
        return payload
    finally:
        sess.close()


def fetch_account_snapshot(access_token: str, account_id: str = "", device_id: str = "") -> dict:
    if not str(access_token or "").strip():
        raise RuntimeError("OpenAI Web access token is empty")
    sess = session(use_curl=True)
    use_curl = True
    headers = base_headers(access_token=access_token, account_id=account_id, device_id=device_id or str(uuid.uuid4()))
    snapshot = {"models": [], "account_check_info": {}, "accounts_info": {}}
    try:
        sess, models_response, use_curl = perform_request(
            sess,
            "GET",
            f"{BASE_URL}/backend-api/models?history_and_training_disabled=false",
            headers=headers,
            use_curl=use_curl,
            timeout=30,
        )
        if models_response.status_code == 200:
            snapshot["models"] = (models_response.json() or {}).get("models") or []

        sess, accounts_response, use_curl = perform_request(
            sess,
            "GET",
            f"{BASE_URL}/backend-api/accounts/check/v4-2023-04-27",
            headers=headers,
            use_curl=use_curl,
            timeout=30,
        )
        if accounts_response.status_code == 200:
            info = accounts_response.json() or {}
            snapshot["accounts_info"] = info
            ordering = info.get("account_ordering", []) or []
            active = []
            teams = []
            plan_type = ""
            for item in ordering:
                account = ((info.get("accounts") or {}).get(item) or {}).get("account") or {}
                if account.get("is_deactivated"):
                    continue
                active.append(item)
                this_plan = str(account.get("plan_type") or "free")
                if not plan_type:
                    plan_type = this_plan
                if "team" in this_plan:
                    teams.append(item)
            snapshot["account_check_info"] = {"active_account_ids": active, "team_ids": teams, "plan_type": plan_type}
        return snapshot
    finally:
        sess.close()


def choose_account_id(snapshot: dict) -> str:
    active = list((snapshot.get("account_check_info") or {}).get("active_account_ids") or [])
    return str(active[0]) if len(active) == 1 else ""


def resolve_access_token(credentials: dict) -> str:
    access_token = str(credentials.get("access_token") or "").strip()
    cookie = str(credentials.get("cookie") or "").strip()
    if access_token and jwt_exp(access_token) > int(time.time()) + 300:
        return access_token
    if cookie:
        cache_key = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
        cached = TOKEN_CACHE.get(cache_key) or {}
        if cached.get("token") and int(cached.get("exp") or 0) > int(time.time()) + 300:
            return cached["token"]
        payload = session_from_cookie(cookie)
        access_token = str(payload.get("accessToken") or "").strip()
        TOKEN_CACHE[cache_key] = {"token": access_token, "exp": jwt_exp(access_token)}
        return access_token
    if access_token:
        return access_token
    raise RuntimeError("OpenAI Web access token is not configured")


def get_dpl(sess, headers: dict) -> bool:
    global CACHED_SCRIPTS, CACHED_DPL, CACHED_DPL_TIME
    if CACHED_DPL and int(time.time()) - CACHED_DPL_TIME < 15 * 60:
        return True
    CACHED_SCRIPTS = []
    CACHED_DPL = ""
    CACHED_DPL_TIME = int(time.time())

    response = sess.get(f"{BASE_URL}/", headers=headers, timeout=30)
    response.raise_for_status()
    parser = ScriptSrcParser()
    parser.feed(response.text)
    if not CACHED_DPL:
        match = re.search(r'<html[^>]*data-build="([^"]+)"', response.text)
        if match:
            CACHED_DPL = match.group(1)
            CACHED_DPL_TIME = int(time.time())
    if not CACHED_SCRIPTS:
        CACHED_SCRIPTS.append(f"{BASE_URL}/backend-api/sentinel/sdk.js")
    return bool(CACHED_DPL)


def proof_config() -> list:
    return [
        random.choice([3000, 4000]),
        time.strftime("%a %b %d %Y %H:%M:%S GMT-0500 (Eastern Standard Time)", time.gmtime()),
        4294705152,
        0,
        DEFAULT_USER_AGENT,
        random.choice(CACHED_SCRIPTS) if CACHED_SCRIPTS else "",
        CACHED_DPL,
        "en-US",
        "en-US,en;q=0.9",
        0,
        random.choice(NAV_KEYS),
        random.choice(DOC_KEYS),
        random.choice(WIN_KEYS),
        time.perf_counter() * 1000,
        str(uuid.uuid4()),
        "",
        random.choice(CORES),
        time.time() * 1000 - (time.perf_counter() * 1000),
    ]


def generate_answer(seed: str, diff: str, config: list):
    diff_len = len(diff)
    target_diff = bytes.fromhex(diff)
    seed_bytes = str(seed).encode("utf-8")
    part1 = (json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ",").encode("utf-8")
    part2 = ("," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ",").encode("utf-8")
    part3 = ("," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]).encode("utf-8")
    for index in range(500000):
        payload = part1 + str(index).encode("utf-8") + part2 + str(index >> 1).encode("utf-8") + part3
        encoded = base64.b64encode(payload)
        if hashlib.sha3_512(seed_bytes + encoded).digest()[:diff_len] <= target_diff:
            return encoded.decode("utf-8"), True
    fallback = base64.b64encode(f'"{seed}"'.encode("utf-8")).decode("utf-8")
    return "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + fallback, False


def requirements_token(config: list) -> str:
    answer, _ = generate_answer(format(random.random()), "0fffff", config)
    return "gAAAAAC" + answer


def proof_token(seed: str, diff: str, config: list) -> str:
    answer, solved = generate_answer(seed, diff, config)
    if not solved:
        raise RuntimeError("OpenAI Web proof-of-work could not be solved")
    return "gAAAAAB" + answer


def fetch_chat_requirements(sess, headers: dict):
    if not get_dpl(sess, headers):
        raise RuntimeError("OpenAI Web sentinel dpl was not resolved")
    config = proof_config()
    response = sess.post(
        f"{BASE_URL}/backend-api/sentinel/chat-requirements",
        headers=headers,
        json={"p": requirements_token(config)},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI Web chat requirements failed: HTTP {response.status_code}")
    data = response.json() or {}
    if ((data.get("turnstile") or {}).get("required")):
        raise RuntimeError("OpenAI Web requested Turnstile verification")
    if ((data.get("arkose") or {}).get("required")):
        raise RuntimeError("OpenAI Web requested Arkose verification")
    pow_info = data.get("proofofwork") or {}
    solved = proof_token(pow_info.get("seed"), pow_info.get("difficulty"), config) if pow_info.get("required") else ""
    token = str(data.get("token") or "").strip()
    if not token:
        raise RuntimeError("OpenAI Web chat requirements token is empty")
    return {"chat_token": token, "proof_token": solved, "persona": str(data.get("persona") or "")}


def text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def messages_to_chat(messages):
    result = []
    for message in messages or []:
        role = str(message.get("role") or "user").strip().lower()
        if role not in {"system", "user", "assistant"}:
            role = "user"
        text = text_from_content(message.get("content"))
        if not text.strip():
            continue
        result.append(
            {
                "id": str(uuid.uuid4()),
                "author": {"role": role},
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            }
        )
    return result


def request_spec(payload: dict):
    request_model = str(payload.get("model") or "chatgpt-auto").strip()
    upstream_model = map_model(request_model)
    chat_messages = messages_to_chat(payload.get("messages") or [])
    if not chat_messages:
        raise RuntimeError("OpenAI Web prompt is empty after normalization")
    return request_model, upstream_model, chat_messages


def conversation_request(payload: dict, request_model: str, upstream_model: str, chat_messages):
    return {
        "action": "next",
        "client_contextual_info": {
            "is_dark_mode": False,
            "time_since_loaded": random.randint(50, 500),
            "page_height": random.randint(700, 1100),
            "page_width": random.randint(1100, 1800),
            "pixel_ratio": 1.5,
            "screen_height": random.randint(900, 1200),
            "screen_width": random.randint(1400, 2200),
        },
        "conversation_mode": {"kind": "primary_assistant"},
        "conversation_origin": None,
        "force_paragen": False,
        "force_paragen_model_slug": "",
        "force_rate_limit": False,
        "force_use_sse": True,
        "history_and_training_disabled": bool(payload.get("history_disabled", True)),
        "messages": chat_messages,
        "model": upstream_model,
        "paragen_cot_summary_display_override": "allow",
        "paragen_stream_type_override": None,
        "parent_message_id": str(uuid.uuid4()),
        "reset_rate_limits": False,
        "suggestions": [],
        "supported_encodings": [],
        "system_hints": [],
        "timezone": "Europe/Moscow",
        "timezone_offset_min": -180,
        "variant_purpose": "comparison_implicit",
        "websocket_request_id": str(uuid.uuid4()),
        "requested_model": request_model,
    }


def iter_events(response):
    for raw in response.iter_lines():
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            if data == "[DONE]":
                break
            continue
        try:
            yield json.loads(data)
        except Exception:
            continue


def extract_delta(event: dict, state: dict):
    if event.get("error"):
        raise RuntimeError(str(event.get("error")))
    message = event.get("message") or {}
    if not message:
        return {"delta": "", "finished": event.get("type") == "moderation"}

    if not state.get("response_id") and event.get("conversation_id"):
        state["response_id"] = str(event.get("conversation_id"))

    author_role = str(((message.get("author") or {}).get("role") or "")).strip().lower()
    if author_role != "assistant":
        return {"delta": "", "finished": False}

    content = message.get("content") or {}
    if str(content.get("content_type") or "") != "text":
        return {"delta": "", "finished": bool(message.get("end_turn"))}

    message_id = str(message.get("id") or "").strip()
    parts = content.get("parts") or []
    text = str(parts[0] if parts and isinstance(parts[0], str) else "")
    if state.get("message_id") != message_id:
        state["message_id"] = message_id
        state["text"] = ""
    previous = str(state.get("text") or "")
    delta = text[len(previous) :] if text.startswith(previous) else text
    state["text"] = text
    finished = str(message.get("status") or "") == "finished_successfully" and bool(message.get("end_turn"))
    return {"delta": delta, "finished": finished}


def chat_completion(credentials: dict, payload: dict):
    request_model, upstream_model, chat_messages = request_spec(payload)
    access_token = resolve_access_token(credentials)
    account_id = str(credentials.get("account_id") or "").strip()
    device_id = str(credentials.get("device_id") or "").strip() or str(uuid.uuid4())
    headers = base_headers(access_token=access_token, account_id=account_id, device_id=device_id)

    sess = session(use_curl=True)
    use_curl = True
    try:
        requirements = fetch_chat_requirements(sess, headers)
        stream_headers = dict(headers)
        stream_headers.update(
            {
                "Accept": "text/event-stream",
                "Openai-Sentinel-Chat-Requirements-Token": requirements["chat_token"],
                "Openai-Sentinel-Proof-Token": requirements["proof_token"],
            }
        )
        if not requirements["proof_token"]:
            stream_headers.pop("Openai-Sentinel-Proof-Token", None)
        body = conversation_request(payload, request_model, upstream_model, chat_messages)
        sess, response, use_curl = perform_request(
            sess,
            "POST",
            f"{BASE_URL}/backend-api/conversation",
            headers=stream_headers,
            json=body,
            use_curl=use_curl,
            timeout=120,
            stream=True,
        )
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI Web conversation failed: HTTP {response.status_code}")
        debug_log("openai_web_chat_started", request_model=request_model, upstream_model=upstream_model, transport=transport_name(use_curl))
        return sess, response, request_model
    except Exception:
        sess.close()
        raise


def stream_chunks(credentials: dict, payload: dict):
    sess, response, request_model = chat_completion(credentials, payload)
    builder = OpenAIStreamBuilder(str(uuid.uuid4()), request_model)
    state = {"response_id": "", "message_id": "", "text": ""}
    saw_any = False
    try:
        for event in iter_events(response):
            info = extract_delta(event, state)
            if state["response_id"]:
                builder.set_response_id(state["response_id"])
            if info["delta"]:
                saw_any = True
                for chunk in builder.content(info["delta"]):
                    yield chunk
            if info["finished"]:
                break
    finally:
        response.close()
        sess.close()
    if not saw_any:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk
    debug_log("openai_web_stream_done", chat_id=builder.response_id, model=request_model, content_length=len(str(state.get("text") or "")))
    yield builder.finish()


def complete_non_stream(credentials: dict, payload: dict):
    sess, response, request_model = chat_completion(credentials, payload)
    state = {"response_id": "", "message_id": "", "text": ""}
    saw_finished = False
    try:
        for event in iter_events(response):
            info = extract_delta(event, state)
            if info["finished"]:
                saw_finished = True
                break
    finally:
        response.close()
        sess.close()
    content = str(state.get("text") or "")
    if not content:
        raise RuntimeError("OpenAI Web returned an empty completion")
    result = {
        "id": state.get("response_id") or str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    meta = {
        "provider": "openai-web",
        "chat_id": result["id"],
        "model": request_model,
        "content_length": len(content),
        "empty_content": not bool(content),
        "finished": saw_finished,
    }
    debug_log("openai_web_non_stream_done", **meta)
    return result, meta
