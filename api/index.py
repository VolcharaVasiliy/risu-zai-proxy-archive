import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py.credentials_bootstrap import load_credentials_env

load_credentials_env()

import base64
import hashlib
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from py.http_helpers import (
    proxy_auth_error,
    proxy_authorized,
    read_json_body,
    send_json,
)
from py.provider_registry import (
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
from py.responses_api import (
    complete_response,
    delete_stored_response,
    get_stored_response,
    stream_response_events,
)
from py.zai_proxy import debug_log
from py.observability import (
    elapsed_ms,
    header_summary,
    log_event,
    log_exception,
    request_context,
    request_id,
)
from py.metrics import metrics
from py.bridge_manager import status_payload as bridge_status

ZAI_SESSION_SECRET = hashlib.sha256(
    (os.environ.get("ZAI_TOKEN") or "zai-session-secret").encode("utf-8")
).digest()


def sse_frame(event, response_format: str = "chat") -> bytes:
    event_name = ""
    if response_format == "response" and isinstance(event, dict):
        event_name = str(event.get("type") or "").strip()
    prefix = f"event: {event_name}\n" if event_name else ""
    return f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def sse_error_frame(message: str, error_type: str = "server_error") -> bytes:
    return sse_frame({"error": {"message": message, "type": error_type, "request_id": request_id()}})


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
    expected = hmac.new(
        ZAI_SESSION_SECRET, body.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = body + "=" * ((4 - len(body) % 4) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
    except Exception:
        return None
    if not payload.get("upstream_chat_id") or not payload.get("last_user_message_id"):
        return None
    return payload


class handler(BaseHTTPRequestHandler):
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
                route=self._route(),
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
            route=self._route() if hasattr(self, "path") else "",
            status=self._last_response_status,
            duration_ms=elapsed_ms(self._request_started),
            stream_chunks=self._stream_chunk_count,
            **self._observability_fields,
        )
        metrics.observe_request(elapsed_ms(self._request_started), self._last_response_status, self._observability_fields.get("provider"), self._observability_fields.get("stream", False), self._stream_chunk_count)
        self._request_context.__exit__(None, None, None)

    def finish(self):
        try:
            self._finish_log()
        finally:
            super().finish()

    def send_response(self, code, message=None):
        self._last_response_status = int(code)
        return super().send_response(code, message)

    def _route(self):
        parsed = urlparse(self.path)
        route_values = parse_qs(parsed.query).get("route", [])
        return route_values[0] if route_values else ""

    def _route_path(self):
        parsed = urlparse(self.path)
        path_values = parse_qs(parsed.query).get("path", [])
        return path_values[0] if path_values else ""

    def do_GET(self):
        route = self._route()

        if route == "metrics":
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            if "text/plain" in self.headers.get("Accept", ""):
                body = metrics.prometheus().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return send_json(self, 200, metrics.snapshot())
        if route == "bridges":
            if not proxy_authorized(self):
                return send_json(self, 401, proxy_auth_error())
            return send_json(self, 200, {"object": "list", "data": bridge_status()})

        if route == "health":
            import time as _time
            from py.zai_captcha import (
                CAPTCHA_FILE,
                fresh_param,
                ttl_seconds,
            )

            captcha_status = {"exists": False}
            if os.path.exists(CAPTCHA_FILE):
                try:
                    with open(CAPTCHA_FILE, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    captured_at = int(payload.get("captured_at") or 0)
                    age_seconds = (
                        round(_time.time() - captured_at / 1000.0, 1)
                        if captured_at
                        else None
                    )
                    captcha_status = {
                        "exists": True,
                        "captured_at": captured_at,
                        "age_seconds": age_seconds,
                        "ttl_seconds": ttl_seconds(),
                        "expired": bool(captured_at and age_seconds is not None and age_seconds > ttl_seconds()),
                        "param_length": len(str(payload.get("captcha_verify_param") or "")),
                        "fresh": bool(fresh_param()),
                    }
                except Exception as exc:
                    captcha_status = {"exists": True, "read_error": str(exc)}
            send_json(
                self,
                200,
                {"ok": True, "captcha_file": captcha_status},
            )
            return

        if route == "openai-turnstile":
            import time as _time

            from py.openai_turnstile import (
                TURNSTILE_FILE,
                fresh_token,
                ttl_seconds,
            )

            turnstile_status = {"exists": False}
            if os.path.exists(TURNSTILE_FILE):
                try:
                    with open(TURNSTILE_FILE, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    captured_at = int(payload.get("captured_at") or 0)
                    age_seconds = (
                        round(_time.time() - captured_at / 1000.0, 1)
                        if captured_at
                        else None
                    )
                    turnstile_status = {
                        "exists": True,
                        "captured_at": captured_at,
                        "age_seconds": age_seconds,
                        "ttl_seconds": ttl_seconds(),
                        "expired": bool(
                            captured_at
                            and ttl_seconds() > 0
                            and age_seconds is not None
                            and age_seconds > ttl_seconds()
                        ),
                        "token_length": len(str(payload.get("turnstile_token") or "")),
                        "fresh": bool(fresh_token()),
                    }
                except Exception as exc:
                    turnstile_status = {"exists": True, "read_error": str(exc)}
            send_json(
                self,
                200,
                {"ok": True, "openai_turnstile_file": turnstile_status},
            )
            return

        if route == "grok-cf-clearance":
            import time as _time

            from py.grok_proxy import CLEARANCE_FILE, fresh_cf_clearance

            status = {"exists": False}
            if os.path.exists(CLEARANCE_FILE):
                try:
                    with open(CLEARANCE_FILE, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    captured_at = int(payload.get("captured_at") or 0)
                    age_seconds = (
                        round(_time.time() - captured_at / 1000.0, 1)
                        if captured_at
                        else None
                    )
                    status = {
                        "exists": True,
                        "captured_at": captured_at,
                        "age_seconds": age_seconds,
                        "token_length": len(str(payload.get("cf_clearance") or "")),
                        "fresh": bool(fresh_cf_clearance()),
                    }
                except Exception as exc:
                    status = {"exists": True, "read_error": str(exc)}
            send_json(self, 200, {"ok": True, "grok_cf_clearance_file": status})
            return

        if route == "lmarena-recaptcha":
            import time as _time

            from py.lmarena_captcha import RECAPTCHA_FILE, fresh_token, ttl_seconds

            status = {"exists": False}
            if os.path.exists(RECAPTCHA_FILE):
                try:
                    with open(RECAPTCHA_FILE, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    captured_at = int(payload.get("captured_at") or 0)
                    age_seconds = (
                        round(_time.time() - captured_at / 1000.0, 1)
                        if captured_at
                        else None
                    )
                    status = {
                        "exists": True,
                        "captured_at": captured_at,
                        "age_seconds": age_seconds,
                        "ttl_seconds": ttl_seconds(),
                        "expired": bool(
                            captured_at
                            and ttl_seconds() > 0
                            and age_seconds is not None
                            and age_seconds > ttl_seconds()
                        ),
                        "token_length": len(str(payload.get("token") or "")),
                        "fresh": bool(fresh_token()),
                    }
                except Exception as exc:
                    status = {"exists": True, "read_error": str(exc)}
            send_json(self, 200, {"ok": True, "lmarena_recaptcha_file": status})
            return

        if route == "models":
            if not proxy_authorized(self):
                send_json(self, 401, proxy_auth_error())
                return
            send_json(self, 200, models_payload())
            return

        if route == "doctor":
            if not proxy_authorized(self):
                send_json(self, 401, proxy_auth_error())
                return
            runtime_values = parse_qs(urlparse(self.path).query).get("runtime", [])
            runtime = runtime_values[0] if runtime_values else ""
            status = provider_status_payload(runtime)
            if not status["runtime_valid"]:
                send_json(self, 400, {"error": {"message": "Unsupported runtime", "runtime": runtime, "supported": status["supported_runtimes"]}})
                return
            send_json(self, 200, doctor_payload(runtime))
            return

        if route == "providers":
            if not proxy_authorized(self):
                send_json(self, 401, proxy_auth_error())
                return
            runtime_values = parse_qs(urlparse(self.path).query).get("runtime", [])
            runtime = runtime_values[0] if runtime_values else ""
            status = provider_status_payload(runtime)
            if not status["runtime_valid"]:
                send_json(self, 400, {"error": {"message": "Unsupported runtime", "runtime": runtime, "supported": status["supported_runtimes"]}})
                return
            send_json(self, 200, status)
            return

        if route == "responses":
            if not proxy_authorized(self):
                send_json(self, 401, proxy_auth_error())
                return
            response_id = self._route_path().strip("/")
            if not response_id:
                send_json(self, 404, {"error": {"message": "Not found"}})
                return
            response = get_stored_response(response_id)
            if not response:
                send_json(self, 404, {"error": {"message": "Response not found"}})
                return
            send_json(self, 200, response)
            return

        send_json(self, 404, {"error": {"message": "Not found"}})

    def do_DELETE(self):
        route = self._route()
        if route != "responses":
            send_json(self, 404, {"error": {"message": "Not found"}})
            return
        if not proxy_authorized(self):
            send_json(self, 401, proxy_auth_error())
            return
        response_id = self._route_path().strip("/")
        if not response_id:
            send_json(self, 404, {"error": {"message": "Not found"}})
            return
        deleted = delete_stored_response(response_id)
        send_json(
            self,
            200 if deleted else 404,
            {"id": response_id, "object": "response.deleted", "deleted": deleted},
        )

    def do_POST(self):
        route = self._route()
        if route not in {"chat", "responses", "responses-chat", "java-chat", "openai-turnstile", "grok-cf-clearance", "lmarena-recaptcha"}:
            send_json(self, 404, {"error": {"message": "Not found"}})
            return

        if not proxy_authorized(self):
            send_json(self, 401, proxy_auth_error())
            return

        if route == "openai-turnstile":
            import time as _time

            from py.openai_turnstile import TURNSTILE_FILE

            try:
                body = read_json_body(self)
            except Exception:
                send_json(self, 400, {"error": {"message": "Invalid JSON body"}})
                return
            token = str((body or {}).get("turnstile_token") or "").strip()
            if not token:
                send_json(self, 400, {"error": {"message": "turnstile_token is required"}})
                return
            payload = {
                "turnstile_token": token,
                "captured_at": int((body or {}).get("captured_at") or _time.time() * 1000),
            }
            proof = str((body or {}).get("proof_token") or "").strip()
            if proof:
                payload["proof_token"] = proof
            try:
                with open(TURNSTILE_FILE, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                send_json(
                    self,
                    200,
                    {"ok": True, "written": TURNSTILE_FILE, "token_length": len(token)},
                )
            except Exception as exc:
                send_json(self, 500, {"ok": False, "error": str(exc)})
            return

        if route == "grok-cf-clearance":
            import time as _time

            from py.grok_proxy import CLEARANCE_FILE

            try:
                body = read_json_body(self)
            except Exception:
                send_json(self, 400, {"error": {"message": "Invalid JSON body"}})
                return
            token = str((body or {}).get("cf_clearance") or "").strip()
            if not token:
                send_json(self, 400, {"error": {"message": "cf_clearance is required"}})
                return
            payload = {
                "cf_clearance": token,
                "captured_at": int((body or {}).get("captured_at") or _time.time() * 1000),
            }
            try:
                with open(CLEARANCE_FILE, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                send_json(
                    self,
                    200,
                    {"ok": True, "written": CLEARANCE_FILE, "token_length": len(token)},
                )
            except Exception as exc:
                send_json(self, 500, {"ok": False, "error": str(exc)})
            return

        if route == "lmarena-recaptcha":
            import time as _time

            from py.lmarena_captcha import RECAPTCHA_FILE

            try:
                body = read_json_body(self)
            except Exception:
                send_json(self, 400, {"error": {"message": "Invalid JSON body"}})
                return
            token = str((body or {}).get("token") or "").strip()
            if not token:
                send_json(self, 400, {"error": {"message": "token is required"}})
                return
            payload = {
                "token": token,
                "captured_at": int((body or {}).get("captured_at") or _time.time() * 1000),
            }
            try:
                with open(RECAPTCHA_FILE, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                send_json(
                    self,
                    200,
                    {"ok": True, "written": RECAPTCHA_FILE, "token_length": len(token)},
                )
            except Exception as exc:
                send_json(self, 500, {"ok": False, "error": str(exc)})
            return

        try:
            payload = read_json_body(self)
            # Support both conversation_id (explicit session) and chat_id (local Risu chat)
            payload["conversation_id"] = payload.get(
                "conversation_id"
            ) or self.headers.get("x-conversation-id", "")
            payload["chat_id"] = payload.get("chat_id") or self.headers.get(
                "x-chat-id", ""
            )
            if resolve_provider_id(payload.get("model")) == "zai":
                token_state = _decode_zai_session_token(
                    payload.get("conversation_id")
                ) or _decode_zai_session_token(payload.get("chat_id"))
                if token_state:
                    payload["_zai_session_state"] = token_state
            debug_log(
                "api_incoming_request",
                conversation_id=payload.get("conversation_id"),
                chat_id=payload.get("chat_id"),
                model=payload.get("model"),
                message_count=len(payload.get("messages", [])),
                first_message=str(payload.get("messages", [{}])[0]).replace("\\", "")[
                    :100
                ]
                if payload.get("messages")
                else None,
                headers=header_summary(self.headers),
            )
        except Exception:
            send_json(
                self,
                400,
                {
                    "error": {
                        "message": "Invalid JSON body",
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        if not payload.get("model"):
            send_json(
                self,
                400,
                {
                    "error": {
                        "message": "model is required",
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        if route in {"chat", "responses-chat", "java-chat"} and (
            not isinstance(payload.get("messages"), list) or not payload["messages"]
        ):
            send_json(
                self,
                400,
                {
                    "error": {
                        "message": "messages must be a non-empty array",
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        if (
            route in {"responses", "responses-chat"}
            and payload.get("input") is None
            and payload.get("messages") is None
        ):
            send_json(
                self,
                400,
                {
                    "error": {
                        "message": "input or messages is required",
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        provider_id = resolve_provider_id(payload.get("model"))
        if not provider_id:
            send_json(
                self,
                400,
                {
                    "error": {
                        "message": f"Unsupported model: {payload.get('model')}",
                        "type": "invalid_request_error",
                    }
                },
            )
            return

        credentials = resolve_credentials(self, provider_id)
        if not credentials:
            send_json(
                self,
                401,
                {
                    "error": {
                        "message": provider_error_hint(provider_id),
                        "type": "authentication_error",
                    }
                },
            )
            return

        self._observability_fields.update(
            {
                "provider": provider_id,
                "model": payload.get("model"),
                "stream": payload.get("stream", True) is not False,
            }
        )

        if route == "java-chat":
            payload["stream"] = False

        stream_started = False
        try:
            debug_log(
                "api_chat_request",
                route=route,
                provider=provider_id,
                stream=payload.get("stream", True),
                model=payload.get("model"),
                message_count=len(payload.get("messages", [])),
            )
            if route in {"responses", "responses-chat"}:
                response_format = "response" if route == "responses" else "chat"
                if payload.get("stream") is False:
                    result, meta = complete_response(
                        provider_id,
                        credentials,
                        payload,
                        response_format=response_format,
                    )
                    debug_log("api_chat_response", route=route, **meta)
                    send_json(self, 200, result)
                    return

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
                result, meta = complete_non_stream(provider_id, credentials, payload)
                if provider_id == "zai":
                    continuation_state = (
                        meta.get("continuation_state")
                        or payload.get("_zai_continuation_state")
                        or {}
                    )
                    session_token = _zai_session_token(continuation_state)
                    if session_token:
                        result["id"] = session_token
                        result["chat_id"] = session_token
                        result["conversation_id"] = session_token
                        result["upstream_chat_id"] = meta.get("chat_id")
                else:
                    result["chat_id"] = meta.get("chat_id")
                debug_log("api_chat_response", route=route, **meta)
                if route == "java-chat":
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
                    send_json(self, 200, result)
                    return
                send_json(self, 200, result)
                return

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
                if provider_id == "zai":
                    continuation_state = payload.get("_zai_continuation_state") or {}
                    session_token = _zai_session_token(continuation_state)
                    upstream_chunk_id = first_chunk.get("id")
                    if session_token:
                        first_chunk["id"] = session_token
                        first_chunk["conversation_id"] = session_token
                        first_chunk["chat_id"] = session_token
                        first_chunk["upstream_chat_id"] = upstream_chunk_id
                self.wfile.write(
                    f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n".encode(
                        "utf-8"
                    )
                )
                self.wfile.flush()
                self._stream_chunk_count += 1

            for chunk in iterator:
                if provider_id == "zai":
                    continuation_state = payload.get("_zai_continuation_state") or {}
                    session_token = _zai_session_token(continuation_state)
                    if session_token:
                        chunk["id"] = session_token
                        chunk["conversation_id"] = session_token
                        chunk["chat_id"] = session_token
                self.wfile.write(
                    f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
                self._stream_chunk_count += 1

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self._observability_fields["stream_outcome"] = "complete"
            self.close_connection = True
        except BrokenPipeError as exc:
            self._observability_fields["stream_outcome"] = "client_closed"
            log_event(
                "http_stream_aborted",
                level="info",
                route=route,
                provider=self._observability_fields.get("provider", ""),
                chunks=self._stream_chunk_count,
            )
            debug_log(
                "api_chat_stream_closed",
                route=route,
                provider=provider_id,
                error_type=type(exc).__name__,
            )
        except ProviderAuthError as exc:
            self._observability_fields["stream_outcome"] = "provider_auth_error"
            debug_log(
                "api_chat_auth_error",
                route=route,
                provider=provider_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if stream_started:
                try:
                    self.wfile.write(sse_error_frame(str(exc), "authentication_error"))
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    pass
                return
            send_json(
                self,
                401,
                {"error": {"message": str(exc), "type": "authentication_error"}},
            )
        except ProviderRateLimitError as exc:
            self._observability_fields["stream_outcome"] = "provider_rate_limit"
            debug_log(
                "api_chat_rate_limit_error",
                route=route,
                provider=provider_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if stream_started:
                try:
                    self.wfile.write(sse_error_frame(str(exc), "rate_limit_error"))
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    pass
                return
            send_json(
                self,
                429,
                {"error": {"message": str(exc), "type": "rate_limit_error"}},
            )
        except Exception as exc:
            log_exception(
                "api_request_error",
                exc,
                route=route,
                provider=locals().get("provider_id", ""),
            )
            debug_log(
                "api_chat_error",
                route=route,
                error_type=type(exc).__name__,
            )
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
                send_json(
                    self,
                    429,
                    {
                        "error": {
                            "message": str(rate_exc),
                            "type": "rate_limit_error",
                        }
                    },
                )
                return
            try:
                raise_provider_auth_if_needed(provider_id, exc)
            except ProviderAuthError as auth_exc:
                send_json(
                    self,
                    401,
                    {
                        "error": {
                            "message": str(auth_exc),
                            "type": "authentication_error",
                        }
                    },
                )
                return
            send_json(
                self,
                502,
                {
                    "error": {
                        "message": "Provider request failed; inspect server logs with the X-Request-ID",
                        "type": "server_error",
                    }
                },
            )
