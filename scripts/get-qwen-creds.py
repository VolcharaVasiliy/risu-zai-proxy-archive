import argparse
import base64
import ctypes
import json
import re
import shutil
import sqlite3
import tempfile
from ctypes import Structure, byref, c_void_p, windll, wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


COOKIE_NAMES = [
    "atpsida",
    "aui",
    "cna",
    "cnaui",
    "isg",
    "sca",
    "token",
    "acw_tc",
    "qwen-locale",
    "qwen-theme",
    "x-ap",
]


class DATA_BLOB(Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", c_void_p)]


CRYPT_UNPROTECT = windll.crypt32.CryptUnprotectData
LOCAL_FREE = windll.kernel32.LocalFree
LOCAL_FREE.argtypes = [c_void_p]
LOCAL_FREE.restype = c_void_p


def dpapi_decrypt(encrypted: bytes) -> bytes:
    buffer = ctypes.create_string_buffer(encrypted, len(encrypted))
    blob_in = DATA_BLOB(len(encrypted), ctypes.cast(buffer, c_void_p))
    blob_out = DATA_BLOB()
    if not CRYPT_UNPROTECT(byref(blob_in), None, None, None, None, 0, byref(blob_out)):
        raise RuntimeError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        LOCAL_FREE(c_void_p(blob_out.pbData))


def chrome_master_key(local_state_path: Path) -> bytes:
    local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
    encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    if encrypted_key.startswith(b"DPAPI"):
        encrypted_key = encrypted_key[5:]
    return dpapi_decrypt(encrypted_key)


def decrypt_cookie_value(master_key: bytes, encrypted_value: bytes, plain_value: str) -> str:
    if plain_value:
        return plain_value
    if not encrypted_value:
        return ""
    raw = encrypted_value
    if raw[:3] in {b"v10", b"v11", b"v20"}:
        raw = AESGCM(master_key).decrypt(raw[3:15], raw[15:], None)
    else:
        raw = dpapi_decrypt(raw)
    return raw.decode("utf-8", "replace")


def sanitize_cookie(name: str, value: str) -> str:
    text = str(value or "")
    if name == "token":
        match = re.search(r"(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)", text)
        return match.group(1) if match else ""
    if name == "acw_tc":
        match = re.search(r"(0[a-f0-9]{24,})", text)
        return match.group(1) if match else ""
    if name in {"qwen-locale", "qwen-theme", "x-ap"}:
        match = re.findall(r"[A-Za-z0-9._:-]{2,}", text)
        return match[-1] if match else ""
    match = re.findall(r"[A-Za-z0-9._:+/=-]{4,}", text)
    if not match:
        return ""
    candidate = match[-1]
    if candidate.startswith("ao") and len(candidate) > 6:
        candidate = candidate[2:]
    return candidate


def load_cookie_header(cookies_db: Path, master_key: bytes) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="qwen-cookie-copy-") as temp_dir:
        copied = Path(temp_dir) / "Cookies"
        shutil.copy2(cookies_db, copied)
        conn = sqlite3.connect(copied)
        try:
            rows = conn.execute(
                """
                select host_key, name, value, encrypted_value
                from cookies
                where host_key like '%qwen.ai%'
                order by host_key, name
                """
            ).fetchall()
        finally:
            conn.close()

    values = {}
    token = ""
    for _host, name, value, encrypted_value in rows:
        if name not in COOKIE_NAMES:
            continue
        plain = sanitize_cookie(name, decrypt_cookie_value(master_key, encrypted_value, value))
        if not plain:
            continue
        values[name] = plain
        if name == "token":
            token = plain

    ordered = [f"{name}={values[name]}" for name in COOKIE_NAMES if values.get(name)]
    return "; ".join(ordered), token


def parse_netlog(netlog_path: Path) -> dict:
    text = netlog_path.read_text(encoding="utf-8")
    bx_ua_matches = re.findall(r'"bx-ua":\s*"([^"]+)"', text)
    bx_umidtoken = re.search(r'"bx-umidtoken":\s*"([^"]+)"', text)
    bx_v = re.search(r'"bx-v":\s*"([^"]+)"', text)
    timezone = re.search(r'"timezone":\s*"([^"]+)"', text)
    return {
        "qwen_ai_bx_ua": bx_ua_matches[0] if bx_ua_matches else "",
        "qwen_ai_bx_ua_create": bx_ua_matches[0] if bx_ua_matches else "",
        "qwen_ai_bx_ua_chat": bx_ua_matches[1] if len(bx_ua_matches) > 1 else (bx_ua_matches[0] if bx_ua_matches else ""),
        "qwen_ai_bx_umidtoken": bx_umidtoken.group(1) if bx_umidtoken else "",
        "qwen_ai_bx_v": bx_v.group(1) if bx_v else "2.5.36",
        "qwen_ai_timezone": timezone.group(1) if timezone else "Thu Apr 16 2026 00:34:21 GMT+0300",
    }


def resolve_default_netlog() -> Path:
    desktop = Path(r"C:\Users\gamer\Desktop")
    matches = sorted(desktop.glob("*квен*сетка*.txt"))
    if matches:
        return matches[-1]
    raise RuntimeError("Qwen netlog file was not found on the Desktop")


def main():
    parser = argparse.ArgumentParser(description="Extract Qwen cookies and bx headers into auth\\qwen-creds.json")
    parser.add_argument(
        "--cookies-db",
        default=r"F:\Projects\risu-zai-proxy-archive\run\qwen-browser-cookies.db",
        help="Path to a copied Chromium cookies DB",
    )
    parser.add_argument(
        "--local-state",
        default=r"F:\Projects\risu-zai-proxy-archive\run\qwen-browser-local-state.json",
        help="Path to the copied Chromium Local State file",
    )
    parser.add_argument(
        "--netlog",
        default="",
        help="Path to the exported Qwen fetch log text file",
    )
    parser.add_argument(
        "--out",
        default=r"F:\Projects\risu-zai-proxy-archive\auth\qwen-creds.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    cookies_db = Path(args.cookies_db)
    local_state = Path(args.local_state)
    netlog_path = Path(args.netlog) if args.netlog else resolve_default_netlog()
    output_path = Path(args.out)

    master_key = chrome_master_key(local_state)
    cookie_header, token = load_cookie_header(cookies_db, master_key)
    netlog = parse_netlog(netlog_path)

    payload = {
        "qwen_ai_cookie": cookie_header,
        "qwen_ai_token": token,
        **netlog,
        "source_cookies_db": str(cookies_db),
        "source_netlog": str(netlog_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
