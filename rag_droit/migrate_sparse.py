"""Migration one-shot : peuple le vecteur creux `sparse` des points existants.

Le corpus a déjà été embeddé (6,9 M de points) avant l'introduction du vecteur
creux BM25. Re-passer par `ingest` ré-embederait le dense via Ollama/GPU (~12 h),
ce qui est exclu. Ce script ne calcule QUE le vecteur creux, localement (CPU Xeon),
et l'ajoute via `update_vectors()` sans jamais toucher au vecteur dense `""` ni
appeler Ollama.

Usage :
    venv/bin/python -m rag_droit.migrate_sparse [--collection NOM]
                                                 [--batch N] [--limit N]
                                                 [--checkpoint FICHIER]

Idempotent + reprise : le checkpoint stocke l'offset `scroll` (id du point).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import PointVectors

from . import config
from .embedder import EMBED_DIM
from .ingest import COLLECTION, QDRANT_WAIT, ensure_collection, get_client
from .lexical import SPARSE_VECTOR_NAME, text_to_sparse

# Nombre de points par page `scroll` / par appel `update_vectors`.
SCROLL_BATCH = int(os.environ.get("RAG_MIGRATE_BATCH", "1000"))

# Timeout (secondes) et reprises pour les appels Qdrant : l'indexation creuse
# concurrente peut ralentir ponctuellement `scroll`/`update_vectors`.
QDRANT_TIMEOUT = int(os.environ.get("RAG_MIGRATE_TIMEOUT", "300"))
RETRY_ATTEMPTS = int(os.environ.get("RAG_MIGRATE_RETRY", "6"))


def _retry(fn, *args, **kwargs):
    """Réessaie un appel Qdrant avec backoff (idempotent, sûr)."""
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(2 * (attempt + 1))
    raise last


def migrate_sparse(
    client: QdrantClient,
    collection: str,
    batch: int,
    checkpoint_path: Optional[str],
    limit: Optional[int],
) -> int:
    """Parcourt les points et ajoute le vecteur creux `sparse` (idempotent)."""
    offset = None
    processed = 0
    if checkpoint_path and os.path.exists(checkpoint_path):
        with open(checkpoint_path, encoding="utf-8") as cf:
            saved = cf.read().strip()
            if saved:
                offset = saved

    while True:
        records, next_offset = _retry(
            client.scroll,
            collection_name=collection,
            limit=batch,
            offset=offset,
            with_payload=["chunk_text"],
            with_vectors=False,
            timeout=QDRANT_TIMEOUT,
        )
        if not records:
            break

        points: List[PointVectors] = []
        for rec in records:
            text = (rec.payload or {}).get("chunk_text", "")
            sv = text_to_sparse(text)
            if not sv.indices:
                continue
            points.append(PointVectors(id=rec.id, vector={SPARSE_VECTOR_NAME: sv}))

        if points:
            _retry(
                client.update_vectors,
                collection_name=collection,
                points=points,
                wait=QDRANT_WAIT,
                timeout=QDRANT_TIMEOUT,
            )

        processed += len(records)
        offset = next_offset
        if checkpoint_path:
            with open(checkpoint_path, "w", encoding="utf-8") as cf:
                cf.write(str(offset) if offset is not None else "")
        print(f"[migrate_sparse] {processed} points traités", file=sys.stderr)

        if offset is None:
            break
        if limit is not None and processed >= limit:
            break

    print(f"[migrate_sparse] terminé : {processed} points traités", file=sys.stderr)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Migration one-shot vecteur creux (sans Ollama).")
    parser.add_argument("--collection", default=COLLECTION, help="Collection Qdrant.")
    parser.add_argument("--batch", type=int, default=SCROLL_BATCH, help="Taille des lots scroll/update.")
    parser.add_argument("--limit", type=int, default=None, help="Nb max de points (test).")
    parser.add_argument("--checkpoint", default=None, help="Fichier de reprise (offset).")
    args = parser.parse_args()

    client = get_client()
    ensure_collection(client, args.collection, EMBED_DIM)

    checkpoint = args.checkpoint or os.path.join(
        config.BASE_DIR, f"{args.collection}.migrate_sparse_offset"
    )
    migrate_sparse(client, args.collection, args.batch, checkpoint, args.limit)


if __name__ == "__main__":
    main()
