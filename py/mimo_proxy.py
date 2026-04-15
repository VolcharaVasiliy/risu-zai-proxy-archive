import json
import os
import re
import socket
import sys
import time
import uuid
from urllib.parse import quote
from urllib.request import urlopen

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.const import CurlOpt
except Exception:
    curl_requests = None
    CurlOpt = None

import requests
import urllib3

try:
    from py.zai_proxy import debug_log
except ImportError:
    from zai_proxy import debug_log

MIMO_BASE = "https://aistudio.xiaomimimo.com"
OWNED_BY = "Xiaomi Mimo"

SUPPORTED_MODELS = [
    "mimo-v2-flash-studio",
    "mimo-v2-pro",
    "mimo-v2-omni",
]

_MODEL_INDEX = {model.lower(): model for model in SUPPORTED_MODELS}

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Origin": MIMO_BASE,
    "Referer": f"{MIMO_BASE}/",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="144", "Not(A:Brand";v="8", "Google Chrome";v="144"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "X-Timezone": "Asia/Shanghai",
}


def supports_model(model: str) -> bool:
    return str(model or "").lower() in _MODEL_INDEX


def map_model(model: str) -> str:
    return _MODEL_INDEX.get(str(model or "").lower()) or str(model or "") or SUPPORTED_MODELS[0]


def _tls_verify() -> bool:
    raw = os.environ.get("MIMO_SKIP_TLS_VERIFY", "").strip().lower()
    verify = raw not in {"1", "true", "yes", "on"}
    if not verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return verify


def _loopback_resolution(hostname: str) -> bool:
    try:
        addresses = socket.gethostbyname_ex(hostname)[2]
    except Exception:
        return True
    if not addresses:
        return True
    return all(ip.startswith("127.") or ip == "0.0.0.0" for ip in addresses)


