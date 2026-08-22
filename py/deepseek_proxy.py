import base64
import json
import os
import random
import re
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import requests

try:
    from py.deepseek_hash import build_pow_response
    from py.openai_stream import OpenAIStreamBuilder
    from py.zai_proxy import debug_log
    from py.client_fingerprint import CLIENT_BUNDLE_ID, CLIENT_VERSION
except ImportError:
    from deepseek_hash import build_pow_response
    from openai_stream import OpenAIStreamBuilder
    from zai_proxy import debug_log
    try:
        from client_fingerprint import CLIENT_BUNDLE_ID, CLIENT_VERSION
    except Exception:
        CLIENT_BUNDLE_ID = "com.deepseek.chat"
        CLIENT_VERSION = "2.3.0"


DEEPSEEK_API_BASE = "https://chat.deepseek.com/api"
OWNED_BY = "chat.deepseek.com"

_DATA_URL_RE = re.compile(r"^data:image/(?P<ext>\w+);base64,(?P<data>.+)$", re.DOTALL)
DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
FILE_READY_STATUSES = {"SUCCESS", "CONTENT_EMPTY", "READY", "COMPLETED"}

SUPPORTED_MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-search",
    "deepseek-vision",
]

MODEL_OPTIONS = {
    "deepseek": {"model": "deepseek-chat", "model_type": "default", "thinking": False, "search": False},
    "deepseek-chat": {"model": "deepseek-chat", "model_type": "default", "thinking": False, "search": False},
    "deepseek-reasoner": {"model": "deepseek-reasoner", "model_type": "default", "thinking": True, "search": False},
    "deepseek-search": {"model": "deepseek-search", "model_type": "default", "thinking": False, "search": True},
    "deepseek-vision": {"model": "deepseek-vision", "model_type": "vision", "thinking": False, "search": False},
}

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://chat.deepseek.com",
    "Referer": "https://chat.deepseek.com/",
    "Sec-Ch-Ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "X-Client-Locale": "zh-CN",
    "X-Client-Platform": "web",
    "X-Client-Bundle-Id": CLIENT_BUNDLE_ID,
    "X-Client-Version": CLIENT_VERSION,
}

_ACCESS_CACHE = {}
_SESSION_CACHE = {}


def supports_model(model: str) -> bool:
    return str(model or "").lower() in MODEL_OPTIONS


def _cache_get(cache: dict, key: str):
    item = cache.get(key)
    if not item:
        return None
    if item["expires_at"] <= time.time():
        cache.pop(key, None)
        return None
    return item["value"]


def _cache_set(cache: dict, key: str, value, ttl_seconds: int):
    cache[key] = {"value": value, "expires_at": time.time() + ttl_seconds}


def _random_string(length: int, alphabet: str = "0123456789abcdefghijklmnopqrstuvwxyz") -> str:
    return "".join(random.choice(alphabet) for _ in range(length))


