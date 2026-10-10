"""Construction du keep-set LEGI (articles de codes + domaine budget/finances).

Identifie, directement depuis l'arborescence XML LEGI, les identifiants de
documents à CONSERVER pour la base RAG :

  - tous les articles de codes (`code_en_vigueur` + `code_non_vigueur`) ;
  - les textes et articles du domaine budget/finances/fiscal dans les TNC
    (lois de finances, LFSS, lois organiques financières, LPFP, décrets et
    arrêtés techniques).

Le reste des TNC (arrêtés/décrets/ordonnances/lois hors finance) est écarté.

Usage :
    python -m rag_droit.legi_keepset --dry-run      # comptage seul
    python -m rag_droit.legi_keepset --out FICHIER # écrit le keep-set
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Set

from . import config

# Préfixes NOR et mots-clés de titre du domaine finances (miroir de legi.py).
_FINANCE_NOR_PREFIXES = ("BCR", "BCF", "CPA", "EFI", "FCP", "ECF", "BCP", "BUD")
_FINANCE_TITLE_KEYS = (
    "de finances",
    "financement de la sécurité sociale",
    "de règlement",
    "programmation des finances",
)

_CODE_DIRS = (
    f"{config.SOURCES_XML_DIR}/legi/global/code_et_TNC_en_vigueur/code_en_vigueur",
    f"{config.SOURCES_XML_DIR}/legi/global/code_et_TNC_non_vigueur/code_non_vigueur",
)
_TNC_DIRS = (
    f"{config.SOURCES_XML_DIR}/legi/global/code_et_TNC_en_vigueur/TNC_en_vigueur",
    f"{config.SOURCES_XML_DIR}/legi/global/code_et_TNC_non_vigueur/TNC_non_vigueur",
)

_TEXT_FOLDER_RE = re.compile(r"(?:LEGI|JORF)TEXT\d{12}")
_ARTI_RE = re.compile(r"LEGIARTI\d{12}")


def _finance_from_text_xml(raw: str) -> bool:
    """Applique la règle finances à un contenu de `texte/version/*.xml`."""
    nor = ""
    nature = ""
    titrefull = ""
    m = re.search(r"<NOR>([^<]*)</NOR>", raw)
    if m:
        nor = m.group(1).strip().upper()
    m = re.search(r"<NATURE>([^<]*)</NATURE>", raw)
    if m:
        nature = m.group(1).strip().upper()
    m = re.search(r"<TITREFULL>([^<]*)</TITREFULL>", raw)
    if m:
        titrefull = m.group(1).lower()
    if nor and nor[:3] in _FINANCE_NOR_PREFIXES:
        return True
    if nature in ("LOI", "LOI_ORGANIQUE") and any(k in titrefull for k in _FINANCE_TITLE_KEYS):
        return True
    return False


def _iter_xml_files(dirs) -> "iter":
    for base in dirs:
        for root, dnames, fnames in os.walk(base):
            for fn in fnames:
                if fn.endswith(".xml"):
                    yield os.path.join(root, fn)


def build_keepset() -> Set[str]:
    """Retourne l'ensemble des `id` JSONL LEGI à conserver."""
    keep: Set[str] = set()

    # 1) Articles de codes (tous conservés).
    for path in _iter_xml_files(_CODE_DIRS):
        m = _ARTI_RE.search(path)
        if m:
            keep.add(m.group(0))

    # 2) Domaine finances dans les TNC : textes + articles.
    finance_text_ids: Set[str] = set()  # id des dossiers LEGITEXT/JORFTEXT financiers
    for path in _iter_xml_files(_TNC_DIRS):
        if "/texte/version/" not in path:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read(65536)
        except OSError:
            continue
        if not _finance_from_text_xml(raw):
            continue
        # NOR (id JSONL prioritaire) + LEGITEXT id (fallback si NOR vide).
        m = re.search(r"<NOR>([^<]*)</NOR>", raw)
        if m and m.group(1).strip():
            keep.add(m.group(1).strip())
        legitext_id = os.path.splitext(os.path.basename(path))[0]
        keep.add(legitext_id)
        m = _TEXT_FOLDER_RE.search(path)
        if m:
            finance_text_ids.add(m.group(0))

    # 3) Articles des textes financiers TNC.
    for path in _iter_xml_files(_TNC_DIRS):
        if "/article/" not in path:
            continue
        m = _TEXT_FOLDER_RE.search(path)
        if not m or m.group(0) not in finance_text_ids:
            continue
        a = _ARTI_RE.search(path)
        if a:
            keep.add(a.group(0))

    return keep


def _counts() -> dict:
    stats = {
        "code_articles": 0,
        "finance_texts": 0,
        "finance_articles": 0,
        "tnc_texts_dropped": 0,
        "tnc_articles_dropped": 0,
    }
    finance_text_ids: Set[str] = set()
    for path in _iter_xml_files(_CODE_DIRS):
        if "/article/" in path and _ARTI_RE.search(path):
            stats["code_articles"] += 1
    for path in _iter_xml_files(_TNC_DIRS):
        if "/texte/version/" in path:
            try:
                with open(path, encoding="utf-8") as fh:
                    raw = fh.read(65536)
            except OSError:
                continue
            if _finance_from_text_xml(raw):
                stats["finance_texts"] += 1
                m = _TEXT_FOLDER_RE.search(path)
                if m:
                    finance_text_ids.add(m.group(0))
            else:
                stats["tnc_texts_dropped"] += 1
    for path in _iter_xml_files(_TNC_DIRS):
        if "/article/" not in path:
            continue
        m = _TEXT_FOLDER_RE.search(path)
        if m and m.group(0) in finance_text_ids:
            stats["finance_articles"] += 1
        else:
            stats["tnc_articles_dropped"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep-set LEGI (codes + finances).")
    parser.add_argument("--out", default=None, help="Fichier de sortie (un id par ligne).")
    parser.add_argument("--dry-run", action="store_true", help="Comptage seul.")
    args = parser.parse_args()

    stats = _counts()
    total_keep = (
        stats["code_articles"] + stats["finance_texts"] + stats["finance_articles"]
    )
    total_drop = stats["tnc_texts_dropped"] + stats["tnc_articles_dropped"]
    print("=== Comptage LEGI (fichiers XML) ===", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"  TOTAL conservé: {total_keep}", file=sys.stderr)
    print(f"  TOTAL écarté (TNC): {total_drop}", file=sys.stderr)

    if args.dry_run:
        return

    keep = build_keepset()
    print(f"keep-set: {len(keep)} ids uniques", file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for ident in sorted(keep):
                fh.write(ident + "\n")
        print(f"écrit dans {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
