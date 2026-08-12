import json
import os
import subprocess
import sys
import threading
import time

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
TURNSTILE_FILE = os.environ.get("OPENAI_TURNSTILE_FILE") or os.path.join(PROJECT_ROOT, "openai_turnstile.json")
GRABBER_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "fetch-openai-turnstile.mjs")
GRABBER_LOG = os.path.join(PROJECT_ROOT, "openai-turnstile-grabber.log")

_grabber_lock = threading.Lock()
_active_grabber = None


def debug_log(message: str, **fields):
    if os.environ.get("DEBUG_LOGGING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        payload = {"message": message, **fields}
        print(
            f"[openai-turnstile] {json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
            flush=True,
        )


def turnstile_mode() -> str:
    return os.environ.get("OPENAI_TURNSTILE_MODE", "auto").strip().lower() or "auto"


def ttl_seconds() -> float:
    # Default 0 = session-long token: never expire on a timer, refresh only when a
    # real request fails (the proxy retries with a fresh grab). The OpenAI sentinel
    # turnstile token is reused for the whole session (see chatgpt network dump), so a
    # periodic re-grab is unnecessary. Set a positive value to force re-validation after N seconds.
    try:
        return max(0.0, float(os.environ.get("OPENAI_TURNSTILE_TTL_SECONDS", "0")))
    except ValueError:
        return 0.0


def grabber_timeout_seconds() -> float:
    try:
        return max(10.0, float(os.environ.get("OPENAI_TURNSTILE_TIMEOUT_SECONDS", "150")))
    except ValueError:
        return 150.0


def grab_enabled() -> bool:
    mode = turnstile_mode()
    if mode in {"off", "file"}:
        return False
    return True


def _read_file_token():
    try:
        with open(TURNSTILE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None, 0
    token = str(payload.get("turnstile_token") or "").strip()
    captured_at = int(payload.get("captured_at") or 0)
    if not token:
        return None, captured_at
    return token, captured_at


def fresh_token():
    token, captured_at = _read_file_token()
    if not token:
        return None
    if captured_at and ttl_seconds() > 0:
        age = time.time() - captured_at / 1000.0
        if age > ttl_seconds():
            debug_log("turnstile_param_expired", age_seconds=round(age, 1))
            return None
    return token


def _spawn_grabber(force):
    global _active_grabber
    with _grabber_lock:
        if _active_grabber is not None and _active_grabber.poll() is None:
            return _active_grabber
        if not os.path.exists(GRABBER_SCRIPT):
            debug_log("grabber_script_missing", path=GRABBER_SCRIPT)
            return None
        node = os.environ.get("OPENAI_TURNSTILE_NODE", os.environ.get("ZAI_NODE", "node"))
        command = [
            node,
            GRABBER_SCRIPT,
            "--timeout",
            str(int(grabber_timeout_seconds() * 1000)),
        ]
        headless_env = os.environ.get("OPENAI_TURNSTILE_HEADLESS", "1")
        if headless_env not in {"1", "true", "yes", "on"}:
            command.append("--headed")
        log_handle = open(GRABBER_LOG, "ab")
        log_handle.write(
            f"\n--- turnstile grabber start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode()
        )
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
        )
        _active_grabber = process
        debug_log(
            "turnstile_grabber_started",
            pid=process.pid,
            headless=headless_env not in {"0", "false", "no", "off"},
            force=force,
        )
        process._openai_log_handle = log_handle
        return process


def _wait_for_grabber(process, wait_seconds):
    deadline = time.time() + max(0.0, wait_seconds)
    while time.time() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.25)
    if process.poll() is None:
        debug_log("turnstile_grabber_timed_out", pid=process.pid)
        return None
    try:
        process._openai_log_handle.close()
    except Exception:
        pass
    return fresh_token()


def get_turnstile_token(wait_seconds=0.0):
    token = fresh_token()
    if token:
        return token
    env_token = os.environ.get("OPENAI_WEB_SENTINEL_TURNSTILE", "").strip()
    if env_token:
        return env_token
    if not grab_enabled():
        return None
    process = _spawn_grabber(force=False)
    if process is None:
        return None
    return _wait_for_grabber(process, wait_seconds or grabber_timeout_seconds())


def force_refresh(wait_seconds=None):
    token = fresh_token()
    if not grab_enabled():
        return token or os.environ.get("OPENAI_WEB_SENTINEL_TURNSTILE", "").strip() or None
    if wait_seconds is None:
        wait_seconds = grabber_timeout_seconds()
    process = _spawn_grabber(force=True)
    if process is None:
        return fresh_token()
    return _wait_for_grabber(process, wait_seconds)


def is_turnstile_required_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return "turnstile" in lowered or "sentinel" in lowered


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "get"
    if mode == "refresh":
        result = force_refresh()
    else:
        result = get_turnstile_token()
    if result:
        print(result)
    else:
        print("NO_TURNSTILE_TOKEN", file=sys.stderr)
        sys.exit(1)
