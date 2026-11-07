import json
from pathlib import Path

import yaml

from tools.lineage_forward import load_declared_datasets


ROOT = Path(__file__).parents[2]

# Types réels de silver.observation_v2 / silver.observation_v2_quarantine, relevés sur
# infoclimat-labs/chom-poc-data@d0be025c (scripts/chom_lakehouse/silver.py,
# SILVER_SCHEMA_TEMPOREL) et scripts/mf_quarantine.py (QUARANTINE_SCHEMA) — le contrat
# source de vérité pour l'égalité de schéma, pas une recopie du contrat sous test.
PRODUCER_CANONICAL_TYPES = {
    "station_uid": "TEXT",
    "dh_utc": "TIMESTAMP",
    "parametre": "TEXT",
    "valeur": "DOUBLE",
    "duree_s": "INTEGER",
    "qc_flag": "TEXT",
    "source": "TEXT",
    "version_obs": "INTEGER",
    "ingest_run_id": "TEXT",
    "jour_climatologique_local": "DATE",
    "tz_iana": "TEXT",
}

PRODUCER_QUARANTINE_TYPES = {
    "station_uid": "TEXT",
    "dh_source_local": "TIMESTAMP",
    "parametre": "TEXT",
    "valeur": "DOUBLE",
    "duree_s": "INTEGER",
    "qc_flag": "TEXT",
    "source": "TEXT",
    "version_obs": "INTEGER",
    "ingest_run_id": "TEXT",
    "quarantine_reason": "TEXT",
    "decision_id": "TEXT",
    "quarantined_run_id": "TEXT",
    "quarantined_at": "TIMESTAMP",
}

# Consommateurs Gold réels de silver.observation_v2, vérifiés sur
# infoclimat-labs/chom-poc-data@d0be025c : chacun charge
# warehouse_catalog().load_table("silver.observation_v2") (meta = silver.metadata_location).
# batch.gold_qc_pics (gold_qc_pics.py:151) est un consommateur direct au même titre que
# les autres — il n'a simplement pas de contrat ODCS distinct pour son propre dataset
# gold_qc.pic_temperature (hors périmètre de cette correction).
GOLD_CONSUMERS_OF_CANONICAL = {
    "batch.gold_ref_station_parametre",
    "batch.gold_dataclimat_quotidienne",
    "batch.gold_v2_journaliere",
    "batch.gold_ic_journaliere",
    "batch.gold_statIC_journaliere",
    "batch.gold_canicule_station_saison",
    "batch.gold_qc_pics",
}

# Auto-lectures Silver réelles de silver.observation_v2_quarantine : ni l'une ni l'autre
# n'est un consommateur Gold/serving (cf. contrat, quality.never_served).
SILVER_SELF_READERS_OF_QUARANTINE = {
    "batch.silver_v2_temporal_backfill",
    "batch.catchup_silver_delta",
}

IC_BRONZE_INPUTS = {
    "bronze.synop",
    "bronze.static",
    "bronze.metar",
    "bronze.bouees",
}


def contract(name):
    return yaml.safe_load((ROOT / "contracts" / name).read_text())


def tables(document):
    return {item.get("physicalName", item["name"]): item for item in document["schema"]}


def properties(table):
    return {item["name"]: item for item in table["properties"]}


def custom_properties(document):
    return {item["property"]: item["value"] for item in document["customProperties"]}


