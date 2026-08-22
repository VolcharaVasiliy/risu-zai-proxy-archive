import threading
import time


class Metrics:
    def __init__(self):
        self._lock = threading.RLock()
        self.started = time.time()
        self.counters = {}
        self.durations = {"count": 0, "sum_ms": 0.0, "max_ms": 0.0}

    def inc(self, name, value=1, **labels):
        key = name
        if labels:
            key += "{" + ",".join(f"{k}={str(v)[:80]}" for k, v in sorted(labels.items())) + "}"
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + value

    def observe_request(self, duration_ms, status=None, provider=None, stream=False, chunks=0):
        with self._lock:
            self.durations["count"] += 1
            self.durations["sum_ms"] += float(duration_ms or 0)
            self.durations["max_ms"] = max(self.durations["max_ms"], float(duration_ms or 0))
        self.inc("proxy_requests_total", status=int(status or 0), stream=str(bool(stream)).lower())
        if provider:
            self.inc("proxy_provider_requests_total", provider=str(provider)[:64])
        if chunks:
            self.inc("proxy_stream_chunks_total", value=int(chunks), provider=str(provider or "unknown")[:64])

    def snapshot(self):
        with self._lock:
            return {"uptime_seconds": round(time.time() - self.started, 3), "counters": dict(self.counters), "request_duration_ms": dict(self.durations)}

    def prometheus(self):
        snap = self.snapshot()
        lines = ["# TYPE proxy_uptime_seconds gauge", f"proxy_uptime_seconds {snap['uptime_seconds']}"]
        d = snap["request_duration_ms"]
        lines += ["# TYPE proxy_request_duration_ms summary", f"proxy_request_duration_ms_count {d['count']}", f"proxy_request_duration_ms_sum {d['sum_ms']:.3f}", f"proxy_request_duration_ms_max {d['max_ms']:.3f}"]
        for key, value in snap["counters"].items():
            if "{" in key:
                name, labels = key.split("{", 1)
                rendered = ",".join(f'{part.split("=", 1)[0]}="{part.split("=", 1)[1]}"' for part in labels.rstrip("}").split(","))
                lines.append(f"{name}{{{rendered}}} {value}")
            else:
                lines.append(f"{key} {value}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
