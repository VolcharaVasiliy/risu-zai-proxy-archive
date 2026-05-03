try:
    from py import (
        arcee_proxy,
        deepseek_proxy,
        gemini_web_proxy,
        grok_proxy,
        inception_proxy,
        inflection_proxy,
        kimi_proxy,
        longcat_proxy,
        mimo_proxy,
        mistral_proxy,
        openai_web_proxy,
        perplexity_proxy,
        phind_proxy,
        pi_local_proxy,
        qwen_ai_proxy,
        uncloseai_proxy,
        zai_proxy,
    )
    from py.agent_tools import (
        normalize_tool_result,
        prepare_prompt_tool_payload,
        provider_has_native_tools,
        request_config_from_payload,
        request_has_tools,
        should_use_prompt_tool_shim,
        tool_call_delta,
        tool_request_supported,
        unsupported_tool_message,
    )
    from py.http_helpers import (
        cookie_value,
        env_or_header_token,
        env_token,
        header_token,
    )
    from py.openai_stream import OpenAIStreamBuilder, openai_chunk
except ImportError:
    import arcee_proxy
    import deepseek_proxy
    import gemini_web_proxy
    import grok_proxy
    import inception_proxy
    import inflection_proxy
    import kimi_proxy
    import longcat_proxy
    import mimo_proxy
    import mistral_proxy
    import openai_web_proxy
    import perplexity_proxy
    import phind_proxy
    import pi_local_proxy
    import qwen_ai_proxy
    import uncloseai_proxy
    import zai_proxy
    from agent_tools import (
        normalize_tool_result,
        prepare_prompt_tool_payload,
        provider_has_native_tools,
        request_config_from_payload,
        request_has_tools,
        should_use_prompt_tool_shim,
        tool_call_delta,
        tool_request_supported,
        unsupported_tool_message,
    )
    from http_helpers import cookie_value, env_or_header_token, env_token, header_token
    from openai_stream import OpenAIStreamBuilder, openai_chunk

import json
import os

try:
    with open("credentials.json", "r") as f:
        credentials = json.load(f)
except FileNotFoundError:
    credentials = {}


def env_or_kv_token(key):
    return credentials.get(key, os.environ.get(key, ""))


MODEL_SPECS = []
_TOOL_CAPABILITY_PROBE = {
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "probe_tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
}


def _model_capabilities(provider_id: str) -> dict:
    native_tools = provider_has_native_tools(provider_id)
    tools_supported = tool_request_supported(provider_id, _TOOL_CAPABILITY_PROBE)
    return {
        "chat_completions": True,
        "responses": True,
        "tools": tools_supported,
        "native_tools": native_tools,
        "prompt_tool_shim": tools_supported and not native_tools,
        "streaming": True,
    }


def _add_models(provider_id: str, owned_by: str, models, requires_env):
    capabilities = _model_capabilities(provider_id)
    for model in models:
        MODEL_SPECS.append(
            {
                "id": model,
                "object": "model",
                "created": 0,
                "owned_by": owned_by,
                "provider": provider_id,
                "requires_env": list(requires_env),
                "capabilities": dict(capabilities),
            }
        )


