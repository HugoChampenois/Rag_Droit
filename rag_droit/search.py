"""API de recherche RAG (retrieval pur).

Lancement :
    uvicorn rag_droit.search:app --host 0.0.0.0 --port 8010

Endpoints :
    GET  /health   -> état + collection
    POST /search   -> {"query": "...", "limit": N}  => top-k chunks + sources
    POST /ingest   -> {"documents": [{...}]}        => MAJ incrémentale (CPU local)
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from qdrant_client.models import Fusion, FusionQuery, Prefetch

from .embedder import EMBED_DIM, UPDATE_BACKEND, UPDATE_OLLAMA_URL, Embedder
from .ingest import (
    COLLECTION,
    QDRANT_URL,
    ensure_collection,
    get_client,
    ingest_documents,
)
from .lexical import SPARSE_VECTOR_NAME, text_to_sparse

app = FastAPI(title="RAG Droit - API de recherche")

_client = get_client()
_embedder = Embedder(ollama_url=UPDATE_OLLAMA_URL, backend=UPDATE_BACKEND)


@app.on_event("startup")
def _startup() -> None:
    ensure_collection(_client, COLLECTION, EMBED_DIM)


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    search_type: str = "dense"  # dense | sparse | hybrid


class IngestRequest(BaseModel):
    documents: List[Dict[str, Any]]


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "collection": COLLECTION,
        "embed_model": _embedder.model,
        "embed_url": _embedder.url,
    }


@app.post("/search")
def search(req: SearchRequest) -> Dict[str, Any]:
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="requête vide")
    limit = max(1, min(req.limit, 100))

    search_type = (req.search_type or "dense").lower()
    if search_type not in ("dense", "sparse", "hybrid"):
        raise HTTPException(status_code=400, detail="search_type invalide")

    if search_type == "dense":
        vector = _embedder.embed_one(query)
        resp = _client.query_points(
            collection_name=COLLECTION,
            query=vector,
            using="",
            limit=limit,
            with_payload=True,
        )
    elif search_type == "sparse":
        resp = _client.query_points(
            collection_name=COLLECTION,
            query=text_to_sparse(query, as_query=True),
            using=SPARSE_VECTOR_NAME,
            limit=limit,
            with_payload=True,
        )
    else:  # hybrid : fusion RRF dense + creux
        resp = _client.query_points(
            collection_name=COLLECTION,
            prefetch=[
                Prefetch(query=_embedder.embed_one(query), using="", limit=limit),
                Prefetch(
                    query=text_to_sparse(query, as_query=True),
                    using=SPARSE_VECTOR_NAME,
                    limit=limit,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            with_payload=True,
            limit=limit,
        )

    results: List[Dict[str, Any]] = []
    for point in resp.points:
        payload = point.payload or {}
        results.append(
            {
                "score": point.score,
                "doc_id": payload.get("doc_id"),
                "source": payload.get("source"),
                "statut": payload.get("statut"),
                "date": payload.get("date"),
                "num": payload.get("num"),
                "titre": payload.get("titre"),
                "tags": payload.get("tags", []),
                "chunk_index": payload.get("chunk_index"),
                "chunk_count": payload.get("chunk_count"),
                "extrait": payload.get("chunk_text", ""),
            }
        )
    return {"query": query, "results": results}


@app.post("/ingest")
def ingest(req: IngestRequest) -> Dict[str, Any]:
    if not req.documents:
        raise HTTPException(status_code=400, detail="aucun document")
    n = ingest_documents(_client, _embedder, req.documents, COLLECTION)
    return {"ingested": n}
