import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py.credentials_bootstrap import load_credentials_env

load_credentials_env()

import json
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from py.http_helpers import read_json_body, send_json
from py.provider_registry import complete_non_stream, models_payload, provider_error_hint, resolve_credentials, resolve_provider_id, stream_chunks
from py.zai_proxy import debug_log


ZAI_SESSION_SECRET = hashlib.sha256(
    (os.environ.get("ZAI_TOKEN") or "zai-session-secret").encode("utf-8")
).digest()


def _zai_session_token(state):
    if not state:
        return ""
    payload = json.dumps(
        {
            "v": 1,
            "upstream_chat_id": state.get("upstream_chat_id", ""),
            "last_user_message_id": state.get("last_user_message_id", ""),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    sig = hmac.new(ZAI_SESSION_SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"zai-session.{body}.{sig}"


def _decode_zai_session_token(value):
    raw = str(value or "").strip()
    if not raw.startswith("zai-session."):
        return None
    try:
        _prefix, body, sig = raw.split(".", 2)
    except ValueError:
        return None
    expected = hmac.new(ZAI_SESSION_SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = body + "=" * ((4 - len(body) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not payload.get("upstream_chat_id") or not payload.get("last_user_message_id"):
        return None
    return payload


class handler(BaseHTTPRequestHandler):
    def _route(self):
        parsed = urlparse(self.path)
        route_values = parse_qs(parsed.query).get("route", [])
        return route_values[0] if route_values else ""

    def do_GET(self):
        route = self._route()

        if route == "health":
            send_json(self, 200, {"ok": True})
            return

        if route == "models":
            send_json(self, 200, models_payload())
            return

        if route == "responses":
            send_json(self, 404, {"error": {"message": "Not found"}})
            return

        send_json(self, 404, {"error": {"message": "Not found"}})

    def do_POST(self):
        route = self._route()
        if route not in {"chat", "responses", "responses-chat"}:
            send_json(self, 404, {"error": {"message": "Not found"}})
            return

        try:
            payload = read_json_body(self)
            # Support both conversation_id (explicit session) and chat_id (local Risu chat)
            payload["conversation_id"] = payload.get("conversation_id") or self.headers.get("x-conversation-id", "")
            payload["chat_id"] = payload.get("chat_id") or self.headers.get("x-chat-id", "")
            if resolve_provider_id(payload.get("model")) == "zai":
                token_state = _decode_zai_session_token(payload.get("conversation_id")) or _decode_zai_session_token(payload.get("chat_id"))
                if token_state:
                    payload["_zai_session_state"] = token_state
            debug_log("api_incoming_request", 
                conversation_id=payload.get("conversation_id"),
                chat_id=payload.get("chat_id"),
                model=payload.get("model"),
                message_count=len(payload.get("messages", [])),
                first_message=str(payload.get("messages", [{}])[0]).replace("\\", "")[:100] if payload.get("messages") else None,
                headers=dict(self.headers))
        except Exception:
            send_json(self, 400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})
            return

        if not payload.get("model"):
            send_json(self, 400, {"error": {"message": "model is required", "type": "invalid_request_error"}})
            return

        if route in {"chat", "responses-chat"} and (not isinstance(payload.get("messages"), list) or not payload["messages"]):
            send_json(self, 400, {"error": {"message": "messages must be a non-empty array", "type": "invalid_request_error"}})
            return

        if route in {"responses", "responses-chat"} and payload.get("input") is None and payload.get("messages") is None:
            send_json(self, 400, {"error": {"message": "input or messages is required", "type": "invalid_request_error"}})
            return

        provider_id = resolve_provider_id(payload.get("model"))
        if not provider_id:
            send_json(self, 400, {"error": {"message": f"Unsupported model: {payload.get('model')}", "type": "invalid_request_error"}})
            return

        credentials = resolve_credentials(self, provider_id)
        if not credentials:
            send_json(self, 401, {"error": {"message": provider_error_hint(provider_id), "type": "invalid_request_error"}})
            return

        stream_started = False
        try:
            debug_log("api_chat_request", route=route, provider=provider_id, stream=payload.get("stream", True), model=payload.get("model"), message_count=len(payload.get("messages", [])))
            if payload.get("stream") is False:
                result, meta = complete_non_stream(provider_id, credentials, payload)
                if provider_id == "zai":
                    continuation_state = meta.get("continuation_state") or payload.get("_zai_continuation_state") or {}
                    session_token = _zai_session_token(continuation_state)
                    if session_token:
                        result["id"] = session_token
                        result["chat_id"] = session_token
                        result["conversation_id"] = session_token
                        result["upstream_chat_id"] = meta.get("chat_id")
                else:
                    result["chat_id"] = meta.get("chat_id")
                debug_log("api_chat_response", route=route, **meta)
                send_json(self, 200, result)
                return

            iterator = iter(stream_chunks(provider_id, credentials, payload))
            first_chunk = next(iterator, None)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.end_headers()
            stream_started = True

            if first_chunk is not None:
                if provider_id == "zai":
                    continuation_state = payload.get("_zai_continuation_state") or {}
                    session_token = _zai_session_token(continuation_state)
                    upstream_chunk_id = first_chunk.get("id")
                    if session_token:
                        first_chunk["id"] = session_token
                        first_chunk["conversation_id"] = session_token
                        first_chunk["chat_id"] = session_token
                        first_chunk["upstream_chat_id"] = upstream_chunk_id
                self.wfile.write(f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            for chunk in iterator:
                if provider_id == "zai":
                    continuation_state = payload.get("_zai_continuation_state") or {}
                    session_token = _zai_session_token(continuation_state)
                    if session_token:
                        chunk["id"] = session_token
                        chunk["conversation_id"] = session_token
                        chunk["chat_id"] = session_token
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
        except BrokenPipeError as exc:
            debug_log("api_chat_stream_closed", route=route, provider=provider_id, error_type=type(exc).__name__)
        except Exception as exc:
            debug_log("api_chat_error", route=route, error_type=type(exc).__name__, error=str(exc))
            if stream_started:
                return
            send_json(self, 502, {"error": {"message": str(exc), "type": "invalid_request_error"}})