def server(document):
    servers = document["servers"]
    assert len(servers) == 1
    return servers[0]


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
    """Arêtes physiques réelles par job, vérifiées sur chom-poc-data@d0be025c —
    PAS un graphe partagé : les deux jobs ont des entrées différentes."""
    warehouse = "iceberg://warehouse"
    return {
        "batch.silver_v2_temporal_backfill": {
            # retro_remplir() ne lit AUCUN Bronze ni dim.station : il rejoue
            # silver.observation_v2 lui-même et relit sa propre quarantaine écrite
            # pour recompter sa preuve (silver_v2_temporal_backfill.py).
            "inputs": {
                (warehouse, "silver.observation_v2"),
                (warehouse, "silver.observation_v2_quarantine"),
            },
            "outputs": {
                (warehouse, "silver.observation_v2"),
                (warehouse, "silver.observation_v2_quarantine"),
            },
        },
        "batch.catchup_silver_delta": {
            # main() exécute par défaut LES DEUX branches run_ic() ET run_mf() sous une
            # seule identité de job — deploy/catchup_all.sh appelle le script sans
            # sélecteur (lignes 59-66) donc l'invocation de production ne les sépare pas.
            # run_ic() lit chaque famille bronze IC séparément (FAMILLES = ("synop",
            # "static", "metar", "bouees"), ligne 82) ; run_mf() lit chaque famille bronze
            # MF séparément (silver_mf.FAMILLES). Les deux relisent silver.observation_v2
            # (curseur) + silver.observation_v2_quarantine (curseur_quarantine_mf) avant
            # tout append (catchup_silver_delta.py).
            "inputs": {
                (warehouse, "bronze.synop"),
                (warehouse, "bronze.static"),
                (warehouse, "bronze.metar"),
                (warehouse, "bronze.bouees"),
                (warehouse, "bronze.mf_horaire"),
                (warehouse, "bronze.mf_infrahoraire"),
                (warehouse, "bronze.mf_quotidienne"),
                (warehouse, "dim.station"),
                (warehouse, "silver.observation_v2"),
                (warehouse, "silver.observation_v2_quarantine"),
            },
            "outputs": {
                (warehouse, "silver.observation_v2"),
                (warehouse, "silver.observation_v2_quarantine"),
            },
        },
    }


