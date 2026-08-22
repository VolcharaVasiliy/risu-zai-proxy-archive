"""Offline contract test for the optional HTTP Responses state backend."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from py.state_store import StateStore


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def close(self):
        return None


def main():
    records = {}
    calls = []

    def fake_urlopen(request, timeout=0):
        method = request.get_method()
        calls.append((method, request.full_url, dict(request.headers), timeout))
        key = request.full_url.rsplit("/state/", 1)[1]
        if method == "PUT":
            records[key] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"ok": True})
        if method == "GET":
            if key not in records:
                raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
            return FakeResponse(records[key])
        if method == "DELETE":
            existed = key in records
            records.pop(key, None)
            return FakeResponse({"deleted": existed})
        raise AssertionError(method)

    original = urllib.request.urlopen
    old_backend = os.environ.get("PROXY_STATE_BACKEND")
    old_url = os.environ.get("PROXY_STATE_URL")
    old_token = os.environ.get("PROXY_STATE_TOKEN")
    urllib.request.urlopen = fake_urlopen
    try:
        os.environ["PROXY_STATE_BACKEND"] = "http"
        os.environ["PROXY_STATE_URL"] = "https://state.example.test"
        os.environ["PROXY_STATE_TOKEN"] = "test-token"
        store = StateStore()
        store.put("response/one", {"output": [{"type": "message"}]}, updated_at=123.0)
        assert store.get("response/one") == {"output": [{"type": "message"}]}
        assert store.delete("response/one") is True
        assert store.get("response/one") is None
        assert calls[0][0] == "PUT" and calls[0][3] == 4
        assert calls[0][2].get("Authorization") == "Bearer test-token"
        assert all("response%2Fone" in call[1] for call in calls)
    finally:
        urllib.request.urlopen = original
        for key, value in (("PROXY_STATE_BACKEND", old_backend), ("PROXY_STATE_URL", old_url), ("PROXY_STATE_TOKEN", old_token)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("http state tests: ok")


if __name__ == "__main__":
    main()
