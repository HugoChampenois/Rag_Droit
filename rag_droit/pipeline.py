"""Pipeline de traitement par flux (streaming / yield).

Itère sur les fichiers XML un par un afin de ne jamais saturer la RAM,
et écrit la sortie de façon incrémentale (JSONL uniquement ; le Vault Obsidian
est produit séparément par `consolidate_vault.py`).

Le JSONL est idempotent : un identifiant déjà présent dans le fichier de sortie
est ignoré lors des relances (pas de doublons).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Iterator, Optional, Set

from . import config
from .factory import ParserFactory
from .parsers.base import SkipDocument


def iter_xml_files(archives_dir: str) -> Iterator[str]:
    """Générateur : liste les chemins XML sans les charger en mémoire.

    Élagage :
      - `eli/`   : index `<ID>` (stubs) sans texte ;
      - `deltas/`: fichiers delta, traités séparément par `integrate_delta.py`
        (upsert par id), pas par le pipeline add-only.
    """
    for root, dirs, files in os.walk(archives_dir):
        dirs[:] = [d for d in dirs if d.lower() not in ("eli", "deltas")]
        dirs.sort()
        files.sort()
        for filename in files:
            if filename.lower().endswith(".xml"):
                yield os.path.join(root, filename)


def _write_jsonl_line(handle, obj: dict) -> None:
    handle.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_existing_ids(jsonl_path: str) -> Set[str]:
    """Lit les identifiants déjà présents dans le JSONL (idempotence)."""
    ids: Set[str] = set()
    if not os.path.exists(jsonl_path):
        return ids
    with open(jsonl_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc_id = obj.get("id")
            if doc_id:
                ids.add(doc_id)
    return ids


def run_pipeline(
    archives_dir: Optional[str] = None,
    jsonl_path: Optional[str] = None,
    vault_dir: Optional[str] = None,
    limit: Optional[int] = None,
    source_filter: Optional[str] = None,
) -> Iterator[dict]:
    """Traite le corpus et produit (yield) un résumé par document traité."""
    archives_dir = archives_dir or config.SOURCES_XML_DIR
    jsonl_path = jsonl_path or config.CORPUS_GLOBAL_JSONL
    vault_dir = vault_dir or config.VAULT_OBSIDIAN_DIR

    os.makedirs(os.path.dirname(jsonl_path) or ".", exist_ok=True)
    os.makedirs(vault_dir, exist_ok=True)

    seen_ids = _load_existing_ids(jsonl_path)
    count = 0
    skipped_dupes = 0
    failed = 0

    with open(jsonl_path, "a", encoding="utf-8") as out:
        for xml_path in iter_xml_files(archives_dir):
            if source_filter and source_filter not in xml_path.lower().replace("\\", "/"):
                continue
            if limit is not None and count >= limit:
                break

            parser = ParserFactory.create(xml_path)
            try:
                parser.parse()
            except SkipDocument:
                continue
            except Exception as exc:
                failed += 1
                if failed <= 5:
                    print(f"[pipeline] échec de parsing ignoré : {xml_path} ({exc})", file=sys.stderr)
                continue

            parser.extract_metadata()
            parser.generate_tags()
            _, jsonl_obj = parser.format_outputs()

            doc_id = jsonl_obj["id"]
            if doc_id in seen_ids:
                skipped_dupes += 1
                continue

            _write_jsonl_line(out, jsonl_obj)
            seen_ids.add(doc_id)
            count += 1
            yield {
                "index": count,
                "id": jsonl_obj["id"],
                "source": parser.metadata["source_donnee"],
                "tags": jsonl_obj["tags"],
            }

    print(
        f"[pipeline] terminé : {count} document(s) traité(s), "
        f"{skipped_dupes} doublon(s) ignoré(s), {failed} fichier(s) en échec.",
        file=sys.stderr,
    )