_add_models("zai", "z.ai", zai_proxy.SUPPORTED_MODELS, ["ZAI_TOKEN"])
_add_models(
    "deepseek",
    deepseek_proxy.OWNED_BY,
    deepseek_proxy.SUPPORTED_MODELS,
    ["DEEPSEEK_TOKEN"],
)
_add_models(
    "arcee", arcee_proxy.OWNED_BY, arcee_proxy.SUPPORTED_MODELS, ["ARCEE_ACCESS_TOKEN"]
)
_add_models(
    "gemini-web",
    gemini_web_proxy.OWNED_BY,
    gemini_web_proxy.SUPPORTED_MODELS,
    [
        "GEMINI_WEB_SECURE_1PSID",
        "GEMINI_WEB_SECURE_1PSIDTS (optional)",
        "GEMINI_WEB_COOKIE (optional)",
    ],
)
_add_models("grok", grok_proxy.OWNED_BY, grok_proxy.SUPPORTED_MODELS, ["GROK_COOKIE"])
_add_models("kimi", kimi_proxy.OWNED_BY, kimi_proxy.SUPPORTED_MODELS, ["KIMI_TOKEN"])
_add_models(
    "inception",
    inception_proxy.OWNED_BY,
    inception_proxy.SUPPORTED_MODELS,
    ["INCEPTION_SESSION_TOKEN", "INCEPTION_COOKIE (optional)"],
)
_add_models(
    "longcat",
    longcat_proxy.OWNED_BY,
    longcat_proxy.SUPPORTED_MODELS,
    ["LONGCAT_COOKIE"],
)
_add_models(
    "mistral",
    mistral_proxy.OWNED_BY,
    mistral_proxy.SUPPORTED_MODELS,
    ["MISTRAL_COOKIE", "MISTRAL_CSRF_TOKEN (optional)"],
)
_add_models(
    "mimo",
    mimo_proxy.OWNED_BY,
    mimo_proxy.SUPPORTED_MODELS,
    ["MIMO_SERVICE_TOKEN", "MIMO_USER_ID", "MIMO_PH_TOKEN", "MIMO_COOKIE (optional)"],
)
_add_models(
    "openai-web",
    openai_web_proxy.OWNED_BY,
    openai_web_proxy.SUPPORTED_MODELS,
    ["OPENAI_WEB_ACCESS_TOKEN"],
)
_add_models(
    "perplexity",
    perplexity_proxy.OWNED_BY,
    perplexity_proxy.SUPPORTED_MODELS,
    ["PERPLEXITY_COOKIE"],
)
_add_models(
    "phind",
    phind_proxy.OWNED_BY,
    phind_proxy.SUPPORTED_MODELS,
    ["PHIND_COOKIE", "PHIND_NONCE (optional)"],
)
_add_models(
    "inflection",
    inflection_proxy.OWNED_BY,
    inflection_proxy.SUPPORTED_MODELS,
    ["INFLECTION_API_KEY", "PI_INFLECTION_API_KEY"],
)
_add_models("pi-local", pi_local_proxy.OWNED_BY, pi_local_proxy.SUPPORTED_MODELS, [])
_add_models(
    "qwen-ai",
    qwen_ai_proxy.OWNED_BY,
    qwen_ai_proxy.SUPPORTED_MODELS,
    ["QWEN_AI_COOKIE"],
)
_add_models("uncloseai", uncloseai_proxy.OWNED_BY, uncloseai_proxy.SUPPORTED_MODELS, [])


def models_payload():
    return {"object": "list", "data": MODEL_SPECS}


def resolve_provider_id(model: str) -> str:
    if zai_proxy.supports_model(model):
        return "zai"
    if deepseek_proxy.supports_model(model):
        return "deepseek"
    if arcee_proxy.supports_model(model):
        return "arcee"
    if gemini_web_proxy.supports_model(model):
        return "gemini-web"
    if grok_proxy.supports_model(model):
        return "grok"
    if kimi_proxy.supports_model(model):
        return "kimi"
    if inception_proxy.supports_model(model):
        return "inception"
    if longcat_proxy.supports_model(model):
        return "longcat"
    if mistral_proxy.supports_model(model):
        return "mistral"
    if mimo_proxy.supports_model(model):
        return "mimo"
    if openai_web_proxy.supports_model(model):
        return "openai-web"
    if perplexity_proxy.supports_model(model):
        return "perplexity"
    if phind_proxy.supports_model(model):
        return "phind"
    if inflection_proxy.supports_model(model):
        return "inflection"
    if pi_local_proxy.supports_model(model):
        return "pi-local"
    if qwen_ai_proxy.supports_model(model):
        return "qwen-ai"
    if uncloseai_proxy.supports_model(model):
        return "uncloseai"
    return ""