def _max_image_bytes() -> int:
    try:
        return max(1, int(os.environ.get("DEEPSEEK_MAX_IMAGE_BYTES", DEFAULT_MAX_IMAGE_BYTES)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_IMAGE_BYTES


def _validate_image_bytes(raw: bytes) -> bytes:
    if not raw:
        raise ValueError("DeepSeek image is empty")
    limit = _max_image_bytes()
    if len(raw) > limit:
        raise ValueError(f"DeepSeek image exceeds {limit} bytes")
    return raw


def _cookie() -> str:
    timestamp_ms = int(time.time() * 1000)
    timestamp_s = int(time.time())
    return "; ".join(
        [
            f"intercom-HWWAFSESTIME={timestamp_ms}",
            f"HWWAFSESID={_random_string(18, '0123456789abcdef')}",
            f"_frid={uuid.uuid4().hex}",
            f"_fr_ssid={uuid.uuid4().hex}",
            f"_fr_pvid={uuid.uuid4().hex}",
            f"Hm_lvt_{uuid.uuid4().hex[:16]}={timestamp_s},{timestamp_s},{timestamp_s}",
            f"Hm_lpvt_{uuid.uuid4().hex[:16]}={timestamp_s}",
        ]
    )


def _check_response(response, label: str):
    if response.status_code == 401:
        raise RuntimeError("DeepSeek token invalid or expired")
    if response.status_code != 200:
        raise RuntimeError(f"DeepSeek {label} failed: HTTP {response.status_code}")
    return response.json()


def acquire_access_token(token: str) -> str:
    cached = _cache_get(_ACCESS_CACHE, token)
    if cached:
        return cached

    response = requests.get(
        f"{DEEPSEEK_API_BASE}/v0/users/current",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {token}"},
        timeout=30,
    )
    data = _check_response(response, "token exchange")
    biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data") or {}
    access_token = str(biz_data.get("token") or "").strip()
    if not access_token:
        raise RuntimeError(f"DeepSeek token exchange returned no access token: {data}")
    _cache_set(_ACCESS_CACHE, token, access_token, 3000)
    return access_token


def create_session(access_token: str) -> str:
    cached = _cache_get(_SESSION_CACHE, access_token)
    if cached:
        return cached

    response = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/chat_session/create",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {access_token}", "Cookie": _cookie()},
        json={"character_id": None},
        timeout=30,
    )
    data = _check_response(response, "create session")
    biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data") or {}
    # biz_data may contain either an 'id' directly or a nested 'chat_session' object
    session_id = str(biz_data.get("id") or (biz_data.get("chat_session") or {}).get("id") or "").strip()
    if not session_id:
        raise RuntimeError(f"DeepSeek create session returned no session id: {data}")
    _cache_set(_SESSION_CACHE, access_token, session_id, 300)
    return session_id


def get_challenge(access_token: str, target_path: str = "/api/v0/chat/completion") -> dict:
    response = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/chat/create_pow_challenge",
        headers={**FAKE_HEADERS, "Authorization": f"Bearer {access_token}"},
        json={"target_path": target_path},
        timeout=30,
    )
    data = _check_response(response, "get challenge")
    biz_data = (data.get("data") or {}).get("biz_data") or data.get("biz_data") or {}
    challenge = biz_data.get("challenge") or {}
    if not challenge:
        raise RuntimeError(f"DeepSeek challenge response is empty: {data}")
    return challenge


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
    parts = []
    for message in messages or []:
        role = str(message.get("role") or "user").capitalize()
        text = _text_from_content(message.get("content"))
        if not text.strip():
            continue
        parts.append(f"{role}: {text}")
    return "\n\n".join(parts).replace("![](", "! [").strip()


def _flags_for(request_model: str, payload: dict):
    model_key = str(request_model or "").lower()
    defaults = MODEL_OPTIONS.get(model_key) or MODEL_OPTIONS["deepseek-chat"]
    search_enabled = defaults["search"] or bool(payload.get("web_search"))
    thinking_enabled = defaults["thinking"] or bool(payload.get("reasoning_effort"))
    return defaults["model"], defaults["model_type"], search_enabled, thinking_enabled


def _fetch_file_sync(access_token: str, file_id: str, max_polls: int = 60) -> dict:
    for _ in range(max_polls):
        time.sleep(2)
        resp = requests.get(
            f"{DEEPSEEK_API_BASE}/v0/file/fetch_files",
            headers={**FAKE_HEADERS, "Authorization": f"Bearer {access_token}", "Cookie": _cookie()},
            params={"file_ids": file_id},
            timeout=30,
        )
        if resp.status_code != 200:
            continue
        body = resp.json()
        files = body.get("data", {})
        if isinstance(files, dict):
            files = files.get("biz_data", {}).get("files", [])
        if isinstance(files, list):
            for f in files:
                if isinstance(f, dict) and f.get("id") == file_id:
                    status = str(f.get("status") or "").upper()
                    if status == "FAILED":
                        return f
                    if status in FILE_READY_STATUSES:
                        return f
    raise RuntimeError(f"DeepSeek file {file_id} did not become ready within {max_polls * 2}s")


