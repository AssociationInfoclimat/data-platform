import json
import os
from pathlib import Path
import sys

from tools import lineage_run


EVIDENCE = {
    "schema_version": "1.0",
    "input_snapshot_ids": {"iceberg://warehouse/dim.station": "42"},
    "output_snapshot_ids": {
        "iceberg://diffusion/bronze_ref.station_source": "101"
    },
    "ingest_run_id": "station-ref:42",
    "status_counts": {"raw": 3, "canonical": 1},
    "flag_counts": {"outside_declared_territory": 2},
    "registry_version": "station-reference-corrections/v1@sha256:abc",
}


def _events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _writer_command(evidence, exit_code=0):
    script = (
        "import json,os,pathlib,sys;"
        "p=pathlib.Path(os.environ['LINEAGE_EVIDENCE_PATH']);"
        f"p.write_text(json.dumps({evidence!r}));"
        f"sys.exit({exit_code})"
    )
    return [sys.executable, "-c", script]


def test_terminal_complete_event_ingests_namespaced_bounded_evidence(tmp_path):
    spool = tmp_path / "events.jsonl"
    evidence_path = tmp_path / "run-evidence.json"
    result = lineage_run.main([
        "--job", "batch.station_ref_bronze",
        "--spool", str(spool),
        "--evidence", str(evidence_path),
        "--", *_writer_command(EVIDENCE),
    ])

    assert result == 0
    start, complete = _events(spool)
    assert "infoclimat_station_reference" not in start["run"]["facets"]
    facet = complete["run"]["facets"]["infoclimat_station_reference"]
    assert {k: v for k, v in facet.items() if not k.startswith("_")} == EVIDENCE


def test_terminal_fail_event_keeps_business_exit_code_and_evidence(tmp_path):
    spool = tmp_path / "events.jsonl"
    evidence_path = tmp_path / "run-evidence.json"
    result = lineage_run.main([
        "--job=batch.station_ref_silver",
        f"--spool={spool}",
        f"--evidence={evidence_path}",
        "--", *_writer_command(EVIDENCE, exit_code=9),
    ])

    assert result == 9
    fail = _events(spool)[-1]
    assert fail["eventType"] == "FAIL"
    assert fail["run"]["facets"]["infoclimat_station_reference"]["ingest_run_id"] == "station-ref:42"


def test_invalid_or_oversized_evidence_is_nonblocking_and_not_attached(tmp_path):
    spool = tmp_path / "events.jsonl"
    evidence_path = tmp_path / "run-evidence.json"
    invalid = {**EVIDENCE, "raw_rows": ["secret"]}
    result = lineage_run.main([
        "--job", "batch.station_ref_dim",
        "--spool", str(spool),
        "--evidence", str(evidence_path),
        "--", *_writer_command(invalid),
    ])

    assert result == 0
    complete = _events(spool)[-1]
    assert "infoclimat_station_reference" not in complete["run"]["facets"]
