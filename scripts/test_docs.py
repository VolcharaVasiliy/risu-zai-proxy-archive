"""Small, dependency-free consistency checks for user-facing Markdown."""

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "README.md",
    ROOT / "README.ru.md",
    ROOT / "README.zh.md",
    ROOT / "INSTALLATION.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "deployment.md",
    ROOT / "docs" / "providers.md",
    ROOT / "docs" / "observability.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "REDEPLOY.md",
]


def fail(message: str) -> None:
    print(f"docs_test: {message}", file=sys.stderr)
    raise SystemExit(1)


for path in DOCS:
    if not path.exists():
        fail(f"missing documentation file: {path.relative_to(ROOT)}")

text = {path: path.read_text(encoding="utf-8") for path in DOCS}

for name in ("README.md", "README.ru.md", "README.zh.md"):
    body = text[ROOT / name]
    for route in ("/v1/models", "/v1/providers", "/doctor", "/v1/responses"):
        if route not in body:
            fail(f"{name} does not mention {route}")
    if "observ" not in body.lower() and "диагност" not in body.lower() and "诊断" not in body:
        fail(f"{name} is missing the diagnostics/logging section")
    for command in ("npm run providers:check", "npm run providers:live", "npm run providers:generate"):
        if command not in body:
            fail(f"{name} does not mention {command}")

joined = "\n".join(text.values())
for stale in ("zai:glm-4.5v", "glm-4.5v\",", "LM_ARENA_COOKIE = \"C:\\"):
    if stale in joined:
        fail(f"stale example remains: {stale}")

for source, body in text.items():
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]+)?\)", body):
        if "://" in target or target.startswith("mailto:"):
            continue
        resolved = (source.parent / target).resolve()
        if not resolved.exists():
            fail(f"broken local link in {source.relative_to(ROOT)}: {target}")

print("docs_test: ok")
