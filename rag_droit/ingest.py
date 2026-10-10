"""Ingestion du corpus dans Qdrant (bulk GPU + reprise).

Usage :
    python -m rag_droit.ingest [--embed-url URL] [--jsonl FICHIER]
                               [--collection NOM] [--batch N] [--limit N]
                               [--checkpoint FICHIER]

Par défaut :
    - Embedding bulk : vLLM, OLLAMA_BULK_URL (http://localhost:8000)
    - Qdrant         : QDRANT_URL (http://localhost:6333)
    - Collection     : rag_droit (1024 dims, cosine)

Idempotent + reprise : le point Qdrant est un UUID déterministe du `id`, et un
checkpoint (nombre de lignes JSONL consommées) permet d'arrêter/reprendre.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterator, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Modifier,
    PointStruct,
    SparseVectorConfig,
    SparseVectorNameConfig,
    SparseVectorParams,
    VectorParams,
)

from . import config
from .embedder import BULK_BACKEND, BULK_OLLAMA_URL, EMBED_DIM, Embedder, chunk_text
from .lexical import SPARSE_VECTOR_NAME, text_to_sparse

COLLECTION = os.environ.get("RAG_COLLECTION", "rag_droit")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

# Nombre de chunks par requête d'embedding. On reste sous la capacité de
# planification du GPU vLLM (max_num_seqs ~256) pour éviter la file d'attente.
EMBED_BATCH = int(os.environ.get("RAG_EMBED_BATCH", "256"))

# Nombre de requêtes d'embedding envoyées en parallèle au GPU vLLM.
EMBED_WORKERS = int(os.environ.get("RAG_EMBED_WORKERS", "2"))

# Nombre max de points par appel Qdrant. Le payload JSON d'un lot de points peut
# dépasser la limite Qdrant (32 Mo) ; on découpe l'upsert en petits paquets.
QDRANT_UPSERT_BATCH = int(os.environ.get("RAG_QDRANT_UPSERT_BATCH", "1000"))

# wait=True attend l'indexation complète (lent) ; wait=False valide dès le WAL
# (durable, beaucoup plus rapide). Les points restent idempotents.
QDRANT_WAIT = os.environ.get("RAG_QDRANT_WAIT", "0") == "1"


def _point_id(doc_id: str, chunk_index: int = 0) -> str:
    """UUID déterministe (idempotent) dérivé de l'identifiant document + chunk."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}::{chunk_index}"))


def get_client(url: Optional[str] = None) -> QdrantClient:
    return QdrantClient(url=url or QDRANT_URL)


def ensure_collection(client: QdrantClient, name: str, dim: int) -> None:
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF),
            },
        )
        return
    _ensure_sparse_vector(client, name)


def _ensure_sparse_vector(client: QdrantClient, name: str) -> None:
    """Ajoute le vecteur creux à une collection existante (idempotent).

    Qdrant ne permet pas d'ajouter un vecteur nommé via `update_collection` ;
    il faut passer par `create_vector_name` (PUT /collections/{name}/vectors/{n}).
    """
    info = client.get_collection(name)
    sparse = info.config.params.sparse_vectors or {}
    if SPARSE_VECTOR_NAME not in sparse:
        client.create_vector_name(
            collection_name=name,
            vector_name=SPARSE_VECTOR_NAME,
            vector_name_config=SparseVectorNameConfig(
                sparse=SparseVectorConfig(modifier=Modifier.IDF)
            ),
        )


def build_chunks(doc: Dict[str, Any]) -> List[str]:
    return chunk_text(doc.get("markdown", ""))


def build_payload(
    doc: Dict[str, Any],
    chunk_index: int = 0,
    chunk_count: int = 1,
    chunk_text: str = "",
) -> Dict[str, Any]:
    return {
        "doc_id": doc.get("id", ""),
        "source": doc.get("source", ""),
        "statut": doc.get("statut", ""),
        "date": doc.get("date", ""),
        "date_fin": doc.get("date_fin", ""),
        "num": doc.get("num", ""),
        "titre": doc.get("titre", ""),
        "categorie": doc.get("categorie", ""),
        "tags": doc.get("tags", []),
        "obsidian_path": doc.get("obsidian_path", ""),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "chunk_text": chunk_text,
    }


