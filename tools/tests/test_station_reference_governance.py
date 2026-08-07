import json
import hashlib
from pathlib import Path

import yaml

from tools.lineage_forward import load_declared_datasets


ROOT = Path(__file__).parents[2]


def contract(name):
    return yaml.safe_load((ROOT / "contracts" / name).read_text())


def tables(document):
    return {item.get("physicalName", item["name"]): item for item in document["schema"]}


def properties(table):
    return {item["name"]: item for item in table["properties"]}


def custom_properties(document):
    return {item["property"]: item["value"] for item in document["customProperties"]}


def dataset_pairs(job, direction):
    datasets = [
        (dataset["namespace"], dataset["name"])
        for dataset in job.get(direction, [])
    ]
    assert len(datasets) == len(set(datasets)), (
        f"duplicate {direction} datasets in {job['job_name']}"
    )
    return set(datasets)


def assert_contract_lineage(document, jobs):
    lineage_jobs = json.loads(custom_properties(document)["lineageJob"])["datasets"]
    assert set(lineage_jobs) == set(tables(document))
    for dataset_name, references in lineage_jobs.items():
        producer = jobs[references["producer"]]
        assert ("iceberg://diffusion", dataset_name) in dataset_pairs(producer, "outputs")
        for consumer_name in references["consumers"]:
            consumer = jobs[consumer_name]
            assert ("iceberg://diffusion", dataset_name) in dataset_pairs(consumer, "inputs")


def expected_station_jobs():
    return {
        "batch.station_ref_bronze": {
            "inputs": {("iceberg://warehouse", "dim.station")},
            "outputs": {("iceberg://diffusion", "bronze_ref.station_source")},
        },
        "batch.station_ref_silver": {
            "inputs": {("iceberg://diffusion", "bronze_ref.station_source")},
            "outputs": {
                ("iceberg://diffusion", "silver_ref.station"),
                ("iceberg://diffusion", "silver_ref.station_alias"),
            },
        },
        "batch.station_ref_dim": {
            "inputs": {
                ("iceberg://diffusion", "silver_ref.station"),
                ("iceberg://diffusion", "silver_ref.station_alias"),
            },
            "outputs": {
                ("iceberg://diffusion", "dim_ref.station"),
                ("iceberg://diffusion", "dim_ref.station_alias"),
            },
        },
        "batch.gold_ref_station_parametre": {
            "inputs": {
                ("iceberg://warehouse", "silver.observation_v2"),
                ("iceberg://diffusion", "dim_ref.station_alias"),
            },
            "outputs": {("iceberg://diffusion", "gold_ref.station_parametre")},
        },
        "batch.station_ref_gold": {
            "inputs": {
                ("iceberg://diffusion", "dim_ref.station"),
                ("iceberg://diffusion", "dim_ref.station_alias"),
                ("iceberg://diffusion", "gold_ref.station_parametre"),
            },
            "outputs": {
                ("iceberg://diffusion", "gold_ref.station"),
                ("iceberg://diffusion", "gold_ref.station_alias"),
            },
        },
    }


def test_station_medallion_openlineage_jobs_define_exact_physical_edges():
    lineage = yaml.safe_load((ROOT / "lineage" / "jobs.yaml").read_text())
    job_names = [job["job_name"] for job in lineage["jobs"]]
    assert len(job_names) == len(set(job_names)), "duplicate OpenLineage job names"
    jobs = {job["job_name"]: job for job in lineage["jobs"]}
    for job_name, expected in expected_station_jobs().items():
        job = jobs[job_name]
        assert job["job_namespace"] == "batch://chom-poc-data"
        for direction, datasets in expected.items():
            assert dataset_pairs(job, direction) == datasets


def test_station_contract_storage_and_lineage_jobs_match_declared_graph():
    lineage = yaml.safe_load((ROOT / "lineage" / "jobs.yaml").read_text())
    job_names = [job["job_name"] for job in lineage["jobs"]]
    assert len(job_names) == len(set(job_names)), "duplicate OpenLineage job names"
    jobs = {job["job_name"]: job for job in lineage["jobs"]}

    bronze = contract("bronze-ref-station.odcs.yaml")
    silver = contract("silver-ref-station.odcs.yaml")
    gold = contract("gold-ref.odcs.yaml")
    assert bronze["servers"] == [{
        "server": "diffusion-iceberg",
        "type": "s3",
        "environment": "production",
        "location": "s3://chom-ic-lake-diffusion/bronze_ref",
        "format": "iceberg",
    }]
    assert silver["servers"] == [{
        "server": "diffusion-iceberg",
        "type": "s3",
        "environment": "production",
        "location": "s3://chom-ic-lake-diffusion/silver_ref",
        "format": "iceberg",
    }]
    for document in (bronze, silver, gold):
        assert_contract_lineage(document, jobs)


