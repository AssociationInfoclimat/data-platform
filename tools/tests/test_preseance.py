"""Tests de non-régression de catalog/preseance.yaml (lot A2) : les règles
transcrites doivent rester fidèles aux cas extraits du monolithe (citations
fichier:ligne dans le YAML). Si un test casse, c'est que la table a été
éditée — vérifier contre le code source cité avant d'adapter le test."""

from pathlib import Path

import yaml

YAML_PATH = Path(__file__).resolve().parents[2] / "catalog" / "preseance.yaml"


def load():
    return yaml.safe_load(YAML_PATH.read_text())


def test_yaml_valide_et_sections():
    doc = load()
    for section in ("meta", "sources", "sql_combined", "php_live",
                    "climato_quotidienne", "ambiguites"):
        assert section in doc, f"section manquante: {section}"


def test_regle_transversale_h_htr_itr():
    """combined.php : H > HTR > ITR — vérifié sur temperature (ligne 28/434)."""
    ordres = load()["sql_combined"]["ordres_standards"]
    assert ordres["temperature"]["priorite"] == ["mf-h.T", "mf-htr.t", "mf-itr.t"]


def test_vent_rafales_fallback_vent_moyen():
    """combined.php:35 — la cascade rafales finit sur le vent moyen."""
    prio = load()["sql_combined"]["ordres_standards"]["vent_rafales"]["priorite"]
    assert prio[0] == "mf-h.FXI3S"
    assert prio[-4:] == ["mf-h.FF", "mf-h.FF2", "mf-htr.ff", "mf-itr.ff"]


def test_pression_pmer_avant_pstat():
    prio = load()["sql_combined"]["ordres_standards"]["pression"]["priorite"]
    assert prio.index("mf-h.PMER") < prio.index("mf-h.PSTAT")


def test_php_live_exceptions_mf_ecrase():
    """tableaux.php:1643/1665 — pluie_1h et vent_rafales : MF écrase toujours."""
    champs = load()["php_live"]["champs"]
    assert "ÉCRASE TOUJOURS" in champs["pluie_1h"]["regle"]
    assert "ÉCRASE TOUJOURS" in champs["vent_rafales"]["regle"]


def test_php_live_temperature_exception_meteo24():
    assert "meteo24" in load()["php_live"]["champs"]["temperature"]["regle"]


def test_php_live_natif_gagne_champs_standard():
    """Contre-revue 13/07 : seuls 5 champs sont gardés !isset (tableaux.php:
    1648-1673) ; visibilite (l.1707) et nebulosite (l.1702) écrasent SANS
    garde et appartiennent à mf_ecrase_si_non_vide."""
    champs = load()["php_live"]["champs"]
    natif = champs["natif_gagne"]["champs"]
    for c in ("humidite", "pression", "vent_moyen", "vent_direction", "point_de_rosee"):
        assert c in natif
    ecrase = champs["mf_ecrase_si_non_vide"]["champs"]
    for c in ("visibilite", "nebulosite"):
        assert c not in natif and c in ecrase


def test_ordre_chargement_natif_premier_metar_dernier():
    ordre = load()["php_live"]["ordre_chargement"]
    assert ordre[0]["rang"] == 1 and "natif" in ordre[0]["source"]
    assert ordre[-1]["source"] == "metar-ic"


def test_climato_tn_min_tx_max():
    ag = load()["climato_quotidienne"]["agregats"]
    assert ag["tn"]["regle"].startswith("min(")
    assert ag["tx"]["regle"].startswith("max(")


def test_ordre_archives_quotidiennes_mf_prioritaires():
    """Contre-revue 13/07 : le bloc final climato.php:1431-1485 lit les
    quotidiennes MF officielles (via Timescale, format noaa) — renommé
    quotidiennes-mf pour ne pas confondre avec GSOD (V5_climato_noaa)."""
    archives = load()["climato_quotidienne"]["sources_archives_ordre_effectif"]
    assert archives["regle"].split(">")[0].strip().endswith("quotidiennes-mf")
    assert "noaa" in archives["note_nommage"]


def test_ambiguites_documentees():
    """AMB-8 et AMB-9 découvertes par la contre-revue du 13/07."""
    ids = [a["id"] for a in load()["ambiguites"]]
    assert ids == [f"AMB-{i}" for i in range(1, 10)]


def test_ambiguites_toutes_tranchees():
    """Décisions actées le 13/07 (adoption des recommandations de la
    contre-revue) — chaque ambiguïté doit porter une décision non vide."""
    for a in load()["ambiguites"]:
        assert a.get("decision", "").strip(), f"{a['id']} sans décision"


def test_decision_amb6_semantique_coalesce():
    """AMB-6 fixe la sémantique universelle de la table : un NULL ne gagne
    jamais. Toute édition qui la retire doit casser un test."""
    amb6 = next(a for a in load()["ambiguites"] if a["id"] == "AMB-6")
    assert "NON NULLE" in amb6["decision"]


def test_toutes_les_regles_citent_leur_source():
    """Chaque ordre standard doit citer combined.php:<lignes>."""
    for champ, spec in load()["sql_combined"]["ordres_standards"].items():
        assert "combined.php:" in spec.get("source", ""), f"{champ} sans citation"
