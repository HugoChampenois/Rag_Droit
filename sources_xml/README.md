# `sources_xml/` — XML décompressés (source du pipeline)

C'est **ici** que le pipeline (`main.py`) lit les documents. Contient les
archives globales décompressées **et** les deltas intégrés.

```
sources_xml/
├── legi/       # législation (articles, textes, sections)
├── cass/       # Cour de cassation
├── capp/       # cours d'appel
├── constit/    # Conseil constitutionnel
├── jade/       # jurisprudence administrative (CE, CAA, TA)
└── deltas/     # mises à jour incrémentielles, 1 sous-dossier <ts>/ par delta
```

## Règles de traitement

- `main.py` parcourt `legi/`, `cass/`, `capp/`, `constit/`, `jade/` et **ignore**
  `deltas/` ainsi que `legi/…/eli/` (index sans texte).
- Les fichiers de `deltas/<ts>/` sont intégrés par
  `rag_droit/integrate_delta.py` (upsert par id), **pas** par `main.py`.
- Ne **jamais** supprimer un fichier ici : les versions abrogées sont des
  marqueurs de l'évolution du droit.
