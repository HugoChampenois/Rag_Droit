# `archives_brutes/` — archives sources (`.tar.gz` uniquement)

Ce dossier **ne contient que les archives `.tar.gz`** de la DILA et ne doit
**jamais être lu** par le pipeline.

- **Archives globales** (baseline 2025-07-13) : `Freemium_*_global_20250713-140000.tar.gz`
  (LEGI, CASS, CAPP, CONSTIT, JADE).
- **Deltas quotidiens** : déposés ici ou dans `maj/data/` par `maj.py`
  (`LEGI_YYYYMMDD-HHMMSS.tar.gz`, etc.).

Les fichiers **décompressés** vivent dans `../sources_xml/` (voir son README).
Conserver les `.tar.gz` permet de **régénérer** le corpus à tout moment sans
re-télécharger.
