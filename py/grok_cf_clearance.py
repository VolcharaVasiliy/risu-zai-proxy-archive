import json
import os
import subprocess
import sys
import threading
import time

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
CLEARANCE_FILE = os.environ.get("GROK_CF_CLEARANCE_FILE") or os.path.join(
    PROJECT_ROOT, "grok_cf_clearance.json"
)
GRABBER_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "fetch-grok-cf-clearance.mjs")
GRABBER_LOG = os.path.join(PROJECT_ROOT, "grok-clearance-grabber.log")

_grabber_lock = threading.Lock()
_active_grabber = None


def debug_log(message: str, **fields):
    if os.environ.get("DEBUG_LOGGING", "").strip().lower() in {"1", "true", "yes", "on"}:
        payload = {"message": message, **fields}
        print(
            f"[grok-clearance] {json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
            flush=True,
        )


def clearance_mode() -> str:
    return os.environ.get("GROK_CF_CLEARANCE_MODE", "auto").strip().lower() or "auto"


def grabber_timeout_seconds() -> float:
    try:
        return max(10.0, float(os.environ.get("GROK_CF_CLEARANCE_TIMEOUT_SECONDS", "180")))
    except ValueError:
        return 180.0


def grab_enabled() -> bool:
    mode = clearance_mode()
    if mode in {"off", "file"}:
        return False
    return True


def _read_file():
    try:
        with open(CLEARANCE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None, 0
    token = str((payload or {}).get("cf_clearance") or "").strip()
    captured_at = int(payload.get("captured_at") or 0)
    if not token:
        return None, captured_at
    return token, captured_at


def fresh_clearance():
    token, _ = _read_file()
    return token or None


def fresh_cookie():
    _, _captured = _read_file()
    try:
        with open(CLEARANCE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    cookie = str((payload or {}).get("cookie") or "").strip()
    if not cookie:
        return None
    return cookie


def _spawn_grabber(force):
    global _active_grabber
    with _grabber_lock:
        if _active_grabber is not None and _active_grabber.poll() is None:
            return _active_grabber
        if not os.path.exists(GRABBER_SCRIPT):
            debug_log("grabber_script_missing", path=GRABBER_SCRIPT)
            return None
        node = os.environ.get("GROK_NODE", "node")
        command = [
            node,
            GRABBER_SCRIPT,
            "--timeout",
            str(int(grabber_timeout_seconds() * 1000)),
        ]
        headless_env = os.environ.get("GROK_CF_CLEARANCE_HEADLESS", "0")
        if headless_env in {"1", "true", "yes", "on"}:
            command.append("--headless")
        log_handle = open(GRABBER_LOG, "ab")
        log_handle.write(
            f"\n--- grok clearance grabber start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode()
        )
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=log_handle,
            stdin=subprocess.DEVNULL,
        )
        _active_grabber = process
        process._grok_log_handle = log_handle
        debug_log(
            "grabber_started",
            pid=process.pid,
            headless=headless_env in {"1", "true", "yes", "on"},
            force=force,
        )
        return process


def _wait_for_grabber(process, wait_seconds):
    deadline = time.time() + max(0.0, wait_seconds)
    while time.time() < deadline:
        if process.poll() is not None:
            break
        time.sleep(0.25)
    if process.poll() is None:
        debug_log("grabber_timed_out", pid=process.pid)
        return None
    try:
        process._grok_log_handle.close()
    except Exception:
        pass
    return fresh_clearance()


def get_clearance(wait_seconds=180.0):
    token = fresh_clearance()
    if token:
        return token
    if not grab_enabled():
        debug_log("grabber_disabled")
        return None
    process = _spawn_grabber(force=False)
    if process is None:
        return None
    return _wait_for_grabber(process, wait_seconds)


def force_refresh(wait_seconds=None):
    if wait_seconds is None:
        wait_seconds = grabber_timeout_seconds()
    if not grab_enabled():
        return fresh_clearance()
    process = _spawn_grabber(force=True)
    if process is None:
        return fresh_clearance()
    return _wait_for_grabber(process, wait_seconds)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "get"

    if mode == "refresh":
        result = force_refresh()
    else:
        result = get_clearance()
    if result:
        print(result)
    else:
        print("NO_CF_CLEARANCE", file=sys.stderr)
        sys.exit(1)
