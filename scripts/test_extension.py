import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extensions" / "credentials-exporter"


def main():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert "cookies" in manifest["permissions"] and "debugger" in manifest["permissions"]
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    assert "if (value) out[k] = value" in popup
    assert "out.headerCapture = Object.fromEntries" in popup
    for locale in ("en", "ru", "zh"):
        messages = json.loads((EXT / "_locales" / locale / "messages.json").read_text(encoding="utf-8"))
        assert "extName" in messages and "extDescription" in messages
    print("extension tests: ok")


if __name__ == "__main__":
    main()
