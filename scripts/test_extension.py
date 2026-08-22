import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extensions" / "credentials-exporter"


def main():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert "cookies" in manifest["permissions"] and "debugger" in manifest["permissions"]
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    schema = (EXT / "provider-schema.js").read_text(encoding="utf-8")
    assert 'window.PROVIDER_SCHEMA' in schema
    assert 'renderSelfCheck' in popup
    assert 'credentialSetReady' in popup
    assert manifest["version"] == "1.3.0"
    assert "if (value) out[k] = value" in popup
    assert "out.headerCapture = Object.fromEntries" in popup
    assert '"LM_ARENA_STORAGE"' in popup and '"LM_ARENA_HEADERS"' in popup
    assert "ARENA_STORAGE_READER" in popup and "readArenaStorage" in popup
    for locale in ("en", "ru", "zh"):
        messages = json.loads((EXT / "_locales" / locale / "messages.json").read_text(encoding="utf-8"))
        assert "extName" in messages and "extDescription" in messages
        for key in ("selfCheckTitle", "selfCheckReady", "selfCheckPartial", "selfCheckLocal", "selfCheckStale"):
            assert key in messages, f"missing locale key: {locale}/{key}"
    print("extension tests: ok")


if __name__ == "__main__":
    main()
