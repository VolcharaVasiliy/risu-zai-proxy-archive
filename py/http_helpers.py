import json
import os
from http import cookies


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def send_json(handler, status, payload):
    body = json_bytes(payload)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def bearer_token(handler):
    env_value = os.environ.get("ZAI_TOKEN", "").strip()
    if env_value:
        return env_value

    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token and token != configured_proxy_api_key():
            return token

    alt = handler.headers.get("x-zai-token", "").strip()
    return alt


def read_json_body(handler):
    raw = handler.rfile.read(int(handler.headers.get("Content-Length", "0") or "0"))
    return json.loads(raw.decode("utf-8") if raw else "{}")


def header_token(handler, *header_names):
    for name in header_names:
        value = handler.headers.get(name, "").strip()
        if value:
            return value
    return ""


def configured_proxy_api_key() -> str:
    return env_token("PROXY_API_KEY", "RISU_PROXY_API_KEY")


def header_bearer_token(handler, include_proxy_key: bool = False):
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return ""
    token = auth[7:].strip()
    if not include_proxy_key and token and token == configured_proxy_api_key():
        return ""
    return token


def env_token(*env_names):
    for name in env_names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def env_or_header_token(handler, env_names, header_names=()):
    token = env_token(*env_names)
    if token:
        return token

    token = header_token(handler, *header_names)
    if token:
        return token

    return header_bearer_token(handler)


def proxy_authorized(handler) -> bool:
    expected = configured_proxy_api_key()
    if not expected:
        return True

    presented = header_bearer_token(handler, include_proxy_key=True) or header_token(
        handler,
        "x-api-key",
        "x-proxy-api-key",
        "x-risu-proxy-api-key",
    )
    return bool(presented and presented == expected)


def proxy_auth_error() -> dict:
    return {
        "error": {
            "message": "Proxy API key is required",
            "type": "authentication_error",
        }
    }


def cookie_value(cookie_header: str, cookie_name: str) -> str:
    raw = str(cookie_header or "").strip()
    if not raw:
        return ""

    jar = cookies.SimpleCookie()
    try:
        jar.load(raw)
    except Exception:
        return ""

    morsel = jar.get(cookie_name)
    if not morsel:
        return ""
    return morsel.value.strip()
