#!/usr/bin/env python3
"""Exporte le manifeste JSON station-reference depuis les contrats ODCS."""

import hashlib
import json
from pathlib import Path
import sys

import yaml


CONTRACTS = (
    "bronze-ref-station.odcs.yaml",
    "silver-ref-station.odcs.yaml",
    "gold-ref.odcs.yaml",
)
MANIFEST_VERSION = "station-reference.schema/v1"


def custom_property(item: dict, name: str):
    for prop in item.get("customProperties", []):
        if prop.get("property") == name:
            return prop.get("value")
    return None


def build_manifest(root: Path) -> dict:
    source_contracts = {}
    tables = {}
    for name in CONTRACTS:
        document = yaml.safe_load((root / "contracts" / name).read_text())
        source_contracts[name] = document["version"]
        for table in document["schema"]:
            exported_table = {
                "fields": {
                    prop["name"]: {
                        "physicalType": prop["physicalType"],
                        "required": bool(prop.get("required", False)),
                    }
                    for prop in table["properties"]
                }
            }
            served = custom_property(table, "served")
            if served is not None:
                exported_table["served"] = served
            tables[table["physicalName"]] = exported_table
    payload = {
        "manifestVersion": MANIFEST_VERSION,
        "sourceContracts": source_contracts,
        "tables": tables,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**payload, "contentSha256": f"sha256:{digest}"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(build_manifest(root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