def _upload_and_wait(access_token: str, raw: bytes, filename: str, mime: str) -> str:
    _validate_image_bytes(raw)
    debug_log(
        "deepseek_vision_upload_started",
        filename=filename,
        mime=mime,
        bytes=len(raw),
    )
    target = "/api/v0/file/upload_file"
    challenge = get_challenge(access_token, target_path=target)
    pow_response = build_pow_response(challenge, target_path=target)

    uh = {k: v for k, v in FAKE_HEADERS.items() if k.lower() != "accept-encoding"}
    uh["Authorization"] = f"Bearer {access_token}"
    uh["Cookie"] = _cookie()
    uh["X-Ds-Pow-Response"] = pow_response
    uh["X-File-Size"] = str(len(raw))

    resp = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/file/upload_file",
        headers=uh,
        files={"file": (filename, raw, mime)},
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek upload failed: HTTP {resp.status_code} {resp.text[:200]}")

    body = resp.json()
    d = body.get("data", {})
    if isinstance(d, dict):
        biz = d.get("biz_data", {})
        file_id = str(biz.get("id") or "").strip()
    else:
        file_id = ""
    if not file_id:
        raise RuntimeError(f"DeepSeek upload returned no file_id: {body}")

    info = _fetch_file_sync(access_token, file_id)
    status = str(info.get("status") or "").upper()
    if status == "FAILED":
        raise RuntimeError(f"DeepSeek file {file_id} processing failed: {info.get('error_code')}")
    if status not in FILE_READY_STATUSES:
        raise RuntimeError(f"DeepSeek file {file_id} unexpected status: {status}")

    if info.get("is_image"):
        fork_resp = requests.post(
            f"{DEEPSEEK_API_BASE}/v0/file/fork_file_task",
            headers={
                **FAKE_HEADERS,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"file_id": file_id, "to_model_type": "vision"},
            timeout=30,
        )
        if fork_resp.status_code != 200:
            raise RuntimeError(f"DeepSeek fork failed: HTTP {fork_resp.status_code} {fork_resp.text[:200]}")
        fork_body = fork_resp.json()
        fd = fork_body.get("data", {})
        if isinstance(fd, dict):
            fbiz = fd.get("biz_data", {})
            vision_id = str(fbiz.get("id") or "").strip()
        else:
            vision_id = ""
        if not vision_id:
            raise RuntimeError(f"DeepSeek fork returned no vision file_id: {fork_body}")

        vinfo = _fetch_file_sync(access_token, vision_id)
        vstatus = str(vinfo.get("status") or "").upper()
        if vstatus == "FAILED":
            raise RuntimeError(f"DeepSeek vision file {vision_id} processing failed: {vinfo.get('error_code')}")
        if vstatus not in FILE_READY_STATUSES:
            raise RuntimeError(f"DeepSeek vision file {vision_id} unexpected status: {vstatus}")
        debug_log("deepseek_vision_upload_ready", file_id=vision_id, bytes=len(raw))
        return vision_id

    debug_log("deepseek_vision_upload_ready", file_id=file_id, bytes=len(raw))
    return file_id


