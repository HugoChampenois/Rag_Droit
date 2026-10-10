"""Mise à jour quotidienne des archives juridiques DILA (open data).

Rôle
----
Télécharge les fichiers de mise à jour incrémentiels (deltas) publiés
quotidiennement par la DILA sur https://echanges.dila.gouv.fr/OPENDATA/<BASE>/,
pour les bases LEGI, CASS, CAPP, JADE et CONSTIT.

Ce programme ne fait QUE télécharger les archives `.tar.gz` de mise à jour
dans un dossier local. Il ne modifie, n'extrait ni n'indexe rien : l'intégration
au pipeline RAG est une étape distincte, non gérée ici.

Isolation stricte : aucune écriture hors de son propre dossier.

Usage
-----
    python3 maj.py                 # met à jour les 5 bases
    python3 maj.py --base legi     # met à jour une seule base
    python3 maj.py --dry-run       # affiche ce qui serait téléchargé, sans rien faire

Cron (mise à jour quotidienne, vers 23h30 après la publication DILA ~21h) :
    30 23 * * * /usr/bin/python3 /chemin/vers/maj/maj.py >> /chemin/vers/maj/logs/cron.out 2>&1

États et journal
----------------
    state/<base>.last   curseur : timestamp du dernier fichier traité (reprise)
    logs/maj.log        journal d'historique consulté pour se guider
    logs/cron.out       sortie brute du cron (capture de secours)

Principe de synchronisation
---------------------------
Chaque fichier delta `<BASE>_YYYYMMDD-HHMMSS.tar.gz` contient les modifications
d'une journée (au même format XML/DTD que les archives globales). Ils sont
incrémentiels : il faut les appliquer dans l'ordre chronologique. Le programme
conserve un curseur par base et ne télécharge que les fichiers strictement
plus récents, ce qui assure le rattrapage automatique après une interruption.

Baseline initiale : 20250713-140000 (date des archives globales
`Freemium_*_global_20250713-140000.tar.gz` déjà téléchargées).
"""

from __future__ import annotations

import argparse
import os
import re
import tarfile
import urllib.request
from datetime import datetime

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

BASE_DIR = os.path.join(os.environ.get("RAG_BASE_DIR", "/opt/rag"), "maj")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_DIR = os.path.join(BASE_DIR, "state")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "maj.log")

# base -> répertoire OPENDATA (le nom de base est en minuscules, l'URL en majuscules).
BASES = {
    "legi": "https://echanges.dila.gouv.fr/OPENDATA/LEGI/",
    "cass": "https://echanges.dila.gouv.fr/OPENDATA/CASS/",
    "capp": "https://echanges.dila.gouv.fr/OPENDATA/CAPP/",
    "jade": "https://echanges.dila.gouv.fr/OPENDATA/JADE/",
    "constit": "https://echanges.dila.gouv.fr/OPENDATA/CONSTIT/",
}

# Curseur initial si aucun état : date des archives globales déjà possédées.
BASELINE = "20250713-140000"

# Seuil (en jours) au-delà duquel une alerte de retard est journalisée.
LATE_DAYS = 3

USER_AGENT = "rag-maj/1.0 (mise a jour quotidienne des archives DILA)"

# Nom des fichiers delta : <BASE>_YYYYMMDD-HHMMSS.tar.gz (exclut les Freemium_*_global_*).
DELTA_RE = re.compile(r"\b([A-Z]+)_(\d{8}-\d{6})\.tar\.gz\b")

_TS_FMT = "%Y%m%d-%H%M%S"


# --------------------------------------------------------------------------- #
# Utilitaires (journal, état, timestamps)
# --------------------------------------------------------------------------- #

def ensure_dirs() -> None:
    for directory in (DATA_DIR, STATE_DIR, LOG_DIR):
        os.makedirs(directory, exist_ok=True)


def log(message: str) -> None:
    """Écrit une ligne horodatée dans le journal et sur la sortie standard."""
    line = f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def ts_to_dt(ts: str) -> datetime:
    """Convertit un timestamp 'YYYYMMDD-HHMMSS' en objet datetime."""
    return datetime.strptime(ts, _TS_FMT)


def read_cursor(state_path: str) -> str:
    """Lit le curseur d'une base ; renvoie la baseline si absent ou vide."""
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as handle:
            content = handle.read().strip()
            if content:
                return content
    return BASELINE


def write_cursor(state_path: str, ts: str) -> None:
    """Persiste le curseur d'une base."""
    with open(state_path, "w", encoding="utf-8") as handle:
        handle.write(ts + "\n")


# --------------------------------------------------------------------------- #
# Accès réseau
# --------------------------------------------------------------------------- #

