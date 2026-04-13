import base64
import ctypes
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = Path(r"C:\Users\gamer\AppData\Roaming\chat2api")
PARTITIONS_ROOT = ROOT / "Partitions"


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


def _load_master_key() -> bytes:
    local_state = ROOT / "Local State"
    raw = json.loads(local_state.read_text(encoding="utf-8"))
    encrypted_key = base64.b64decode(raw["os_crypt"]["encrypted_key"])
    if encrypted_key.startswith(b"DPAPI"):
        encrypted_key = encrypted_key[5:]
    return _dpapi_unprotect(encrypted_key)


def _iter_partitions():
    if not PARTITIONS_ROOT.exists():
        return []
    return sorted((p for p in PARTITIONS_ROOT.iterdir() if p.is_dir() and p.name.startswith("oauth-")), key=lambda p: p.stat().st_mtime, reverse=True)


def _read_leveldb_text(partition: Path) -> str:
    leveldb = partition / "Local Storage" / "leveldb"
    if not leveldb.exists():
        return ""
    chunks = []
    for path in sorted(leveldb.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            chunks.append(path.read_bytes().decode("latin-1", errors="ignore"))
        except Exception:
            continue
    return "\n".join(chunks)


def _find_partition_by_domain(domain_hint: str):
    needle = domain_hint.lower()
    for partition in _iter_partitions():
        text = _read_leveldb_text(partition)
        if needle in text.lower():
            return partition, text
    return None, ""


def _find_partition_by_any_domain(domain_hints):
    needles = [str(item or "").lower() for item in domain_hints if str(item or "").strip()]
    for partition in _iter_partitions():
        text = _read_leveldb_text(partition).lower()
        if any(needle in text for needle in needles):
            return partition, text
    return None, ""


def _find_partition_with_cookie(domain_like: str, cookie_name: str):
    for partition in _iter_partitions():
        cookie_header = _extract_cookie_header(partition, domain_like)
        if _cookie_value(cookie_header, cookie_name):
            return partition, cookie_header
    return None, ""


def _extract_last_jwt(text: str) -> str:
    matches = re.findall(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", text or "")
    return matches[-1] if matches else ""


def _extract_storage_value(text: str, key: str) -> str:
    pattern = re.compile(re.escape(key) + r'.{0,256}?"value":"([^"]+)"', re.IGNORECASE | re.DOTALL)
    matches = pattern.findall(text or "")
    if not matches and key in {"access_token", "refresh_token", "anonymous_access_token", "anonymous_refresh_token"}:
        raw_pattern = re.compile(re.escape(key) + r".{0,64}(eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)", re.IGNORECASE | re.DOTALL)
        matches = raw_pattern.findall(text or "")
    return matches[-1] if matches else ""


def _decrypt_cookie_value(blob: bytes, master_key: bytes) -> str:
    if not blob:
        return ""
    if blob.startswith((b"v10", b"v11", b"v20")):
        nonce = blob[3:15]
        ciphertext = blob[15:]
        return AESGCM(master_key).decrypt(nonce, ciphertext, None).decode("utf-8")
    return _dpapi_unprotect(blob).decode("utf-8")


def _extract_cookie_header(partition: Path, domain_like: str) -> str:
    cookie_db = partition / "Network" / "Cookies"
    if not cookie_db.exists():
        return ""

    tmp_root = Path(__file__).resolve().parents[1] / ".tmp"
    tmp_root.mkdir(exist_ok=True)
    copied_db = tmp_root / f"{partition.name}-cookies.db"
    shutil.copy2(cookie_db, copied_db)

    master_key = _load_master_key()
    cookies = {}
    try:
        with sqlite3.connect(str(copied_db)) as conn:
            rows = conn.execute(
                "select host_key, name, value, encrypted_value from cookies where host_key like ? order by host_key, name",
                (f"%{domain_like}%",),
            ).fetchall()
        for _host_key, name, value, encrypted_value in rows:
            plain = value or ""
            if not plain and encrypted_value:
                try:
                    plain = _decrypt_cookie_value(encrypted_value, master_key)
                except Exception:
                    plain = ""
            if plain:
                cookies[str(name)] = plain
    finally:
        try:
            copied_db.unlink()
        except OSError:
            pass

    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _cookie_value(cookie_header: str, name: str) -> str:
    match = re.search(rf"(?:^|;\s*){re.escape(name)}=([^;]+)", cookie_header or "")
    return match.group(1) if match else ""


def _normalize_value(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def main():
    result = {
        "zai_token": "",
        "deepseek_token": "",
        "kimi_access_token": "",
        "kimi_refresh_token": "",
        "gemini_web_cookie": "",
        "gemini_web_secure_1psid": "",
        "gemini_web_secure_1psidts": "",
        "mimo_cookie": "",
        "mimo_service_token": "",
        "mimo_user_id": "",
        "mimo_ph_token": "",
        "qwen_cookie": "",
        "qwen_token": "",
        "perplexity_cookie": "",
        "perplexity_session_token": "",
        "partitions": {},
    }

    zai_partition, zai_text = _find_partition_by_domain("chat.z.ai")
    if zai_partition:
        result["partitions"]["zai"] = str(zai_partition)
        result["zai_token"] = _extract_last_jwt(zai_text)

    deepseek_partition, deepseek_text = _find_partition_by_domain("chat.deepseek.com")
    if deepseek_partition:
        result["partitions"]["deepseek"] = str(deepseek_partition)
        result["deepseek_token"] = _extract_storage_value(deepseek_text, "userToken")

    kimi_partition, kimi_text = _find_partition_by_domain("www.kimi.com")
    if kimi_partition:
        result["partitions"]["kimi"] = str(kimi_partition)
        result["kimi_access_token"] = _extract_storage_value(kimi_text, "access_token")
        result["kimi_refresh_token"] = _extract_storage_value(kimi_text, "refresh_token")

    gemini_partition, gemini_cookie = _find_partition_with_cookie("google.com", "__Secure-1PSID")
    if not gemini_partition:
        gemini_partition, _gemini_text = _find_partition_by_any_domain(["gemini.google.com", "google.com"])
        if gemini_partition:
            gemini_cookie = _extract_cookie_header(gemini_partition, "google.com")
    if gemini_partition:
        result["partitions"]["gemini_web"] = str(gemini_partition)
        result["gemini_web_cookie"] = gemini_cookie
        result["gemini_web_secure_1psid"] = _cookie_value(result["gemini_web_cookie"], "__Secure-1PSID")
        result["gemini_web_secure_1psidts"] = _cookie_value(result["gemini_web_cookie"], "__Secure-1PSIDTS")

    mimo_partition, _mimo_text = _find_partition_by_domain("aistudio.xiaomimimo.com")
    if mimo_partition:
        result["partitions"]["mimo"] = str(mimo_partition)
        result["mimo_cookie"] = _extract_cookie_header(mimo_partition, "xiaomimimo.com")
        result["mimo_service_token"] = _normalize_value(_cookie_value(result["mimo_cookie"], "serviceToken"))
        result["mimo_user_id"] = _normalize_value(_cookie_value(result["mimo_cookie"], "userId"))
        result["mimo_ph_token"] = _normalize_value(_cookie_value(result["mimo_cookie"], "xiaomichatbot_ph"))

    qwen_partition, _qwen_text = _find_partition_by_domain("chat.qwen.ai")
    if qwen_partition:
        result["partitions"]["qwen"] = str(qwen_partition)
        result["qwen_cookie"] = _extract_cookie_header(qwen_partition, "qwen.ai")
        result["qwen_token"] = _cookie_value(result["qwen_cookie"], "token")

    perplexity_partition, _perplexity_text = _find_partition_by_domain("www.perplexity.ai")
    if perplexity_partition:
        result["partitions"]["perplexity"] = str(perplexity_partition)
        result["perplexity_cookie"] = _extract_cookie_header(perplexity_partition, "perplexity.ai")
        result["perplexity_session_token"] = _cookie_value(result["perplexity_cookie"], "__Secure-next-auth.session-token")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