def embed_documents(embedder: Embedder, docs: List[Dict[str, Any]]) -> List[PointStruct]:
    """Découpe, embeede et construit les points Qdrant d'un lot de documents.

    L'embedding est découpé par paquets de `EMBED_BATCH` chunks, envoyés en
    parallèle (`EMBED_WORKERS`) pour saturer le GPU vLLM. Ne fait PAS l'upsert.
    """
    if not docs:
        return []

    texts: List[str] = []
    metas: List[tuple] = []
    for d in docs:
        chunks = build_chunks(d)
        for i, c in enumerate(chunks):
            texts.append(c)
            metas.append((d, i, len(chunks), c))

    starts = list(range(0, len(texts), EMBED_BATCH))
    points: List[PointStruct] = []

    def _append(sub_start: int, vectors: List[List[float]]) -> None:
        sub_metas = metas[sub_start : sub_start + EMBED_BATCH]
        for (d, i, n, c), v in zip(sub_metas, vectors):
            vector = {"": v}
            sv = text_to_sparse(c)
            if sv.indices:
                vector[SPARSE_VECTOR_NAME] = sv
            points.append(
                PointStruct(
                    id=_point_id(d["id"], i),
                    vector=vector,
                    payload=build_payload(d, i, n, c),
                )
            )

    if EMBED_WORKERS > 1 and len(starts) > 1:
        with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
            futures = [
                (s, pool.submit(embedder.embed, texts[s : s + EMBED_BATCH]))
                for s in starts
            ]
            for s, fut in futures:
                _append(s, fut.result())
    else:
        for s in starts:
            _append(s, embedder.embed(texts[s : s + EMBED_BATCH]))

    return points


def upsert_documents(
    client: QdrantClient,
    embedder: Embedder,
    docs: List[Dict[str, Any]],
    collection: str,
) -> int:
    """Embede et insère un lot de documents (idempotent), un point par chunk."""
    points = embed_documents(embedder, docs)
    if not points:
        return 0
    for start in range(0, len(points), QDRANT_UPSERT_BATCH):
        client.upsert(
            collection_name=collection,
            points=points[start : start + QDRANT_UPSERT_BATCH],
            wait=QDRANT_WAIT,
        )
    return len(points)


def ingest_documents(
    client: QdrantClient,
    embedder: Embedder,
    docs: List[Dict[str, Any]],
    collection: str,
) -> int:
    """Point d'entrée réutilisable (bulk CLI et endpoint /ingest)."""
    return upsert_documents(client, embedder, docs, collection)


def iter_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def run_bulk(args: argparse.Namespace) -> int:
    client = get_client()
    ensure_collection(client, args.collection, EMBED_DIM)
    embedder = Embedder(ollama_url=args.ollama_url, backend=BULK_BACKEND)

    jsonl_path = args.jsonl or config.CORPUS_GLOBAL_JSONL
    checkpoint = args.checkpoint or (jsonl_path + ".ingest_done")

    done = 0
    if os.path.exists(checkpoint):
        with open(checkpoint, encoding="utf-8") as cf:
            done = int(cf.read().strip() or 0)

    # Pipeline producteur/consommateur : le producteur lit + découpe + embeede
    # (GPU) tandis que le consommateur insère dans Qdrant et avance le
    # checkpoint. Le GPU reste ainsi occupé en continu, sans creux entre lots.
    q: "queue.Queue" = queue.Queue(maxsize=2)
    error_holder: List[BaseException] = []

    def producer() -> None:
        try:
            batch: List[Dict[str, Any]] = []
            doc_count = 0
            cursor = 0
            with open(jsonl_path, encoding="utf-8") as handle:
                for raw in handle:
                    cursor += 1
                    if cursor <= done:
                        continue
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not doc.get("id") or not doc.get("markdown"):
                        continue
                    batch.append(doc)
                    doc_count += 1
                    if args.limit is not None and doc_count >= args.limit:
                        break
                    if len(batch) >= args.batch:
                        q.put((cursor, embed_documents(embedder, batch)))
                        batch = []
                if batch:
                    q.put((cursor, embed_documents(embedder, batch)))
            q.put(None)
        except BaseException as exc:  # noqa: BLE001
            error_holder.append(exc)
            q.put(None)

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    count = 0
    while True:
        item = q.get()
        if item is None:
            break
        cursor, points = item
        for start in range(0, len(points), QDRANT_UPSERT_BATCH):
            client.upsert(
                collection_name=args.collection,
                points=points[start : start + QDRANT_UPSERT_BATCH],
                wait=QDRANT_WAIT,
            )
        count += len(points)
        with open(checkpoint, "w", encoding="utf-8") as cf:
            cf.write(str(cursor))
        print(f"[ingest] {count} chunks indexés", file=sys.stderr)

    thread.join()
    if error_holder:
        raise error_holder[0]

    print(f"[ingest] terminé : {count} chunks indexés", file=sys.stderr)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestion RAG dans Qdrant (bulk).")
    parser.add_argument("--embed-url", "--ollama-url", dest="ollama_url",
                        default=BULK_OLLAMA_URL,
                        help="URL du serveur d'embedding bulk (vLLM).")
    parser.add_argument("--jsonl", default=None, help="Chemin du corpus_global.jsonl.")
    parser.add_argument("--collection", default=COLLECTION, help="Nom de collection Qdrant.")
    parser.add_argument("--batch", type=int, default=200, help="Nb de documents par lot (checkpoint).")
    parser.add_argument("--limit", type=int, default=None, help="Nb max de docs (test).")
    parser.add_argument("--checkpoint", default=None, help="Fichier de reprise.")
    args = parser.parse_args()
    run_bulk(args)


if __name__ == "__main__":
    main()
