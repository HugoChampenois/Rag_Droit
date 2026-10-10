"""Consolidation du Vault Obsidian à partir de corpus_global.jsonl.

But
---
Le JSONL (`corpus_global.jsonl`) est la source de vérité (log d'événements
append-only, jamais modifiée). Ce module reconstruit le Vault Obsidian sous une
forme consolidée, lisible et navigable :

    Vault_Obsidian/
      Codes/Code_<nom>.md                      (~75 codes officiels consolidés)
      Lois/{YYYY}.md                           (textes + articles non codifiés)
      Lois/Finances/{YYYY}.md                  (lois de finances + rectificatives)
      Lois/Securite_Sociale/{YYYY}.md          (lois de financement de la sécu)
      JP/Inedites/{Matiere}/{YYYY}.md          (jurisprudence inédite)
      JP/Publiees/{Juridiction}/{Pourvoi}.md   (1 affaire = CASS + arrêt(s) CAPP)

Règles
------
- Codes : registre canonique (~75) ; annexes / variantes / territoriaux /
  anciens / déontologie fusionnés ; tout autre nom reclassé en texte non codifié.
- Jurisprudence publiée : regroupée en « procédures » via l'index produit par
  `link_jurisprudence.py` (CASS + arrêt(s) d'appel attaqué(s)), tri décroissant.
- Mise à jour : rebuild complet (purge puis régénération), dédup par `id`.

Usage
-----
    python -m rag_droit.consolidate_vault --full [--limit N] [--filter SRC]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from . import config
from .router import MATIERE_FOLDER, RACINE_FOLDER

SPOOL_ROOT = os.path.join(config.DONNEES_TRAITEES_DIR, "spool")
LINK_PATH = os.path.join(config.DONNEES_TRAITEES_DIR, "liens_jurisprudence.json")

OUTPUT_DIRS = ("Codes", "Lois", "JP")
LEGACY_DIRS = ("Loi", "Reglements")

# --------------------------------------------------------------------------- #
# Registre canonique des codes (~75) et alias de fusion
# --------------------------------------------------------------------------- #
CANON_CODES: Dict[str, str] = {
    "code civil": "Code civil",
    "code de commerce": "Code de commerce",
    "code penal": "Code pénal",
    "code de procedure civile": "Code de procédure civile",
    "code de procedure penale": "Code de procédure pénale",
    "code du travail": "Code du travail",
    "code de la securite sociale": "Code de la sécurité sociale",
    "code de la consommation": "Code de la consommation",
    "code des assurances": "Code des assurances",
    "code monetaire et financier": "Code monétaire et financier",
    "code de la propriete intellectuelle": "Code de la propriété intellectuelle",
    "code rural et de la peche maritime": "Code rural et de la pêche maritime",
    "code de la construction et de l'habitation": "Code de la construction et de l'habitation",
    "code de l'action sociale et des familles": "Code de l'action sociale et des familles",
    "code de l'artisanat": "Code de l'artisanat",
    "code du tourisme": "Code du tourisme",
    "code general des impots": "Code général des impôts",
    "code de l'environnement": "Code de l'environnement",
    "code de l'urbanisme": "Code de l'urbanisme",
    "code de la sante publique": "Code de la santé publique",
    "code de la route": "Code de la route",
    "code de la voirie routiere": "Code de la voirie routière",
    "code des transports": "Code des transports",
    "code de l'energie": "Code de l'énergie",
    "code minier": "Code minier",
    "code forestier": "Code forestier",
    "code de l'education": "Code de l'éducation",
    "code general de la fonction publique": "Code général de la fonction publique",
    "code de la defense": "Code de la défense",
    "code de la securite interieure": "Code de la sécurité intérieure",
    "code de justice administrative": "Code de justice administrative",
    "code des relations entre le public et l'administration": "Code des relations entre le public et l'administration",
    "code general de la propriete des personnes publiques": "Code général de la propriété des personnes publiques",
    "code de la commande publique": "Code de la commande publique",
    "code de l'entree et du sejour des etrangers et du droit d'asile": "Code de l'entrée et du séjour des étrangers et du droit d'asile",
    "code de l'organisation judiciaire": "Code de l'organisation judiciaire",
    "code de l'expropriation pour cause d'utilite publique": "Code de l'expropriation pour cause d'utilité publique",
    "code des postes et des communications electroniques": "Code des postes et des communications électroniques",
    "code des douanes": "Code des douanes",
    "code du sport": "Code du sport",
    "code electoral": "Code électoral",
    "code du patrimoine": "Code du patrimoine",
    "code de la recherche": "Code de la recherche",
    "code de l'aviation civile": "Code de l'aviation civile",
    "code penitentiaire": "Code pénitentiaire",
    "code de la mutualite": "Code de la mutualité",
    "code du service national": "Code du service national",
    "code des juridictions financieres": "Code des juridictions financières",
    "code des impositions sur les biens et services": "Code des impositions sur les biens et services",
    "code du cinema et de l'image animee": "Code du cinéma et de l'image animée",
    "code des communes": "Code des communes",
    "code general des collectivites territoriales": "Code général des collectivités territoriales",
    "code des procedures civiles d'execution": "Code des procédures civiles d'exécution",
    "code du domaine de l'etat": "Code du domaine de l'État",
    "code de la legion d'honneur, de la medaille militaire et de l'ordre national du merite": "Code de la Légion d'honneur, de la Médaille militaire et de l'ordre national du Mérite",
    "code des pensions militaires d'invalidite et des victimes de la guerre": "Code des pensions militaires d'invalidité et des victimes de la guerre",
    "code des pensions civiles et militaires de retraite": "Code des pensions civiles et militaires de retraite",
    "code de justice militaire": "Code de justice militaire",
    "code de la justice penale des mineurs": "Code de la justice pénale des mineurs",
    "code de deontologie": "Code de déontologie",
}

# Fusion des variantes / anciens / territoriaux vers un code parent (clé canonique).
CODE_ALIASES: Dict[str, str] = {
    "code de la famille et de l'aide sociale": "code de l'action sociale et des familles",
    "code de la famille et de l'aide sociale (ancien)": "code de l'action sociale et des familles",
    "code de la nationalite francaise": "code civil",
    "code du travail maritime": "code des transports",
    "code des ports maritimes": "code des transports",
    "code du domaine public fluvial et de la navigation interieure": "code general de la propriete des personnes publiques",
    "code de l'enseignement technique": "code de l'education",
    "code des debits de boissons et des mesures contre l'alcoolisme": "code de la sante publique",
    "code du vin": "code rural et de la peche maritime",
    "code des instruments monetaires et des medailles": "code monetaire et financier",
    "code disciplinaire et penal de la marine marchande": "code des transports",
    "code des caisses d'epargne": "code monetaire et financier",
    "code de l'industrie cinematographique": "code du cinema et de l'image animee",
    "code des pensions de retraite des marins francais du commerce, de peche ou de plaisance": "code des transports",
    "code du ble": "code rural et de la peche maritime",
    "code de l'office national interprofessionnel du ble": "code rural et de la peche maritime",
    "code des tribunaux administratifs et des cours administratives d'appel": "code de justice administrative",
    "code des marches publics": "code de la commande publique",
    "code rural": "code rural et de la peche maritime",
    "code rural (ancien)": "code rural et de la peche maritime",
    "code rural ancien": "code rural et de la peche maritime",
    # territoriaux -> parent métropolitain
    "code du travail applicable a mayotte": "code du travail",
    "code des communes de la nouvelle-caledonie": "code des communes",
    "code des douanes de mayotte": "code des douanes",
    "code forestier de mayotte": "code forestier",
    "code du domaine de l'etat et des collectivites publiques applicable a la collectivite territoriale de mayotte": "code du domaine de l'etat",
    "code de la consommation des boissons et des mesures contre l'alcoolisme applicable dans la collectivite territoriale de mayotte": "code de la sante publique",
    # variantes de libellé / ponctuation
    "code des postes et telecommunications": "code des postes et des communications electroniques",
    "code de sante publique": "code de la sante publique",
    "code des pensions militaires d'invalidite et des victimes de guerre": "code des pensions militaires d'invalidite et des victimes de la guerre",
}

# --------------------------------------------------------------------------- #
# Expressions régulières
# --------------------------------------------------------------------------- #
FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n\n", re.DOTALL)
TITLE_RE = re.compile(r"^# .*\n\n")
CODE_NAME_RE = re.compile(r"\bdu\s+(Code\b[^\n]*)", re.IGNORECASE)
WIKILINK_RE = re.compile(
    r"\[\[Article\s+([^\]]+?)\s+du\s+(Code\s+[^\]]+?)\]\]", re.IGNORECASE
)
STRUCT_RE = re.compile(
    r"^(Livre|Titre|Chapitre|Section|Sous[- ]section|Partie|Annexe)\b", re.IGNORECASE
)
ANNEXE_RE = re.compile(r",?\s*annexe\s+(?:i{1,3}|iv|[1-4])\b.*$", re.IGNORECASE)
PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
# Verbe d'un titre long : point de coupe pour le titre court.
TNC_CUT_RE = re.compile(
    r"\s+(?:portant|relatif|relative|relatives|relatifs|fixant|modifiant|autorisant|"
    r"instituant|pris|prise|tendant|definissant|completant|suspendant|abrogeant|"
    r"ratifiant|approuvant|validant)\b",
    re.IGNORECASE,
)

# Juridictions (formation) pour le dossier des procédures publiées.
JURIDICTION_TAGS = (
    "cass_soc", "cass_com", "cass_crim", "cass_civ1", "cass_civ2", "cass_civ3",
    "cass_civ", "cass_ap", "cass_mixte", "cass_chambres_reunies", "cass_avis",
    "cass_crd", "cass", "conseil_etat", "cour_appel", "cour_admin_appel",
    "tribunal_conflits", "tribunal_administratif", "conseil_constitutionnel",
    "conseil_prudhommes", "tribunal_commerce", "tribunal_judiciaire",
)


# --------------------------------------------------------------------------- #
# Normalisation / utilitaires
# --------------------------------------------------------------------------- #
def fold_accents_keepcase(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in normalized if not unicodedata.combining(c))


def fold_accents_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def canon_key(text: str) -> str:
    return " ".join(fold_accents_lower(text).split())


def slugify(name: str) -> str:
    s = fold_accents_keepcase(name)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    if len(s) > 80:
        digest = hashlib.md5((name or "").encode("utf-8")).hexdigest()[:8]
        s = s[:80].rstrip("_") + "_" + digest
    return s or "code"


def norm_num(num: str) -> str:
    s = fold_accents_lower(num)
    return s.replace(" ", "").replace(".", "").replace("\u00a0", "")


def safe_id(doc_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", doc_id or "doc")


def natural_key(value: str) -> List[Tuple[int, Any]]:
    key: List[Tuple[int, Any]] = []
    for part in re.split(r"(\d+)", value or ""):
        if part == "":
            continue
        if part.isdigit():
            key.append((1, int(part)))
        else:
            key.append((0, fold_accents_lower(part)))
    return key


def extract_code_name(titre: str) -> str:
    m = CODE_NAME_RE.search(titre or "")
    return " ".join(m.group(1).split()) if m else ""


def canon_code_key(name: str) -> str:
    """Normalise un nom de code extrait : accents, annexes, variantes, abréviations."""
    k = canon_key(name)
    k = re.sub(r",\s*(cgi|cgian?\w*|capp)\s*\.?\s*$", "", k)
    k = ANNEXE_RE.sub("", k)
    k = PAREN_RE.sub("", k)
    k = re.sub(r"[\s,.;:]+$", "", k)
    k = " ".join(k.split())
    if "deontologie" in k:
        return "code de deontologie"
    return CODE_ALIASES.get(k, k)


def resolve_code_key(name: str) -> Optional[str]:
    """Retourne la clé canonique si le nom correspond à un code officiel, sinon None."""
    k = canon_code_key(name)
    return k if k in CANON_CODES else None


def extract_body(markdown: str) -> str:
    if not markdown:
        return ""
    rest = FRONTMATTER_RE.sub("", markdown, count=1)
    rest = TITLE_RE.sub("", rest, count=1)
    rest = rest.split("\n\n## Références", 1)[0]
    return rest.strip()


def better(new: Tuple[str, str, str], cur: Tuple[str, str, str]) -> bool:
    _, n_date, n_stat = new
    _, c_date, c_stat = cur
    if n_stat == "vigueur" and c_stat != "vigueur":
        return True
    if c_stat == "vigueur" and n_stat != "vigueur":
        return False
    return (n_date or "") > (c_date or "")


def meta_line(record: Dict[str, Any]) -> str:
    parts: List[str] = []
    if record.get("statut"):
        parts.append(record["statut"])
    if record.get("date"):
        parts.append(record["date"])
    if record.get("date_fin"):
        parts.append("→ " + record["date_fin"])
    return " · ".join(parts)


def short_titre(titre: str) -> str:
    """Titre court d'un texte non codifié (coupe avant le verbe descriptif)."""
    t = (titre or "").strip()
    m = TNC_CUT_RE.search(t)
    if m:
        t = t[: m.start()].strip().rstrip(" ,")
    return t or (titre or "").strip()