def provider_error_hint(provider_id: str) -> str:
    if provider_id == "zai":
        return "Configure ZAI_TOKEN in server env or pass the Z.ai JWT as Bearer token / x-zai-token header"
    if provider_id == "deepseek":
        return "Configure DEEPSEEK_TOKEN in server env or pass the DeepSeek userToken as Bearer token"
    if provider_id == "arcee":
        return "Configure ARCEE_ACCESS_TOKEN in server env or pass the Arcee bearer access token via Authorization / x-arcee-access-token"
    if provider_id == "gemini-web":
        return "Configure GEMINI_WEB_SECURE_1PSID plus optional GEMINI_WEB_SECURE_1PSIDTS or GEMINI_WEB_COOKIE in server env"
    if provider_id == "grok":
        return "Configure GROK_COOKIE in server env or pass GROK_SSO plus optional GROK_CF_CLEARANCE"
    if provider_id == "kimi":
        return "Configure KIMI_TOKEN in server env or pass the Kimi access token as Bearer token"
    if provider_id == "inception":
        return "Configure INCEPTION_SESSION_TOKEN in server env, optionally INCEPTION_COOKIE, or pass the Inception session cookie / x-session-token header"
    if provider_id == "longcat":
        return "Configure LONGCAT_COOKIE in server env, or pass the LongCat session cookie header"
    if provider_id == "mistral":
        return "Configure MISTRAL_COOKIE in server env, optionally MISTRAL_CSRF_TOKEN, or pass the Mistral console cookie header"
    if provider_id == "mimo":
        return "Configure MIMO_SERVICE_TOKEN, MIMO_USER_ID, and MIMO_PH_TOKEN in server env, or pass x-mimo-* headers / MIMO_COOKIE"
    if provider_id == "openai-web":
        return "Configure OPENAI_WEB_ACCESS_TOKEN or OPENAI_WEB_COOKIE in server env, or pass x-openai-web-token / x-openai-web-cookie"
    if provider_id == "perplexity":
        return "Configure PERPLEXITY_COOKIE or PERPLEXITY_SESSION_TOKEN in server env"
    if provider_id == "phind":
        return "Configure PHIND_COOKIE and optionally PHIND_NONCE in server env or pass x-phind-cookie / x-phind-nonce headers"
    if provider_id == "inflection":
        return "Configure INFLECTION_API_KEY (or PI_INFLECTION_API_KEY) from https://developers.inflection.ai/keys, or pass x-inflection-api-key"
    if provider_id == "pi-local":
        return "Run scripts\\launch-pi-auth.ps1, log in to pi.ai, and use the local Python server with the saved pi-edge-profile"
    if provider_id == "qwen-ai":
        return "Configure QWEN_AI_COOKIE in server env"
    if provider_id == "uncloseai":
        return "UncloseAI public endpoints do not require credentials"
    return "Provider credentials are not configured"


