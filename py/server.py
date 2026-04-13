import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from http_helpers import read_json_body, send_json
from provider_registry import complete_non_stream, models_payload, provider_error_hint, resolve_credentials, resolve_provider_id, stream_chunks
from zai_proxy import debug_log


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            return send_json(self, 200, {"ok": True})
        if self.path == "/v1/models":
            return send_json(self, 200, models_payload())
        return send_json(self, 404, {"error": {"message": "Not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return send_json(self, 404, {"error": {"message": "Not found"}})

        try:
            payload = read_json_body(self)
        except Exception:
            return send_json(self, 400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})

        if not payload.get("model"):
            return send_json(self, 400, {"error": {"message": "model is required", "type": "invalid_request_error"}})
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            return send_json(self, 400, {"error": {"message": "messages must be a non-empty array", "type": "invalid_request_error"}})

        provider_id = resolve_provider_id(payload.get("model"))
        if not provider_id:
            return send_json(self, 400, {"error": {"message": f"Unsupported model: {payload.get('model')}", "type": "invalid_request_error"}})

        credentials = resolve_credentials(self, provider_id)
        if not credentials:
            return send_json(self, 401, {"error": {"message": provider_error_hint(provider_id), "type": "invalid_request_error"}})

        stream_started = False
        try:
            debug_log("local_api_chat_request", provider=provider_id, stream=payload.get("stream", True), model=payload.get("model"), message_count=len(payload.get("messages", [])))
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
                self.wfile.write(f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            for chunk in iterator:
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
        except BrokenPipeError:
            return
        except Exception as exc:
            if stream_started:
                return
            return send_json(self, 502, {"error": {"message": str(exc), "type": "invalid_request_error"}})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 3001), Handler)
    print("Risu multi-provider Python proxy listening on http://127.0.0.1:3001")
    server.serve_forever()
