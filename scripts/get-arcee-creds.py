import argparse
import base64
import ctypes
import json
import shutil
import sqlite3
import tempfile
from ctypes import Structure, byref, c_void_p, windll, wintypes
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


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

    text = raw.decode("utf-8", "replace")
    marker = "eyJ"
    if marker in text:
        return text[text.index(marker) :].strip()
    return text.strip()


def extract_access_token(cookies_db: Path, master_key: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="arcee-cookie-copy-") as temp_dir:
        copied = Path(temp_dir) / "Cookies"
        shutil.copy2(cookies_db, copied)
        conn = sqlite3.connect(copied)
        try:
            row = conn.execute(
                """
                select encrypted_value, value
                from cookies
                where host_key = 'api.arcee.ai' and name = 'access_token'
                order by creation_utc desc
                limit 1
                """
            ).fetchone()
        finally:
            conn.close()

    if not row:
        raise RuntimeError("Arcee access_token cookie was not found")

    token = decrypt_cookie_value(master_key, row[0], row[1])
    if not token.startswith("eyJ"):
        raise RuntimeError("Arcee access token was found but could not be decoded cleanly")
    return token


def main():
    parser = argparse.ArgumentParser(description="Extract the Arcee bearer token from a Chromium/Yandex profile.")
    parser.add_argument(
        "--user-data-dir",
        default=r"C:\Users\gamer\AppData\Local\Yandex\YandexBrowser\User Data",
        help="Chromium-style user data dir",
    )
    parser.add_argument(
        "--profile",
        default="Default",
        help="Profile directory name inside the user data dir",
    )
    parser.add_argument(
        "--out",
        default=r"F:\Projects\risu-zai-proxy-archive\auth\arcee-creds.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--cookies-db",
        default="",
        help="Optional explicit path to a copied Chromium Cookies sqlite DB",
    )
    parser.add_argument(
        "--local-state",
        default="",
        help="Optional explicit path to a copied Chromium Local State json file",
    )
    args = parser.parse_args()

    user_data_dir = Path(args.user_data_dir)
    profile_dir = user_data_dir / args.profile
    cookies_db = Path(args.cookies_db) if args.cookies_db else (profile_dir / "Network" / "Cookies")
    local_state = Path(args.local_state) if args.local_state else (user_data_dir / "Local State")
    output_path = Path(args.out)

    master_key = chrome_master_key(local_state)
    token = extract_access_token(cookies_db, master_key)

    payload = {
        "access_token": token,
        "source_profile": str(profile_dir),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(output_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
