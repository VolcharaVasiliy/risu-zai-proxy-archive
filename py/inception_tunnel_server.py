import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from py import inception_proxy
except ImportError:
    import inception_proxy


def env_token(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip()


def header_token(handler: BaseHTTPRequestHandler, name: str) -> str:
    return str(handler.headers.get(name, "") or "").strip()


def send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def model_payload() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": 0,
                "owned_by": inception_proxy.OWNED_BY,
                "provider": "inception",
                "requires_env": ["INCEPTION_SESSION_TOKEN", "INCEPTION_COOKIE (optional)"],
            }
            for model in inception_proxy.SUPPORTED_MODELS
        ],
    }


def resolve_credentials(handler: BaseHTTPRequestHandler) -> dict | None:
    cookie = env_token("INCEPTION_COOKIE") or header_token(handler, "x-inception-cookie")
    session_token = env_token("INCEPTION_SESSION_TOKEN") or header_token(handler, "x-inception-session-token")

    if not session_token and cookie:
        for part in cookie.split(";"):
            key, sep, value = part.partition("=")
            if sep and key.strip() == "session":
                session_token = value.strip()
                break

    if not cookie and session_token:
        cookie = f"session={session_token}"

    return {"cookie": cookie, "session_token": session_token} if session_token else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            return send_json(self, 200, {"ok": True, "provider": "inception", "transport": "local-tunnel"})
        if self.path == "/v1/models":
            return send_json(self, 200, model_payload())
        return send_json(self, 404, {"error": {"message": "Not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return send_json(self, 404, {"error": {"message": "Not found"}})

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw)
        except Exception:
            return send_json(self, 400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}})

        if not payload.get("model"):
            return send_json(self, 400, {"error": {"message": "model is required", "type": "invalid_request_error"}})
        if not inception_proxy.supports_model(payload.get("model")):
            return send_json(
                self,
                400,
                {"error": {"message": f"Unsupported model: {payload.get('model')}", "type": "invalid_request_error"}},
            )
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            return send_json(self, 400, {"error": {"message": "messages must be a non-empty array", "type": "invalid_request_error"}})

        credentials = resolve_credentials(self)
        if not credentials:
            return send_json(
                self,
                401,
                {
                    "error": {
                        "message": "Configure INCEPTION_SESSION_TOKEN and optional INCEPTION_COOKIE, or pass x-inception-* headers",
                        "type": "invalid_request_error",
                    }
                },
            )

        body = dict(payload)
        body["stream"] = False

        try:
            result, meta = inception_proxy.complete_non_stream(credentials, body)
            result.setdefault("provider", "inception")
            result.setdefault("transport", meta.get("transport", "local-direct"))
            return send_json(self, 200, result)
        except Exception as exc:
            return send_json(self, 502, {"error": {"message": str(exc), "type": "invalid_request_error"}})


if __name__ == "__main__":
    host = env_token("INCEPTION_TUNNEL_HOST") or "127.0.0.1"
    port = int(env_token("INCEPTION_TUNNEL_PORT") or "3001")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Inception tunnel server listening on http://{host}:{port}")
    server.serve_forever()
