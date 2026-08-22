import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from py.bridge_manager import status_payload as bridge_status
from py.credential_adapters import ADAPTERS as CREDENTIAL_ADAPTERS
from py.provider_registry import PROVIDER_ADAPTERS, provider_status_payload
from py.state_store import store


def build_report(runtime=""):
    status = provider_status_payload(runtime)
    bridges = bridge_status() if runtime in {"", "local"} else {}
    rows = []
    for provider in status["data"]:
        provider_id = provider["id"]
        adapter = PROVIDER_ADAPTERS.get(provider_id, {})
        bridge = bridges.get(provider_id)
        rows.append({
            "id": provider_id,
            "ready": provider["ready"],
            "auth_mode": provider["auth_mode"],
            "models": len(provider["models"]),
            "complete": callable(adapter.get("complete")),
            "stream": callable(adapter.get("stream")),
            "declarative_credentials": provider_id in CREDENTIAL_ADAPTERS,
            "missing": provider["missing_env"],
            "bridge": bridge,
        })
    return {"runtime": runtime or "all", "ok": all(row["ready"] for row in rows), "providers": rows, "bridges": bridges, "state": store.status()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("local", "vercel", "cloudflare"), default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = build_report(args.runtime)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("provider                 ready auth             models complete stream credentials bridge")
        for row in report["providers"]:
            bridge = row["bridge"]
            bridge_text = "-" if bridge is None else ("ok" if bridge.get("healthy") else "down")
            print(f"{row['id']:<24} {'yes' if row['ready'] else 'no':<5} {row['auth_mode']:<16} {row['models']:<6} {'yes' if row['complete'] else 'no':<8} {'yes' if row['stream'] else 'buffered':<8} {'decl' if row['declarative_credentials'] else 'custom':<11} {bridge_text}")
        print(f"state: {report['state']['backend']} ({report['state']['entries']} entries)")
    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
