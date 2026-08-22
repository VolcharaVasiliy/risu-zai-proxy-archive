import json
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error

try:
    from py.observability import log_event
except ImportError:
    from observability import log_event

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
RECAPTCHA_FILE = os.path.join(PROJECT_ROOT, "lmarena-recaptcha.json")
GRABBER_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "fetch-lmarena-recaptcha.mjs")
GRABBER_LOG = os.path.join(PROJECT_ROOT, "lmarena-recaptcha.log")
BRIDGE_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "lmarena-recaptcha-bridge.mjs")
BRIDGE_LOG = os.path.join(PROJECT_ROOT, "lmarena-bridge.log")
BRIDGE_URL = os.environ.get("LM_ARENA_BRIDGE_URL", "http://127.0.0.1:8772").rstrip("/")
COOKIE_FILE = os.environ.get("LM_ARENA_COOKIE_FILE", r"C:\Users\gamer\Desktop\lmarena-cookie.txt")

_grabber_lock = threading.Lock()
_active_grabber = None
_bridge_lock = threading.Lock()
_bridge_spawned = False


def debug_log(message: str, **fields):
    log_event(f"lmarena_captcha.{message}", level="debug", **fields)


def ttl_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("LM_ARENA_CAPTCHA_TTL_SECONDS", "120")))
    except ValueError:
        return 120.0


def grabber_timeout_seconds() -> float:
    try:
        return max(10.0, float(os.environ.get("LM_ARENA_CAPTCHA_TIMEOUT_SECONDS", "150")))
    except ValueError:
        return 150.0


def bridge_enabled() -> bool:
    return os.environ.get("LM_ARENA_BRIDGE_MODE", "auto").strip().lower() in {"auto", "on", "true", "1"}


def _read_file_param():
    try:
        with open(RECAPTCHA_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None, 0
    token = str(payload.get("token") or "")
    captured_at = int(payload.get("captured_at") or 0)
    return (token or None), captured_at


def fresh_token():
    token, captured_at = _read_file_param()
    if not token:
        return None
    if captured_at and ttl_seconds() > 0:
        age = time.time() - captured_at / 1000.0
        if age > ttl_seconds():
            debug_log("recaptcha_expired", age_seconds=round(age, 1))
            return None
    return token


def _http_get_json(url: str, timeout: float):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None


def _bridge_mint(max_wait: float = 60.0):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        data = _http_get_json(f"{BRIDGE_URL}/mint", 20)
        if data and isinstance(data, dict) and data.get("token"):
            tok = str(data["token"])
            if len(tok) >= 100:
                return tok
        time.sleep(1.0)
    return None


def _ensure_bridge():
    global _bridge_spawned
    with _bridge_lock:
        try:
            from py.bridge_manager import ensure as manager_ensure
        except ImportError:
            from bridge_manager import ensure as manager_ensure
        if manager_ensure("lmarena"):
            _bridge_spawned = True
            return
        if _bridge_spawned:
            return
        if _http_get_json(f"{BRIDGE_URL}/health", 2):
            _bridge_spawned = True
            return
        if not os.path.exists(BRIDGE_SCRIPT):
            debug_log("bridge_script_missing", path=BRIDGE_SCRIPT)
            return
        node = os.environ.get("LM_ARENA_NODE", "node")
        command = [node, BRIDGE_SCRIPT, "--cookie-file", COOKIE_FILE]
        log_handle = open(BRIDGE_LOG, "ab")
        log_handle.write(f"\n--- bridge start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode())
        subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL)
        _bridge_spawned = True


def _spawn_grabber():
    global _active_grabber
    with _grabber_lock:
        if _active_grabber is not None and _active_grabber.poll() is None:
            return _active_grabber
        if not os.path.exists(GRABBER_SCRIPT):
            debug_log("grabber_script_missing", path=GRABBER_SCRIPT)
            return None
        node = os.environ.get("LM_ARENA_NODE", "node")
        command = [node, GRABBER_SCRIPT, "--cookie-file", COOKIE_FILE, "--out", RECAPTCHA_FILE]
        if os.environ.get("LM_ARENA_CAPTCHA_HEADLESS", "0") not in {"1", "true", "yes", "on"}:
            command.append("--headed")
        log_handle = open(GRABBER_LOG, "ab")
        log_handle.write(f"\n--- grabber start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode())
        process = subprocess.Popen(command, cwd=PROJECT_ROOT, stdout=log_handle, stderr=log_handle, stdin=subprocess.DEVNULL)
        _active_grabber = process
        process._lm_log_handle = log_handle
        return process


def get_token(wait_seconds=None):
    if bridge_enabled():
        _ensure_bridge()
        tok = _bridge_mint()
        if tok:
            return tok
    token = fresh_token()
    if token:
        return token
    return _grab_and_wait(wait_seconds)


def force_refresh(wait_seconds=None):
    if bridge_enabled():
        _ensure_bridge()
        tok = _bridge_mint()
        if tok:
            return tok
    return _grab_and_wait(wait_seconds)


def _grab_and_wait(wait_seconds=None):
    if wait_seconds is None:
        wait_seconds = grabber_timeout_seconds()
    process = _spawn_grabber()
    if process is None:
        return None
    deadline = time.time() + max(0.0, wait_seconds)
    while time.time() < deadline and process.poll() is None:
        time.sleep(0.3)
    try:
        process._lm_log_handle.close()
    except Exception:
        pass
    return fresh_token()


if __name__ == "__main__":
    result = get_token()
    if result:
        print(result)
    else:
        print("NO_RECAPTCHA_TOKEN", file=__import__("sys").stderr)
        __import__("sys").exit(1)
