import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"


def _normalize_value(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def load_credentials_env(path: Path = CREDENTIALS_PATH) -> dict:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    applied = {}
    for key, value in payload.items():
        normalized = _normalize_value(value)
        if not normalized:
            continue
        env_key = str(key)
        os.environ[env_key] = normalized
        applied[env_key] = normalized

        upper_key = env_key.upper()
        if upper_key != env_key:
            os.environ[upper_key] = normalized
            applied[upper_key] = normalized

    inflection_token = applied.get("INFLECTION_TOKEN", "")
    if inflection_token:
        os.environ["INFLECTION_API_KEY"] = inflection_token
        os.environ["PI_INFLECTION_API_KEY"] = inflection_token
        applied["INFLECTION_API_KEY"] = inflection_token
        applied["PI_INFLECTION_API_KEY"] = inflection_token

    return applied
