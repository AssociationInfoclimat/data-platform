# Dataset — Bulletins de prévision rédigés

| | |
|---|---|
| **Contrat** | Non défini (ajout au catalogue le 2026-06-07 — contrat candidat) |
| **Domaine** | Prévisions |
| **Stockage fichiers** | `previsions/` dans l'arbre web : `bn_*.txt` (bulletin national), `bulletin{id}.prev` (bulletins régionaux), `archives_pdf/`, `audio_mp3/` |
| **Stockage MariaDB** | `V5_prevs.previsionnistes` (référentiel prévisionnistes — **personal_data**) ; `V5_chroniques.bim` (bulletins infos météo) |
| **Fréquence** | Éditoriale — au rythme de rédaction des prévisionnistes bénévoles (quotidienne en pratique pour le national) |
| **Rétention** | Archives PDF conservées (`previsions/archives_pdf/`) ; fichiers `.txt`/`.prev` écrasés à chaque publication |
| **Owner** | pam |

## Flux

```
Prévisionnistes bénévoles (UI web gestion-prevs/)
  → gestion-prevs/national.php        → previsions/bn_prev.txt, bn_sstitre.txt, bn_situevo.txt, bn_evou.txt
  → gestion-prevs/ajax_publi.php      → previsions/bulletin{id}.prev (régionaux)
                                      → UPDATE V5_prevs.previsionnistes (last_prev)
  → gestion-prevs/upload_audio.php    → previsions/audio_mp3/
  → gestion-prevs/bim.php             → V5_chroniques.bim (type='bim')
```

Aucun pipeline batch : production 100 % humaine via l'interface web. C'est le seul
dataset du catalogue dont le « producteur » est éditorial.

## Consommateurs connus

- `previsions/nationales.php` — bulletin national (lecture directe des `bn_*.txt`)
- `previsions/regionales.php` — bulletins régionaux (`bulletin{id}.prev`)
- `recherche/recherche_jour.inc.php` — recherche dans les BIM (`V5_chroniques.bim`)
- `gestion-prevs/index.php` — back-office (lecture `V5_prevs.previsionnistes`)

## Points d'attention

- **Données personnelles** : `V5_prevs.previsionnistes` (identité des bénévoles,
  `personal_data: true` dans tables.yaml) — à inscrire au registre RGPD (audits/rgpd).
- L'inventaire (`tables.yaml`) liste `V5_chroniques.bim` avec `writers: []` alors que
  `gestion-prevs/bim.php` l'édite — writer humain via UI, non détecté par l'analyse
  des pipelines batch. À corriger lors d'une passe sur tables.yaml.
- Pas de versionnage des bulletins `.txt`/`.prev` : chaque publication écrase la
  précédente (seuls les PDF sont archivés).
- Frontière de périmètre : les **cartes et sorties modèles** (WRF, GFS…) relèvent du
  dataset `modeles-nwp-fichiers` ; les **bulletins spéciaux** (BS) de suivi
  d'événements relèvent de `vigilances-meteo` (`bulletins_speciaux_suivi`).

## Documentation source

- `data-platform/inventory/tables.yaml` — entrées `V5_prevs/previsionnistes`, `V5_chroniques/bim`
- Code : `gestion-prevs/` (back-office), `previsions/` (front)
