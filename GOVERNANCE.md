# Gouvernance des données — rôles et responsabilités

## Deux rôles

| Rôle | Responsabilité | Qui |
|---|---|---|
| **Owner métier** | Répond du sens et de la qualité d'un pôle de datasets : valide les évolutions de contrat (schéma, SLA, licence), tranche les statuts douteux, porte les décisions de rétention/purge | Un membre de l'association par pôle (voir table) |
| **Steward data** | Tient les registres et l'outillage : inventaires, catalogue, conformité ODCS, lineage, CI | pam (data engineer) |

L'owner n'a pas besoin d'être technicien : il valide le *quoi* (ce que la donnée signifie,
ce qu'on promet aux consommateurs), le steward s'occupe du *comment* (la mécanique des
fichiers et de la CI).

## Pôles de gouvernance

| Pôle | Datasets (contrats) | Owner métier | Steward |
|---|---|---|---|
| **Observations & opendata** | infrahoraire-mf, horaire-mf-timescale, static-stations-obs, synop-metar-reseau-etranger, foudre, opendata-export | *à attribuer* | pam |
| **Climatologie & hydrologie** | climato-mf-timescale, quotidienne-mf-timescale, climato-mariadb, hydro-eaufrance-vigicrues | *à attribuer* | pam |
| **Imagerie & modèles** | radar-tuiles, satellite-tuiles-fichiers, modeles-nwp-fichiers | *à attribuer* | pam |
| **Prévision & vigilance** | previsions-bulletins, vigilances-meteo | *à attribuer* | pam |
| **Communauté** | v5-comptes-utilisateurs, photolive, forums2-ipboard | *à attribuer* | pam |

Tant qu'un pôle n'a pas d'owner attribué, le steward assure l'intérim — c'est l'état
actuel (`owner: pam` dans les contrats et le catalogue), à résorber : un chantier de
gouvernance porté par une seule personne est le principal risque identifié de cette
data-platform.

## Processus

1. **Toute MR touchant `contracts/`** requiert la revue de l'owner du pôle concerné
   (mécanisme : [`.github/CODEOWNERS`](.github/CODEOWNERS) — revue demandée
   automatiquement quand les owners ont un compte GitHub).
2. **Évolution de schéma** = bump semver du contrat + revue owner. Une rupture
   (suppression/renommage de colonne, changement d'unité) = version majeure +
   information des consommateurs déclarés.
3. **Les statuts `douteux`** des registres (`inventory/`) sont tranchés par l'owner du
   pôle, sur proposition du steward.
4. **Litiges ou arbitrages inter-pôles** (un dataset consommé par plusieurs pôles,
   politique de rétention coûteuse…) : remontée au bureau de l'association.

## Attribution

L'attribution des owners se fait en réunion d'équipe, un pôle pouvant être couvert par
la même personne qu'un autre. À l'attribution d'un pôle : mise à jour de cette table,
des champs `team`/`owner` des contrats et du catalogue, et du CODEOWNERS.