def test_lineage_forward_loads_all_station_jobs_with_declared_datasets():
    declared = load_declared_datasets(str(ROOT / "lineage" / "jobs.yaml"))
    for job_name, expected in expected_station_jobs().items():
        loaded = declared[job_name]
        for direction, expected_datasets in expected.items():
            datasets = [
                (dataset["namespace"], dataset["name"])
                for dataset in loaded[direction]
            ]
            assert len(datasets) == len(set(datasets)), (
                f"duplicate loaded {direction} datasets in {job_name}"
            )
            assert set(datasets) == expected_datasets


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


def test_station_reference_manifest_is_a_versioned_export_of_odcs_contracts():
    manifest_path = ROOT / "contracts" / "station-reference.schema.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["manifestVersion"] == "station-reference.schema/v1"
    assert manifest["sourceContracts"] == {
        "bronze-ref-station.odcs.yaml": "0.2.0",
        "silver-ref-station.odcs.yaml": "0.2.0",
        "gold-ref.odcs.yaml": "0.2.0",
    }

    exported = {}
    for contract_name in manifest["sourceContracts"]:
        document = contract(contract_name)
        assert document["version"] == manifest["sourceContracts"][contract_name]
        for table_name, table in tables(document).items():
            if table_name in manifest["tables"]:
                exported[table_name] = {
                    prop["name"]: {
                        "physicalType": prop["physicalType"],
                        "required": bool(prop.get("required", False)),
                    }
                    for prop in table["properties"]
                }
    assert exported == {
        table_name: table["fields"]
        for table_name, table in manifest["tables"].items()
    }
    payload = {
        key: manifest[key]
        for key in ("manifestVersion", "sourceContracts", "tables")
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert manifest["contentSha256"] == f"sha256:{digest}"


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


def test_silver_quality_policy_is_lintable_and_requires_executable_evidence():
    silver_document = contract("silver-ref-station.odcs.yaml")
    station = properties(tables(silver_document)["silver_ref.station"])
    quality_status_rules = station["quality_status"]["quality"]
    assert len(quality_status_rules) == 1
    assert quality_status_rules[0]["rule"] == "validValues"
    assert quality_status_rules[0]["mustBeIn"] == [
        "canonical",
        "alias_obsolete",
        "quarantined",
    ]
    assert quality_status_rules[0]["severity"] == "error"

    for document in (
        contract("bronze-ref-station.odcs.yaml"),
        silver_document,
        contract("gold-ref.odcs.yaml"),
    ):
        for table in document["schema"]:
            for prop in table["properties"]:
                for rule in prop.get("quality", []):
                    if rule["rule"] == "validValues":
                        assert any(key.startswith("must") for key in rule), (
                            "unconstrained validValues rule on "
                            f"{table['physicalName']}.{prop['name']}"
                        )

    silver_properties = custom_properties(silver_document)
    evidence_policy = json.loads(silver_properties["correctionEvidencePolicy"])
    assert evidence_policy == {
        "appliesWhenAny": [
            {"qualityStatusIn": ["alias_obsolete"]},
            {
                "qualityFlagsContainAny": [
                    "corrected_identity",
                    "corrected_coordinates",
                    "obsolete_identifier",
                ]
            },
        ],
        "requiredFields": [
            "correction_rule_id",
            "authority_uri",
            "authority_checked_at",
        ],
        "onMissingStatus": "quarantined",
    }
    quality_execution = json.loads(silver_properties["qualityExecution"])
    assert quality_execution == {
        "pipeline": "station_reference_build.py",
        "engine": "pipeline",
        "territorialCheck": {
            "geometryFormat": "GeoJSON",
            "geometryDataset": "communes",
            "coordinatePolicy": {
                "approvedCorrection": "canonical",
                "otherwise": "source",
            },
            "result": {
                "name": "territorial_check_passed",
                "type": "boolean",
                "blocking": True,
            },
            "onFailureStatus": "quarantined",
            "failClosed": True,
        },
    }


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
        "silver.observation_v2 + dim_ref.station_alias "
        "-> gold_ref.station_parametre ; "
        "dim_ref.station + dim_ref.station_alias + gold_ref.station_parametre "
        "-> gold_ref.station + gold_ref.station_alias"
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
