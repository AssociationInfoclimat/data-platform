# Registre RGPD — volet data-platform

Contribution technique de la data-platform au **registre des traitements** de
l'association (art. 30 RGPD) : l'inventaire de *où vivent les données personnelles*
dans le système d'information, regroupées par finalité.

| Fichier | Rôle |
|---|---|
| `traitements.yaml` | **Source** — traitements (finalité, personnes, données, base légale, conservation) et tables rattachées. À éditer ici. |
| `registre-traitements.md` | **Généré** par `tools/build_rgpd_register.py`. Ne pas éditer à la main. |

## Périmètre et limites

- Le **périmètre des données personnelles** fait foi depuis `inventory/tables.yaml`
  (flag `personal_data: true`). Le générateur échoue si une table flaggée manque au
  registre ou inversement — le registre ne peut pas dériver en silence de l'inventaire.
- Les champs **juridiques** (base légale, durée de conservation, mesures de sécurité,
  exercice des droits) relèvent du **bureau de l'association** et sont à confirmer. Ce
  volet documente le *factuel data* (quelles données, où, pour quelle finalité), pas la
  position légale arrêtée.

## Régénérer / vérifier

```bash
python3 tools/build_rgpd_register.py          # régénère registre-traitements.md
python3 tools/build_rgpd_register.py --check  # vérifie la cohérence (exécuté en CI)
```

## Suites à donner (bureau)

- Compléter base légale et durée de conservation par traitement.
- Trancher le sort des tables forum mortes (`forums/ibf_*`) et des jetons push legacy.
- Documenter les modalités d'exercice des droits (accès, effacement, portabilité).
