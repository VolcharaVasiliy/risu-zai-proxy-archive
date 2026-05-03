import argparse
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FETCH_DUMP = Path(r"C:\Users\gamer\Desktop\СЕТКА.txt")
DEFAULT_COOKIE_EXPORT = Path(r"C:\Users\gamer\Desktop\КУКИ.txt")
DEFAULT_OUTPUT = PROJECT_ROOT / "auth" / "google-ai-studio-web-creds.json"

SENSITIVE_HEADERS = {"authorization", "cookie", "content-length", "host"}


def js_string_end(text: str, quote_index: int) -> int:
    quote = text[quote_index]
    escape = False
    for index in range(quote_index + 1, len(text)):
        char = text[index]
        if escape:
            escape = False
        elif char == "\\":
            escape = True
        elif char == quote:
            return index
    return -1


def brace_end(text: str, brace_index: int) -> int:
    stack = ["}"]
    in_string = False
    quote = ""
    escape = False
    for index in range(brace_index + 1, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            quote = char
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if not stack or char != stack[-1]:
                return -1
            stack.pop()
            if not stack:
                return index
    return -1


def parse_fetches(text: str) -> list[dict]:
    fetches = []
    pos = 0
    while True:
        start = text.find("fetch(", pos)
        if start < 0:
            break
        q = text.find('"', start)
        if q < 0:
            pos = start + 6
            continue
        e = js_string_end(text, q)
        if e < 0:
            pos = start + 6
            continue
        url = json.loads(text[q : e + 1])
        o = text.find("{", e)
        if o < 0:
            pos = e + 1
            continue
        oe = brace_end(text, o)
        if oe < 0:
            pos = o + 1
            continue
        try:
            options = json.loads(text[o : oe + 1])
        except Exception:
            options = {}
        fetches.append({"url": url, "options": options})
        pos = oe + 1
    return fetches


def rpc_name(url: str) -> str:
    marker = "MakerSuiteService/"
    if marker not in url:
        return ""
    return url.split(marker, 1)[1].split("?", 1)[0]


def cookie_header_from_export(path: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    items = json.loads(path.read_text(encoding="utf-8"))
    cookies = {}
    domains = {}
    for item in items:
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        if not name or not value:
            continue
        cookies[name] = value
        domains[name] = str(item.get("domain") or "")
    return (
        "; ".join(f"{name}={value}" for name, value in cookies.items()),
        cookies,
        domains,
    )


def clean_headers(headers: dict) -> dict:
    cleaned = {}
    for key, value in (headers or {}).items():
        lowered = str(key).lower()
        if lowered in SENSITIVE_HEADERS:
            continue
        cleaned[str(key)] = str(value)
    return cleaned


def parse_body(body_text: str):
    if not body_text:
        return None
    try:
        return json.loads(body_text)
    except Exception:
        return None


def select_generate_fetch(fetches: list[dict]) -> dict | None:
    candidates = []
    for fetch in fetches:
        options = fetch.get("options") or {}
        if rpc_name(str(fetch.get("url") or "")) != "GenerateContent":
            continue
        if options.get("method") != "POST":
            continue
        body = parse_body(options.get("body") or "")
        if isinstance(body, list) and len(body) >= 5 and isinstance(body[4], str):
            candidates.append(fetch)
    return candidates[-1] if candidates else None


def select_rpc_fetch(fetches: list[dict], name: str) -> dict | None:
    for fetch in reversed(fetches):
        options = fetch.get("options") or {}
        if (
            rpc_name(str(fetch.get("url") or "")) == name
            and options.get("method") == "POST"
        ):
            return fetch
    return None


def make_payload(fetch_dump: Path, cookie_export: Path) -> dict:
    text = fetch_dump.read_text(encoding="utf-8", errors="replace")
    fetches = parse_fetches(text)
    cookie_header, cookies, domains = cookie_header_from_export(cookie_export)
    generate_fetch = select_generate_fetch(fetches)
    count_fetch = select_rpc_fetch(fetches, "CountTokens")
    source_fetch = generate_fetch or count_fetch or {}
    source_options = source_fetch.get("options") or {}
    headers = clean_headers(source_options.get("headers") or {})
    template = parse_body(source_options.get("body") or "") if generate_fetch else None

    payload = {
        "GOOGLE_AI_STUDIO_WEB_COOKIE": cookie_header,
        "GOOGLE_AI_STUDIO_WEB_HEADERS": headers,
        "GOOGLE_AI_STUDIO_WEB_SAPISID": cookies.get("SAPISID", ""),
        "GOOGLE_AI_STUDIO_WEB_SECURE_1PAPISID": cookies.get("__Secure-1PAPISID", ""),
        "GOOGLE_AI_STUDIO_WEB_SECURE_3PAPISID": cookies.get("__Secure-3PAPISID", ""),
        "GOOGLE_AI_STUDIO_WEB_SECURE_1PSID": cookies.get("__Secure-1PSID", ""),
        "GOOGLE_AI_STUDIO_WEB_SECURE_3PSID": cookies.get("__Secure-3PSID", ""),
        "GOOGLE_AI_STUDIO_WEB_COOKIE_DOMAINS": domains,
        "google_ai_studio_web_source": {
            "fetch_dump": str(fetch_dump),
            "cookie_export": str(cookie_export),
            "fetch_count": len(fetches),
            "has_generate_template": bool(template),
            "generate_template_slots": len(template)
            if isinstance(template, list)
            else 0,
            "generate_slot4_length": len(template[4])
            if isinstance(template, list)
            and len(template) > 4
            and isinstance(template[4], str)
            else 0,
            "selected_rpc": rpc_name(str(source_fetch.get("url") or "")),
        },
    }
    if template:
        payload["GOOGLE_AI_STUDIO_WEB_GENERATE_TEMPLATE"] = template
    api_key = headers.get("x-goog-api-key") or headers.get("X-Goog-Api-Key")
    if api_key:
        payload["GOOGLE_AI_STUDIO_WEB_API_KEY"] = api_key
    visit_id = headers.get("x-aistudio-visit-id") or headers.get("X-Aistudio-Visit-Id")
    if visit_id:
        payload["GOOGLE_AI_STUDIO_WEB_VISIT_ID"] = visit_id
    ext = headers.get("x-goog-ext-519733851-bin") or headers.get(
        "X-Goog-Ext-519733851-Bin"
    )
    if ext:
        payload["GOOGLE_AI_STUDIO_WEB_EXT_519733851_BIN"] = ext
    return payload


def main():
    parser = argparse.ArgumentParser(
        description="Extract Google AI Studio Web RPC credentials from a cookie export and Copy-as-fetch network dump."
    )
    parser.add_argument("--fetch-dump", default=str(DEFAULT_FETCH_DUMP))
    parser.add_argument("--cookies", default=str(DEFAULT_COOKIE_EXPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-output", action="store_true")
    args = parser.parse_args()

    payload = make_payload(Path(args.fetch_dump), Path(args.cookies))
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if not args.no_output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
