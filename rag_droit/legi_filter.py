"""Filtre le corpus LEGI : produit `legi_clean.jsonl` (codes + finances).

Ne conserve que les entrées DILA dont l'`id` appartient au keep-set
(`legi_keep_ids.txt`). Les autres sources (CASS/JADE/etc.) et le fichier
`corpus_global.jsonl` d'origine restent inchangés.

Usage :
    python -m rag_droit.legi_filter
"""
from __future__ import annotations

import json
import sys

from . import config

KEEPSET_PATH = f"{config.DONNEES_TRAITEES_DIR}/legi_keep_ids.txt"
OUT_PATH = f"{config.DONNEES_TRAITEES_DIR}/legi_clean.jsonl"


def main() -> None:
    keep = set()
    with open(KEEPSET_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                keep.add(line)

    kept = 0
    dropped = 0
    total_dila = 0
    with open(config.CORPUS_GLOBAL_JSONL, encoding="utf-8") as src, \
            open(OUT_PATH, "w", encoding="utf-8") as out:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if doc.get("source") != "DILA":
                continue
            total_dila += 1
            if doc.get("id") in keep:
                out.write(line + "\n")
                kept += 1
            else:
                dropped += 1

    print(f"entrées DILA totales: {total_dila}", file=sys.stderr)
    print(f"conservées (codes+finances): {kept}", file=sys.stderr)
    print(f"écartées (TNC non-finance): {dropped}", file=sys.stderr)
    print(f"écrit dans {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
