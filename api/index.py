import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py.credentials_bootstrap import load_credentials_env

load_credentials_env()

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from py.http_helpers import read_json_body, send_json
from py.provider_registry import complete_non_stream, models_payload, provider_error_hint, resolve_credentials, resolve_provider_id, stream_chunks
from py.zai_proxy import debug_log


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

        send_json(self, 404, {"error": {"message": "Not found"}})

    def do_POST(self):
        route = self._route()
        if route != "chat":
            send_json(self, 404, {"error": {"message": "Not found"}})
            return

        try:
            payload = read_json_body(self)
            payload["conversation_id"] = payload.get("conversation_id") or self.headers.get("x-conversation-id", "")
        except Exception:
            send_json(self, 400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})
            return

        if not payload.get("model"):
            send_json(self, 400, {"error": {"message": "model is required", "type": "invalid_request_error"}})
            return

        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            send_json(self, 400, {"error": {"message": "messages must be a non-empty array", "type": "invalid_request_error"}})
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
                self.wfile.write(f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            for chunk in iterator:
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
