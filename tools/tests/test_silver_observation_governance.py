import json
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


def expected_observation_jobs():
    bronze_mf_inputs = {
        ("iceberg://warehouse", "bronze.mf_horaire"),
        ("iceberg://warehouse", "bronze.mf_infrahoraire"),
        ("iceberg://warehouse", "bronze.mf_quotidienne"),
        ("iceberg://warehouse", "dim.station"),
    }
    silver_outputs = {
        ("iceberg://warehouse", "silver.observation_v2"),
        ("iceberg://warehouse", "silver.observation_v2_quarantine"),
    }
    return {
        "batch.silver_v2_temporal_backfill": {
            "inputs": bronze_mf_inputs,
            "outputs": silver_outputs,
        },
        "batch.catchup_silver_delta": {
            "inputs": bronze_mf_inputs,
            "outputs": silver_outputs,
        },
    }


def load_jobs():
    lineage = yaml.safe_load((ROOT / "lineage" / "jobs.yaml").read_text())
    job_names = [job["job_name"] for job in lineage["jobs"]]
    assert len(job_names) == len(set(job_names)), "duplicate OpenLineage job names"
    return {job["job_name"]: job for job in lineage["jobs"]}


def test_silver_observation_v2_contracts_are_valid_odcs_and_keep_v2_identity():
    canonical = contract("silver.observation_v2.odcs.yaml")
    quarantine = contract("silver.observation_v2_quarantine.odcs.yaml")

    assert canonical["apiVersion"] == "v3.0.2"
    assert quarantine["apiVersion"] == "v3.0.2"
    assert canonical["id"] == "urn:infoclimat:contract:silver-observation-v2"
    assert quarantine["id"] == "urn:infoclimat:contract:silver-observation-v2-quarantine"

    canonical_tables = tables(canonical)
    quarantine_tables = tables(quarantine)
    assert set(canonical_tables) == {"silver.observation_v2"}
    assert set(quarantine_tables) == {"silver.observation_v2_quarantine"}


def test_silver_observation_v2_schema_carries_additive_temporal_pair():
    canonical = tables(contract("silver.observation_v2.odcs.yaml"))["silver.observation_v2"]
    fields = properties(canonical)
    assert {
        "station_uid", "dh_utc", "parametre", "source", "version_obs", "ingest_run_id",
        "jour_climatologique_local", "tz_iana",
    } <= fields.keys()
    assert fields["jour_climatologique_local"].get("required", False) is False
    assert fields["tz_iana"].get("required", False) is False
    assert fields["dh_utc"]["required"] is True


def test_silver_observation_v2_quarantine_schema_carries_full_provenance():
    quarantine = tables(contract("silver.observation_v2_quarantine.odcs.yaml"))[
        "silver.observation_v2_quarantine"
    ]
    fields = properties(quarantine)
    assert {
        "station_uid", "dh_source_local", "quarantine_reason", "decision_id",
        "quarantined_run_id", "quarantined_at",
    } <= fields.keys()
    for required_field in (
        "station_uid", "dh_source_local", "quarantine_reason", "decision_id",
        "quarantined_run_id", "quarantined_at",
    ):
        assert fields[required_field]["required"] is True


def test_silver_observation_v2_quarantine_declares_no_consumer():
    quarantine = contract("silver.observation_v2_quarantine.odcs.yaml")
    lineage_job = json.loads(custom_properties(quarantine)["lineageJob"])
    dataset = lineage_job["datasets"]["silver.observation_v2_quarantine"]
    assert dataset["consumers"] == []


def test_bronze_mf_to_silver_lineage_jobs_define_exact_physical_edges():
    jobs = load_jobs()
    for job_name, expected in expected_observation_jobs().items():
        job = jobs[job_name]
        assert job["job_namespace"] == "batch://chom-poc-data"
        for direction, datasets in expected.items():
            assert dataset_pairs(job, direction) == datasets


def test_lineage_forward_loads_bronze_mf_to_silver_jobs_with_declared_datasets():
    declared = load_declared_datasets(str(ROOT / "lineage" / "jobs.yaml"))
    for job_name, expected in expected_observation_jobs().items():
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


def test_silver_observation_v2_lineage_job_producers_are_declared_in_jobs_yaml():
    jobs = load_jobs()
    for contract_name, dataset_name in (
        ("silver.observation_v2.odcs.yaml", "silver.observation_v2"),
        ("silver.observation_v2_quarantine.odcs.yaml", "silver.observation_v2_quarantine"),
    ):
        document = contract(contract_name)
        lineage_job = json.loads(custom_properties(document)["lineageJob"])
        dataset = lineage_job["datasets"][dataset_name]
        for producer_name in dataset["producers"]:
            producer = jobs[producer_name]
            assert ("iceberg://warehouse", dataset_name) in dataset_pairs(producer, "outputs")
        for consumer_name in dataset["consumers"]:
            consumer = jobs[consumer_name]
            assert ("iceberg://warehouse", dataset_name) in dataset_pairs(consumer, "inputs")
