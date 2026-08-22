import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BRIDGES = {
    "grok": {"url": os.environ.get("GROK_BRIDGE_URL", "http://127.0.0.1:8771"), "script": ROOT / "scripts" / "grok-ws-bridge.mjs", "env": "GROK_BRIDGE_MODE"},
    "lmarena": {"url": os.environ.get("LM_ARENA_BRIDGE_URL", "http://127.0.0.1:8772"), "script": ROOT / "scripts" / "lmarena-recaptcha-bridge.mjs", "env": "LM_ARENA_BRIDGE_MODE"},
}
_owned = {}


def _health(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


def ensure(name):
    spec = BRIDGES.get(name)
    if not spec:
        return False
    if _health(spec["url"]):
        return True
    mode = os.environ.get(spec["env"], "off").strip().lower()
    if mode not in {"auto", "on", "true", "1"} or not spec["script"].exists() or os.environ.get("VERCEL"):
        return False
    proc = subprocess.Popen(["node", str(spec["script"])], cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    _owned[name] = proc
    deadline = time.time() + 8
    while time.time() < deadline:
        if _health(spec["url"]):
            return True
        time.sleep(0.2)
    return False


def status_payload():
    return {name: {"url": spec["url"], "healthy": _health(spec["url"]), "owned": name in _owned} for name, spec in BRIDGES.items()}


def stop_owned():
    for name, proc in list(_owned.items()):
        if proc.poll() is None:
            proc.terminate()
        _owned.pop(name, None)