def resolve_credentials(handler, provider_id: str):
    def _normalized(value):
        text = str(value or "").strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            return text[1:-1]
        return text

    if provider_id == "zai":
        token = env_or_header_token(handler, ["ZAI_TOKEN"], ["x-zai-token"])
        return {"token": token} if token else None

    if provider_id == "deepseek":
        token = env_or_header_token(handler, ["DEEPSEEK_TOKEN"], ["x-deepseek-token"])
        return {"token": token} if token else None

    if provider_id == "arcee":
        token = env_or_header_token(
            handler, ["ARCEE_ACCESS_TOKEN"], ["x-arcee-access-token"]
        )
        session_id = env_or_kv_token("ARCEE_SESSION_ID") or header_token(
            handler, "x-arcee-session-id"
        )
        return {"token": token, "session_id": session_id} if token else None

    if provider_id == "gemini-web":
        cookie = env_or_kv_token("GEMINI_WEB_COOKIE") or header_token(
            handler, "x-gemini-web-cookie"
        )
        secure_1psid = env_or_kv_token("GEMINI_WEB_SECURE_1PSID") or header_token(
            handler, "x-gemini-web-secure-1psid"
        )
        secure_1psidts = env_or_kv_token("GEMINI_WEB_SECURE_1PSIDTS") or header_token(
            handler, "x-gemini-web-secure-1psidts"
        )

        if cookie:
            secure_1psid = secure_1psid or cookie_value(cookie, "__Secure-1PSID")
            secure_1psidts = secure_1psidts or cookie_value(cookie, "__Secure-1PSIDTS")

        if not cookie and secure_1psid:
            parts = [f"__Secure-1PSID={secure_1psid}"]
            if secure_1psidts:
                parts.append(f"__Secure-1PSIDTS={secure_1psidts}")
            cookie = "; ".join(parts)

        if not secure_1psid and not cookie:
            return None

        return {
            "cookie": cookie,
            "secure_1psid": secure_1psid,
            "secure_1psidts": secure_1psidts,
        }

    if provider_id == "grok":
        cookie = env_or_kv_token("GROK_COOKIE")
        if not cookie:
            cookie = handler.headers.get("x-grok-cookie", "").strip()

        sso = env_or_header_token(handler, ["GROK_SSO"], ["x-grok-sso"])
        if not sso and cookie:
            sso = cookie_value(cookie, "sso") or cookie_value(cookie, "sso-rw")

        cf_clearance = env_or_kv_token("GROK_CF_CLEARANCE")
        if not cf_clearance and cookie:
            cf_clearance = cookie_value(cookie, "cf_clearance")

        if not cookie and sso:
            parts = [f"sso={sso}", f"sso-rw={sso}"]
            if cf_clearance:
                parts.append(f"cf_clearance={cf_clearance}")
            cookie = "; ".join(parts)

        return (
            {"cookie": cookie, "sso": sso, "cf_clearance": cf_clearance}
            if cookie
            else None
        )

    if provider_id == "kimi":
        token = env_or_header_token(handler, ["KIMI_TOKEN"], ["x-kimi-token"])
        return {"token": token} if token else None

    if provider_id == "inception":
        cookie = env_or_kv_token("INCEPTION_COOKIE") or header_token(
            handler, "x-inception-cookie"
        )
        session_token = env_or_kv_token("INCEPTION_SESSION_TOKEN") or header_token(
            handler, "x-inception-session-token"
        )
        if not session_token and cookie:
            for part in cookie.split(";"):
                key, sep, value = part.partition("=")
                if sep and key.strip() == "session":
                    session_token = value.strip()
                    break
        if not cookie and session_token:
            cookie = f"session={session_token}"
        return (
            {"cookie": cookie, "session_token": session_token}
            if session_token
            else None
        )

    if provider_id == "longcat":
        cookie = env_or_kv_token("LONGCAT_COOKIE") or header_token(
            handler, "x-longcat-cookie"
        )
        return {"cookie": cookie} if cookie else None

    if provider_id == "mistral":
        cookie = env_or_kv_token("MISTRAL_COOKIE") or header_token(
            handler, "x-mistral-cookie"
        )
        csrf_token = env_or_kv_token("MISTRAL_CSRF_TOKEN") or header_token(
            handler, "x-mistral-csrf-token"
        )
        if not csrf_token and cookie:
            for part in cookie.split(";"):
                key, sep, value = part.partition("=")
                if sep and key.strip().startswith("csrf_token_"):
                    csrf_token = value.strip()
                    break
        return {"cookie": cookie, "csrf_token": csrf_token} if cookie else None

    if provider_id == "mimo":
        cookie = env_or_kv_token("MIMO_COOKIE") or header_token(
            handler, "x-mimo-cookie"
        )
        service_token = env_or_kv_token("MIMO_SERVICE_TOKEN") or header_token(
            handler, "x-mimo-service-token"
        )
        user_id = env_or_kv_token("MIMO_USER_ID") or header_token(
            handler, "x-mimo-user-id"
        )
        ph_token = env_or_kv_token("MIMO_PH_TOKEN") or header_token(
            handler, "x-mimo-ph-token"
        )

        if cookie:
            service_token = service_token or cookie_value(cookie, "serviceToken")
            user_id = user_id or cookie_value(cookie, "userId")
            ph_token = ph_token or cookie_value(cookie, "xiaomichatbot_ph")

        service_token = _normalized(service_token)
        user_id = _normalized(user_id)
        ph_token = _normalized(ph_token)

        if not service_token or not user_id or not ph_token:
            return None

        if not cookie:
            cookie = f"serviceToken={service_token}; userId={user_id}; xiaomichatbot_ph={ph_token}"

        return {
            "service_token": service_token,
            "user_id": user_id,
            "ph_token": ph_token,
            "cookie": cookie,
        }

    if provider_id == "openai-web":
        access_token = env_or_header_token(
            handler, ["OPENAI_WEB_ACCESS_TOKEN"], ["x-openai-web-token"]
        )
        cookie = env_or_kv_token("OPENAI_WEB_COOKIE") or header_token(
            handler, "x-openai-web-cookie"
        )
        account_id = env_or_kv_token("OPENAI_WEB_ACCOUNT_ID") or header_token(
            handler, "x-openai-web-account-id"
        )
        device_id = env_or_kv_token("OPENAI_WEB_DEVICE_ID") or header_token(
            handler, "x-openai-web-device-id"
        )
        if not access_token and not cookie:
            return None
        return {
            "access_token": access_token,
            "cookie": cookie,
            "account_id": account_id,
            "device_id": device_id,
        }

    if provider_id == "perplexity":
        cookie = env_or_kv_token("PERPLEXITY_COOKIE")
        session_token = env_or_header_token(
            handler, ["PERPLEXITY_SESSION_TOKEN"], ["x-perplexity-session"]
        )
        if not session_token and cookie:
            session_token = cookie_value(cookie, "__Secure-next-auth.session-token")
        if not cookie and session_token:
            cookie = f"__Secure-next-auth.session-token={session_token}"
        return {"cookie": cookie, "session_token": session_token} if cookie else None

    if provider_id == "phind":
        cookie = env_or_kv_token("PHIND_COOKIE")
        if not cookie:
            cookie = handler.headers.get("x-phind-cookie", "").strip()
        nonce = env_or_kv_token("PHIND_NONCE")
        if not nonce:
            nonce = handler.headers.get("x-phind-nonce", "").strip()
        return {"cookie": cookie, "nonce": nonce} if cookie else None

    if provider_id == "inflection":
        token = env_or_header_token(
            handler,
            ["INFLECTION_API_KEY", "PI_INFLECTION_API_KEY", "INFLECTION_TOKEN"],
            ["x-inflection-api-key"],
        )
        return {"token": token} if token else None

    if provider_id == "pi-local":
        return {"local": True}

    if provider_id == "qwen-ai":
        cookie = env_or_kv_token("QWEN_AI_COOKIE") or header_token(
            handler, "x-qwen-ai-cookie"
        )
        bx_umidtoken = env_or_kv_token("QWEN_AI_BX_UMIDTOKEN") or header_token(
            handler, "x-qwen-ai-bx-umidtoken"
        )
        bx_ua = env_or_kv_token("QWEN_AI_BX_UA") or header_token(
            handler, "x-qwen-ai-bx-ua"
        )
        bx_ua_create = env_or_kv_token("QWEN_AI_BX_UA_CREATE") or header_token(
            handler, "x-qwen-ai-bx-ua-create"
        )
        bx_ua_chat = env_or_kv_token("QWEN_AI_BX_UA_CHAT") or header_token(
            handler, "x-qwen-ai-bx-ua-chat"
        )
        token = env_or_header_token(handler, ["QWEN_AI_TOKEN"], ["x-qwen-ai-token"])
        if not token and cookie:
            token = cookie_value(cookie, "token")
        if not cookie:
            return None
        # Removed checks for bx_umidtoken and bx_ua to make them optional
        return {
            "token": token,
            "cookie": cookie,
            "bx_umidtoken": bx_umidtoken,
            "bx_ua": bx_ua,
            "bx_ua_create": bx_ua_create or bx_ua,
            "bx_ua_chat": bx_ua_chat or bx_ua,
            "bx_v": env_or_kv_token("QWEN_AI_BX_V")
            or header_token(handler, "x-qwen-ai-bx-v"),
            "timezone": env_or_kv_token("QWEN_AI_TIMEZONE")
            or header_token(handler, "x-qwen-ai-timezone"),
        }

    if provider_id == "uncloseai":
        return {"public": True}

    return None


