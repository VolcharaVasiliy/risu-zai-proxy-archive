"""Offline LM Arena adapter tests; no cookies, browser, or upstream calls required."""

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT / "py"))

import lmarena_proxy as proxy
import lmarena_captcha as captcha


def main():
    assert proxy.supports_model("arena:gpt-5.2")
    assert proxy.supports_model("gpt-5.2")
    assert proxy.supports_model("qwen3-max")
    assert proxy.supports_model("b0ea1407-2f92-4515-b9cc-b22a6d6c14f2")
    assert proxy._parse_stream_line('a0:"hello"') == "hello"
    assert proxy._parse_stream_line('ad:{"finishReason":"stop"}') == {"finishReason": "stop"}
    assert "keyPath" in (ROOT / "extensions" / "credentials-exporter" / "popup.js").read_text(encoding="utf-8")
    assert "store.keyPath == null" in (ROOT / "scripts" / "lmarena-recaptcha-bridge.mjs").read_text(encoding="utf-8")
    bridge_source = (ROOT / "scripts" / "lmarena-recaptcha-bridge.mjs").read_text(encoding="utf-8")
    assert "LM_ARENA_BROWSER_CDP_URL" in bridge_source
    assert "taskkill" in bridge_source
    assert "LM_ARENA_ALLOW_TEMP_BROWSER" in bridge_source
    assert "LM_ARENA_ALLOW_TEMP_BROWSER" in (ROOT / "scripts" / "fetch-lmarena-recaptcha.mjs").read_text(encoding="utf-8")
    payload = proxy._build_payload("019cc543-573d-7a3f-b155-ad9cc5733aa6", "hello", "token")
    assert payload["recaptchaV3Token"] == "token"
    assert payload["modelAId"].startswith("019")
    old_storage = os.environ.get("LM_ARENA_STORAGE")
    try:
        proxy._apply_browser_state({"storage": {"version": 1}, "headers": {"x-arena-test": "ok"}})
        assert '"version":1' in os.environ["LM_ARENA_STORAGE"]
        assert os.environ["LM_ARENA_HEADERS"] == '{"x-arena-test":"ok"}'
    finally:
        if old_storage is None:
            os.environ.pop("LM_ARENA_STORAGE", None)
        else:
            os.environ["LM_ARENA_STORAGE"] = old_storage
        os.environ.pop("LM_ARENA_HEADERS", None)

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "captcha.json"
        path.write_text(json.dumps({"token": "x" * 120, "captured_at": 0}), encoding="utf-8")
        old_file = captcha.RECAPTCHA_FILE
        old_mode = os.environ.get("LM_ARENA_CAPTCHA_MODE")
        old_token = os.environ.get("LM_ARENA_CAPTCHA")
        old_session = captcha.SESSION_FILE
        try:
            captcha.RECAPTCHA_FILE = str(path)
            os.environ["LM_ARENA_CAPTCHA_MODE"] = "file"
            os.environ.pop("LM_ARENA_CAPTCHA", None)
            assert captcha.get_token() == "x" * 120
            path.unlink()
            os.environ["LM_ARENA_CAPTCHA"] = "y" * 120
            assert captcha.get_token() == "y" * 120
            session_path = Path(directory) / "session.json"
            session_path.write_text(json.dumps({"cookie": "fresh=1", "captured_at": int(__import__("time").time() * 1000)}), encoding="utf-8")
            captcha.SESSION_FILE = str(session_path)
            assert captcha.effective_cookie("old=1") == "fresh=1"
        finally:
            captcha.RECAPTCHA_FILE = old_file
            if old_mode is None:
                os.environ.pop("LM_ARENA_CAPTCHA_MODE", None)
            else:
                os.environ["LM_ARENA_CAPTCHA_MODE"] = old_mode
            if old_token is None:
                os.environ.pop("LM_ARENA_CAPTCHA", None)
            else:
                os.environ["LM_ARENA_CAPTCHA"] = old_token
            captcha.SESSION_FILE = old_session
    print("LM Arena contract tests: ok")


if __name__ == "__main__":
    main()
