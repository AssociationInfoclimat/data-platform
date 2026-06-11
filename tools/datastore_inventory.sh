#!/bin/bash
# Inventaire lecture seule d'un montage data (datastore, modeles).
# Usage : ./datastore_inventory.sh <point-de-montage> sortie.txt
# Produit : taille par dossier de niveau 1-2 + comptage de fichiers + extensions dominantes.
set -euo pipefail

main() {
    local mount_point="${1:?Usage: datastore_inventory.sh <mount_point> <output_file>}"
    local output_file="${2:?Usage: datastore_inventory.sh <mount_point> <output_file>}"

    {
        echo "# datastore_inventory — $(date -u +%Y-%m-%dT%H:%M:%SZ) — ${mount_point}"
        echo "## Tailles niveau 1"
        du -x -d 1 -h "${mount_point}" 2>/dev/null | sort -rh
        echo "## Tailles niveau 2 (top 100)"
        du -x -d 2 -h "${mount_point}" 2>/dev/null | sort -rh | head -100
        echo "## Extensions dominantes (échantillon 200k fichiers)"
        find "${mount_point}" -xdev -type f 2>/dev/null | head -200000 \
            | sed -E 's/.*\.([A-Za-z0-9]{1,8})$/\1/;t;s/.*/SANS_EXT/' \
            | sort | uniq -c | sort -rn | head -30
    } > "${output_file}"
    echo "OK → ${output_file}"
}

main "$@"