def describe_image_item(credentials: dict, item: dict, context_text: str = "", index: int = 1) -> str:
    token = str((credentials or {}).get("token") or os.environ.get("DEEPSEEK_TOKEN") or "").strip()
    if not token:
        return ""
    iv = item.get("image_url")
    url = ""
    if isinstance(iv, dict):
        url = str(iv.get("url") or "")
    elif isinstance(iv, str):
        url = iv
    if not url:
        file_data = str(item.get("file_data") or item.get("data") or "").strip()
        if file_data:
            if file_data.startswith("data:"):
                url = file_data
            else:
                url = f"data:image/jpeg;base64,{file_data}"
    if not url:
        return ""

    try:
        access_token = acquire_access_token(token)
        m = _DATA_URL_RE.match(url)
        if m:
            raw = _validate_image_bytes(base64.b64decode(re.sub(r"\s+", "", m.group("data")), validate=True))
            ext = m.group("ext") or "png"
        elif url.startswith(("http://", "https://")):
            resp = requests.get(url, headers={"User-Agent": FAKE_HEADERS["User-Agent"]}, timeout=30)
            resp.raise_for_status()
            raw = _validate_image_bytes(resp.content)
            ext = "jpg"
        else:
            return ""

        fid = _upload_and_wait(access_token, raw, f"image.{ext}", f"image/{ext}")
        if not fid:
            return ""

        messages = [{"role": "user", "content": [
            {"type": "text", "text": f"Describe image {index} for another language model. Include visible objects, people, text, UI elements, layout, colors, and any details needed to answer the user's request. Be factual and concise."},
        ]}]
        if context_text:
            messages[0]["content"].insert(0, {"type": "text", "text": f"Conversation context:\n{context_text}\n"})
        file_ids = [fid]
        model_type = "vision"
        session_id = create_session(access_token)
        challenge = get_challenge(access_token)
        pow_response = build_pow_response(challenge)
        prompt_text = "User: " + " ".join(
            p["text"] for p in messages[0]["content"] if isinstance(p, dict) and p.get("type") == "text"
        )
        resp = requests.post(
            f"{DEEPSEEK_API_BASE}/v0/chat/completion",
            headers={
                **FAKE_HEADERS,
                "Authorization": f"Bearer {access_token}",
                "Cookie": _cookie(),
                "X-Ds-Pow-Response": pow_response,
            },
            json={
                "chat_session_id": session_id,
                "parent_message_id": None,
                "model_type": model_type,
                "prompt": prompt_text,
                "ref_file_ids": file_ids,
                "search_enabled": False,
                "thinking_enabled": False,
            },
            timeout=120,
            stream=True,
        )
        if resp.status_code != 200:
            return ""

        answer_parts = []
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data = raw_line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            value = event.get("v")
            if isinstance(value, dict) and isinstance(value.get("response", {}).get("fragments"), list):
                for fragment in value["response"]["fragments"]:
                    ftype = str(fragment.get("type") or "").upper()
                    if ftype in ("ANSWER", "RESPONSE"):
                        answer_parts.append(str(fragment.get("content") or ""))
                continue
            if isinstance(value, list) and event.get("p") == "response/fragments":
                for fragment in value:
                    ftype = str(fragment.get("type") or "").upper()
                    if ftype in ("ANSWER", "RESPONSE"):
                        answer_parts.append(str(fragment.get("content") or ""))
                continue
            if isinstance(value, str) and value not in ("FINISHED", ""):
                answer_parts.append(value)
        resp.close()
        return "".join(answer_parts).strip()
    except Exception:
        return ""


