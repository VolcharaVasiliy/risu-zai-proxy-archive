import base64
import json
import os
import struct
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))
import wasmtime


WASM_FILENAME = "sha3_wasm_bg.7b9ca65ddd.wasm"


class DeepSeekPowSolver:
    def __init__(self, wasm_path: str):
        engine = wasmtime.Engine()
        self._store = wasmtime.Store(engine)
        module = wasmtime.Module.from_file(engine, wasm_path)
        instance = wasmtime.Instance(self._store, module, [])
        exports = instance.exports(self._store)
        self._memory = exports["memory"]
        self._solve = exports["wasm_solve"]
        self._add_sp = exports["__wbindgen_add_to_stack_pointer"]
        self._malloc = exports["__wbindgen_export_0"]
        self._lock = threading.Lock()

    def _alloc_text(self, text: str):
        data = text.encode("utf-8")
        ptr = self._malloc(self._store, len(data), 1)
        self._memory.write(self._store, data, ptr)
        return ptr, len(data)

    def solve(self, challenge: str, salt: str, expire_at: int, difficulty: int) -> int:
        prefix = f"{salt}_{int(expire_at)}_"
        with self._lock:
            retptr = self._add_sp(self._store, -16)
            try:
                ptr0, len0 = self._alloc_text(challenge)
                ptr1, len1 = self._alloc_text(prefix)
                self._solve(self._store, retptr, ptr0, len0, ptr1, len1, float(difficulty))
                raw = self._memory.read(self._store, retptr, retptr + 16)
                status = struct.unpack("<i", raw[:4])[0]
                if status == 0:
                    raise RuntimeError("DeepSeek PoW solve returned empty result")
                return int(struct.unpack("<d", raw[8:16])[0])
            finally:
                self._add_sp(self._store, 16)


_solver = None
_solver_lock = threading.Lock()


def default_wasm_path() -> str:
    return os.path.join(os.path.dirname(__file__), WASM_FILENAME)


def get_solver() -> DeepSeekPowSolver:
    global _solver
    if _solver is not None:
        return _solver

    with _solver_lock:
        if _solver is None:
            wasm_path = default_wasm_path()
            if not os.path.exists(wasm_path):
                raise FileNotFoundError(f"DeepSeek wasm file is missing: {wasm_path}")
            _solver = DeepSeekPowSolver(wasm_path)
    return _solver


def build_pow_response(challenge: dict, target_path: str = "/api/v0/chat/completion") -> str:
    answer = get_solver().solve(
        str(challenge.get("challenge") or ""),
        str(challenge.get("salt") or ""),
        int(challenge.get("expire_at") or 0),
        int(challenge.get("difficulty") or 0),
    )
    payload = {
        "algorithm": challenge.get("algorithm"),
        "challenge": challenge.get("challenge"),
        "salt": challenge.get("salt"),
        "answer": answer,
        "signature": challenge.get("signature"),
        "target_path": target_path,
    }
    compact = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(compact).decode("ascii")
