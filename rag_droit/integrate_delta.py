"""Intégration des deltas DILA dans le corpus (upsert par id, jamais de suppression).

Rôle
----
`maj.py` ne fait que télécharger les deltas. Ce module les **intègre** :
  1. extraction d'un delta `.tar.gz` dans `sources_xml/deltas/<ts>/` ;
  2. parsing de chaque XML avec les parseurs existants ;
   3. **upsert par `id`** : ajout (nouvelle version) ou mise à jour de statut
      (même id, `ETAT`/dates modifiés) — une ligne est ajoutée au JSONL
      (log d'événements). Le Vault Obsidian consolidé est régénéré ensuite par
      `consolidate_vault.py --full`.

Aucune suppression : les textes abrogés restent (marqueur de l'évolution du
droit, applicables aux situations antérieures).

Usage
-----
    python -m rag_droit.integrate_delta --targz /chemin/delta.tar.gz
    python -m rag_droit.integrate_delta --all          # tous les deltas de maj/data
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
from typing import Iterator, Optional

from . import config
from .factory import ParserFactory
from .parsers.base import SkipDocument
from .pipeline import _load_existing_ids, _write_jsonl_line, iter_xml_files

DELTAS_DIR = os.path.join(config.SOURCES_XML_DIR, "deltas")
CHECKPOINT = os.path.join(DELTAS_DIR, ".integrated")
MAJ_DATA_DIR = os.environ.get("RAG_MAJ_DATA_DIR", os.path.join(config.BASE_DIR, "maj", "data"))


def extract_delta(targz_path: str) -> str:
    """Extrait un delta dans `sources_xml/deltas/`, renvoie le dossier extrait."""
    os.makedirs(DELTAS_DIR, exist_ok=True)
    with tarfile.open(targz_path, "r:gz") as tar:
        members = tar.getmembers()
        tar.extractall(DELTAS_DIR)
    # Le dossier de plus haut niveau (le timestamp) est le premier membre répertoire.
    for m in members:
        if m.isdir() and "/" not in m.name.rstrip("/"):
            return os.path.join(DELTAS_DIR, m.name)
    return DELTAS_DIR


def integrate_dir(delta_dir: str, jsonl_path: str, vault_dir: str) -> tuple[int, int, int]:
    """Parse et upsert tous les XML d'un dossier delta (append JSONL uniquement)."""
    count = skipped = failed = 0
    os.makedirs(os.path.dirname(jsonl_path) or ".", exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as out:
        for xml_path in iter_xml_files(delta_dir):
            parser = ParserFactory.create(xml_path)
            try:
                parser.parse()
            except SkipDocument:
                skipped += 1
                continue
            except Exception as exc:  # noqa: BLE001
                failed += 1
                if failed <= 5:
                    print(f"[delta] échec ignoré : {xml_path} ({exc})", file=sys.stderr)
                continue

            parser.extract_metadata()
            parser.generate_tags()
            _, jsonl_obj = parser.format_outputs()
            _write_jsonl_line(out, jsonl_obj)
            count += 1
    return count, skipped, failed


def _load_checkpoint() -> set[str]:
    if not os.path.exists(CHECKPOINT):
        return set()
    with open(CHECKPOINT, encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip()}


def _save_checkpoint(ts: str) -> None:
    os.makedirs(DELTAS_DIR, exist_ok=True)
    with open(CHECKPOINT, "a", encoding="utf-8") as handle:
        handle.write(ts + "\n")


def _list_delta_targz() -> list[str]:
    """Liste les `.tar.gz` de deltas de `maj/data/<base>/`, triés par nom."""
    out: list[str] = []
    if not os.path.isdir(MAJ_DATA_DIR):
        return out
    for base in os.listdir(MAJ_DATA_DIR):
        base_dir = os.path.join(MAJ_DATA_DIR, base)
        if not os.path.isdir(base_dir):
            continue
        for name in sorted(os.listdir(base_dir)):
            if name.endswith(".tar.gz") and "global" not in name:
                out.append(os.path.join(base_dir, name))
    return sorted(out)


def integrate_all(jsonl_path: str, vault_dir: str) -> None:
    done = _load_checkpoint()
    for targz in _list_delta_targz():
        ts = os.path.basename(targz)[:-len(".tar.gz")]
        if ts in done:
            continue
        print(f"[delta] intégration de {os.path.basename(targz)} ...", file=sys.stderr)
        delta_dir = extract_delta(targz)
        count, skipped, failed = integrate_dir(delta_dir, jsonl_path, vault_dir)
        _save_checkpoint(ts)
        print(f"[delta] {ts} : {count} doc(s), {skipped} ignoré(s), {failed} échec(s)",
              file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Intégration des deltas DILA au corpus.")
    parser.add_argument("--targz", default=None, help="Un fichier delta .tar.gz à intégrer.")
    parser.add_argument("--all", action="store_true", help="Intégrer tous les deltas de maj/data.")
    parser.add_argument("--jsonl", default=config.CORPUS_GLOBAL_JSONL)
    parser.add_argument("--vault", default=config.VAULT_OBSIDIAN_DIR)
    args = parser.parse_args()

    if args.targz:
        delta_dir = extract_delta(args.targz)
        count, skipped, failed = integrate_dir(delta_dir, args.jsonl, args.vault)
        print(f"[delta] {count} doc(s), {skipped} ignoré(s), {failed} échec(s)", file=sys.stderr)
    elif args.all:
        integrate_all(args.jsonl, args.vault)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
