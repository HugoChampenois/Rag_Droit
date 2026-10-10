"""Construction du lien entre décisions de cassation et arrêts d'appel attaqués.

Rôle
----
La donnée LEGI ne fournit aucun identifiant reliant une décision de la Cour de
cassation (CASS) à l'arrêt de cour d'appel (CAPP) qu'elle attaque. Ce module
reconstruit un lien **best-effort** à partir des seuls signaux disponibles :

  - CASS : `FORM_DEC_ATT` (« Chambre de l'instruction de la cour d'appel de
    Rennes ») + `DATE_DEC_ATT` (date de la décision attaquée) ;
  - CAPP : `JURIDICTION` (« Cour d'appel de Rennes ») + `FORMATION` + `DATE_DEC`.

Le rapprochement se fait sur la clé `(cour + date)`, affinée par la formation
quand elle est exploitable. Tous les candidats sont conservés (aucun silence).

Sortie
------
Un index JSON `donnees_traitees/liens_jurisprudence.json` :
    {"cass_to_capp": {"<id_cass>": ["<id_capp>", ...], ...}, "meta": {...}}

Les identifiants reproduisent exactement le champ `id` du `corpus_global.jsonl`
(priorité `num_affaire` > `nor` > `ecli` > `id` > `numero`), pour que
`consolidate_vault.py` puisse rapprocher les enregistrements.

Usage
-----
    python -m rag_droit.link_jurisprudence --full
    python -m rag_droit.link_jurisprudence --limit 5000   # test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import config

CASS_DIR = os.path.join(config.SOURCES_XML_DIR, "cass")
CAPP_DIR = os.path.join(config.SOURCES_XML_DIR, "capp")
LINK_PATH = os.path.join(config.DONNEES_TRAITEES_DIR, "liens_jurisprudence.json")


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def _norm(text: str) -> str:
    return " ".join(_fold(text).split())


def iter_xml(base: str) -> Iterator[str]:
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d.lower() not in ("eli", "deltas")]
        dirs.sort()
        files.sort()
        for filename in files:
            if filename.lower().endswith(".xml"):
                yield os.path.join(root, filename)


def _tag_value(raw: str, tag: str) -> str:
    m = re.search(r"<%s>([^<]*)</%s>" % (re.escape(tag), re.escape(tag)), raw)
    return m.group(1).strip() if m else ""


def _attr_value(raw: str, tag: str, attr: str) -> str:
    m = re.search(r"<%s\b[^>]*\b%s=\"([^\"]*)\"" % (re.escape(tag), re.escape(attr)), raw)
    if not m:
        m = re.search(r"<%s\b[^>]*\b%s='([^']*)'" % (re.escape(tag), re.escape(attr)), raw)
    return m.group(1).strip() if m else ""


def jsonl_id(num_affaire: str, nor: str, ecli: str, doc_id: str, numero: str) -> str:
    """Reproduit le calcul du champ `id` du pipeline (extract_metadata)."""
    return (num_affaire or nor or ecli or doc_id or numero).strip()


# --------------------------------------------------------------------------- #
# Normalisation cour / formation
# --------------------------------------------------------------------------- #
def norm_cour(text: str) -> str:
    """Extrait la ville de la cour d'appel (« cour d'appel de Lyon » -> « lyon »)."""
    t = _norm(text)
    idx = t.rfind("cour d'appel")
    if idx == -1:
        return ""
    rest = t[idx + len("cour d'appel"):].strip()
    # retire le séparateur « de » / « d' » éventuel devant la ville.
    rest = re.sub(r"^(?:d[e]['’]?\s+|d['’])", "", rest)
    rest = rest.strip(" ,.")
    if not rest:
        return ""
    city = rest.split()[0]
    # la ville doit ressembler à un toponyme (lettres / tirets), pas à une date.
    if not re.match(r"^[a-zà-ÿ][a-zà-ÿ\-]*$", city):
        return ""
    return city


def norm_formation(text: str) -> str:
    """Normalise un libellé de formation, en retirant la mention de la cour."""
    t = _norm(text)
    t = re.sub(r",?\s*cour d['’]appel d[e']?\s*[a-z\- ]*$", "", t).strip()
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t


def formation_compatible(cand: str, att: str) -> bool:
    """Indique si la formation candidate correspond à celle de la décision attaquée."""
    if not att:
        return True
    if not cand:
        return False
    if cand == att:
        return True
    if cand in att or att in cand:
        return True
    # chevauchement de jetons significatifs (hors mots-outils)
    stop = {"chambre", "section", "formation", "de", "la", "du", "des", "a", "1", "2", "3"}
    a = {t for t in att.split() if t not in stop and len(t) > 2}
    c = {t for t in cand.split() if t not in stop and len(t) > 2}
    if not a:
        return True
    return bool(a & c)


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def extract_cass(raw: str) -> Optional[Dict[str, Any]]:
    num_affaire = _tag_value(raw, "NUMERO_AFFAIRE")
    nor = _tag_value(raw, "NOR")
    ecli = _tag_value(raw, "ECLI")
    doc_id = _tag_value(raw, "ID")
    numero = _tag_value(raw, "NUMERO")
    publie = _attr_value(raw, "PUBLI_BULL", "publie").lower()
    form_dec_att = _tag_value(raw, "FORM_DEC_ATT")
    date_dec_att = _tag_value(raw, "DATE_DEC_ATT")
    return {
        "id": jsonl_id(num_affaire, nor, ecli, doc_id, numero),
        "publie": publie == "oui",
        "form_dec_att": form_dec_att,
        "date_dec_att": date_dec_att,
    }


def extract_capp(raw: str) -> Optional[Dict[str, Any]]:
    num_affaire = _tag_value(raw, "NUMERO_AFFAIRE")
    nor = _tag_value(raw, "NOR")
    ecli = _tag_value(raw, "ECLI")
    doc_id = _tag_value(raw, "ID")
    numero = _tag_value(raw, "NUMERO")
    juridiction = _tag_value(raw, "JURIDICTION")
    formation = _tag_value(raw, "FORMATION")
    date = _tag_value(raw, "DATE_DEC")
    return {
        "id": jsonl_id(num_affaire, nor, ecli, doc_id, numero),
        "cour": norm_cour(juridiction),
        "formation": norm_formation(formation),
        "date": date,
    }


# --------------------------------------------------------------------------- #
# Index + lien
# --------------------------------------------------------------------------- #
def build_links(limit: Optional[int] = None) -> Dict[str, Any]:
    # 1) décisions CASS publiées (les racines des procédures)
    cass_attacks: Dict[str, Dict[str, str]] = {}
    cass_scanned = 0
    for path in iter_xml(CASS_DIR):
        cass_scanned += 1
        if limit is not None and cass_scanned > limit:
            break
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                raw = handle.read()
        except OSError:
            continue
        rec = extract_cass(raw)
        if rec is None or not rec["id"]:
            continue
        if not rec["publie"]:
            continue
        if rec["form_dec_att"] or rec["date_dec_att"]:
            cass_attacks[rec["id"]] = {
                "cour": norm_cour(rec["form_dec_att"]),
                "formation": norm_formation(rec["form_dec_att"]),
                "date": rec["date_dec_att"],
            }

    # 2) index des décisions CAPP par (cour, date)
    capp_index: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    capp_scanned = 0
    for path in iter_xml(CAPP_DIR):
        capp_scanned += 1
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                raw = handle.read()
        except OSError:
            continue
        rec = extract_capp(raw)
        if rec is None or not rec["id"]:
            continue
        if rec["cour"] and rec["date"]:
            capp_index[(rec["cour"], rec["date"])].append(rec)

    # 3) résolution : pour chaque CASS publiée, candidats CAPP (cour+date, affinés formation)
    cass_to_capp: Dict[str, List[str]] = {}
    for cass_id, att in cass_attacks.items():
        if not att["cour"] or not att["date"]:
            continue
        candidates = capp_index.get((att["cour"], att["date"]), [])
        if not candidates:
            continue
        if att["formation"]:
            refined = [c for c in candidates if formation_compatible(c["formation"], att["formation"])]
            if refined:
                candidates = refined
        cass_to_capp[cass_id] = [c["id"] for c in candidates]

    return {
        "cass_to_capp": cass_to_capp,
        "meta": {
            "cass_scanned": cass_scanned,
            "cass_pub_avec_attaque": len(cass_attacks),
            "capp_scanned": capp_scanned,
            "linked": len(cass_to_capp),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Lien CASS <-> CAPP (procédures).")
    parser.add_argument("--full", action="store_true", help="Index complet.")
    parser.add_argument("--limit", type=int, default=None, help="Nb max de fichiers (test).")
    args = parser.parse_args()

    result = build_links(args.limit)
    os.makedirs(os.path.dirname(LINK_PATH), exist_ok=True)
    with open(LINK_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)

    print(f"[link] terminé : {json.dumps(result['meta'], ensure_ascii=False)}", file=sys.stderr)


if __name__ == "__main__":
    main()
