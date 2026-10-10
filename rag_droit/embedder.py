"""Client d'embedding : Ollama ou vLLM (API OpenAI-compatible).

Deux usages :
- Bulk (GPU distant)  : OLLAMA_BULK_URL   (défaut http://localhost:8000, vLLM)
- MAJ incrémentales    : OLLAMA_UPDATE_URL (défaut http://localhost:11434, Ollama)

Deux backends :
- `ollama` : POST /api/embed
- `openai` : POST /v1/embeddings (compatible vLLM, OpenAI, etc.)

Même modèle bge-m3 partout => même dimension (1024), vecteurs compatibles.
Le bulk passe par vLLM (backend `openai` par défaut) ; la MAJ/recherche reste
sur Ollama local. Clé API vLLM via RAG_EMBED_API_KEY (en-tête Authorization).
"""
from __future__ import annotations

import os
import re
import time
from typing import List, Optional

import httpx

EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "bge-m3")
EMBED_DIM = int(os.environ.get("RAG_EMBED_DIM", "1024"))
# "ollama" (POST /api/embed) | "openai" (POST /v1/embeddings, ex. vLLM)
EMBED_BACKEND = os.environ.get("RAG_EMBED_BACKEND", "ollama")
# Backends distincts bulk (GPU vLLM) / MAJ (CPU Ollama).
BULK_BACKEND = os.environ.get("RAG_BULK_BACKEND", "openai")
UPDATE_BACKEND = os.environ.get("RAG_UPDATE_BACKEND", EMBED_BACKEND)
# Clé API pour le backend OpenAI/vLLM (en-tête Authorization: Bearer ...).
EMBED_API_KEY = os.environ.get("RAG_EMBED_API_KEY", "")
BULK_OLLAMA_URL = os.environ.get("OLLAMA_BULK_URL", "http://localhost:8000")
UPDATE_OLLAMA_URL = os.environ.get("OLLAMA_UPDATE_URL", "http://localhost:11434")

# Taille cible d'un chunk (~500 tokens). bge-m3 a une attention en O(n²) :
# découper les textes longs en petits chunks divise le coût par ~10.
CHUNK_CHARS = int(os.environ.get("RAG_CHUNK_CHARS", "1800"))

# Limite dure au-delà de laquelle on tronque (sécurité, contexte bge-m3 = 8192 tokens).
MAX_CHUNK_CHARS = int(os.environ.get("RAG_MAX_CHUNK_CHARS", "24000"))


def truncate(text: str, max_chars: int = MAX_CHUNK_CHARS) -> str:
    """Tronque un texte au nombre de caractères max (limite du modèle)."""
    text = text or ""
    return text[:max_chars]


def _split_paragraph(para: str, max_chars: int) -> List[str]:
    """Découpe un paragraphe trop long, de préférence sur des fins de phrase."""
    parts: List[str] = []
    while len(para) > max_chars:
        cut = para.rfind(". ", 0, max_chars)
        if cut == -1:
            cut = para.rfind("\n", 0, max_chars)
        if cut == -1:
            cut = para.rfind(" ", 0, max_chars)
        if cut == -1:
            cut = max_chars
        parts.append(para[: cut + 1].strip())
        para = para[cut + 1 :].strip()
    if para:
        parts.append(para)
    return parts


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> List[str]:
    """Découpe un texte en chunks de ~`max_chars` (paragraphes puis phrases)."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    current = ""
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
                current = ""
            if len(para) <= max_chars:
                current = para
            else:
                chunks.extend(_split_paragraph(para, max_chars))
    if current:
        chunks.append(current)
    return chunks or [text]


class Embedder:
    """Enveloppe l'API d'embedding (Ollama `/api/embed` ou OpenAI `/v1/embeddings`)."""

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        model: Optional[str] = None,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.url = (ollama_url or UPDATE_OLLAMA_URL).rstrip("/")
        self.model = model or EMBED_MODEL
        self.backend = (backend or EMBED_BACKEND).lower()
        self.api_key = api_key if api_key is not None else EMBED_API_KEY

    def _retry_post(self, url: str, payload: dict, attempts: int = 6):
        """POST avec reprise : le tokenizer Ollama peut échouer transitoirement
        (erreur 400 « No connection »), on réessaie avec backoff."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last = None
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=300.0) as client:
                    resp = client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last = exc
                if attempt < attempts - 1:
                    time.sleep(2 * (attempt + 1))
        raise last

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Retourne un vecteur par texte, dans le même ordre."""
        if self.backend == "ollama":
            return self._embed_ollama(texts)
        return self._embed_openai(texts)

    def _embed_ollama(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        data = self._retry_post(
            f"{self.url}/api/embed",
            {"model": self.model, "input": list(texts)},
        )
        embeddings = list(data.get("embeddings", []))
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama a renvoyé {len(embeddings)} vecteurs pour {len(texts)} textes"
            )
        return embeddings

    def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        data = self._retry_post(
            f"{self.url}/v1/embeddings",
            {"model": self.model, "input": list(texts)},
        )
        # data = {"data": [{"embedding": [...], "index": i}, ...]}
        items = sorted(data.get("data", []), key=lambda it: it.get("index", 0))
        embeddings = [it["embedding"] for it in items]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Backend OpenAI a renvoyé {len(embeddings)} vecteurs pour {len(texts)} textes"
            )
        return embeddings

    def embed_one(self, text: str) -> List[float]:
        vectors = self.embed([text])
        if not vectors:
            raise RuntimeError("embedding vide renvoyé par le backend")
        return vectors[0]
