import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]


def contract(name):
    return yaml.safe_load((ROOT / "contracts" / name).read_text())


def tables(document):
    return {item.get("physicalName", item["name"]): item for item in document["schema"]}


def properties(table):
    return {item["name"]: item for item in table["properties"]}


def custom_properties(document):
    return {item["property"]: item["value"] for item in document["customProperties"]}


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


def test_station_67128_governance_is_immutable_canonical_and_not_proximity_based():
    bronze_document = contract("bronze-ref-station.odcs.yaml")
    silver_document = contract("silver-ref-station.odcs.yaml")
    bronze = tables(bronze_document)["bronze_ref.station_source"]
    silver = tables(silver_document)
    alias_relation = properties(silver["silver_ref.station_alias"])["relation"]

    assert custom_properties(bronze_document)["station_67128_immutable_source"] == (
        "ic_id=67128; latitude=-19.467; longitude=55.483; immutable=true"
    )
    assert "67128/-19.467/55.483" in bronze["description"]
    assert custom_properties(silver_document)["station_67128_canonicalization"] == (
        "source_ic_id=67128; canonical_ic_id=61980; canonical_name=Gillot; "
        "canonical_latitude=-20.887; canonical_longitude=55.510"
    )
    territorial_control = json.loads(
        custom_properties(silver_document)["station_67128_territorial_scenario"]
    )
    assert territorial_control["territory"] == "974"
    assert territorial_control["source"] == {
        "latitude": -19.467,
        "longitude": 55.483,
        "expected": False,
    }
    assert territorial_control["canonical"] == {
        "latitude": -20.887,
        "longitude": 55.510,
        "expected": True,
    }
    assert territorial_control["proximityCorrectionAllowed"] is False
    assert alias_relation["quality"][0]["mustBeIn"] == ["obsolete_alias", "quarantine_redirect"]


def test_gold_station_contract_exposes_canonical_aliases_and_corrected_lineage():
    gold_document = contract("gold-ref.odcs.yaml")
    gold = tables(gold_document)
    gold_properties = custom_properties(gold_document)

    assert gold_document["version"] == "0.2.0"
    assert properties(gold["gold_ref.station"])["aliases"]["physicalType"] == "ARRAY"
    alias = properties(gold["gold_ref.station_alias"])
    assert {"alias_ic_id", "canonical_ic_id", "relation"} <= alias.keys()
    assert alias["relation"]["quality"][0]["mustBeIn"] == ["obsolete_alias"]
    assert gold_properties["lineage"] == (
        "dim_ref.station + dim_ref.station_alias + silver.observation_v2 "
        "-> gold_ref.station_parametre -> gold_ref.station"
    )
    assert json.loads(gold_properties["station_67128_alias_resolution"]) == {
        "alias_ic_id": "67128",
        "canonical_ic_id": "61980",
        "relation": "obsolete_alias",
    }
    assert json.loads(gold_properties["publicationPolicy"]) == {
        "excludedQualityStatuses": ["alias_obsolete", "quarantined"],
        "publishedQualityStatuses": ["canonical"],
    }
