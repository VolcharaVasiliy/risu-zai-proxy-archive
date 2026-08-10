import json
import os
import subprocess
import sys
import threading
import time

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(MODULE_DIR)
CAPTCHA_FILE = os.path.join(PROJECT_ROOT, "captcha_param.json")
GRABBER_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "fetch-zai-captcha.mjs")
GRABBER_LOG = os.path.join(PROJECT_ROOT, "captcha-grabber.log")

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
            f"[zai-captcha] {json.dumps(payload, ensure_ascii=False, sort_keys=True)}",
            flush=True,
        )


def captcha_mode() -> str:
    return os.environ.get("ZAI_CAPTCHA_MODE", "auto").strip().lower() or "auto"


def ttl_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get("ZAI_CAPTCHA_TTL_SECONDS", "60")))
    except ValueError:
        return 60.0


def grabber_timeout_seconds() -> float:
    try:
        return max(10.0, float(os.environ.get("ZAI_CAPTCHA_TIMEOUT_SECONDS", "150")))
    except ValueError:
        return 150.0


def grab_enabled() -> bool:
    mode = captcha_mode()
    if mode in {"off", "file"}:
        return False
    if mode in {"grabber", "auto"}:
        return True
    return True


def _read_file_param():
    try:
        with open(CAPTCHA_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None, 0
    param = str(payload.get("captcha_verify_param") or "")
    captured_at = int(payload.get("captured_at") or 0)
    if not param:
        return None, captured_at
    return param, captured_at


def fresh_param():
    param, captured_at = _read_file_param()
    if not param:
        return None
    if captured_at and ttl_seconds() > 0:
        age = time.time() - captured_at / 1000.0
        if age > ttl_seconds():
            debug_log("captcha_param_expired", age_seconds=round(age, 1))
            return None
    return param


def _spawn_grabber(force):
    global _active_grabber
    with _grabber_lock:
        if _active_grabber is not None and _active_grabber.poll() is None:
            return _active_grabber
        if not os.path.exists(GRABBER_SCRIPT):
            debug_log("grabber_script_missing", path=GRABBER_SCRIPT)
            return None
        node = os.environ.get("ZAI_NODE", "node")
        command = [
            node,
            GRABBER_SCRIPT,
            "--timeout",
            str(int(grabber_timeout_seconds() * 1000)),
        ]
        headless_env = os.environ.get("ZAI_CAPTCHA_HEADLESS", "1")
        if headless_env not in {"1", "true", "yes", "on"}:
            command.append("--headed")
        log_handle = open(GRABBER_LOG, "ab")
        log_handle.write(
            f"\n--- grabber start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode()
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
            "grabber_started",
            pid=process.pid,
            headless=headless_env not in {"0", "false", "no", "off"},
            force=force,
        )
        process._zai_log_handle = log_handle
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
        process._zai_log_handle.close()
    except Exception:
        pass
    return fresh_param()


def get_captcha_param(wait_seconds=60.0):
    param = fresh_param()
    if param:
        return param
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
    process = _spawn_grabber(force=True)
    if process is None:
        return fresh_param()
    return _wait_for_grabber(process, wait_seconds)


def is_captcha_required_text(text: str) -> bool:
    lowered = str(text or "").lower()
    return "frontend_captcha_required" in lowered or "missing_param" in lowered


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "get"
    if mode == "refresh":
        result = force_refresh()
    else:
        result = get_captcha_param()
    if result:
        print(result)
    else:
        print("NO_CAPTCHA_PARAM", file=sys.stderr)
        sys.exit(1)