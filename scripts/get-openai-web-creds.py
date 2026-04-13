import argparse
import base64
import ctypes
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


POWERSHELL_EXE = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
NODE_CANDIDATES = [
    Path(r"F:\DevTools\Portable\NodeJS\node.exe"),
    Path(r"F:\DevTools\NodeJS\node.exe"),
]
BROWSER_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


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


def _read_cookie_rows(cookie_db_path: Path):
    with sqlite3.connect(str(cookie_db_path)) as conn:
        return conn.execute(
            """
            select host_key, name, value, encrypted_value
            from cookies
            where host_key like '%chatgpt.com%' or host_key like '%openai.com%'
            order by host_key, name
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
    copied_db = tmp_root / f"{profile_root.name}-openai-cookies.db"

    master_key = _load_master_key(local_state)
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


def _resolve_existing_path(candidates, explicit: str = "") -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"Required path does not exist: {path}")
        return path
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise FileNotFoundError("Required executable was not found in the expected locations")


def _powershell_command(command: str):
    shell = str(POWERSHELL_EXE if POWERSHELL_EXE.exists() else "powershell")
    return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]


def _stop_profile_browsers(profile_root: Path):
    profile = str(profile_root).replace("'", "''")
    command = (
        f"$profile = '{profile}'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { ($_.Name -in @('msedge.exe','chrome.exe')) -and $_.CommandLine -like \"*$profile*\" } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(_powershell_command(command), capture_output=True, text=True, check=False)


def _launch_browser_for_cdp(profile_root: Path, browser_path: Path, cdp_port: int):
    args = [
        str(browser_path),
        f"--remote-debugging-port={cdp_port}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_root}",
        "https://chatgpt.com/",
    ]
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def _wait_for_cdp(port: int, timeout_sec: int = 30):
    deadline = time.time() + timeout_sec
    url = f"http://127.0.0.1:{port}/json/version"
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"OpenAI Web CDP did not start on port {port}: {last_error}")


def _run_cdp_session(node_path: Path, cdp_port: int):
    script_path = PROJECT_ROOT / "scripts" / "get-openai-web-session.mjs"
    result = subprocess.run(
        [str(node_path), str(script_path), "--port", str(cdp_port)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(f"OpenAI Web CDP extractor failed: {message}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenAI Web CDP extractor returned invalid JSON: {exc}") from exc


def _fetch_session_via_cdp(profile_root: Path, browser_path: Path, node_path: Path, cdp_port: int):
    _stop_profile_browsers(profile_root)
    browser_proc = _launch_browser_for_cdp(profile_root, browser_path, cdp_port)
    try:
        _wait_for_cdp(cdp_port)
        return _run_cdp_session(node_path, cdp_port)
    finally:
        if browser_proc.poll() is None:
            browser_proc.terminate()
            try:
                browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser_proc.kill()
        time.sleep(1)
        _stop_profile_browsers(profile_root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-root", default=r"F:\Projects\risu-zai-proxy\auth\openai-web-edge-profile")
    parser.add_argument("--output", default="")
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--node-path", default="")
    parser.add_argument("--cdp-port", type=int, default=9222)
    args = parser.parse_args()

    profile_root = Path(args.profile_root)
    browser_path = _resolve_existing_path(BROWSER_CANDIDATES, args.browser_path)
    node_path = _resolve_existing_path(NODE_CANDIDATES, args.node_path)

    _stop_profile_browsers(profile_root)
    cookies, domains = _extract_cookies(profile_root)
    cookie_names = list(cookies.keys())
    cookie_header = "; ".join(f"{name}={cookies[name]}" for name in cookie_names)

    session_data = _fetch_session_via_cdp(
        profile_root=profile_root,
        browser_path=browser_path,
        node_path=node_path,
        cdp_port=args.cdp_port,
    )

    access_token = str(session_data.get("accessToken") or "").strip()
    if not access_token:
        raise RuntimeError("OpenAI Web CDP session did not return accessToken")

    account = session_data.get("account") or {}
    active_account_ids = list(session_data.get("accountOrdering") or [])
    account_id = str(account.get("id") or (active_account_ids[0] if active_account_ids else "")).strip()
    plan_type = str(account.get("planType") or "").strip()
    models = []
    seen = set()
    for item in session_data.get("modelSlugs") or []:
        value = str(item or "").strip()
        lowered = value.lower()
        if value and lowered not in seen:
            models.append(value)
            seen.add(lowered)

    result = {
        "profile_root": str(profile_root),
        "cookie_count": len(cookies),
        "cookie_names": cookie_names,
        "domains": domains,
        "openai_web_cookie": cookie_header,
        "openai_web_access_token": access_token,
        "openai_web_device_id": str(session_data.get("deviceId") or cookies.get("oai-did") or ""),
        "openai_web_account_id": account_id,
        "openai_web_models": models,
        "session_user": session_data.get("user") or {},
        "session_account": account,
        "account_check_info": {
            "active_account_ids": active_account_ids,
            "team_ids": [],
            "plan_type": plan_type,
        },
    }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
