import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py.provider_registry import PROVIDER_ADAPTERS, PROVIDER_MANIFEST
from py.credential_adapters import ADAPTERS


def main():
    manifest_ids = {item["id"] for item in PROVIDER_MANIFEST}
    adapter_ids = set(PROVIDER_ADAPTERS)
    assert manifest_ids == adapter_ids, (manifest_ids - adapter_ids, adapter_ids - manifest_ids)
    assert set(ADAPTERS).issubset(manifest_ids)
    for entry in PROVIDER_MANIFEST:
        adapter = PROVIDER_ADAPTERS[entry["id"]]
        assert callable(adapter.get("complete")), entry["id"]
        assert entry["models"], entry["id"]
    print(f"provider contracts: ok ({len(manifest_ids)} providers)")


if __name__ == "__main__":
    main()