def finance_domain(titre: str) -> Optional[str]:
    """Domaine « finances » / « securite_sociale » si c'est une loi de finances / LFSS.

    On examine le libellé du texte lui-même (conteneur) ou de son texte parent
    (article « Article X du … »), afin d'ignorer les décrets/arrêtés qui se
    contentent de référencer une loi de finances.
    """
    t = canon_key(titre)
    if t.startswith("article"):
        m = re.match(r"article\s+.+?\s+du\s+(.+)$", t)
        parent = m.group(1) if m else ""
    else:
        parent = t
    if not parent.startswith("loi"):
        return None
    if "financement de la securite sociale" in parent:
        return "securite_sociale"
    if "de finances" in parent:
        return "finances"
    return None


def finance_year(titre: str, date: str) -> str:
    """Année d'une loi de finances / LFSS : l'exercice (« pour 2024 ») sinon la date."""
    m = re.search(r"pour\s+(\d{4})", titre or "", re.IGNORECASE)
    if m:
        return m.group(1)
    return (date or "")[:4] or "sans_date"


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(record: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Retourne (catégorie, clé_de_code éventuelle)."""
    source = record.get("source", "")
    num = (record.get("num") or "").strip()
    titre = (record.get("titre") or "").strip()

    if source != "DILA":
        return "jp", None
    if num:
        code = extract_code_name(titre)
        if code:
            key = resolve_code_key(code)
            if key:
                return "code_article", key
        return "tnc_article", None
    if re.match(r"^(Code|CODE)\b", titre):
        return "code_container", None
    if STRUCT_RE.match(titre):
        return "struct", None
    return "tnc_container", None


def specialite(tags: List[str]) -> str:
    for tag in tags:
        if tag in MATIERE_FOLDER:
            return MATIERE_FOLDER[tag]
    return "General"


def root_matiere_tags(tags: List[str]) -> Set[str]:
    return {t for t in tags if t in RACINE_FOLDER or t in MATIERE_FOLDER}


def juridiction_tag(tags: List[str]) -> str:
    for tag in tags:
        if tag in JURIDICTION_TAGS:
            return tag
    return "Autres"


# --------------------------------------------------------------------------- #
# Lecture / écriture
# --------------------------------------------------------------------------- #
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


def atomic_write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, path)


def load_links() -> Dict[str, List[str]]:
    if not os.path.exists(LINK_PATH):
        return {}
    with open(LINK_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("cass_to_capp", {})


def purge_outputs(vault_dir: str) -> None:
    for name in OUTPUT_DIRS + LEGACY_DIRS:
        target = os.path.join(vault_dir, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)


def purge_spools() -> None:
    if os.path.isdir(SPOOL_ROOT):
        shutil.rmtree(SPOOL_ROOT, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Spool (persistance temporaire par groupe, mémoire constante)
# --------------------------------------------------------------------------- #
class SpoolWriter:
    def __init__(self, base_dir: str, max_open: int = 256) -> None:
        self.base_dir = base_dir
        self.max_open = max_open
        self.handles: Dict[str, Any] = {}

    def _handle(self, relpath: str) -> Any:
        handle = self.handles.pop(relpath, None)
        if handle is None:
            path = os.path.join(self.base_dir, relpath)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle = open(path, "a", encoding="utf-8")
        self.handles[relpath] = handle
        while len(self.handles) > self.max_open:
            oldest = next(iter(self.handles))
            self.handles.pop(oldest).close()
        return handle

    def append(self, relpath: str, obj: Dict[str, Any]) -> None:
        self._handle(relpath).write(json.dumps(obj, ensure_ascii=False) + "\n")

    def close(self) -> None:
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()


def read_spool(relpath: str) -> List[Dict[str, Any]]:
    path = os.path.join(SPOOL_ROOT, relpath)
    if not os.path.exists(path):
        return []
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def dedup_last(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        by_id[rec["id"]] = rec
    return list(by_id.values())


# --------------------------------------------------------------------------- #
# Assemblage des fichiers consolidés
# --------------------------------------------------------------------------- #
def build_code_frontmatter(slug: str, name: str, tags: Set[str]) -> str:
    tag_list = ["code", slug]
    tag_list += sorted(t for t in tags if t and t not in tag_list)
    return "\n".join([
        "---",
        f"id: {slug}",
        "type: code",
        "source: DILA",
        f"titre: {name}",
        "tags: " + json.dumps(tag_list, ensure_ascii=False),
        "---",
    ])


def rewrite_wikilinks(
    body: str,
    canon: str,
    local_best: Dict[str, Tuple[str, str, str]],
    global_best: Dict[str, Dict[str, Tuple[str, str, str]]],
    code_info: Dict[str, Dict[str, str]],
) -> str:
    def repl(match: "re.Match[str]") -> str:
        art = match.group(1).strip()
        code_name = match.group(2).strip()
        c = canon_key(code_name)
        n = norm_num(art)
        target: Optional[Tuple[str, str, str]] = None
        if c == canon:
            target = local_best.get(n)
        else:
            target = global_best.get(c, {}).get(n)
        if target is None:
            return match.group(0)
        label = f"Article {art} du {code_name}"
        if c == canon:
            return f"[[#{target[0]}|{label}]]"
        slug2 = code_info.get(c, {}).get("slug") or slugify(code_name)
        return f"[[{slug2}#{target[0]}|{label}]]"

    return WIKILINK_RE.sub(repl, body)


def build_code_markdown(
    slug: str,
    name: str,
    tags: Set[str],
    articles: List[Dict[str, Any]],
    global_best: Dict[str, Dict[str, Tuple[str, str, str]]],
    code_info: Dict[str, Dict[str, str]],
) -> str:
    canon = canon_key(name)
    articles.sort(key=lambda a: (natural_key(a.get("num", "")), a.get("date", "") or ""))

    local_best: Dict[str, Tuple[str, str, str]] = {}
    for art in articles:
        n = norm_num(art.get("num", ""))
        candidate = (art["id"], art.get("date", ""), art.get("statut", ""))
        if n not in local_best or better(candidate, local_best[n]):
            local_best[n] = candidate

    sommaire: List[str] = []
    sections: List[str] = []
    for art in articles:
        anchor = art["id"]
        num_disp = art.get("num", "")
        statut = art.get("statut", "") or "inconnu"
        body = rewrite_wikilinks(art.get("body", ""), canon, local_best, global_best, code_info)

        meta = [f"Statut : {statut}"]
        if art.get("date"):
            meta.append(art["date"])
        if art.get("date_fin"):
            meta.append("→ " + art["date_fin"])

        sommaire.append(f"- [[#{anchor}|Article {num_disp}]] ({statut})")
        sections.append(
            f"## Article {num_disp} {{#{anchor}}}\n\n"
            f"> " + " · ".join(meta) + "\n\n" + body
        )

    frontmatter = build_code_frontmatter(slug, name, tags)
    toc = "\n".join(sommaire) if sommaire else "- *(aucun article)*"
    body_md = "\n\n---\n\n".join(sections)
    return f"{frontmatter}\n\n# {name}\n\n## Sommaire\n\n{toc}\n\n---\n\n{body_md}\n"


def _render_section(record: Dict[str, Any], level: int, label: str) -> Tuple[str, str]:
    anchor = safe_id(record["id"])
    heading = f"{'#' * level} {label} {{#{anchor}}}"
    parts: List[str] = [heading]
    meta = meta_line(record)
    if meta:
        parts.append("> " + meta)
    body = (record.get("body") or "").strip()
    if body:
        parts.append("")
        parts.append(body)
    return anchor, "\n\n".join(parts)


def _toc_label(label: str, limit: int = 90) -> str:
    return label if len(label) <= limit else label[: limit - 1].rstrip() + "…"


def build_lois_frontmatter(annee: str, domaine: Optional[str]) -> str:
    tags = ["lois_reglements", str(annee)]
    if domaine:
        tags.append(domaine)
    lines = [
        "---",
        "type: lois_reglements",
        f"annee: {annee}",
    ]
    if domaine:
        lines.append(f"domaine: {domaine}")
    lines.append("tags: " + json.dumps(tags, ensure_ascii=False))
    lines.append("---")
    return "\n".join(lines)


def build_tnc_markdown(annee: str, records: List[Dict[str, Any]], domaine: Optional[str]) -> str:
    textes = [r for r in records if r.get("role") != "article"]
    articles = [r for r in records if r.get("role") == "article"]

    textes.sort(key=lambda r: ((r.get("date") or ""), canon_key(r.get("titre", ""))))
    articles.sort(key=lambda r: (
        canon_key(r.get("parent", "")),
        natural_key(r.get("num", "")),
        r.get("date") or "",
    ))

    sommaire: List[str] = []
    sections: List[str] = []

    if textes:
        sommaire.append("**Textes**")
        rendered = []
        for r in textes:
            short = short_titre(r.get("titre", ""))
            full = (r.get("titre") or "").strip()
            anchor, sec = _render_section(r, 3, short)
            if full and full != short:
                sec += "\n\n> " + full.replace("\n", " ")
            rendered.append(sec)
            sommaire.append(f"- [[#{anchor}|{_toc_label(short)}]]")
        sections.append("## Textes\n\n" + "\n\n---\n\n".join(rendered))

    if articles:
        sommaire.append("**Articles**")
        rendered = []
        for r in articles:
            label = (r.get("titre") or "").strip() or f"Article {r.get('num', '')}"
            anchor, sec = _render_section(r, 3, label)
            rendered.append(sec)
            sommaire.append(f"- [[#{anchor}|{_toc_label(label)}]]")
        sections.append("## Articles\n\n" + "\n\n---\n\n".join(rendered))

    frontmatter = build_lois_frontmatter(annee, domaine)
    titre = f"Lois — {annee}" + (f" ({domaine})" if domaine else "")
    toc = "\n".join(sommaire) if sommaire else "- *(vide)*"
    body_md = "\n\n---\n\n".join(sections)
    return f"{frontmatter}\n\n# {titre}\n\n## Sommaire\n\n{toc}\n\n---\n\n{body_md}\n"


def build_jp_frontmatter(annee: str, matiere: str) -> str:
    return "\n".join([
        "---",
        "type: jurisprudence",
        f"annee: {annee}",
        f"matiere: {matiere}",
        "tags: " + json.dumps(["jurisprudence", slugify(matiere), str(annee)], ensure_ascii=False),
        "---",
    ])


def build_jp_markdown(annee: str, matiere: str, records: List[Dict[str, Any]]) -> str:
    records.sort(key=lambda r: ((r.get("date") or ""), canon_key(r.get("titre", ""))))

    sommaire: List[str] = []
    sections: List[str] = []
    for r in records:
        label = (r.get("titre") or "").strip() or r["id"]
        anchor, sec = _render_section(r, 3, label)
        sommaire.append(f"- [[#{anchor}|{_toc_label(label)}]]")
        sections.append(sec)

    frontmatter = build_jp_frontmatter(annee, matiere)
    toc = "\n".join(sommaire) if sommaire else "- *(vide)*"
    body_md = "\n\n---\n\n".join(sections)
    return f"{frontmatter}\n\n# {matiere} — {annee}\n\n## Sommaire\n\n{toc}\n\n---\n\n{body_md}\n"


def build_procedure_frontmatter(pourvoi: str, juridiction: str) -> str:
    return "\n".join([
        "---",
        "type: procedure",
        f"pourvoi: {pourvoi}",
        f"juridiction: {juridiction}",
        "tags: " + json.dumps(["jurisprudence", "procedure", slugify(juridiction)], ensure_ascii=False),
        "---",
    ])


def build_procedure_markdown(
    pourvoi: str, juridiction: str, records: List[Dict[str, Any]]
) -> str:
    # du plus récent au plus ancien
    records.sort(key=lambda r: (r.get("date") or ""), reverse=True)

    sommaire: List[str] = []
    sections: List[str] = []
    for r in records:
        label = (r.get("titre") or "").strip() or r["id"]
        anchor, sec = _render_section(r, 3, label)
        sommaire.append(f"- [[#{anchor}|{_toc_label(label)}]]")
        sections.append(sec)

    frontmatter = build_procedure_frontmatter(pourvoi, juridiction)
    toc = "\n".join(sommaire) if sommaire else "- *(vide)*"
    body_md = "\n\n---\n\n".join(sections)
    return f"{frontmatter}\n\n# {pourvoi}\n\n## Procédure\n\n{toc}\n\n---\n\n{body_md}\n"


# --------------------------------------------------------------------------- #
# Mode principal (rebuild complet)
# --------------------------------------------------------------------------- #
def run_full(
    jsonl_path: str,
    vault_dir: str,
    source_filter: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    purge_outputs(vault_dir)
    purge_spools()

    cass_to_capp = load_links()
    linked_capp: Set[str] = {cid for ids in cass_to_capp.values() for cid in ids}

    code_info: Dict[str, Dict[str, Any]] = {}
    global_best: Dict[str, Dict[str, Tuple[str, str, str]]] = {}
    tnc_groups: Set[Tuple[str, Optional[str]]] = set()   # (annee, domaine)
    ined_groups: Set[Tuple[str, str]] = set()            # (matiere, annee)
    pub_roots: Set[str] = set()

    spool = SpoolWriter(SPOOL_ROOT)
    stats: Dict[str, int] = defaultdict(int)
    processed = 0

    try:
        for record in iter_jsonl(jsonl_path):
            source = record.get("source", "")
            if source_filter and source_filter.lower() != source.lower():
                continue
            if limit is not None and processed >= limit:
                break
            processed += 1

            category, code_key = classify(record)
            stats[category] += 1
            tags = record.get("tags", [])
            annee = (record.get("date") or "")[:4] or "sans_date"

            if category == "code_article":
                info = code_info.setdefault(
                    code_key,
                    {"name": CANON_CODES[code_key], "slug": slugify(CANON_CODES[code_key]),
                     "tags": set()},
                )
                info["tags"].update(root_matiere_tags(tags))
                n = norm_num(record.get("num", ""))
                candidate = (record["id"], record.get("date", ""), record.get("statut", ""))
                cur = global_best.setdefault(code_key, {}).get(n)
                if cur is None or better(candidate, cur):
                    global_best[code_key][n] = candidate
                spool.append(
                    f"codes/{info['slug']}.jsonl",
                    {
                        "id": record["id"],
                        "num": (record.get("num") or "").strip(),
                        "date": record.get("date", ""),
                        "date_fin": record.get("date_fin", ""),
                        "statut": record.get("statut", ""),
                        "body": extract_body(record.get("markdown", "")),
                    },
                )
            elif category == "tnc_container":
                titre = (record.get("titre") or "").strip()
                domaine = finance_domain(titre)
                grp_annee = finance_year(titre, record.get("date", "")) if domaine else annee
                tnc_groups.add((grp_annee, domaine))
                spool.append(
                    f"tnc/{grp_annee}__{domaine or 'gen'}.jsonl",
                    {
                        "id": record["id"],
                        "role": "texte",
                        "date": record.get("date", ""),
                        "date_fin": record.get("date_fin", ""),
                        "statut": record.get("statut", ""),
                        "titre": titre,
                        "body": extract_body(record.get("markdown", "")),
                    },
                )
            elif category == "tnc_article":
                titre = (record.get("titre") or "").strip()
                domaine = finance_domain(titre)
                grp_annee = finance_year(titre, record.get("date", "")) if domaine else annee
                tnc_groups.add((grp_annee, domaine))
                spool.append(
                    f"tnc/{grp_annee}__{domaine or 'gen'}.jsonl",
                    {
                        "id": record["id"],
                        "role": "article",
                        "date": record.get("date", ""),
                        "date_fin": record.get("date_fin", ""),
                        "statut": record.get("statut", ""),
                        "num": (record.get("num") or "").strip(),
                        "titre": titre,
                        "parent": extract_parent(titre),
                        "body": extract_body(record.get("markdown", "")),
                    },
                )
            elif category == "jp":
                if "arret_de_principe" in tags:
                    jur = juridiction_tag(tags)
                    pub_roots.add(safe_id(record["id"]))
                    spool.append(
                        f"pub/{safe_id(record['id'])}.jsonl",
                        {
                            "id": record["id"],
                            "date": record.get("date", ""),
                            "date_fin": record.get("date_fin", ""),
                            "statut": record.get("statut", ""),
                            "titre": (record.get("titre") or "").strip(),
                            "juridiction": jur,
                            "body": extract_body(record.get("markdown", "")),
                        },
                    )
                elif record["id"] in linked_capp:
                    spool.append(
                        f"linked/{safe_id(record['id'])}.jsonl",
                        {
                            "id": record["id"],
                            "date": record.get("date", ""),
                            "date_fin": record.get("date_fin", ""),
                            "statut": record.get("statut", ""),
                            "titre": (record.get("titre") or "").strip(),
                            "body": extract_body(record.get("markdown", "")),
                        },
                    )
                else:
                    matiere = specialite(tags)
                    ined_groups.add((matiere, annee))
                    spool.append(
                        f"ined/{matiere}/{annee}.jsonl",
                        {
                            "id": record["id"],
                            "date": record.get("date", ""),
                            "date_fin": record.get("date_fin", ""),
                            "statut": record.get("statut", ""),
                            "titre": (record.get("titre") or "").strip(),
                            "body": extract_body(record.get("markdown", "")),
                        },
                    )
            # code_container / struct : ignorés.

            if processed % 100000 == 0:
                print(f"[consolidate] {processed} enregistrements lus…", file=sys.stderr)
    finally:
        spool.close()

    # Phase 2 : assemblage.
    for code_key, info in code_info.items():
        articles = dedup_last(read_spool(f"codes/{info['slug']}.jsonl"))
        if not articles:
            continue
        md = build_code_markdown(
            info["slug"], info["name"], set(info["tags"]), articles, global_best, code_info
        )
        atomic_write(posixpath.join(vault_dir, "Codes", info["slug"] + ".md"), md)

    for annee, domaine in tnc_groups:
        records = dedup_last(read_spool(f"tnc/{annee}__{domaine or 'gen'}.jsonl"))
        if not records:
            continue
        md = build_tnc_markdown(annee, records, domaine)
        subdir = {
            "finances": "Finances",
            "securite_sociale": "Securite_Sociale",
        }.get(domaine, "")
        if subdir:
            path = posixpath.join(vault_dir, "Lois", subdir, annee + ".md")
        else:
            path = posixpath.join(vault_dir, "Lois", annee + ".md")
        atomic_write(path, md)

    for matiere, annee in ined_groups:
        records = dedup_last(read_spool(f"ined/{matiere}/{annee}.jsonl"))
        if not records:
            continue
        md = build_jp_markdown(annee, matiere, records)
        atomic_write(posixpath.join(vault_dir, "JP", "Inedites", matiere, annee + ".md"), md)

    for root_key in pub_roots:
        root = read_spool(f"pub/{root_key}.jsonl")
        if not root:
            continue
        root = dedup_last(root)[0]
        linked: List[Dict[str, Any]] = []
        for cid in cass_to_capp.get(root["id"], []):
            linked.extend(dedup_last(read_spool(f"linked/{safe_id(cid)}.jsonl")))
        records = [root] + linked
        md = build_procedure_markdown(root["id"], root.get("juridiction", "Autres"), records)
        atomic_write(
            posixpath.join(vault_dir, "JP", "Publiees", root.get("juridiction", "Autres"),
                           safe_id(root["id"]) + ".md"),
            md,
        )

    stats["codes"] = len(code_info)
    stats["lois_files"] = len(tnc_groups)
    stats["ined_files"] = len(ined_groups)
    stats["procedure_files"] = len(pub_roots)
    stats["records"] = processed
    return dict(stats)


def extract_parent(titre: str) -> str:
    m = re.match(r"^Article\s+(.+?)\s+du\s+(.+)$", (titre or "").strip(), re.IGNORECASE)
    return " ".join(m.group(2).split()) if m else (titre or "")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidation du Vault Obsidian.")
    parser.add_argument("--full", action="store_true",
                        help="Reconstruction complète (seul mode disponible).")
    parser.add_argument("--jsonl", default=config.CORPUS_GLOBAL_JSONL)
    parser.add_argument("--vault", default=config.VAULT_OBSIDIAN_DIR)
    parser.add_argument("--filter", default=None, help="Ne traiter que cette source (ex. DILA).")
    parser.add_argument("--limit", type=int, default=None, help="Nb max d'enregistrements (test).")
    args = parser.parse_args()

    result = run_full(args.jsonl, args.vault, args.filter, args.limit)
    print(f"[consolidate] terminé : {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)


if __name__ == "__main__":
    main()
