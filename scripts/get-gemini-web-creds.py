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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from py import gemini_web_proxy


CHAT2API_ROOT = Path(r"C:\Users\gamer\AppData\Roaming\chat2api")
YANDEX_USER_DATA_ROOT = Path(r"C:\Users\gamer\AppData\Local\Yandex\YandexBrowser\User Data")


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(data: bytes) -> bytes:
    if not data:
        return b""
    in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
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


def _read_cookie_rows(cookie_db_path: Path, domain_like: str):
    with sqlite3.connect(str(cookie_db_path)) as conn:
        return conn.execute(
            """
            select host_key, name, value, encrypted_value
            from cookies
            where host_key like ?
            order by host_key, name
            """,
            (f"%{domain_like}%",),
        ).fetchall()


def _extract_cookie_bundle(local_state_path: Path, cookie_db_path: Path, temp_name: str, domain_like: str):
    temp_root = PROJECT_ROOT / ".tmp"
    temp_root.mkdir(exist_ok=True)
    copied_db = temp_root / f"{temp_name}.db"

    master_key = _load_master_key(local_state_path)
    copied = False
    try:
        shutil.copy2(cookie_db_path, copied_db)
        copied = True
    except PermissionError:
        copied = False

    try:
        rows = _read_cookie_rows(copied_db if copied else cookie_db_path, domain_like)
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


def _profile_cookies(profile_root: Path):
    local_state = profile_root / "Local State"
    cookie_db = next((path for path in _candidate_cookie_dbs(profile_root) if path.exists()), None)
    if not local_state.exists() or cookie_db is None:
        return {}, {}, "", ""
    try:
        cookies, domains = _extract_cookie_bundle(local_state, cookie_db, f"{profile_root.name}-gemini-web-cookies", "google.com")
        return cookies, domains, "profile", ""
    except Exception as exc:
        return {}, {}, "", str(exc)


def _fallback_profile_roots(primary_root: Path):
    ordered = []
    for root in [primary_root, YANDEX_USER_DATA_ROOT]:
        path = Path(root)
        key = str(path).lower()
        if key in ordered:
            continue
        ordered.append(key)
        yield path


def _iter_chat2api_partitions():
    partitions_root = CHAT2API_ROOT / "Partitions"
    if not partitions_root.exists():
        return []
    return sorted(
        (path for path in partitions_root.iterdir() if path.is_dir() and path.name.startswith("oauth-")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _chat2api_cookies():
    local_state = CHAT2API_ROOT / "Local State"
    if not local_state.exists():
        return {}, {}, ""

    for partition in _iter_chat2api_partitions():
        cookie_db = partition / "Network" / "Cookies"
        if not cookie_db.exists():
            continue
        try:
            cookies, domains = _extract_cookie_bundle(local_state, cookie_db, f"{partition.name}-gemini-web-cookies", "google.com")
        except Exception:
            continue
        if "__Secure-1PSID" in cookies:
            return cookies, domains, str(partition)
    return {}, {}, ""


def _cookie_header(cookies: dict) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _discover_models(cookie_header: str, secure_1psid: str, secure_1psidts: str):
    if not secure_1psid and not cookie_header:
        return [], ""
    try:
        models = gemini_web_proxy.discover_models(
            {
                "cookie": cookie_header,
                "secure_1psid": secure_1psid,
                "secure_1psidts": secure_1psidts,
            }
        )
        return models, ""
    except Exception as exc:
        return [], str(exc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-root", default=r"F:\Projects\risu-zai-proxy\auth\gemini-web-edge-profile")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    profile_root = Path(args.profile_root)
    cookies = {}
    domains = {}
    source = ""
    source_path = str(profile_root) if source == "profile" else ""
    profile_errors = {}

    for candidate_root in _fallback_profile_roots(profile_root):
        this_cookies, this_domains, this_source, this_error = _profile_cookies(candidate_root)
        if this_error:
            profile_errors[str(candidate_root)] = this_error
        if "__Secure-1PSID" in this_cookies:
            cookies = this_cookies
            domains = this_domains
            source = "profile"
            source_path = str(candidate_root)
            break

    if "__Secure-1PSID" not in cookies:
        chat2api_cookies, chat2api_domains, partition_path = _chat2api_cookies()
        if chat2api_cookies:
            cookies = chat2api_cookies
            domains = chat2api_domains
            source = "chat2api"
            source_path = partition_path

    secure_1psid = str(cookies.get("__Secure-1PSID") or "")
    secure_1psidts = str(cookies.get("__Secure-1PSIDTS") or "")
    cookie_header = _cookie_header(cookies)
    models, discovery_error = _discover_models(cookie_header, secure_1psid, secure_1psidts)

    result = {
        "profile_root": str(profile_root),
        "source": source,
        "source_path": source_path,
        "profile_errors": profile_errors,
        "cookie_count": len(cookies),
        "cookie_names": list(cookies.keys()),
        "domains": domains,
        "gemini_web_cookie": cookie_header,
        "gemini_web_secure_1psid": secure_1psid,
        "gemini_web_secure_1psidts": secure_1psidts,
        "gemini_web_models": models,
        "model_discovery_error": discovery_error,
    }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