def _resolve_image_ids(access_token: str, messages: list) -> list:
    file_ids = []
    seen = set()
    for msg in messages or []:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") not in ("image_url", "image", "input_image"):
                continue
            if item["type"] in ("image_url", "input_image"):
                iv = item.get("image_url")
                url = ""
                if isinstance(iv, dict):
                    url = str(iv.get("url") or "")
                elif isinstance(iv, str):
                    url = iv
            elif item["type"] == "image":
                iv = item.get("image_url")
                url = str(
                    item.get("file_data")
                    or (iv.get("url") if isinstance(iv, dict) else iv)
                    or item.get("url")
                    or ""
                )
            else:
                continue
            if url and url not in seen:
                seen.add(url)
    if not seen:
        return file_ids
    debug_log("deepseek_vision_images_detected", image_count=len(seen))
    for url in seen:
        m = _DATA_URL_RE.match(url)
        if m:
            raw = _validate_image_bytes(base64.b64decode(re.sub(r"\s+", "", m.group("data")), validate=True))
            ext = m.group("ext") or "png"
            filename = f"image.{ext}"
        elif url.startswith(("http://", "https://")):
            resp = requests.get(
                url,
                headers={"User-Agent": FAKE_HEADERS["User-Agent"]},
                timeout=30,
            )
            resp.raise_for_status()
            raw = _validate_image_bytes(resp.content)
            raw_ext = url.rsplit(".", 1)[-1].split("?")[0].lower() if "." in url else ""
            ext = raw_ext if raw_ext in {"png", "jpg", "jpeg", "gif", "webp", "bmp"} else "png"
            filename = f"image.{ext}"
        else:
            raise ValueError(f"Unsupported image URL: {url[:80]}")
        mime = f"image/{ext}"
        fid = _upload_and_wait(access_token, raw, filename, mime)
        if fid:
            file_ids.append(fid)
    return file_ids


def chat_completion(token: str, payload: dict):
    access_token = acquire_access_token(token)
    messages = payload.get("messages") or []
    file_ids = _resolve_image_ids(access_token, messages)
    session_id = create_session(access_token)
    challenge = get_challenge(access_token)
    pow_response = build_pow_response(challenge)
    request_model = str(payload.get("model") or "deepseek-chat")
    _, model_type, search_enabled, thinking_enabled = _flags_for(request_model, payload)
    if file_ids:
        model_type = "vision"
        search_enabled = False
        thinking_enabled = False
    prompt = _prompt_from_messages(messages)

    response = requests.post(
        f"{DEEPSEEK_API_BASE}/v0/chat/completion",
        headers={
            **FAKE_HEADERS,
            "Authorization": f"Bearer {access_token}",
            "Cookie": _cookie(),
            "X-Ds-Pow-Response": pow_response,
        },
        json={
            "chat_session_id": session_id,
            "parent_message_id": None,
            "model_type": model_type,
            "prompt": prompt,
            "ref_file_ids": file_ids,
            "search_enabled": search_enabled,
            "thinking_enabled": thinking_enabled,
        },
        timeout=120,
        stream=True,
    )
    if response.status_code != 200:
        try:
            body = response.text
        except Exception:
            body = ""
        raise RuntimeError(f"DeepSeek completion failed: HTTP {response.status_code} {body[:300]}")

    debug_log(
        "deepseek_chat_started",
        model=request_model,
        session_id=session_id,
        prompt_length=len(prompt),
        image_count=len(file_ids),
        model_type=model_type,
        search=search_enabled,
        thinking=thinking_enabled,
    )
    return response, session_id, request_model


def _iter_sse_data(response):
    for raw in response.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        data = raw[5:].strip()
        if not data:
            continue
        # Classify provider-side version gate hints explicitly so callers can avoid retries
        if "Update to the latest version" in data or "Update to latest version" in data:
            # Raise a special, identifiable error so upstream can treat it as PROVIDER_VERSION_GATE
            raise RuntimeError(f"PROVIDER_VERSION_GATE: {data}")
        yield data


def _append_fragments(fragments, answer_parts: list, reasoning_parts: list):
    last_path = ""
    for fragment in fragments or []:
        fragment_type = str(fragment.get("type") or "").upper()
        content = str(fragment.get("content") or "")
        if not content:
            continue
        if fragment_type == "THINK":
            reasoning_parts.append(content)
            last_path = "thinking"
        elif fragment_type in {"ANSWER", "RESPONSE"}:
            answer_parts.append(content)
            last_path = "content"
    return last_path


def _append_delta(path: str, value, answer_parts: list, reasoning_parts: list):
    text = str(value or "")
    if not text:
        return path
    if text == "FINISHED":
        return path
    if path == "thinking":
        reasoning_parts.append(text)
        return "thinking"
    answer_parts.append(text)
    return "content"


