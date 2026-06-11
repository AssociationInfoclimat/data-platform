# Data Platform — Gouvernance & Data Management Infoclimat

Socle de gouvernance des données de l'association [Infoclimat](https://www.infoclimat.fr) :
**git-based, léger, fondé sur des standards ouverts**
([ODCS](https://bitol-io.github.io/open-data-contract-standard/) pour les contrats de données,
[OpenLineage](https://openlineage.io/) pour le lineage).

Infoclimat opère un réseau de stations météo participatives et un historique climatologique
de plusieurs décennies (MariaDB ~1 To en cours de migration vers TimescaleDB, ~325 pipelines
de données). Ce repo est la **source de vérité de la gouvernance de ces données** : contrats,
catalogue, inventaires, conventions de lineage et outillage d'audit.

## Arborescence

| Dossier | Contenu | Source de vérité |
|---|---|---|
| `contracts/` | Contrats de données ODCS v3 (YAML), un fichier par dataset | Oui — toute évolution de schéma passe par le contrat |
| `catalog/` | Catalogue : glossaire métier, fiches datasets, index `catalog.yaml` | Curaté à la main, génération par introspection prévue |
| `inventory/` | **Registres vivants** : tables, pipelines, datasets fichiers, sources, stockage | Oui — amendés au fil des introspections (cf. README dédié) |
| `schemas/` | DDL versionné, un fichier courant compressé par système (convention : README dédié) | `timescaledb/` oui ; `mariadb/` est un constat regénéré |
| `lineage/` | Conventions OpenLineage (namespaces, jobs), facets custom, RunEvents d'exemple | Oui pour les conventions |
| `audits/` | Constats figés et datés : états des lieux, série volumétrie, registre RGPD | Sorties d'audit, ne plus éditer une fois clos |
| `tools/` | Outillage Python (audit volumétrie, réconciliation, lineage cron → Marquez) | Oui |

## Workflow de gouvernance

1. **Tout nouveau dataset exposé** (table TimescaleDB, export opendata, dataset ML) doit avoir un
   contrat ODCS dans `contracts/` avant sa mise en production.
2. **Toute évolution de schéma** d'un dataset contractualisé = modification du contrat
   (bump de `version` selon semver) + revue par l'owner indiqué dans le contrat.
3. **Validation** : `datacontract lint` s'exécute en CI sur chaque commit touchant `contracts/`.
   En local :

   ```bash
   pip install datacontract-cli
   datacontract lint contracts/*.odcs.yaml
   ```

4. **Qualité** : les bornes physiques et règles de fraîcheur déclarées dans les contrats sont la
   source de vérité du contrôle qualité (y compris les futurs contrôles assistés par IA).
5. **Lineage** : tout pipeline cron instrumenté émet des RunEvents OpenLineage selon les
   conventions de `lineage/namespaces.md` (wrapper `tools/lineage_run.py`, forwarder
   `tools/lineage_forward.py`, sink Marquez).

## Démarrage rapide

```bash
# Inventaire volumétrie des bases (lecture seule)
cd tools
cp .env.ini.template .env.ini   # puis renseigner les accès lecture seule (jamais committés)
python3 volumetrie_audit.py --help
python3 volumetrie_audit.py --output-dir ../audits/volumetrie

# Tests de l'outillage
python3 -m pytest tests/
```

## Périmètre et confidentialité

Ce repo est public : il contient la gouvernance et la connaissance des données, **pas** les
secrets ni le détail de l'infrastructure. Les introspections brutes de production (crontabs
réels, notes d'hôtes) restent en interne ; les registres référencent les systèmes par leurs
noms logiques uniquement. Tout credential passe par `.env.ini` (gitignoré).

Certains documents référencent des repos internes de l'association (`site-infoclimat`,
`cron-infoclimat`, `infrapilot`) : ces références sont conservées comme contexte historique.

## Contribuer

Issues et pull requests bienvenues — en particulier sur les contrats ODCS, le catalogue et
l'outillage. Toute MR touchant `contracts/` requiert la revue de l'owner du dataset concerné.

## Licence

Licence en cours de définition par l'association. Dans l'intervalle, tous droits réservés —
ouvrez une issue si vous souhaitez réutiliser tout ou partie de ce contenu.
