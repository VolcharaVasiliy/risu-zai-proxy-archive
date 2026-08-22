try:
    from py import (
        arcee_proxy,
        deepseek_proxy,
        gemini_web_proxy,
        glm_web_proxy,
        google_ai_studio_proxy,
        google_ai_studio_web_proxy,
        grok_proxy,
        inception_proxy,
        inflection_proxy,
        kimi_proxy,
        lmarena_proxy,
        longcat_proxy,
        mimo_proxy,
        mistral_proxy,
        multimodal,
        openai_web_proxy,
        perplexity_proxy,
        phind_proxy,
        pi_local_proxy,
        qwen_ai_proxy,
        uncloseai_proxy,
        zai_proxy,
        zen_proxy,
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
    from py.zai_proxy import debug_log
    from py.credential_adapters import resolve as resolve_declarative_credentials
except ImportError:
    import arcee_proxy
    import deepseek_proxy
    import gemini_web_proxy
    import glm_web_proxy
    import google_ai_studio_proxy
    import google_ai_studio_web_proxy
    import grok_proxy
    import inception_proxy
    import inflection_proxy
    import kimi_proxy
    import lmarena_proxy
    import longcat_proxy
    import mimo_proxy
    import mistral_proxy
    import multimodal
    import openai_web_proxy
    import perplexity_proxy
    import phind_proxy
    import pi_local_proxy
    import qwen_ai_proxy
    import uncloseai_proxy
    import zai_proxy
    import zen_proxy
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
    from zai_proxy import debug_log
    from credential_adapters import resolve as resolve_declarative_credentials

import os
import json


class ProviderAuthError(RuntimeError):
    pass


class ProviderRateLimitError(RuntimeError):
    pass


try:
    with open("credentials.json", "r") as f:
        credentials = json.load(f)
except FileNotFoundError:
    credentials = {}


def env_or_kv_token(key):
    return credentials.get(key, os.environ.get(key, ""))


MODEL_SPECS = []
PUBLIC_MODEL_IDS_BY_PROVIDER = {
    "gemini-web": set(getattr(gemini_web_proxy, "PUBLIC_MODELS", gemini_web_proxy.SUPPORTED_MODELS)),
    "google-ai-studio": {
        model
        for model in google_ai_studio_proxy.SUPPORTED_MODELS
        if model not in getattr(google_ai_studio_proxy, "MODEL_ALIASES", {})
    },
    "google-ai-studio-web": set(google_ai_studio_web_proxy.SUPPORTED_MODELS),
    "openai-web": {
        model
        for model in openai_web_proxy.SUPPORTED_MODELS
        if model != "chatgpt"
    },
    "inflection": {"pi-api", "pi-3.1"},
}
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


def _model_capabilities(provider_id: str, model: str = "") -> dict:
    native_tools = provider_has_native_tools(provider_id)
    tools_supported = tool_request_supported(provider_id, _TOOL_CAPABILITY_PROBE)
    native_images = multimodal.provider_accepts_native_images(provider_id, model)
    return {
        "chat_completions": True,
        "responses": True,
        "tools": tools_supported,
        "native_tools": native_tools,
        "prompt_tool_shim": tools_supported and not native_tools,
        "streaming": True,
        "images": True,
        "native_images": native_images,
        "image_descriptions": not native_images,
    }


def _provider(provider_id, module, requires_env, **metadata):
    credential_sets = metadata.pop("credential_sets", None)
    if credential_sets is None:
        required = tuple(
            str(item).split(" ", 1)[0].strip()
            for item in requires_env
            if "(optional)" not in str(item).lower()
        )
        credential_sets = (required,) if required else ()
    return {
        "id": provider_id,
        "module": module,
        "owned_by": getattr(module, "OWNED_BY", provider_id),
        "models": tuple(getattr(module, "SUPPORTED_MODELS", ())),
        "requires_env": tuple(requires_env),
        "runtimes": tuple(metadata.pop("runtimes", ("local", "vercel"))),
        "auth_mode": metadata.pop("auth_mode", "browser_session"),
        "credential_sets": tuple(tuple(group) for group in credential_sets),
        **metadata,
    }


PROVIDER_MANIFEST = [
    _provider("zai", zai_proxy, ["ZAI_TOKEN"], runtimes=("local",), credential_sets=(("ZAI_TOKEN",),)),
    _provider("deepseek", deepseek_proxy, ["DEEPSEEK_TOKEN"]),
    _provider("arcee", arcee_proxy, ["ARCEE_ACCESS_TOKEN"], credential_sets=(("ARCEE_ACCESS_TOKEN",),)),
    _provider(
        "gemini-web",
        gemini_web_proxy,
        [
            "GEMINI_WEB_SECURE_1PSID",
            "GEMINI_WEB_SECURE_1PSIDTS (optional)",
            "GEMINI_WEB_COOKIE (optional)",
        ],
        credential_sets=(("GEMINI_WEB_SECURE_1PSID",), ("GEMINI_WEB_COOKIE",)),
    ),
    _provider(
        "google-ai-studio",
        google_ai_studio_proxy,
        ["GOOGLE_AI_STUDIO_API_KEY"],
        auth_mode="api_key",
        resolve_priority=6,
        credential_sets=(("GOOGLE_AI_STUDIO_API_KEY",), ("GEMINI_API_KEY",), ("GOOGLE_API_KEY",)),
    ),
    _provider(
        "google-ai-studio-web",
        google_ai_studio_web_proxy,
        [
            "GOOGLE_AI_STUDIO_WEB_COOKIE",
            "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE (required for GenerateContent)",
            "GOOGLE_AI_STUDIO_WEB_HEADERS (optional)",
        ],
        credential_sets=(("GOOGLE_AI_STUDIO_WEB_COOKIE",), ("GOOGLE_AI_STUDIO_WEB_SAPISID",)),
        resolve_priority=5,
    ),
    _provider("grok", grok_proxy, ["GROK_COOKIE"], runtimes=("local",), credential_sets=(("GROK_COOKIE",), ("GROK_SSO",))),
    _provider("kimi", kimi_proxy, ["KIMI_TOKEN"], credential_sets=(("KIMI_TOKEN",),)),
    _provider(
        "inception",
        inception_proxy,
        ["INCEPTION_SESSION_TOKEN", "INCEPTION_COOKIE (optional)"],
        runtimes=("local", "vercel", "cloudflare"),
        credential_sets=(("INCEPTION_SESSION_TOKEN",), ("INCEPTION_COOKIE",)),
    ),
    _provider("longcat", longcat_proxy, ["LONGCAT_COOKIE"], credential_sets=(("LONGCAT_COOKIE",),)),
    _provider(
        "mistral",
        mistral_proxy,
        ["MISTRAL_COOKIE", "MISTRAL_CSRF_TOKEN (optional)"],
        credential_sets=(("MISTRAL_COOKIE",),),
    ),
    _provider(
        "mimo",
        mimo_proxy,
        ["MIMO_SERVICE_TOKEN", "MIMO_USER_ID", "MIMO_PH_TOKEN", "MIMO_COOKIE (optional)"],
        credential_sets=(("MIMO_SERVICE_TOKEN", "MIMO_USER_ID", "MIMO_PH_TOKEN"), ("MIMO_COOKIE",)),
    ),
    _provider("openai-web", openai_web_proxy, ["OPENAI_WEB_ACCESS_TOKEN"], credential_sets=(("OPENAI_WEB_ACCESS_TOKEN",), ("OPENAI_WEB_COOKIE",))),
    _provider("perplexity", perplexity_proxy, ["PERPLEXITY_COOKIE"], credential_sets=(("PERPLEXITY_COOKIE",), ("PERPLEXITY_SESSION_TOKEN",))),
    _provider(
        "phind", phind_proxy, ["PHIND_COOKIE", "PHIND_NONCE (optional)"],
        credential_sets=(("PHIND_COOKIE",),),
    ),
    _provider(
        "inflection",
        inflection_proxy,
        ["INFLECTION_API_KEY", "PI_INFLECTION_API_KEY"],
        auth_mode="api_key",
        credential_sets=(("INFLECTION_API_KEY",), ("PI_INFLECTION_API_KEY",)),
    ),
    _provider(
        "pi-local",
        pi_local_proxy,
        [],
        runtimes=("local",),
        auth_mode="local_bridge",
    ),
    _provider("qwen-ai", qwen_ai_proxy, ["QWEN_AI_COOKIE"], credential_sets=(("QWEN_AI_COOKIE",),)),
    _provider("glm-web", glm_web_proxy, ["GLM_REFRESH_TOKEN"], credential_sets=(("GLM_REFRESH_TOKEN",),)),
    _provider("uncloseai", uncloseai_proxy, [], auth_mode="public"),
    _provider(
        "lmarena",
        lmarena_proxy,
        ["LM_ARENA_COOKIE"],
        runtimes=("local",),
        credential_sets=(("LM_ARENA_COOKIE",),),
    ),
    _provider("opencode-zen", zen_proxy, [], auth_mode="public"),
]
PROVIDERS_BY_ID = {entry["id"]: entry for entry in PROVIDER_MANIFEST}


def _add_models(provider_id: str, owned_by: str, models, requires_env):
    for model in models:
        public_ids = PUBLIC_MODEL_IDS_BY_PROVIDER.get(provider_id)
        if public_ids is not None and model not in public_ids:
            continue
        capabilities = _model_capabilities(provider_id, model)
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


for _entry in PROVIDER_MANIFEST:
    _add_models(
        _entry["id"],
        _entry["owned_by"],
        _entry["models"],
        _entry["requires_env"],
    )


def models_payload():
    return {"object": "list", "data": MODEL_SPECS}


def _env_name(requirement: str) -> str:
    return str(requirement or "").split(" ", 1)[0].strip()


def provider_status_payload(runtime: str = "") -> dict:
    runtime = str(runtime or "").strip().lower()
    supported_runtimes = sorted({item for entry in PROVIDER_MANIFEST for item in entry["runtimes"]})
    runtime_valid = not runtime or runtime in supported_runtimes
    data = []
    for entry in PROVIDER_MANIFEST:
        if runtime and runtime not in entry["runtimes"]:
            continue
        requirements = list(entry["requires_env"])
        credential_sets = entry.get("credential_sets") or ()
        names = list(dict.fromkeys(
            [_env_name(item) for item in requirements]
            + [name for group in credential_sets for name in group]
        ))
        configured = [name for name in names if env_or_kv_token(name)]
        public = entry["auth_mode"] == "public"
        ready = public or not credential_sets or any(
            all(env_or_kv_token(name) for name in group)
            for group in credential_sets
        )
        missing = [] if ready else [" or ".join(" + ".join(group) for group in credential_sets)]
        data.append(
            {
                "id": entry["id"],
                "owned_by": entry["owned_by"],
                "models": list(entry["models"]),
                "runtimes": list(entry["runtimes"]),
                "auth_mode": entry["auth_mode"],
                "requires_env": requirements,
                "credential_sets": [list(group) for group in credential_sets],
                "configured_env": configured,
                "missing_env": [] if public else missing,
                "ready": ready,
            }
        )
    return {
        "object": "list",
        "runtime": runtime or None,
        "runtime_valid": runtime_valid,
        "supported_runtimes": supported_runtimes,
        "data": data,
    }


def doctor_payload(runtime: str = "") -> dict:
    runtime = str(runtime or "").strip().lower()
    status = provider_status_payload(runtime)
    providers = status["data"]
    runtime_valid = status["runtime_valid"]
    missing = [item["id"] for item in providers if not item["ready"]]
    runtimes = sorted({runtime for item in providers for runtime in item["runtimes"]})
    return {
        "ok": runtime_valid and not missing,
        "runtime": runtime or None,
        "runtime_valid": runtime_valid,
        "supported_runtimes": status["supported_runtimes"],
        "providers_total": len(providers),
        "providers_ready": len(providers) - len(missing),
        "providers_missing_credentials": len(missing),
        "missing_credentials": missing,
        "runtimes": runtimes,
        "checks": {
            "manifest": True,
            "credentials": not bool(missing),
            "runtime": runtime_valid,
        },
        "providers": [
            {
                "id": item["id"],
                "ready": item["ready"],
                "missing_env": item["missing_env"],
                "runtimes": item["runtimes"],
            }
            for item in providers
        ],
    }


def resolve_provider_id(model: str) -> str:
    ordered = sorted(
        enumerate(PROVIDER_MANIFEST),
        key=lambda item: item[1].get("resolve_priority", item[0] * 10),
    )
    for _index, entry in ordered:
        if entry["module"].supports_model(model):
            return entry["id"]
    return ""


def provider_error_hint(provider_id: str) -> str:
    if provider_id == "zai":
        return "Configure ZAI_TOKEN from a live chat.z.ai session, or pass the Z.ai JWT as Bearer token / x-zai-token header. Some Z.ai models are account-plan gated."
    if provider_id == "deepseek":
        return "Configure DEEPSEEK_TOKEN in server env or pass the DeepSeek userToken as Bearer token"
    if provider_id == "arcee":
        return "Configure ARCEE_ACCESS_TOKEN in server env or pass the Arcee bearer access token via Authorization / x-arcee-access-token"
    if provider_id == "gemini-web":
        return "Configure GEMINI_WEB_SECURE_1PSID plus optional GEMINI_WEB_SECURE_1PSIDTS or GEMINI_WEB_COOKIE in server env"
    if provider_id == "google-ai-studio":
        return "Configure GOOGLE_AI_STUDIO_API_KEY from Google AI Studio, or pass x-google-ai-studio-api-key"
    if provider_id == "google-ai-studio-web":
        return "Configure GOOGLE_AI_STUDIO_WEB_COOKIE from a logged-in AI Studio browser session; GenerateContent also requires GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE captured from a matching AI Studio web request"
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
    if provider_id == "glm-web":
        return "Configure GLM_REFRESH_TOKEN in server env or pass the GLM refresh token as Bearer token / x-glm-refresh-token header"
    if provider_id == "uncloseai":
        return "UncloseAI public endpoints do not require credentials"
    if provider_id == "lmarena":
        return "Configure LM_ARENA_COOKIE in server env or pass x-lmarena-cookie header (export a live arena.ai session cookie jar, including arena-auth-prod-v1.1)"
    if provider_id == "opencode-zen":
        return "OpenCode Zen does not require credentials; use models like hy3-free, big-pickle, nemotron-3.5-lightning-free"
    return "Provider credentials are not configured"


def provider_auth_error_message(provider_id: str, error: Exception) -> str:
    detail = str(error or "").strip()
    hint = provider_error_hint(provider_id)
    if detail:
        return f"Provider authentication/configuration failed for {provider_id}: {detail}. {hint}"
    return f"Provider authentication/configuration failed for {provider_id}. {hint}"


def is_provider_auth_error(error: Exception) -> bool:
    text = str(error or "").lower()
    auth_markers = [
        "401 client error",
        "401 unauthorized",
        "http 401",
        "unauthorized",
        "forbidden",
        "403",
        "http 403",
        "403 client error",
        "api_key_invalid",
        "api key not valid",
        "invalid api key",
        "invalid_argument",
        "permission_denied",
        "access token",
        "token expired",
        "expired token",
        "invalid token",
        "invalid cookie",
        "session expired",
        "model not available for current user level",
        "current user level",
        "当前用户无法使用此模型",
        "无法使用此模型",
        "frontend_captcha_required",
        "captcha_verification_failed",
        "captcha required",
    ]
    return any(marker in text for marker in auth_markers)


def is_provider_rate_limit_error(error: Exception) -> bool:
    text = str(error or "").lower()
    rate_limit_markers = [
        "429",
        "http 429",
        "too many requests",
        "rate limit",
        "quota exceeded",
        "resource_exhausted",
        "exceeded your current quota",
    ]
    return any(marker in text for marker in rate_limit_markers)


def raise_provider_rate_limit_if_needed(provider_id: str, error: Exception):
    if isinstance(error, ProviderRateLimitError):
        raise error
    if is_provider_rate_limit_error(error):
        detail = str(error or "").strip()
        if detail:
            raise ProviderRateLimitError(
                f"Provider rate limit/quota exceeded for {provider_id}: {detail}"
            ) from error
        raise ProviderRateLimitError(
            f"Provider rate limit/quota exceeded for {provider_id}"
        ) from error


def raise_provider_auth_if_needed(provider_id: str, error: Exception):
    if isinstance(error, ProviderAuthError):
        raise error
    if is_provider_auth_error(error):
        raise ProviderAuthError(provider_auth_error_message(provider_id, error)) from error


def resolve_credentials(handler, provider_id: str):
    declarative, handled = resolve_declarative_credentials(handler, provider_id)
    if handled:
        return declarative
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
        refresh_token = env_or_header_token(
            handler, ["ARCEE_REFRESH_TOKEN"], ["x-arcee-refresh-token"]
        )
        if not token:
            return None
        creds = {"token": token, "session_id": session_id}
        if refresh_token:
            creds["refresh_token"] = refresh_token
        return creds

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

    if provider_id == "google-ai-studio":
        api_key = env_or_header_token(
            handler,
            ["GOOGLE_AI_STUDIO_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"],
            ["x-google-ai-studio-api-key", "x-gemini-api-key", "x-google-api-key"],
        )
        return {"api_key": api_key} if api_key else None

    if provider_id == "google-ai-studio-web":
        cookie = env_or_kv_token("GOOGLE_AI_STUDIO_WEB_COOKIE") or header_token(
            handler, "x-google-ai-studio-web-cookie"
        )
        secure_1psid = env_or_kv_token(
            "GOOGLE_AI_STUDIO_WEB_SECURE_1PSID"
        ) or header_token(handler, "x-google-ai-studio-web-secure-1psid")
        secure_3psid = env_or_kv_token(
            "GOOGLE_AI_STUDIO_WEB_SECURE_3PSID"
        ) or header_token(handler, "x-google-ai-studio-web-secure-3psid")
        sapisid = env_or_kv_token("GOOGLE_AI_STUDIO_WEB_SAPISID") or header_token(
            handler, "x-google-ai-studio-web-sapisid"
        )
        secure_1papisid = env_or_kv_token(
            "GOOGLE_AI_STUDIO_WEB_SECURE_1PAPISID"
        ) or header_token(handler, "x-google-ai-studio-web-secure-1papisid")
        secure_3papisid = env_or_kv_token(
            "GOOGLE_AI_STUDIO_WEB_SECURE_3PAPISID"
        ) or header_token(handler, "x-google-ai-studio-web-secure-3papisid")
        if cookie:
            sapisid = sapisid or cookie_value(cookie, "SAPISID")
            secure_1papisid = secure_1papisid or cookie_value(
                cookie, "__Secure-1PAPISID"
            )
            secure_3papisid = secure_3papisid or cookie_value(
                cookie, "__Secure-3PAPISID"
            )
            secure_1psid = secure_1psid or cookie_value(cookie, "__Secure-1PSID")
            secure_3psid = secure_3psid or cookie_value(cookie, "__Secure-3PSID")
        if not cookie:
            parts = []
            for name, value in (
                ("SAPISID", sapisid),
                ("__Secure-1PAPISID", secure_1papisid),
                ("__Secure-3PAPISID", secure_3papisid),
                ("__Secure-1PSID", secure_1psid),
                ("__Secure-3PSID", secure_3psid),
            ):
                if value:
                    parts.append(f"{name}={value}")
            cookie = "; ".join(parts)
        if not cookie and not sapisid and not secure_1papisid and not secure_3papisid:
            return None
        return {
            "cookie": cookie,
            "sapisid": sapisid,
            "secure_1papisid": secure_1papisid,
            "secure_3papisid": secure_3papisid,
            "secure_1psid": secure_1psid,
            "secure_3psid": secure_3psid,
            "headers": env_or_kv_token("GOOGLE_AI_STUDIO_WEB_HEADERS")
            or header_token(handler, "x-google-ai-studio-web-headers"),
            "api_key": env_or_kv_token("GOOGLE_AI_STUDIO_WEB_API_KEY")
            or header_token(handler, "x-google-ai-studio-web-api-key"),
            "authorization": env_or_kv_token("GOOGLE_AI_STUDIO_WEB_AUTHORIZATION")
            or header_token(handler, "x-google-ai-studio-web-authorization"),
            "visit_id": env_or_kv_token("GOOGLE_AI_STUDIO_WEB_VISIT_ID")
            or header_token(handler, "x-google-ai-studio-web-visit-id"),
            "ext_519733851_bin": env_or_kv_token(
                "GOOGLE_AI_STUDIO_WEB_EXT_519733851_BIN"
            )
            or header_token(handler, "x-google-ai-studio-web-ext-519733851-bin"),
            "generate_template": env_or_kv_token(
                "GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE"
            )
            or env_or_kv_token("GOOGLE_AI_STUDIO_WEB_GENERATE_BODY")
            or header_token(handler, "x-google-ai-studio-web-generate-template"),
            "bootstrap_path": env_or_kv_token("GOOGLE_AI_STUDIO_WEB_BOOTSTRAP_PATH")
            or header_token(handler, "x-google-ai-studio-web-bootstrap-path"),
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
        refresh_token = env_or_kv_token("KIMI_REFRESH_TOKEN")
        return {"token": token, "refresh_token": refresh_token} if token else None

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
                if sep and (key.strip().startswith("csrf_token_") or key.strip() == "csrftoken"):
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
        # Sentinel turnstile token may arrive via credentials.json (exported by the
        # browser extension) or a request header; surface it as the env fallback that
        # py/openai_turnstile.py already consults.
        turnstile = env_or_kv_token("OPENAI_WEB_SENTINEL_TURNSTILE") or header_token(
            handler, "x-openai-web-sentinel-turnstile"
        )
        if turnstile:
            os.environ["OPENAI_WEB_SENTINEL_TURNSTILE"] = turnstile
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

    if provider_id == "glm-web":
        token = env_or_header_token(
            handler, ["GLM_REFRESH_TOKEN", "GLM_TOKEN"], ["x-glm-refresh-token", "x-glm-token"]
        )
        return {"refresh_token": token} if token else None

    if provider_id == "lmarena":
        cookie = env_or_kv_token("LM_ARENA_COOKIE") or header_token(
            handler, "x-lmarena-cookie"
        )
        return {"cookie": cookie} if cookie else None

    if provider_id == "opencode-zen":
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


def _complete_with_credentials(module, credentials, payload):
    return module.complete_non_stream(credentials, payload)


def _complete_with_token(module, credentials, payload, key="token"):
    return module.complete_non_stream(credentials[key], payload)


def _complete_kimi(credentials, payload):
    return kimi_proxy.complete_non_stream(
        credentials["token"], payload, credentials.get("refresh_token", "")
    )


def _stream_with_credentials(module, credentials, payload):
    return module.stream_chunks(credentials, payload)


def _stream_with_token(module, credentials, payload, key="token"):
    return module.stream_chunks(credentials[key], payload)


def _stream_kimi(credentials, payload):
    return kimi_proxy.stream_chunks(
        credentials["token"], payload, credentials.get("refresh_token", "")
    )


PROVIDER_ADAPTERS = {
    "zai": {
        "complete": lambda credentials, payload: _complete_with_token(zai_proxy, credentials, payload),
        "stream": lambda credentials, payload: zai_proxy.stream_chunks_with_captcha_retry(credentials["token"], payload),
        "continuation_state": True,
    },
    "deepseek": {
        "complete": lambda credentials, payload: _complete_with_token(deepseek_proxy, credentials, payload),
        "stream": lambda credentials, payload: _stream_with_token(deepseek_proxy, credentials, payload),
    },
    "arcee": {"complete": lambda c, p: _complete_with_credentials(arcee_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(arcee_proxy, c, p)},
    "gemini-web": {"complete": lambda c, p: _complete_with_credentials(gemini_web_proxy, c, p)},
    "google-ai-studio": {"complete": lambda c, p: _complete_with_credentials(google_ai_studio_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(google_ai_studio_proxy, c, p)},
    "google-ai-studio-web": {"complete": lambda c, p: _complete_with_credentials(google_ai_studio_web_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(google_ai_studio_web_proxy, c, p)},
    "grok": {"complete": lambda c, p: _complete_with_token(grok_proxy, c, p, "cookie"), "stream": lambda c, p: _stream_with_token(grok_proxy, c, p, "cookie")},
    "kimi": {"complete": _complete_kimi, "stream": _stream_kimi},
    "inception": {"complete": lambda c, p: _complete_with_credentials(inception_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(inception_proxy, c, p)},
    "longcat": {"complete": lambda c, p: _complete_with_credentials(longcat_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(longcat_proxy, c, p)},
    "mistral": {"complete": lambda c, p: _complete_with_credentials(mistral_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(mistral_proxy, c, p)},
    "mimo": {"complete": lambda c, p: _complete_with_credentials(mimo_proxy, c, p)},
    "openai-web": {"complete": lambda c, p: _complete_with_credentials(openai_web_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(openai_web_proxy, c, p)},
    "perplexity": {"complete": lambda c, p: _complete_with_token(perplexity_proxy, c, p, "cookie"), "stream": lambda c, p: _stream_with_token(perplexity_proxy, c, p, "cookie")},
    "phind": {"complete": lambda c, p: _complete_with_credentials(phind_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(phind_proxy, c, p)},
    "inflection": {"complete": lambda c, p: _complete_with_credentials(inflection_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(inflection_proxy, c, p)},
    "pi-local": {"complete": lambda c, p: _complete_with_credentials(pi_local_proxy, c, p)},
    "qwen-ai": {"complete": lambda c, p: _complete_with_credentials(qwen_ai_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(qwen_ai_proxy, c, p)},
    "glm-web": {"complete": lambda c, p: _complete_with_token(glm_web_proxy, c, p, "refresh_token"), "stream": lambda c, p: _stream_with_token(glm_web_proxy, c, p, "refresh_token")},
    "uncloseai": {"complete": lambda c, p: _complete_with_credentials(uncloseai_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(uncloseai_proxy, c, p)},
    "lmarena": {"complete": lambda c, p: _complete_with_token(lmarena_proxy, c, p, "cookie"), "stream": lambda c, p: _stream_with_token(lmarena_proxy, c, p, "cookie"), "normalize": False},
    "opencode-zen": {"complete": lambda c, p: _complete_with_credentials(zen_proxy, c, p), "stream": lambda c, p: _stream_with_credentials(zen_proxy, c, p)},
}


def _fallback_map():
    raw = os.environ.get("PROXY_FALLBACKS_JSON", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _fallback_candidates(provider_id, model):
    mapping = _fallback_map()
    values = mapping.get(model) or mapping.get(f"provider:{provider_id}") or []
    if isinstance(values, str):
        values = [values]
    return [str(item).strip() for item in values if str(item).strip() and str(item).strip() != model][:3]


def _fallback_allowed(error):
    return not is_provider_auth_error(error) and not ("invalid request" in str(error).lower() or "400" in str(error).lower()) and (is_provider_rate_limit_error(error) or any(mark in str(error).lower() for mark in ("500", "502", "503", "504", "timeout", "temporarily", "connection")))


def complete_non_stream(provider_id: str, credentials: dict, payload: dict):
    payload = multimodal.prepare_payload_for_provider(provider_id, credentials, payload)
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

    adapter = PROVIDER_ADAPTERS.get(provider_id)
    if not adapter or not adapter.get("complete"):
        raise RuntimeError(f"Unsupported provider: {provider_id}")
    try:
        result, meta = adapter["complete"](credentials, payload)
    except Exception as error:
        if not _fallback_allowed(error):
            raise
        original_model = payload.get("model")
        for fallback_model in _fallback_candidates(provider_id, original_model):
            fallback_provider = resolve_provider_id(fallback_model)
            if fallback_provider != provider_id:
                continue
            fallback_payload = dict(payload)
            fallback_payload["model"] = fallback_model
            try:
                result, meta = adapter["complete"](credentials, fallback_payload)
                meta = dict(meta or {})
                meta.update({"fallback": True, "requested_model": original_model, "actual_model": fallback_model})
                result = dict(result or {})
                result.setdefault("model", fallback_model)
                return result, meta
            except Exception as fallback_error:
                debug_log("provider_fallback_failed", provider=provider_id, requested_model=original_model, fallback_model=fallback_model, error_type=type(fallback_error).__name__)
        raise
    if adapter.get("normalize", True):
        result = normalize_tool_result(result, request_config)[0]
    return result, meta


def stream_chunks(provider_id: str, credentials: dict, payload: dict):
    original_payload = payload
    payload = multimodal.prepare_payload_for_provider(provider_id, credentials, payload)
    request_config = request_config_from_payload(payload)
    if request_has_tools(request_config):
        if not tool_request_supported(provider_id, request_config):
            raise RuntimeError(unsupported_tool_message(provider_id))
        if should_use_prompt_tool_shim(provider_id, request_config):
            result, _meta = complete_non_stream(provider_id, credentials, payload)
            for chunk in _buffered_stream_chunks(result):
                yield chunk
            return

    adapter = PROVIDER_ADAPTERS.get(provider_id)
    stream = adapter.get("stream") if adapter else None
    if stream:
        try:
            yield from stream(credentials, payload)
        finally:
            if adapter.get("continuation_state") and original_payload is not payload and payload.get("_zai_continuation_state"):
                original_payload["_zai_continuation_state"] = payload.get("_zai_continuation_state")
        return

    result, _meta = complete_non_stream(provider_id, credentials, payload)
    for chunk in _buffered_stream_chunks(result):
        yield chunk
