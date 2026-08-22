import os
import tempfile
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py.metrics import Metrics
from py.state_store import StateStore


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "state.sqlite3")
        first = StateStore("sqlite", path)
        first.put("a", {"ok": True})
        second = StateStore("sqlite", path)
        assert second.get("a") == {"ok": True}
        second.put("old", {"old": True}, updated_at=time.time() - 20)
        assert second.get("old", ttl=1) is None
        assert second.delete("a") is True
        first.close()
        second.close()
    metrics = Metrics()
    metrics.observe_request(12.5, 200, "deepseek", True, 3)
    snapshot = metrics.snapshot()
    assert snapshot["request_duration_ms"]["count"] == 1
    output = metrics.prometheus()
    assert 'provider="deepseek"' in output and "proxy_stream_chunks_total" in output
    print("state and metrics tests: ok")


if __name__ == "__main__":
    main()
