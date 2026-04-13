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
    env_token = os.environ.get("ZAI_TOKEN", "").strip()
    if env_token:
        return env_token

    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()

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


def header_bearer_token(handler):
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


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

    token = header_bearer_token(handler)
    if token:
        return token

    return header_token(handler, *header_names)


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