def _configured_resolve_ips():
    raw = os.environ.get("MIMO_RESOLVE_IPS", "").strip() or os.environ.get("MIMO_RESOLVE_IP", "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _public_dns_ips(hostname: str):
    try:
        with urlopen(f"https://dns.google/resolve?name={hostname}&type=A", timeout=10) as response:
            data = json.load(response)
    except Exception:
        return []

    ips = []
    for answer in data.get("Answer") or []:
        if answer.get("type") == 1 and answer.get("data"):
            ips.append(str(answer["data"]).strip())
    return ips


def _curl_options_for_host(hostname: str):
    if curl_requests is None or CurlOpt is None:
        return None

    ips = _configured_resolve_ips()
    auto_resolved = False
    if not ips and _loopback_resolution(hostname):
        ips = _public_dns_ips(hostname)
        auto_resolved = bool(ips)

    if not ips:
        return None

    debug_log("mimo_resolve_override", hostname=hostname, ips=ips, auto=auto_resolved)
    return {CurlOpt.RESOLVE: [f"{hostname}:443:{ip}" for ip in ips]}


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


def _latest_user_text(messages) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        return _text_from_content(message.get("content", ""))
    return ""


def _strip_citations(text: str) -> str:
    cleaned = str(text or "")
    cleaned = cleaned.replace("\x00", "")
    cleaned = re.sub(r"д»Ћ\(citation:\d+\)дё­[пјљ:]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"-?\s*citation:\d+[пјљ:]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[пј€\(]\s*citation:\d+(?:,\s*citation:\d+)*\s*[пј‰\)]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(citation:\d+\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"citation:\d+(?:,\s*citation:\d+)*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\d+\]", "", cleaned)
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_reasoning_and_content(text: str):
    raw = str(text or "")
    reasoning_parts = []

    for match in re.finditer(r"<think[^>]*>([\s\S]*?)</think(?:gt;)?>", raw, flags=re.IGNORECASE):
        reasoning_parts.append(match.group(1))

    content = re.sub(r"<think[^>]*>[\s\S]*?</think(?:gt;)?>", "", raw, flags=re.IGNORECASE)
    open_index = content.lower().find("<think")
    if open_index >= 0:
        content = content[:open_index]

    reasoning = _strip_citations("".join(reasoning_parts))
    content = _strip_citations(content)
    return reasoning, content


def _request_headers(credentials: dict):
    headers = dict(DEFAULT_HEADERS)
    headers["Cookie"] = credentials.get("cookie") or (
        f"serviceToken={credentials['service_token']}; "
        f"userId={credentials['user_id']}; "
        f"xiaomichatbot_ph={credentials['ph_token']}"
    )
    return headers


def _request_body(payload: dict):
    request_model = payload.get("model") or SUPPORTED_MODELS[0]
    model = map_model(request_model)
    request_model_lower = str(request_model or "").lower()
    enable_thinking = bool(payload.get("reasoning_effort")) or "think" in request_model_lower or "r1" in request_model_lower
    temperature = payload.get("temperature")
    if temperature is None:
        temperature = 0.8
    top_p = payload.get("top_p")
    if top_p is None:
        top_p = 0.95

    body = {
        "msgId": uuid.uuid4().hex,
        "conversationId": uuid.uuid4().hex,
        "query": _latest_user_text(payload.get("messages") or []),
        "isEditedQuery": False,
        "modelConfig": {
            "enableThinking": enable_thinking,
            "webSearchStatus": "disabled",
            "model": model,
            "temperature": temperature,
            "topP": top_p,
        },
        "multiMedias": [],
    }
    return model, body


def _raise_for_status(response, provider_name: str):
    if response.status_code == 200:
        return
    try:
        detail = response.text
    except Exception:
        detail = ""
    detail = (detail or "").strip()
    if len(detail) > 600:
        detail = detail[:600] + "..."
    if detail:
        raise RuntimeError(f"{provider_name} upstream failed: HTTP {response.status_code} {detail}")
    raise RuntimeError(f"{provider_name} upstream failed: HTTP {response.status_code}")


def chat_completion(credentials: dict, payload: dict):
    model, body = _request_body(payload)
    url = f"{MIMO_BASE}/open-apis/bot/chat?xiaomichatbot_ph={quote(credentials['ph_token'], safe='')}"
    headers = _request_headers(credentials)
    verify = _tls_verify()

    if curl_requests is not None:
        request_kwargs = {
            "headers": headers,
            "json": body,
            "stream": True,
            "impersonate": os.environ.get("MIMO_IMPERSONATE", "chrome136"),
            "timeout": 120,
            "verify": verify,
        }
        curl_options = _curl_options_for_host("aistudio.xiaomimimo.com")
        if curl_options:
            request_kwargs["curl_options"] = curl_options
        response = curl_requests.post(url, **request_kwargs)
        transport = "curl_cffi"
    else:
        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=120,
            stream=True,
            verify=verify,
        )
        transport = "requests"

    _raise_for_status(response, "Mimo")
    debug_log(
        "mimo_chat_started",
        model=model,
        conversation_id=body["conversationId"],
        prompt_length=len(body["query"]),
        thinking=body["modelConfig"]["enableThinking"],
        transport=transport,
    )
    return response, body["conversationId"], model


def _iter_sse_events(response):
    current_event = ""

    def _yield_lines():
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                yield raw_line
            return
        except TypeError:
            pass
        except NotImplementedError:
            pass

        try:
            for raw_line in response.iter_lines():
                yield raw_line
            return
        except NotImplementedError:
            pass

        for raw_line in str(getattr(response, "text", "") or "").splitlines():
            yield raw_line

    for raw in _yield_lines():
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        line = raw.strip()
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue
        yield current_event, data


def _collect_stream(response):
    content_parts = []
    usage = {}
    dialog_id = ""

    for event_name, data in _iter_sse_events(response):
        if event_name in {"message", "text"} and data.get("content"):
            content_parts.append(str(data.get("content", "")))
            continue
        if event_name == "usage" and isinstance(data, dict):
            usage = data
            continue
        if event_name == "dialogId" and data.get("content"):
            dialog_id = str(data.get("content", ""))

    return "".join(content_parts), usage, dialog_id


def complete_non_stream(credentials: dict, payload: dict):
    response, conversation_id, model = chat_completion(credentials, payload)
    try:
        raw_text, usage, dialog_id = _collect_stream(response)
    finally:
        response.close()

    reasoning, content = _extract_reasoning_and_content(raw_text)
    if not content and raw_text and not reasoning:
        content = _strip_citations(raw_text)

    message = {
        "role": "assistant",
        "content": content,
    }
    if reasoning:
        message["reasoning_content"] = reasoning

    response_id = dialog_id or conversation_id
    result = {
        "id": response_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": int(usage.get("promptTokens", 0) or 0),
            "completion_tokens": int(usage.get("completionTokens", 0) or 0),
            "total_tokens": int(usage.get("totalTokens", 0) or 0),
        },
    }

    meta = {
        "chat_id": response_id,
        "conversation_id": conversation_id,
        "model": model,
        "provider": "mimo",
        "content_length": len(content),
        "reasoning_length": len(message.get("reasoning_content", "")),
        "empty_content": not bool(content),
    }
    debug_log("mimo_non_stream_done", **meta)
    return result, meta
