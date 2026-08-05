from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def contract(name):
    return yaml.safe_load((ROOT / "contracts" / name).read_text())


def tables(document):
    return {item.get("physicalName", item["name"]): item for item in document["schema"]}


def properties(table):
    return {item["name"]: item for item in table["properties"]}


def test_station_medallion_contracts_expose_provenance_and_aliases():
    bronze = tables(contract("bronze-ref-station.odcs.yaml"))["bronze_ref.station_source"]
    silver = tables(contract("silver-ref-station.odcs.yaml"))
    assert {"source_snapshot_id", "ingest_run_id", "ic_id", "latitude", "longitude"} <= properties(bronze).keys()
    station = properties(silver["silver_ref.station"])
    assert {"source_latitude", "source_longitude", "canonical_latitude", "canonical_longitude",
            "quality_status", "quality_flags", "correction_rule_id", "authority_uri",
            "authority_checked_at", "source_snapshot_id", "ingest_run_id"} <= station.keys()
    alias = properties(silver["silver_ref.station_alias"])
    assert {"alias_ic_id", "canonical_ic_id", "relation", "correction_rule_id"} <= alias.keys()
    assert all(value in station["quality_status"]["description"]
               for value in ("canonical", "alias_obsolete", "quarantined"))
