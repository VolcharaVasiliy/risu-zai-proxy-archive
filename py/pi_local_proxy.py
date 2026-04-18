import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))

try:
    from py.zai_proxy import debug_log
except ImportError:
    from zai_proxy import debug_log


OWNED_BY = "pi.ai (local browser bridge)"
SUPPORTED_MODELS = ["pi-web-local"]

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


def supports_model(model: str) -> bool:
    return str(model or "").lower() == "pi-web-local"


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
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(_powershell_command(command), capture_output=True, text=True, check=False)


def _launch_browser_for_cdp(profile_root: Path, browser_path: Path, cdp_port: int):
    args = [
        str(browser_path),
        f"--remote-debugging-port={cdp_port}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_root}",
        "https://pi.ai/",
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
    raise RuntimeError(f"Pi local CDP did not start on port {port}: {last_error}")


def _prompt_from_messages(messages) -> str:
    lines = []
    for message in messages or []:
        role = str(message.get("role") or "user").capitalize()
        content = message.get("content")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    text_parts.append(str(item["text"]))
            text = "\n".join(text_parts)
        else:
            text = str(content or "")
        text = text.strip()
        if not text:
            continue
        lines.append(f"{role}: {text}")
    return "\n\n".join(lines).strip()


def _run_bridge(node_path: Path, cdp_port: int, prompt: str, timeout_ms: int):
    script_path = PROJECT_ROOT / "scripts" / "pi-browser-bridge.mjs"
    result = subprocess.run(
        [
            str(node_path),
            str(script_path),
            "--port",
            str(cdp_port),
            "--prompt",
            prompt,
            "--timeout-ms",
            str(timeout_ms),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown error").strip()
        raise RuntimeError(f"Pi local browser bridge failed: {message}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Pi local browser bridge returned invalid JSON: {exc}") from exc


def complete_non_stream(_credentials: dict, payload: dict):
    prompt = _prompt_from_messages(payload.get("messages") or [])
    if not prompt:
        raise RuntimeError("Pi local prompt is empty")

    profile_root = Path(os.environ.get("PI_LOCAL_PROFILE_ROOT") or r"F:\Projects\risu-zai-proxy-archive\auth\pi-edge-profile")
    cdp_port = int(os.environ.get("PI_LOCAL_CDP_PORT") or "9232")
    timeout_ms = int(os.environ.get("PI_LOCAL_TIMEOUT_MS") or "90000")
    browser_path = _resolve_existing_path(BROWSER_CANDIDATES, os.environ.get("PI_LOCAL_BROWSER_PATH", ""))
    node_path = _resolve_existing_path(NODE_CANDIDATES, os.environ.get("PI_LOCAL_NODE_PATH", ""))

    if not profile_root.exists():
        raise RuntimeError(
            f"Pi local profile was not found: {profile_root}. Run scripts\\launch-pi-auth.ps1 and log in to pi.ai first."
        )

    _stop_profile_browsers(profile_root)
    browser_proc = _launch_browser_for_cdp(profile_root, browser_path, cdp_port)
    try:
        _wait_for_cdp(cdp_port)
        bridge_result = _run_bridge(node_path=node_path, cdp_port=cdp_port, prompt=prompt, timeout_ms=timeout_ms)
    finally:
        if browser_proc.poll() is None:
            browser_proc.terminate()
            try:
                browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser_proc.kill()
        time.sleep(1)
        _stop_profile_browsers(profile_root)

    content = str(bridge_result.get("content") or "").strip()
    if not content:
        raise RuntimeError(f"Pi local browser bridge returned no content: {bridge_result}")

    result = {
        "id": str(bridge_result.get("conversationId") or "pi-local"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "pi-web-local",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    meta = {
        "provider": "pi-local",
        "model": "pi-web-local",
        "profile_root": str(profile_root),
        "conversation_id": str(bridge_result.get("conversationId") or ""),
        "message_id": str(bridge_result.get("messageId") or ""),
    }
    debug_log("pi_local_chat_done", **meta)
    return result, meta
