import argparse
import base64
import ctypes
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(data: bytes) -> bytes:
    if not data:
        return b""

    in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _load_master_key(local_state_path: Path) -> bytes:
    raw = json.loads(local_state_path.read_text(encoding="utf-8"))
    encrypted_key = base64.b64decode(raw["os_crypt"]["encrypted_key"])
    if encrypted_key.startswith(b"DPAPI"):
        encrypted_key = encrypted_key[5:]
    return _dpapi_unprotect(encrypted_key)


def _decrypt_cookie_value(blob: bytes, master_key: bytes) -> str:
    if not blob:
        return ""
    if blob.startswith((b"v10", b"v11", b"v20")):
        nonce = blob[3:15]
        ciphertext = blob[15:]
        plain = AESGCM(master_key).decrypt(nonce, ciphertext, None)
        try:
            return plain.decode("utf-8")
        except UnicodeDecodeError:
            if len(plain) > 32:
                return plain[32:].decode("utf-8")
            raise
    return _dpapi_unprotect(blob).decode("utf-8")


def _candidate_cookie_dbs(profile_root: Path):
    return [
        profile_root / "Default" / "Network" / "Cookies",
        profile_root / "Default" / "Cookies",
        profile_root / "Network" / "Cookies",
    ]


def _read_cookie_rows(cookie_db_path: Path):
    uri = cookie_db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as conn:
        return conn.execute(
            """
            select host_key, name, value, encrypted_value
            from cookies
            where host_key like '%grok.com%' or host_key like '%x.ai%'
            order by
              case name
                when 'sso' then 0
                when 'sso-rw' then 1
                when 'cf_clearance' then 2
                else 10
              end,
              host_key,
              name
            """
        ).fetchall()


def _extract_cookies(profile_root: Path):
    local_state = profile_root / "Local State"
    if not local_state.exists():
        raise FileNotFoundError(f"Local State not found under {profile_root}")

    cookie_db = next((path for path in _candidate_cookie_dbs(profile_root) if path.exists()), None)
    if cookie_db is None:
        raise FileNotFoundError(f"Chromium Cookies DB not found under {profile_root}")

    tmp_root = profile_root.parent / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    copied_db = tmp_root / f"{profile_root.name}-grok-cookies.db"

    master_key = _load_master_key(local_state)
    rows = []
    copied = False
    try:
        shutil.copy2(cookie_db, copied_db)
        copied = True
    except PermissionError:
        copied = False

    try:
        rows = _read_cookie_rows(copied_db if copied else cookie_db)
    finally:
        if copied:
            try:
                copied_db.unlink()
            except OSError:
                pass

    cookies = {}
    domains = {}
    for host_key, name, value, encrypted_value in rows:
        plain = value or ""
        if not plain and encrypted_value:
            try:
                plain = _decrypt_cookie_value(encrypted_value, master_key)
            except Exception:
                plain = ""
        if plain:
            cookies[str(name)] = plain
            domains[str(name)] = str(host_key)

    return cookies, domains


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile-root",
        default=r"F:\Projects\risu-zai-proxy\auth\grok-edge-profile",
        help="Chromium user-data-dir root used for the Grok login browser session.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON output path.",
    )
    args = parser.parse_args()

    profile_root = Path(args.profile_root)
    cookies, domains = _extract_cookies(profile_root)
    ordered_names = list(cookies.keys())
    cookie_header = "; ".join(f"{name}={cookies[name]}" for name in ordered_names)

    result = {
        "profile_root": str(profile_root),
        "cookie_count": len(cookies),
        "cookie_names": ordered_names,
        "domains": domains,
        "grok_cookie": cookie_header,
        "grok_sso": cookies.get("sso", ""),
        "grok_sso_rw": cookies.get("sso-rw", ""),
        "grok_cf_clearance": cookies.get("cf_clearance", ""),
    }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