def _iter_event_deltas(event: dict, current_path: str):
    value = event.get("v")
    deltas = []

    if isinstance(value, dict) and isinstance((value.get("response") or {}).get("fragments"), list):
        for fragment in (value.get("response") or {}).get("fragments") or []:
            fragment_type = str(fragment.get("type") or "").upper()
            content = str(fragment.get("content") or "")
            if not content:
                continue
            if fragment_type == "THINK":
                deltas.append(("reasoning", content))
                current_path = "thinking"
            elif fragment_type in {"ANSWER", "RESPONSE"}:
                deltas.append(("content", content))
                current_path = "content"
        return current_path, deltas

    if event.get("p") == "response/fragments" and isinstance(value, list):
        for fragment in value:
            fragment_type = str(fragment.get("type") or "").upper()
            content = str(fragment.get("content") or "")
            if not content:
                continue
            if fragment_type == "THINK":
                deltas.append(("reasoning", content))
                current_path = "thinking"
            elif fragment_type in {"ANSWER", "RESPONSE"}:
                deltas.append(("content", content))
                current_path = "content"
        return current_path, deltas

    path = str(event.get("p") or "")
    if "THINK" in path.upper() or "thinking" in path.lower():
        current_path = "thinking"
    elif "/content" in path or "RESPONSE" in path.upper():
        current_path = "content"

    text = str(value or "")
    if text and text != "FINISHED":
        deltas.append(("reasoning" if current_path == "thinking" else "content", text))

    return current_path, deltas


def stream_chunks(token: str, payload: dict):
    response, session_id, request_model = chat_completion(token, payload)
    builder = OpenAIStreamBuilder(session_id, request_model)
    current_path = "content"
    answer_chars = 0
    reasoning_chars = 0

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            event = json.loads(data)
            builder.set_response_id(str(event.get("response_message_id") or builder.response_id))
            current_path, deltas = _iter_event_deltas(event, current_path)
            for kind, text in deltas:
                if kind == "reasoning":
                    reasoning_chars += len(text)
                    yield from builder.reasoning(text)
                else:
                    answer_chars += len(text)
                    yield from builder.content(text)
    finally:
        response.close()

    debug_log(
        "deepseek_stream_done",
        chat_id=builder.response_id,
        model=request_model,
        content_length=answer_chars,
        reasoning_length=reasoning_chars,
    )
    yield builder.finish()


def complete_non_stream(token: str, payload: dict):
    response, session_id, request_model = chat_completion(token, payload)
    response_id = session_id
    answer_parts = []
    reasoning_parts = []
    current_path = "content"

    try:
        for data in _iter_sse_data(response):
            if data == "[DONE]":
                break

            event = json.loads(data)
            response_id = str(event.get("response_message_id") or response_id)
            value = event.get("v")
            if isinstance(value, dict) and isinstance((value.get("response") or {}).get("fragments"), list):
                current_path = _append_fragments((value.get("response") or {}).get("fragments"), answer_parts, reasoning_parts) or current_path
                continue

            if event.get("p") == "response/fragments" and isinstance(value, list):
                current_path = _append_fragments(value, answer_parts, reasoning_parts) or current_path
                continue

            path = str(event.get("p") or "")
            if "THINK" in path.upper() or "thinking" in path.lower():
                current_path = "thinking"
            elif "/content" in path or "RESPONSE" in path.upper():
                current_path = "content"

            if isinstance(value, str):
                current_path = _append_delta(current_path, value, answer_parts, reasoning_parts)
    finally:
        response.close()

    message = {"role": "assistant", "content": "".join(answer_parts)}
    reasoning_text = "".join(reasoning_parts)
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
        "provider": "deepseek",
        "content_length": len(message["content"]),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(message["content"]),
    }
    debug_log("deepseek_non_stream_done", **meta)
    return result, meta
