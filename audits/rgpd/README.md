# Registre RGPD — volet data-platform

Contribution technique de la data-platform au **registre des traitements** de
l'association (art. 30 RGPD) : l'inventaire de *où vivent les données personnelles*
dans le système d'information, regroupées par finalité.

| Fichier | Rôle |
|---|---|
| `traitements.yaml` | **Source** — en-tête `meta` (responsable, socle de sécurité, réserve juridique) + traitements (finalité, personnes, données, destinataires, transferts, base légale, conservation, localisation, sécurité) et tables rattachées. À éditer ici. |
| `registre-traitements.md` | **Généré** par `tools/build_rgpd_register.py`. Ne pas éditer à la main. |

Modèle de fiche calqué sur un registre art. 30 de référence. Champs par traitement :
`finalite`, `personnes`, `donnees`, `destinataires?`, `transferts?`, `base_legale`,
`conservation`, `localisation`, `securite?`, `contrat?`, `note?`, `tables` (les `?` sont
optionnels — une fiche sans `securite` retombe sur le socle commun de l'en-tête).

## Périmètre et limites

- Le **périmètre des données personnelles** fait foi depuis `inventory/tables.yaml`
  (flag `personal_data: true`). Le générateur échoue si une table flaggée manque au
  registre ou inversement — le registre ne peut pas dériver en silence de l'inventaire.
- Le **factuel data** (quelles données, où — `localisation`, destinataires/transferts
  constatés, mesures de sécurité techniques connues) est renseigné par le volet
  data-platform à partir de l'inventaire et du code.
- Les champs **juridiques** (base légale, durée de conservation, qualification des
  transferts, exercice des droits) relèvent du **bureau de l'association** et restent
  marqués « à confirmer » : ce sont des constats, pas la position légale arrêtée.

## Régénérer / vérifier

```bash
python3 tools/build_rgpd_register.py          # régénère registre-traitements.md
python3 tools/build_rgpd_register.py --check  # vérifie la cohérence (exécuté en CI)
```

## Suites à donner (bureau)

- Compléter base légale et durée de conservation par traitement.
- Trancher le sort des tables forum mortes (`forums/ibf_*`) et des jetons push legacy.
- Documenter les modalités d'exercice des droits (accès, effacement, portabilité).