def fetch_index(url: str) -> str | None:
    """Récupère l'index HTML du répertoire OPENDATA (None si échec)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - on journalise et on abandonne la base
        log(f"  ERREUR de connexion à {url} : {exc}")
        return None


def list_deltas(base: str, html: str) -> list[tuple[str, str]]:
    """Extrait les fichiers delta de la base, triés par horodatage croissant.

    Renvoie une liste de tuples (timestamp, nom_de_fichier). Le nom est
    dédupliqué (l'index HTML peut faire apparaître le fichier deux fois).
    """
    found: dict[str, str] = {}
    for match in DELTA_RE.finditer(html):
        name_upper, ts = match.group(1), match.group(2)
        if name_upper.lower() != base:
            continue
        found.setdefault(ts, f"{name_upper}_{ts}.tar.gz")
    return [(ts, found[ts]) for ts in sorted(found)]


def is_valid_targz(path: str) -> bool:
    """Vérifie qu'un fichier est une archive tar.gz lisible (non tronquée)."""
    try:
        return tarfile.is_tarfile(path)
    except Exception:  # noqa: BLE001
        return False


def download(url: str, dest: str) -> bool:
    """Télécharge `url` vers `dest` de façon atomique (via un fichier .part)."""
    tmp = dest + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    handle.write(chunk)
        os.replace(tmp, dest)
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"  ERREUR de téléchargement {url} : {exc}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


# --------------------------------------------------------------------------- #
# Contrôle de retard
# --------------------------------------------------------------------------- #

def check_lateness(base: str, server_ts: str, cursor_ts: str) -> None:
    """Journalise un avertissement si la base est en retard.

    Deux contrôles :
      1. la DILA n'a rien publié depuis plus de LATE_DAYS jours ;
      2. le curseur local date de plus de LATE_DAYS jours.
    """
    now = datetime.now()
    server_age = (now - ts_to_dt(server_ts)).days
    cursor_age = (now - ts_to_dt(cursor_ts)).days
    if server_age > LATE_DAYS:
        log(f"[{base}] WARN : aucun nouveau fichier DILA depuis {server_ts} "
            f"(> {LATE_DAYS} jours)")
    if cursor_age > LATE_DAYS:
        log(f"[{base}] WARN : curseur local en retard ({cursor_ts}, "
            f"écart {cursor_age} jours)")


# --------------------------------------------------------------------------- #
# Traitement d'une base
# --------------------------------------------------------------------------- #

def process_base(base: str, dry_run: bool) -> None:
    """Met à jour une base : liste, compare au curseur, télécharge, journalise."""
    url = BASES[base]
    data_dir = os.path.join(DATA_DIR, base)
    state_path = os.path.join(STATE_DIR, f"{base}.last")
    os.makedirs(data_dir, exist_ok=True)

    cursor = read_cursor(state_path)

    html = fetch_index(url)
    if html is None:
        return

    files = list_deltas(base, html)
    if not files:
        log(f"[{base}] aucun delta trouvé sur {url}")
        return

    latest_server_ts = files[-1][0]
    to_fetch = [(ts, name) for ts, name in files if ts > cursor]
    log(f"[{base}] curseur={cursor} | {len(files)} delta(s) sur le serveur | "
        f"{len(to_fetch)} à télécharger")

    if dry_run:
        for _, name in to_fetch:
            log(f"[{base}] DRY-RUN téléchargerait {name}")
        check_lateness(base, latest_server_ts, cursor)
        return

    downloaded = 0
    skipped = 0
    failed = 0
    for ts, name in to_fetch:
        dest = os.path.join(data_dir, name)
        if os.path.exists(dest) and is_valid_targz(dest):
            skipped += 1
            cursor = ts
            continue
        if download(url + name, dest) and is_valid_targz(dest):
            downloaded += 1
            cursor = ts
            log(f"[{base}] OK {name}")
        else:
            failed += 1
            log(f"[{base}] ERR {name} (arrêt : on n'avance pas le curseur au-delà d'un trou)")
            break

    write_cursor(state_path, cursor)
    log(f"[{base}] fin : téléchargés={downloaded} ignorés={skipped} échecs={failed}")
    check_lateness(base, latest_server_ts, cursor)


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mise à jour quotidienne des archives DILA (LEGI/CASS/CAPP/JADE/CONSTIT)."
    )
    parser.add_argument("--base", choices=list(BASES), default=None,
                        help="Traiter une seule base (défaut : toutes).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afficher ce qui serait téléchargé sans rien faire.")
    args = parser.parse_args()

    ensure_dirs()
    bases = [args.base] if args.base else list(BASES)

    log(f"=== début de mise à jour ({', '.join(bases)}) ===")
    for base in bases:
        try:
            process_base(base, args.dry_run)
        except Exception as exc:  # noqa: BLE001 - une base en échec ne bloque pas les autres
            log(f"[{base}] ERREUR inattendue : {exc}")
    log("=== fin de mise à jour ===")


if __name__ == "__main__":
    main()
