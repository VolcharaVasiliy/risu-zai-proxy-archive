try:
    from py.credentials_bootstrap import load_credentials_env
except ImportError:
    from credentials_bootstrap import load_credentials_env

load_credentials_env()

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
from urllib.parse import parse_qs, urlparse

from http_helpers import proxy_auth_error, proxy_authorized, read_json_body, send_json
from provider_registry import (
    complete_non_stream,
    models_payload,
    provider_status_payload,
    doctor_payload,
    ProviderAuthError,
    ProviderRateLimitError,
    provider_error_hint,
    raise_provider_auth_if_needed,
    raise_provider_rate_limit_if_needed,
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
try:
    from py.observability import elapsed_ms, header_summary, log_event, log_exception, request_context, request_id
except ImportError:
    from observability import elapsed_ms, header_summary, log_event, log_exception, request_context, request_id


def sse_frame(event, response_format: str = "chat") -> bytes:
    event_name = ""
    if response_format == "response" and isinstance(event, dict):
        event_name = str(event.get("type") or "").strip()
    prefix = f"event: {event_name}\n" if event_name else ""
    return f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def sse_error_frame(message: str, error_type: str = "server_error") -> bytes:
    return sse_frame({"error": {"message": message, "type": error_type, "request_id": request_id()}})


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self._request_started = time.perf_counter()
        self._last_response_status = None
        self._observability_fields = {}
        self._stream_chunk_count = 0

    def parse_request(self):
        parsed = super().parse_request()
        if parsed:
            self._request_context = request_context(self.headers.get("X-Request-ID", ""))
            self.request_id = self._request_context.__enter__()
            log_event(
                "http_request_started",
                level="info",
                method=self.command,
                path=self.path.split("?", 1)[0],
                headers=header_summary(self.headers),
            )
        return parsed

    def _finish_log(self):
        if not hasattr(self, "_request_context"):
            return
        log_event(
            "http_request_finished",
            level="info",
            method=getattr(self, "command", ""),
            path=getattr(self, "path", "").split("?", 1)[0],
            status=self._last_response_status,
            duration_ms=elapsed_ms(self._request_started),
            stream_chunks=self._stream_chunk_count,
            **self._observability_fields,
        )
        self._request_context.__exit__(None, None, None)

    def finish(self):
        try:
            self._finish_log()
        finally:
            super().finish()

    def send_response(self, code, message=None):
        self._last_response_status = int(code)
        return super().send_response(code, message)

    def _request_path(self):
        return self.path.split("?", 1)[0]

    def _query_value(self, name):
        values = parse_qs(urlparse(self.path).query).get(name, [])
        return values[0] if values else ""

    def do_GET(self):
        request_path = self._request_path()
        if request_path == "/health":
            return send_json(self, 200, {"ok": True})
        if request_path == "/doctor":
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            runtime = self._query_value("runtime")
            status = provider_status_payload(runtime)
            if not status["runtime_valid"]:
                return send_json(self, 400, {"error": {"message": "Unsupported runtime", "runtime": runtime, "supported": status["supported_runtimes"]}})
            return send_json(self, 200, doctor_payload(runtime))
        if request_path == "/v1/models":
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            return send_json(self, 200, models_payload())
        if request_path == "/v1/providers":
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            runtime = self._query_value("runtime")
            status = provider_status_payload(runtime)
            if not status["runtime_valid"]:
                return send_json(self, 400, {"error": {"message": "Unsupported runtime", "runtime": runtime, "supported": status["supported_runtimes"]}})
            return send_json(self, 200, status)
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
            "/java/api/v1",
            "/java/api/v1/chat/completions",
            "/java/v1",
            "/java/v1/chat/completions",
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
            "/java/api/v1",
            "/java/api/v1/chat/completions",
            "/java/v1",
            "/java/v1/chat/completions",
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
                        "type": "authentication_error",
                    }
                },
            )

        self._observability_fields.update(
            {
                "provider": provider_id,
                "model": payload.get("model"),
                "stream": payload.get("stream", True) is not False,
            }
        )

        if request_path in {
            "/java/api/v1",
            "/java/api/v1/chat/completions",
            "/java/v1",
            "/java/v1/chat/completions",
        }:
            payload["stream"] = False

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
                self.send_header("X-Request-ID", request_id())
                self.end_headers()
                stream_started = True

                if first_event is not None:
                    self.wfile.write(sse_frame(first_event, response_format))
                    self.wfile.flush()
                    self._stream_chunk_count += 1

                for event in iterator:
                    self.wfile.write(sse_frame(event, response_format))
                    self.wfile.flush()
                    self._stream_chunk_count += 1
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self._observability_fields["stream_outcome"] = "complete"
                self.close_connection = True
                return

            if payload.get("stream") is False:
                result, _meta = complete_non_stream(provider_id, credentials, payload)
                if request_path in {
                    "/java/api/v1",
                    "/java/api/v1/chat/completions",
                    "/java/v1",
                    "/java/v1/chat/completions",
                }:
                    choices = result.get("choices") or [{}]
                    message = (choices[0] or {}).get("message") or {}
                    text_response = (message.get("content") or "").strip()
                    
                    try:
                        content_json = json.loads(text_response)
                        if not isinstance(content_json, dict):
                            raise ValueError()
                    except Exception:
                        content_json = {}

                    keys_to_populate = ["chat_text", "tts_text", "response", "text", "message", "content"]
                    
                    fallback_val = None
                    for key in keys_to_populate:
                        if key in content_json and content_json[key]:
                            fallback_val = content_json[key]
                            break
                    if not fallback_val:
                        fallback_val = text_response

                    for key in keys_to_populate:
                        if key not in content_json or not content_json[key]:
                            content_json[key] = fallback_val

                    message["content"] = json.dumps(content_json, ensure_ascii=False)

                    result["chat_text"] = fallback_val
                    result["tts_text"] = fallback_val
                    result["response"] = fallback_val
                    result["text"] = fallback_val
                    result["message"] = fallback_val
                    result["content"] = fallback_val
                    return send_json(self, 200, result)
                return send_json(self, 200, result)

            iterator = iter(stream_chunks(provider_id, credentials, payload))
            first_chunk = next(iterator, None)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.send_header("X-Request-ID", request_id())
            self.end_headers()
            stream_started = True

            if first_chunk is not None:
                self.wfile.write(
                    f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode(
                        "utf-8"
                    )
                )
                self.wfile.flush()
                self._stream_chunk_count += 1

            for chunk in iterator:
                self.wfile.write(
                    f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
                self._stream_chunk_count += 1
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self._observability_fields["stream_outcome"] = "complete"
            self.close_connection = True
        except BrokenPipeError:
            self._observability_fields["stream_outcome"] = "client_closed"
            log_event(
                "http_stream_aborted",
                level="info",
                provider=self._observability_fields.get("provider", ""),
                chunks=self._stream_chunk_count,
            )
            return
        except ProviderAuthError as exc:
            if stream_started:
                self._observability_fields["stream_outcome"] = "provider_auth_error"
                try:
                    self.wfile.write(sse_error_frame(str(exc), "authentication_error"))
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    pass
                return
            return send_json(
                self,
                401,
                {"error": {"message": str(exc), "type": "authentication_error"}},
            )
        except ProviderRateLimitError as exc:
            if stream_started:
                self._observability_fields["stream_outcome"] = "provider_rate_limit"
                try:
                    self.wfile.write(sse_error_frame(str(exc), "rate_limit_error"))
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    pass
                return
            return send_json(
                self,
                429,
                {"error": {"message": str(exc), "type": "rate_limit_error"}},
            )
        except Exception as exc:
            log_exception("local_request_error", exc, provider=provider_id)
            if stream_started:
                self._observability_fields["stream_outcome"] = "error"
                try:
                    self.wfile.write(
                        sse_error_frame(
                            "Provider request failed; inspect server logs with the X-Request-ID",
                            "server_error",
                        )
                    )
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    pass
                return
            try:
                raise_provider_rate_limit_if_needed(provider_id, exc)
            except ProviderRateLimitError as rate_exc:
                return send_json(
                    self,
                    429,
                    {
                        "error": {
                            "message": str(rate_exc),
                            "type": "rate_limit_error",
                        }
                    },
                )
            try:
                raise_provider_auth_if_needed(provider_id, exc)
            except ProviderAuthError as auth_exc:
                return send_json(
                    self,
                    401,
                    {
                        "error": {
                            "message": str(auth_exc),
                            "type": "authentication_error",
                        }
                    },
                )
            return send_json(
                self,
                502,
                {
                    "error": {
                        "message": "Provider request failed; inspect server logs with the X-Request-ID",
                        "type": "server_error",
                    }
                },
            )


if __name__ == "__main__":
    import os

    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", "3001") or "3001")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Risu multi-provider Python proxy listening on http://{host}:{port}")
    server.serve_forever()
