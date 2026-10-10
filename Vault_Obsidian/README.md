# `Vault_Obsidian/` — corpus navigable (sortie 2)

Fichiers Markdown consolidés, générés par `rag_droit/consolidate_vault.py --full`
depuis `corpus_global.jsonl` (source de vérité) et l'index
`liens_jurisprudence.json` produit par `rag_droit/link_jurisprudence.py`.

```
Codes/Code_<nom>.md                        # ~60 codes officiels consolidés (1 fichier/code)
Lois/{YYYY}.md                             # textes + articles non codifiés (1 fichier/année)
Lois/Finances/{YYYY}.md                    # lois de finances (+ rectificatives)
Lois/Securite_Sociale/{YYYY}.md            # lois de financement de la sécurité sociale
JP/Inedites/{Matiere}/{YYYY}.md            # jurisprudence inédite (par année + matière)
JP/Publiees/{Juridiction}/{Pourvoi}.md     # 1 procédure = 1 affaire (CASS + arrêt(s) CAPP)
```

Chaque fichier contient :

- un **frontmatter YAML** (`type`, `annee`, `matiere`/`domaine`/`juridiction`, `tags`) ;
- un **titre** (`# Code civil`, `# Lois — 2024`, `# 07-21634`) ;
- un **sommaire** de liens `[[#ancre|…]]` (libellés courts) ;
- les **sections** (articles, textes, décisions) avec ancre, ligne de méta
  (`> Statut · date → date_fin`) et texte intégral.

## Règles de consolidation

- **Codes** : registre canonique des codes officiels ; annexes (`CGI, annexe II`),
  variantes (`(ancien)`, `(partie législative)`), territoriaux (Mayotte, …) et
  anciens sont fusionnés dans le code parent. Tout autre nom reclassé en texte
  non codifié.
- **Lois/règlements** : un fichier par année (sections « Textes » + « Articles »),
  titres courts (« Décret n°2007-1136 du 25 juillet 2007 ») avec titre complet en
  sous-titre. Les lois de finances et LFSS sont isolées par domaine + exercice.
- **Jurisprudence publiée** : une « procédure » = une affaire (décision de la Cour
  de cassation + arrêt(s) d'appel attaqué(s)), du plus récent au plus ancien. Le
  lien CASS↔CAPP est **best-effort** (cour + formation + date, tous candidats
  conservés).

## Mise à jour

```bash
# depuis la racine du projet
venv/bin/python -m rag_droit.link_jurisprudence --full
venv/bin/python -m rag_droit.consolidate_vault --full
```

Le Vault est **régénéré intégralement** à chaque mise à jour (pas d'état
incrémental). La recherche (RAG) se fait par **contenu** via Qdrant (`ingest.py`).
