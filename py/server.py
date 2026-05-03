try:
    from py.credentials_bootstrap import load_credentials_env
except ImportError:
    from credentials_bootstrap import load_credentials_env

load_credentials_env()

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from http_helpers import proxy_auth_error, proxy_authorized, read_json_body, send_json
from provider_registry import (
    complete_non_stream,
    models_payload,
    provider_error_hint,
    resolve_credentials,
    resolve_provider_id,
    stream_chunks,
)
from responses_api import (
    complete_response,
    delete_stored_response,
    get_stored_response,
    stream_response_events,
)
from zai_proxy import debug_log


def sse_frame(event, response_format: str = "chat") -> bytes:
    event_name = ""
    if response_format == "response" and isinstance(event, dict):
        event_name = str(event.get("type") or "").strip()
    prefix = f"event: {event_name}\n" if event_name else ""
    return f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def _request_path(self):
        return self.path.split("?", 1)[0]

    def do_GET(self):
        request_path = self._request_path()
        if request_path == "/health":
            return send_json(self, 200, {"ok": True})
        if request_path == "/v1/models":
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            return send_json(self, 200, models_payload())
        if request_path.startswith("/v1/responses/"):
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            response_id = request_path.rsplit("/", 1)[-1]
            response = get_stored_response(response_id)
            if not response:
                return send_json(
                    self, 404, {"error": {"message": "Response not found"}}
                )
            return send_json(self, 200, response)
        return send_json(self, 404, {"error": {"message": "Not found"}})

    def do_DELETE(self):
        request_path = self._request_path()
        if not request_path.startswith("/v1/responses/"):
            return send_json(self, 404, {"error": {"message": "Not found"}})
        if not proxy_authorized(self):
            return send_json(self, 401, proxy_auth_error())
        response_id = request_path.rsplit("/", 1)[-1]
        deleted = delete_stored_response(response_id)
        return send_json(
            self,
            200 if deleted else 404,
            {"id": response_id, "object": "response.deleted", "deleted": deleted},
        )

    def do_POST(self):
        request_path = self._request_path()
        if request_path not in {
            "/v1/chat/completions",
            "/v1/responses",
            "/v1/responses/chat/completions",
        }:
            return send_json(self, 404, {"error": {"message": "Not found"}})

        if not proxy_authorized(self):
            return send_json(self, 401, proxy_auth_error())

        try:
            payload = read_json_body(self)
        except Exception:
            return send_json(
                self,
                400,
                {
                    "error": {
                        "message": "Invalid JSON body",
                        "type": "invalid_request_error",
                    }
                },
            )

        if not payload.get("model"):
            return send_json(
                self,
                400,
                {
                    "error": {
                        "message": "model is required",
                        "type": "invalid_request_error",
                    }
                },
            )

        if request_path in {
            "/v1/chat/completions",
            "/v1/responses/chat/completions",
        } and (
            not isinstance(payload.get("messages"), list) or not payload["messages"]
        ):
            return send_json(
                self,
                400,
                {
                    "error": {
                        "message": "messages must be a non-empty array",
                        "type": "invalid_request_error",
                    }
                },
            )
        if (
            request_path == "/v1/responses"
            and payload.get("input") is None
            and payload.get("messages") is None
        ):
            return send_json(
                self,
                400,
                {
                    "error": {
                        "message": "input or messages is required",
                        "type": "invalid_request_error",
                    }
                },
            )

        provider_id = resolve_provider_id(payload.get("model"))
        if not provider_id:
            return send_json(
                self,
                400,
                {
                    "error": {
                        "message": f"Unsupported model: {payload.get('model')}",
                        "type": "invalid_request_error",
                    }
                },
            )

        credentials = resolve_credentials(self, provider_id)
        if not credentials:
            return send_json(
                self,
                401,
                {
                    "error": {
                        "message": provider_error_hint(provider_id),
                        "type": "invalid_request_error",
                    }
                },
            )

        stream_started = False
        try:
            debug_log(
                "local_api_chat_request",
                provider=provider_id,
                stream=payload.get("stream", True),
                model=payload.get("model"),
                message_count=len(payload.get("messages", [])),
            )
            if request_path in {"/v1/responses", "/v1/responses/chat/completions"}:
                response_format = (
                    "response" if request_path == "/v1/responses" else "chat"
                )
                if payload.get("stream") is False:
                    result, _meta = complete_response(
                        provider_id,
                        credentials,
                        payload,
                        response_format=response_format,
                    )
                    return send_json(self, 200, result)

                iterator = iter(
                    stream_response_events(
                        provider_id,
                        credentials,
                        payload,
                        response_format=response_format,
                    )
                )
                first_event = next(iterator, None)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-transform")
                self.send_header("Connection", "close")
                self.end_headers()
                stream_started = True

                if first_event is not None:
                    self.wfile.write(sse_frame(first_event, response_format))
                    self.wfile.flush()

                for event in iterator:
                    self.wfile.write(sse_frame(event, response_format))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
                return

            if payload.get("stream") is False:
                result, _meta = complete_non_stream(provider_id, credentials, payload)
                return send_json(self, 200, result)

            iterator = iter(stream_chunks(provider_id, credentials, payload))
            first_chunk = next(iterator, None)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.end_headers()
            stream_started = True

            if first_chunk is not None:
                self.wfile.write(
                    f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode(
                        "utf-8"
                    )
                )
                self.wfile.flush()

            for chunk in iterator:
                self.wfile.write(
                    f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
        except BrokenPipeError:
            return
        except Exception as exc:
            if stream_started:
                return
            return send_json(
                self,
                502,
                {"error": {"message": str(exc), "type": "invalid_request_error"}},
            )


if __name__ == "__main__":
    import os

    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", "3001") or "3001")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Risu multi-provider Python proxy listening on http://{host}:{port}")
    server.serve_forever()
