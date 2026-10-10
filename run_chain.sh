#!/usr/bin/env bash
# Enchaîne les étapes restantes du pipeline RAG Droit, après la régénération.
#   1. attend la fin de la régénération (main.py) ;
#   2. attend la fin du téléchargement des deltas (maj.py) ;
#   3. intègre les deltas (upsert par id) ;
#   4. embeede le corpus dans Qdrant (bulk GPU).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Charger les variables d'environnement (.env) : indispensable pour la clé API vLLM.
set -a
. "$SCRIPT_DIR/.env"
set +a

wait_pid() {
    local pid=$1 name=$2
    while kill -0 "$pid" 2>/dev/null; do sleep 10; done
    echo "[chain] $name terminé"
}

# PIDs passés en argument (facultatif) ou détectés.
REGE_PID=${1:-}
MAJ_PID=${2:-}

[ -z "$REGE_PID" ] && REGE_PID=$(pgrep -f "venv/bin/python -u main.py" | head -1 || true)
[ -z "$MAJ_PID" ] && MAJ_PID=$(pgrep -f "venv/bin/python maj/maj.py" | head -1 || true)

if [ -n "$REGE_PID" ]; then wait_pid "$REGE_PID" "régénération"; fi
if [ -n "$MAJ_PID" ]; then wait_pid "$MAJ_PID" "téléchargement deltas"; fi

echo "[chain] intégration des deltas..."
venv/bin/python -u -m rag_droit.integrate_delta --all 2>&1

echo "[chain] lien jurisprudence CASS <-> CAPP..."
venv/bin/python -u -m rag_droit.link_jurisprudence --full 2>&1

echo "[chain] consolidation du Vault Obsidian..."
venv/bin/python -u -m rag_droit.consolidate_vault --full 2>&1

echo "[chain] embedding bulk..."
venv/bin/python -u -m rag_droit.ingest 2>&1

echo "[chain] TERMINÉ"
