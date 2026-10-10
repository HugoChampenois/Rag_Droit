"""Déduplication du corpus JSONL : une seule ligne par `id` (la plus récente).

Le JSONL est un log d'événements append-only : les deltas re-publient des
documents existants (mise à jour de statut `ETAT`), créant des lignes
redondantes. Ce script garde la DERNIÈRE occurrence de chaque `id`.

Usage :
    python -m rag_droit.dedup [chemin_du_jsonl]
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict

from . import config

DEFAULT = config.CORPUS_GLOBAL_JSONL


def dedup_jsonl(path: str) -> tuple[int, int]:
    """Réécrit `path` en ne gardant que la dernière ligne par `id`.

    Retourne (lignes_avant, lignes_après). Écrit atomiquement via un .tmp.
    """
    tmp = path + ".dedup"
    latest: Dict[str, int] = {}

    # Passe 1 : dernière position de chaque id
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            try:
                doc_id = json.loads(line).get("id")
            except json.JSONDecodeError:
                continue
            if doc_id:
                latest[doc_id] = i

    # Passe 2 : ne réécrire que la dernière occurrence
    total = kept = 0
    with open(path, encoding="utf-8") as f, open(tmp, "w", encoding="utf-8") as w:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            total += 1
            try:
                doc_id = json.loads(line).get("id")
            except json.JSONDecodeError:
                doc_id = None
            if doc_id and latest.get(doc_id) == i:
                w.write(line)
                kept += 1

    os.replace(tmp, path)
    return total, kept


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.exists(path):
        print(f"fichier introuvable : {path}", file=sys.stderr)
        sys.exit(1)
    total, kept = dedup_jsonl(path)
    print(
        f"déduplication terminée : {total} lignes -> {kept} lignes "
        f"({total - kept} retirées)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