def expected_gold_qc_pics_job():
    """Arête physique réelle de batch.gold_qc_pics, vérifiée sur chom-poc-data@d0be025c
    (scripts/gold_qc_pics.py, mode --publier, lignes 151-229) : lit directement
    silver.observation_v2 et qc.pic_candidat (warehouse_catalog) et écrit
    gold_qc.pic_temperature (diffusion_catalog)."""
    return {
        "inputs": {
            ("iceberg://warehouse", "silver.observation_v2"),
            ("iceberg://warehouse", "qc.pic_candidat"),
        },
        "outputs": {("iceberg://diffusion", "gold_qc.pic_temperature")},
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


def test_silver_observation_v2_and_quarantine_are_active_not_draft():
    """La fusion de ces contrats est le gate qui autorise la séquence POC post-fusion
    (#79/#176/#178) : draft ne matérialise pas cette autorisation. Cohérent avec le
    contrat sœur actif silver-ref-station.odcs.yaml et avec le fait que les deux
    tables sont déjà écrites par du code de production réel (pas un placeholder)."""
    canonical = contract("silver.observation_v2.odcs.yaml")
    quarantine = contract("silver.observation_v2_quarantine.odcs.yaml")
    assert canonical["status"] == "active"
    assert quarantine["status"] == "active"


def test_silver_observation_v2_schema_matches_producer_types_exactly():
    """Égalité de schéma (noms + types), pas un sous-ensemble : comparée à
    SILVER_SCHEMA_TEMPOREL réel du producteur (chom_lakehouse/silver.py @ d0be025c),
    pas au contrat lui-même."""
    canonical = tables(contract("silver.observation_v2.odcs.yaml"))["silver.observation_v2"]
    fields = properties(canonical)
    assert set(fields) == set(PRODUCER_CANONICAL_TYPES)
    for name, expected_type in PRODUCER_CANONICAL_TYPES.items():
        assert fields[name]["physicalType"] == expected_type, (
            f"{name}: {fields[name]['physicalType']} != producteur {expected_type}"
        )
    assert fields["jour_climatologique_local"].get("required", False) is False
    assert fields["tz_iana"].get("required", False) is False
    assert fields["dh_utc"]["required"] is True


def test_silver_observation_v2_declares_no_primary_key_and_documents_why():
    """La source à d0be025c ne tranche pas l'unicité de ligne : les writers vus
    (catchup_silver_delta.py:586-607) assignent seulement version_obs=1, et le
    canonique append-only porte déjà des doublons connus signalés par des
    consommateurs Gold (gold_v2_journaliere.py:46-54). Un primaryKey serait donc une
    assertion d'identité non établie côté producteur : ce contrat n'en déclare aucun
    et documente explicitement le POC append-only via une règle de qualité dédiée."""
    canonical = contract("silver.observation_v2.odcs.yaml")
    table = tables(canonical)["silver.observation_v2"]
    fields = properties(table)
    assert not any(field.get("primaryKey") for field in fields.values()), (
        "silver.observation_v2 should not assert any primaryKey: row identity/"
        "uniqueness is not established by the producer at d0be025c"
    )
    assert not any("primaryKeyPosition" in field for field in fields.values())

    rules = {rule["rule"]: rule for rule in table["quality"]}
    assert "identity_and_uniqueness_not_established" in rules
    description = rules["identity_and_uniqueness_not_established"]["description"]
    assert "primaryKey" in description
    assert "version_obs=1" in description


def test_silver_observation_v2_quarantine_schema_matches_producer_types_exactly():
    quarantine = tables(contract("silver.observation_v2_quarantine.odcs.yaml"))[
        "silver.observation_v2_quarantine"
    ]
    fields = properties(quarantine)
    assert set(fields) == set(PRODUCER_QUARANTINE_TYPES)
    for name, expected_type in PRODUCER_QUARANTINE_TYPES.items():
        assert fields[name]["physicalType"] == expected_type, (
            f"{name}: {fields[name]['physicalType']} != producteur {expected_type}"
        )
    for required_field in (
        "station_uid", "dh_source_local", "quarantine_reason", "decision_id",
        "quarantined_run_id", "quarantined_at",
    ):
        assert fields[required_field]["required"] is True


def test_silver_observation_v2_quarantine_declares_no_primary_key_and_documents_why():
    """Comme silver.observation_v2, aucune clé de ligne unique n'est établie côté
    producteur à d0be025c : ce contrat ne déclare aucun primaryKey et documente
    explicitement le POC append-only via une règle de qualité dédiée."""
    quarantine = contract("silver.observation_v2_quarantine.odcs.yaml")
    table = tables(quarantine)["silver.observation_v2_quarantine"]
    fields = properties(table)
    assert not any(field.get("primaryKey") for field in fields.values()), (
        "silver.observation_v2_quarantine should not assert any primaryKey: row "
        "identity/uniqueness is not established by the producer at d0be025c"
    )
    assert not any("primaryKeyPosition" in field for field in fields.values())

    rules = {rule["rule"]: rule for rule in table["quality"]}
    assert "identity_and_uniqueness_not_established" in rules
    assert "primaryKey" in rules["identity_and_uniqueness_not_established"]["description"]


def test_silver_observation_v2_quarantine_never_served_rule_uses_the_real_field():
    """La règle never_served doit citer dh_source_local — le champ réel de ce schéma
    (jamais dh_utc, qui n'existe pas ici : la quarantaine n'a pas de fuseau IANA
    versionné pour convertir en UTC)."""
    quarantine = contract("silver.observation_v2_quarantine.odcs.yaml")
    table = tables(quarantine)["silver.observation_v2_quarantine"]
    rules = {rule["rule"]: rule for rule in table["quality"]}
    description = rules["never_served"]["description"]
    assert "dh_source_local" in description
    assert "dh_utc" not in description


def test_silver_observation_v2_servers_never_claim_an_unsourced_s3_bucket():
    """Ni contrat ne déclare de type s3/location physique : le catalogue REST
    Lakekeeper (chom/ic) n'expose ici qu'une identité logique (catalog+warehouse),
    jamais un bucket inventé — cf. remote_catalog.py @ d0be025c (endpoint S3 fourni
    par l'environnement, jamais fixé dans le code)."""
    for name in ("silver.observation_v2.odcs.yaml", "silver.observation_v2_quarantine.odcs.yaml"):
        document = contract(name)
        srv = server(document)
        assert srv["type"] == "custom"
        assert srv["catalog"] == "chom"
        assert srv["warehouse"] == "ic"
        assert "location" not in srv


def test_silver_observation_v2_quarantine_declares_no_gold_serving_consumer():
    """never_served porte sur Gold/serving, pas sur les auto-lectures opérationnelles
    Silver réelles (curseur/preuve) qui, elles, sont déclarées dans lineageJob."""
    quarantine = contract("silver.observation_v2_quarantine.odcs.yaml")
    lineage_job = json.loads(custom_properties(quarantine)["lineageJob"])
    dataset = lineage_job["datasets"]["silver.observation_v2_quarantine"]
    consumers = set(dataset["consumers"])
    assert consumers == SILVER_SELF_READERS_OF_QUARANTINE
    assert consumers.isdisjoint(GOLD_CONSUMERS_OF_CANONICAL)


def test_bronze_mf_to_silver_lineage_jobs_define_exact_physical_edges():
    jobs = load_jobs()
    for job_name, expected in expected_observation_jobs().items():
        job = jobs[job_name]
        assert job["job_namespace"] == "batch://chom-poc-data"
        for direction, datasets in expected.items():
            assert dataset_pairs(job, direction) == datasets, (
                f"{job_name}.{direction}: {dataset_pairs(job, direction)} != {datasets}"
            )


def test_gold_qc_pics_job_defines_exact_physical_edges():
    """batch.gold_qc_pics doit être déclaré comme un job réel du graphe, avec exactement
    les arêtes physiques vérifiées côté source (silver.observation_v2 et
    qc.pic_candidat en entrée, gold_qc.pic_temperature en sortie)."""
    jobs = load_jobs()
    job = jobs["batch.gold_qc_pics"]
    assert job["job_namespace"] == "batch://chom-poc-data"
    expected = expected_gold_qc_pics_job()
    for direction, datasets in expected.items():
        assert dataset_pairs(job, direction) == datasets, (
            f"batch.gold_qc_pics.{direction}: {dataset_pairs(job, direction)} != {datasets}"
        )


def test_silver_observation_v2_source_and_lineage_enumerate_ic_bronze_inputs():
    """Les deux textes contractuels doivent refléter les entrées IC de run_ic(),
    déjà déclarées dans batch.catchup_silver_delta du graphe physique."""
    canonical = contract("silver.observation_v2.odcs.yaml")
    props = custom_properties(canonical)
    for property_name in ("source", "lineage"):
        value = props[property_name]
        for dataset_name in IC_BRONZE_INPUTS:
            assert dataset_name in value, f"{property_name} omet {dataset_name}"


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


def test_silver_observation_v2_lineage_job_producers_and_consumers_are_declared_in_jobs_yaml():
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


def test_silver_observation_v2_declares_the_real_gold_consumer_set():
    """Les 5 contrats Gold qui lisent réellement silver.observation_v2
    (gold-climato-v2, gold-dataclimat, gold-ic, gold-statIC, gold-canicule) plus
    gold-ref doivent apparaître comme consommateurs — pas seulement
    batch.gold_ref_station_parametre."""
    canonical = contract("silver.observation_v2.odcs.yaml")
    lineage_job = json.loads(custom_properties(canonical)["lineageJob"])
    consumers = set(lineage_job["datasets"]["silver.observation_v2"]["consumers"])
    assert consumers == GOLD_CONSUMERS_OF_CANONICAL

    jobs = load_jobs()
    for consumer_name in consumers:
        consumer = jobs[consumer_name]
        assert ("iceberg://warehouse", "silver.observation_v2") in dataset_pairs(
            consumer, "inputs"
        )


def test_gold_contracts_that_read_silver_observation_v2_are_the_declared_consumer_set():
    """Vérifie l'autre sens : chaque contrat Gold dont le texte de lineage mentionne
    silver.observation_v2 a un job correspondant dans le graphe déclaré — pas de
    consommateur Gold réel oublié par lineageJob."""
    gold_contracts_referencing_silver = {
        "gold-ref.odcs.yaml",
        "gold-climato-v2.odcs.yaml",
        "gold-dataclimat.odcs.yaml",
        "gold-ic.odcs.yaml",
        "gold-statIC.odcs.yaml",
        "gold-canicule.odcs.yaml",
    }
    for name in gold_contracts_referencing_silver:
        document = contract(name)
        lineage_text = custom_properties(document).get("lineage", "")
        assert "silver.observation_v2" in lineage_text, (
            f"{name}: lineage text no longer references silver.observation_v2; "
            "update GOLD_CONSUMERS_OF_CANONICAL if this dataProduct dropped it"
        )