def _buffered_stream_chunks(result):
    created = result.get("created", 0)
    model = result.get("model", "")
    response_id = result.get("id", "")
    message = (result.get("choices") or [{}])[0].get("message") or {}
    finish_reason = ((result.get("choices") or [{}])[0].get("finish_reason")) or "stop"
    builder = OpenAIStreamBuilder(response_id, model)
    builder.created = created

    for chunk in builder.reasoning(message.get("reasoning_content") or ""):
        yield chunk

    tool_calls = (
        message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    )
    if tool_calls:
        role_chunk = builder.ensure_role("content")
        if role_chunk is not None:
            yield role_chunk
        yield openai_chunk(
            response_id,
            model,
            created,
            {
                "tool_calls": [
                    tool_call_delta(tool_call, index)
                    for index, tool_call in enumerate(tool_calls)
                ]
            },
        )
    else:
        content = message.get("content") or ""
        if content:
            for chunk in builder.content(content):
                yield chunk
        elif not builder.role_sent:
            role_chunk = builder.ensure_role("content")
            if role_chunk is not None:
                yield role_chunk

    yield builder.finish(finish_reason=finish_reason)


def complete_non_stream(provider_id: str, credentials: dict, payload: dict):
    request_config = request_config_from_payload(payload)
    if request_has_tools(request_config):
        if not tool_request_supported(provider_id, request_config):
            raise RuntimeError(unsupported_tool_message(provider_id))
        if should_use_prompt_tool_shim(provider_id, request_config):
            prepared_payload = prepare_prompt_tool_payload(
                payload, provider_id, request_config
            )
            result, meta = complete_non_stream(
                provider_id, credentials, prepared_payload
            )
            result, tool_call_count = normalize_tool_result(result, request_config)
            meta = dict(meta or {})
            meta.update(
                {"agent_tool_mode": "prompt", "tool_call_count": tool_call_count}
            )
            return result, meta

    if provider_id == "zai":
        result, meta = zai_proxy.complete_non_stream(credentials["token"], payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "deepseek":
        result, meta = deepseek_proxy.complete_non_stream(credentials["token"], payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "arcee":
        result, meta = arcee_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "gemini-web":
        result, meta = gemini_web_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "grok":
        result, meta = grok_proxy.complete_non_stream(credentials["cookie"], payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "kimi":
        result, meta = kimi_proxy.complete_non_stream(credentials["token"], payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "inception":
        result, meta = inception_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "longcat":
        result, meta = longcat_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "mistral":
        result, meta = mistral_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "mimo":
        result, meta = mimo_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "openai-web":
        result, meta = openai_web_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "perplexity":
        result, meta = perplexity_proxy.complete_non_stream(
            credentials["cookie"], payload
        )
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "phind":
        result, meta = phind_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "inflection":
        result, meta = inflection_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "pi-local":
        result, meta = pi_local_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "qwen-ai":
        result, meta = qwen_ai_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    if provider_id == "uncloseai":
        result, meta = uncloseai_proxy.complete_non_stream(credentials, payload)
        return normalize_tool_result(result, request_config)[0], meta
    raise RuntimeError(f"Unsupported provider: {provider_id}")


def stream_chunks(provider_id: str, credentials: dict, payload: dict):
    request_config = request_config_from_payload(payload)
    if request_has_tools(request_config):
        if not tool_request_supported(provider_id, request_config):
            raise RuntimeError(unsupported_tool_message(provider_id))
        if should_use_prompt_tool_shim(provider_id, request_config):
            result, _meta = complete_non_stream(provider_id, credentials, payload)
            for chunk in _buffered_stream_chunks(result):
                yield chunk
            return

    if provider_id == "zai":
        upstream, chat_id, model = zai_proxy.chat_completion(
            credentials["token"], payload
        )
        try:
            session_key = str(
                payload.get("conversation_id") or payload.get("chat_id") or ""
            ).strip()
            for chunk in zai_proxy.openai_stream_chunks(
                upstream, model, chat_id, session_key=session_key
            ):
                yield chunk
        finally:
            upstream.close()
        return

    if provider_id == "deepseek":
        for chunk in deepseek_proxy.stream_chunks(credentials["token"], payload):
            yield chunk
        return

    if provider_id == "arcee":
        for chunk in arcee_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "grok":
        for chunk in grok_proxy.stream_chunks(credentials["cookie"], payload):
            yield chunk
        return

    if provider_id == "kimi":
        for chunk in kimi_proxy.stream_chunks(credentials["token"], payload):
            yield chunk
        return

    if provider_id == "inception":
        for chunk in inception_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "longcat":
        for chunk in longcat_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "mistral":
        for chunk in mistral_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "openai-web":
        for chunk in openai_web_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "perplexity":
        for chunk in perplexity_proxy.stream_chunks(credentials["cookie"], payload):
            yield chunk
        return

    if provider_id == "phind":
        for chunk in phind_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "inflection":
        for chunk in inflection_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "qwen-ai":
        for chunk in qwen_ai_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    if provider_id == "uncloseai":
        for chunk in uncloseai_proxy.stream_chunks(credentials, payload):
            yield chunk
        return

    result, _meta = complete_non_stream(provider_id, credentials, payload)
    for chunk in _buffered_stream_chunks(result):
        yield chunk
