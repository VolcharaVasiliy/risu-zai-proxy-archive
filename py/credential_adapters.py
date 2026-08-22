"""Declarative credential adapters for providers with simple auth contracts."""

try:
    from py.http_helpers import env_or_header_token, env_token
except ImportError:
    from http_helpers import env_or_header_token, env_token
import json
from pathlib import Path

try:
    _credentials = json.loads(Path("credentials.json").read_text(encoding="utf-8"))
except Exception:
    _credentials = {}

def env_or_kv_token(key):
    return str(_credentials.get(key) or env_token(key) or "").strip()


ADAPTERS = {
    "zai": {"kind": "token", "env": ["ZAI_TOKEN"], "headers": ["x-zai-token"]},
    "deepseek": {"kind": "token", "env": ["DEEPSEEK_TOKEN"], "headers": ["x-deepseek-token"]},
    "google-ai-studio": {"kind": "token", "env": ["GOOGLE_AI_STUDIO_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"], "headers": ["x-google-ai-studio-api-key", "x-gemini-api-key", "x-google-api-key"], "field": "api_key"},
    "arcee": {"kind": "token", "env": ["ARCEE_ACCESS_TOKEN"], "headers": ["x-arcee-access-token"], "field": "token"},
    "inflection": {"kind": "token", "env": ["INFLECTION_API_KEY", "PI_INFLECTION_API_KEY"], "headers": ["x-inflection-api-key"], "field": "api_key"},
    "glm-web": {"kind": "token", "env": ["GLM_REFRESH_TOKEN"], "headers": ["x-glm-refresh-token"], "field": "refresh_token"},
    "kimi": {"kind": "token", "env": ["KIMI_TOKEN"], "headers": ["x-kimi-token"], "field": "token"},
    "uncloseai": {"kind": "public"},
    "opencode-zen": {"kind": "public"},
    "pi-local": {"kind": "local"},
}


def resolve(handler, provider_id):
    spec = ADAPTERS.get(provider_id)
    if not spec:
        return None, False
    kind = spec.get("kind")
    if kind in {"public", "local"}:
        return {}, True
    if kind == "token":
        token = env_or_header_token(handler, spec.get("env", []), spec.get("headers", []))
        if not token:
            return None, True
        field = spec.get("field", "token")
        result = {field: token}
        if provider_id == "kimi":
            result["refresh_token"] = env_or_kv_token("KIMI_REFRESH_TOKEN")
        if provider_id == "arcee":
            result["session_id"] = env_or_kv_token("ARCEE_SESSION_ID")
            refresh = env_or_kv_token("ARCEE_REFRESH_TOKEN")
            if refresh:
                result["refresh_token"] = refresh
        return result, True
    return None, True
