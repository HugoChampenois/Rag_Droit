# Mise à jour quotidienne des archives DILA — `maj.py`

Ce dossier contient un programme autonome de **mise à jour quotidienne** des
archives juridiques en open data de la **DILA** (Direction de l'information
légale et administrative). Il est volontairement **isolé** du pipeline RAG : il
ne fait que **collecter** les fichiers de mise à jour, sans toucher au reste du
système.

## Fonctionnement

### Structure du dossier

```
maj/
├── maj.py          # le programme
├── README.md       # ce document
├── data/           # deltas téléchargés, un sous-dossier par base
│   ├── legi/
│   ├── cass/
│   ├── capp/
│   ├── jade/
│   └── constit/
├── state/          # curseur de progression (un fichier .last par base)
│   ├── legi.last
│   ├── cass.last
│   └── ...
└── logs/
    ├── maj.log     # journal consulté par le programme pour se guider
    └── cron.out    # sortie brute du cron (capture de secours)
```

### Principe de synchronisation

La DILA publie, en plus des archives globales « Freemium », un fichier de
mise à jour **incrémentiel** par jour, nommé `<BASE>_YYYYMMDD-HHMMSS.tar.gz`
(ex. `LEGI_20260926-210736.tar.gz`). Chaque fichier contient les modifications
d'une seule journée, dans le même format XML/DTD que les archives globales.

Ces fichiers étant incrémentiels, ils doivent être **rejoués dans l'ordre
chronologique**. Le programme conserve donc, pour chaque base, un **curseur**
(timestamp du dernier fichier traité) et ne télécharge que les fichiers
strictement plus récents.

### Sources

- `https://echanges.dila.gouv.fr/OPENDATA/CAPP/`
- `https://echanges.dila.gouv.fr/OPENDATA/CASS/`
- `https://echanges.dila.gouv.fr/OPENDATA/JADE/`
- `https://echanges.dila.gouv.fr/OPENDATA/LEGI/`
- `https://echanges.dila.gouv.fr/OPENDATA/CONSTIT/`

### Algorithme (à chaque exécution, pour chaque base)

1. Récupérer l'index HTTP du répertoire OPENDATA.
2. Extraire les fichiers delta (`<BASE>_YYYYMMDD-HHMMSS.tar.gz`), en ignorant
   les archives globales `Freemium_*`.
3. Trier les fichiers par **horodatage complet** (une même date peut comporter
   deux fichiers publiés à des heures différentes).
4. Lire le curseur `state/<base>.last` (baseline `20250713-140000` au premier
   lancement).
5. Télécharger dans l'ordre les fichiers postérieurs au curseur, avec
   vérification d'intégrité (`tarfile.is_tarfile`) et écriture atomique
   (fichier temporaire `.part` puis renommage).
6. Avancer le curseur **uniquement après** un téléchargement validé. En cas
   d'échec, l'exécution s'arrête pour cette base afin de ne pas créer de
   « trou » dans la séquence (le prochain lancement reprendra au même endroit).
7. Journaliser chaque action dans `logs/maj.log`.

### Contrôle de retard

À la fin du traitement de chaque base, deux vérifications sont effectuées et
consignées en `WARN` dans le journal si l'écart dépasse le seuil
(`LATE_DAYS = 3` jours) :

1. **Serveur muet** : la DILA n'a rien publié depuis plus de 3 jours
   (possible panne côté DILA).
2. **Curseur local en retard** : notre dernier fichier traité date de plus de
   3 jours (rattrapage nécessaire).

### Reprise après interruption

Le programme est **idempotent et reprenable** : le curseur et le journal lui
permettent de repartir exactement là où il s'était arrêté, sans re-télécharger
ni sauter de fichier.

## Utilisation

```bash
# Mettre à jour les 5 bases
python3 maj/maj.py

# Mettre à jour une seule base
python3 maj/maj.py --base legi

# Aperçu sans rien télécharger
python3 maj/maj.py --dry-run
```

### Mise en place du cron (mise à jour quotidienne)

La DILA publie ses mises à jour en soirée (~21 h). Un lancement vers 23 h 30 est
adapté :

```
30 23 * * * /usr/bin/python3 /chemin/vers/Rag_Droit/maj/maj.py >> /chemin/vers/Rag_Droit/maj/logs/cron.out 2>&1
```

## Limites connues

- Le programme **télécharge seulement** ; il n'extrait pas les archives et
  n'alimente pas le pipeline RAG. L'intégration des nouveaux fichiers dans le
  corpus (extraction → parsing → embedding) reste une étape séparée.
- Le pipeline RAG étant idempotent par identifiant de document, un document
  **modifié** (même identifiant, nouvelle version) n'est pas automatiquement
  ré-embeddé. Ce programme collecte bien la nouvelle version, mais la
  ré-ingestion des modifications doit être traitée à part.
- La base **JADE** ne couvre que les décisions « présentant un intérêt
  jurisprudentiel » (publiées). La jurisprudence administrative **exhaustive**
  (y compris les inédits) provient d'une autre source
  (`opendata.justice-administrative.fr`) et n'est pas gérée ici.
