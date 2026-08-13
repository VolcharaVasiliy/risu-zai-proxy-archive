#!/usr/bin/env python3
"""Extract Qwen bx-* + cookies from DevTools exports (сеть.txt/куки.txt) into credentials.json.

The export file paths are configurable: pass them as positional arguments, or set the
QWEN_NET_FILE / QWEN_COOKIES_FILE environment variables. Without either, the script
looks for the files on the current user's Desktop (cross-user safe).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

CREDS = Path(__file__).resolve().parents[1] / "credentials.json"


def _resolve_export(arg_value: str, env_key: str, default_name: str) -> Path:
    if arg_value:
        return Path(arg_value)
    env_value = os.environ.get(env_key, "").strip()
    if env_value:
        return Path(env_value)
    return Path.home() / "Desktop" / default_name


def load_net(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def extract_bx_ua(text: str) -> dict:
    out = {}
    # блок fetch("URL", {... "headers": { ... "bx-ua": "..." ...}})
    pattern = re.compile(
        r'fetch\("(https://chat\.qwen\.ai/api/v2/[^"]+)"[^}]*?"headers":\s*\{([^}]*?)\}',
        re.S,
    )
    for m in pattern.finditer(text):
        url = m.group(1)
        headers = m.group(2)
        bx_ua = re.search(r'"bx-ua":\s*"([^"]+)"', headers)
        umid = re.search(r'"bx-umidtoken":\s*"([^"]+)"', headers)
        bx_v = re.search(r'"bx-v":\s*"([^"]+)"', headers)
        tz = re.search(r'"timezone":\s*"([^"]+)"', headers)
        if "/chats/new" in url:
            key = "create"
        elif "chat/completions" in url:
            key = "chat"
        elif "/api/v2/chats/?" in url or "/api/v2/chats?page" in url or "chats/?page" in url:
            key = "list"
        else:
            key = url.split("/api/v2/")[-1].split("?")[0].replace("/", "_")
        rec = out.setdefault(key, {})
        if bx_ua:
            rec["bx_ua"] = bx_ua.group(1)
        if umid:
            rec["bx_umidtoken"] = umid.group(1)
        if bx_v:
            rec["bx_v"] = bx_v.group(1)
        if tz:
            rec["timezone"] = tz.group(1)
    return out


def extract_cookies(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {"header": "", "token": ""}
    pairs = []
    for c in data:
        name, value = c.get("name", ""), c.get("value", "")
        if not value:
            continue
        pairs.append(f"{name}={value}")
        if name == "token":
            out["token"] = value
    pairs.sort()
    out["header"] = "; ".join(pairs)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Qwen bx-* + cookies from DevTools exports into credentials.json"
    )
    parser.add_argument("net_file", nargs="?", help="DevTools network export (e.g. сеть.txt)")
    parser.add_argument("cookies_file", nargs="?", help="DevTools cookies export (e.g. куки.txt)")
    args = parser.parse_args()

    net_path = _resolve_export(args.net_file, "QWEN_NET_FILE", "сеть.txt")
    cookies_path = _resolve_export(args.cookies_file, "QWEN_COOKIES_FILE", "куки.txt")

    text = load_net(net_path)
    creds = json.loads(CREDS.read_text(encoding="utf-8"))
    updated = []

    bx = extract_bx_ua(text)
    if bx.get("create", {}).get("bx_ua"):
        creds["QWEN_AI_BX_UA_CREATE"] = bx["create"]["bx_ua"]
        creds["QWEN_AI_BX_UA"] = creds["QWEN_AI_BX_UA_CREATE"]
        updated += ["QX_Б_UA_CREATE", "QWEN_AI_BX_UA"]
    if bx.get("chat", {}).get("bx_ua"):
        creds["QWEN_AI_BX_UA_CHAT"] = bx["chat"]["bx_ua"]
        updated.append("QWEN_AI_BX_UA_CHAT")
    for key in ("bx_umidtoken",):
        for phase in ("create", "chat"):
            if bx.get(phase, {}).get(key):
                creds["QWEN_AI_BX_UMIDTOKEN"] = bx[phase][key]
                updated.append("QWEN_AI_BX_UMIDTOKEN")
                break
    for phase in ("create", "chat", "list"):
        rec = bx.get(phase) or {}
        if rec.get("bx_v"):
            creds["QWEN_AI_BX_V"] = rec["bx_v"]
            updated.append("QWEN_AI_BX_V")
        if rec.get("timezone"):
            creds["QWEN_AI_TIMEZONE"] = rec["timezone"]
            updated.append("QWEN_AI_TIMEZONE")
        if "bx_v" in rec and "timezone" in rec:
            break

    cookies = extract_cookies(cookies_path)
    if cookies.get("header"):
        creds["QWEN_AI_COOKIE"] = cookies["header"]
        updated.append("QWEN_AI_COOKIE")
    if cookies.get("token"):
        creds["QWEN_AI_TOKEN"] = cookies["token"]
        updated.append("QWEN_AI_TOKEN")

    CREDS.write_text(json.dumps(creds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if updated:
        print("Updated:", ", ".join(dict.fromkeys(updated)))
    else:
        print("Nothing extracted — check files")
    return 0


if __name__ == "__main__":
    sys.exit(main())