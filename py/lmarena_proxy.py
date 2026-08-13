import json
import os
import re
import time
import uuid

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
MODELS_FILE = os.path.join(MODULE_DIR, "lmarena_models.json")

ARENA_URL = "https://arena.ai"
CREATE_EVALUATION = f"{ARENA_URL}/nextjs-api/stream/create-evaluation"
OWNED_BY = "arena.ai"
SITE_KEY = "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": ARENA_URL,
    "Referer": f"{ARENA_URL}/text/direct",
    "Sec-Ch-Ua": '"Not(A:Brand";v="8", "Chromium";v="144", "YaBrowser";v="26.3"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 YaBrowser/26.3.0.0 Safari/537.36",
}

UUIDV7_RE = re.compile(r"^019[0-9a-f]{5}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

try:
    from py.lmarena_captcha import get_token as _get_recaptcha_token
    from py.lmarena_captcha import force_refresh as _refresh_recaptcha_token
    from py.openai_stream import openai_chunk
except ImportError:
    from lmarena_captcha import get_token as _get_recaptcha_token
    from lmarena_captcha import force_refresh as _refresh_recaptcha_token
    from openai_stream import openai_chunk

_MODEL_MAP = {}
_MODELS = []


def _load_models():
    global _MODEL_MAP, _MODELS
    if _MODEL_MAP:
        return
    try:
        with open(MODELS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        _MODEL_MAP = {str(k).lower(): v for k, v in (data.get("byName") or {}).items()}
        _MODELS = list(_MODEL_MAP.keys())
    except (OSError, ValueError):
        _MODEL_MAP, _MODELS = {}, []


_load_models()

SUPPORTED_MODELS = _MODELS


def _uuidv7() -> str:
    ts = int(time.time() * 1000)
    rand = os.urandom(10)
    b = bytearray(16)
    b[0:6] = ts.to_bytes(6, "big")
    b[6] = (rand[0] & 0x0F) | 0x70
    b[7] = rand[1]
    b[8] = (rand[2] & 0x3F) | 0x80
    b[9:] = rand[3:10]
    return str(uuid.UUID(bytes=bytes(b)))


def supports_model(model: str) -> bool:
    return _find_id(model) is not None


def _find_id(model: str):
    if not model:
        return None
    model = str(model)
    if ":" in model:
        head, _, tail = model.partition(":")
        if head in ("lmarena", "arena"):
            model = tail
    if UUIDV7_RE.match(model):
        return model
    lowered = model.lower()
    if lowered in _MODEL_MAP:
        return _MODEL_MAP[lowered]
    starts = [k for k in _MODEL_MAP if k.startswith(lowered)]
    if starts:
        return _MODEL_MAP[starts[0]]
    contains = [k for k in _MODEL_MAP if lowered in k]
    if contains:
        contains.sort(key=len)
        return _MODEL_MAP[contains[0]]
    return None


def _resolve_model(model: str) -> str:
    if not model:
        raise RuntimeError("lmarena: model parameter is required")
    rid = _find_id(model)
    if rid is None:
        raise RuntimeError(f"lmarena: unknown model '{model}' (not in arena model catalog)")
    return rid


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


def _extract_prompt(messages) -> str:
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
        label = "User" if role == "user" else "Assistant"
        conversation.append(f"[{label}]: {text}")
    body = "\n\n".join(conversation)
    if system_prompt:
        body = f"[System]: {system_prompt}\n\n{body}"
    return body.strip()


def _build_payload(model_a_id: str, content: str, recaptcha_token: str) -> dict:
    return {
        "id": _uuidv7(),
        "mode": "direct-battle",
        "modelAId": model_a_id,
        "userMessageId": _uuidv7(),
        "modelAMessageId": _uuidv7(),
        "userMessage": {"content": content, "experimental_attachments": [], "metadata": {}},
        "modality": "chat",
        "recaptchaV3Token": recaptcha_token,
    }


def _new_session_id() -> str:
    return _uuidv7()


def _parse_stream_line(line: str):
    line = line.strip()
    if not line:
        return None
    if line.startswith("a0:"):
        raw = line[3:]
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    if line.startswith("ad:"):
        try:
            obj = json.loads(line[3:])
            return obj
        except (ValueError, TypeError):
            return None
    return None


def _post(cookie: str, payload: dict, timeout: float = 180.0):
    import requests

    headers = dict(FAKE_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.post(CREATE_EVALUATION, headers=headers, json=payload, stream=True, timeout=timeout)
    return resp


def _stream_text(cookie: str, payload: dict):
    attempt = 0
    max_attempts = 6
    while attempt < max_attempts:
        attempt += 1
        if attempt == 1:
            recaptcha_token = _get_recaptcha_token()
        else:
            recaptcha_token = _refresh_recaptcha_token()
        if not recaptcha_token:
            raise RuntimeError("lmarena: failed to obtain reCAPTCHA token")
        payload["recaptchaV3Token"] = recaptcha_token
        resp = _post(cookie, payload)
        if resp.status_code != 200:
            body = resp.text
            if resp.status_code == 403 and "recaptcha" in body.lower() and attempt < max_attempts:
                time.sleep(1)
                continue
            raise RuntimeError(f"lmarena: create-evaluation failed ({resp.status_code}): {body[:300]}")
        for raw_line in resp.iter_lines(decode_unicode=True):
            if raw_line is None:
                continue
            parsed = _parse_stream_line(raw_line)
            if parsed is None:
                continue
            if isinstance(parsed, str):
                yield ("delta", parsed)
            elif isinstance(parsed, dict):
                if str(parsed.get("finishReason", "")).lower() == "stop":
                    return
    raise RuntimeError("lmarena: reCAPTCHA validation failed after retries")


def complete_non_stream(cookie: str, payload: dict):
    model_a_id = _resolve_model(payload.get("model"))
    content = _extract_prompt(payload.get("messages"))
    body = _build_payload(model_a_id, content, "")
    text = "".join(delta for kind, delta in _stream_text(cookie, body) if kind == "delta")
    return text, {"provider": "lmarena", "model": model_a_id}


def stream_chunks(cookie: str, payload: dict):
    model_a_id = _resolve_model(payload.get("model"))
    content = _extract_prompt(payload.get("messages"))
    body = _build_payload(model_a_id, content, "")
    yield openai_chunk(system_fingerprint="lmarena", model=str(payload.get("model") or model_a_id))
    for kind, delta in _stream_text(cookie, body):
        if kind == "delta":
            yield openai_chunk(delta=delta, model=str(payload.get("model") or model_a_id))
    yield openai_chunk(finish_reason="stop", model=str(payload.get("model") or model_a_id))
