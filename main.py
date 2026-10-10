"""Point d'entrée CLI du pipeline RAG Droit.

Usage :
    python main.py [--limit N] [--source legi|cass|inca] [--archives DIR]
                   [--jsonl FICHIER] [--vault DIR]

Les chemins par défaut sont définis dans `config` (racine `RAG_BASE_DIR`).
"""
from __future__ import annotations

import argparse

from rag_droit import config, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline RAG Droit (LEGI/CASS/CAPP/CONSTIT/JADE/INCA).")
    parser.add_argument("--archives", default=None, help="Dossier des archives brutes.")
    parser.add_argument("--jsonl", default=None, help="Chemin du corpus_global.jsonl.")
    parser.add_argument("--vault", default=None, help="Racine du Vault Obsidian.")
    parser.add_argument("--source", choices=["legi", "cass", "capp", "constit", "jade", "inca"], default=None,
                        help="Filtrer sur une source.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Nombre maximum de documents à traiter (test).")
    args = parser.parse_args()

    for result in run_pipeline(
        archives_dir=args.archives,
        jsonl_path=args.jsonl,
        vault_dir=args.vault,
        limit=args.limit,
        source_filter=args.source,
    ):
        print(f"[{result['index']}] {result['id']} tags={result['tags']}")


if __name__ == "__main__":
    main()
