import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py.credentials_bootstrap import load_credentials_env

load_credentials_env()

import base64
import hashlib
import hmac
import json
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

ZAI_SESSION_SECRET = hashlib.sha256(
    (os.environ.get("ZAI_TOKEN") or "zai-session-secret").encode("utf-8")
).digest()


def sse_frame(event, response_format: str = "chat") -> bytes:
    event_name = ""
    if response_format == "response" and isinstance(event, dict):
        event_name = str(event.get("type") or "").strip()
    prefix = f"event: {event_name}\n" if event_name else ""
    return f"{prefix}data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


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

        if route == "models":
            if not proxy_authorized(self):
                send_json(self, 401, proxy_auth_error())
                return
            send_json(self, 200, models_payload())
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
        if route not in {"chat", "responses", "responses-chat", "java-chat"}:
            send_json(self, 404, {"error": {"message": "Not found"}})
            return

        if not proxy_authorized(self):
            send_json(self, 401, proxy_auth_error())
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
                headers=dict(self.headers),
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

            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
        except BrokenPipeError as exc:
            debug_log(
                "api_chat_stream_closed",
                route=route,
                provider=provider_id,
                error_type=type(exc).__name__,
            )
        except ProviderAuthError as exc:
            debug_log(
                "api_chat_auth_error",
                route=route,
                provider=provider_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if stream_started:
                return
            send_json(
                self,
                401,
                {"error": {"message": str(exc), "type": "authentication_error"}},
            )
        except ProviderRateLimitError as exc:
            debug_log(
                "api_chat_rate_limit_error",
                route=route,
                provider=provider_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if stream_started:
                return
            send_json(
                self,
                429,
                {"error": {"message": str(exc), "type": "rate_limit_error"}},
            )
        except Exception as exc:
            debug_log(
                "api_chat_error",
                route=route,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if stream_started:
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
                {"error": {"message": str(exc), "type": "invalid_request_error"}},
            )
