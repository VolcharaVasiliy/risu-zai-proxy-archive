import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extensions" / "credentials-exporter"
bundle = {}
for language in ("en", "ru", "zh"):
    raw = json.loads((EXT / "_locales" / language / "messages.json").read_text(encoding="utf-8"))
    bundle[language] = {key: value.get("message", "") for key, value in raw.items()}
content = "/* Auto-generated from _locales — bundled so the popup can switch language at runtime.\n   Do not edit by hand; edit _locales/<lang>/messages.json and re-run the generator. */\nwindow.I18N = " + json.dumps(bundle, ensure_ascii=False, indent=2) + ";\n"
target = EXT / "i18n-bundle.js"
if "--check" in sys.argv:
    if not target.exists() or target.read_text(encoding="utf-8") != content:
        print("extension i18n bundle is stale")
        raise SystemExit(1)
    print("extension i18n: fresh")
else:
    target.write_text(content, encoding="utf-8", newline="\n")
    print("extension i18n: generated")
