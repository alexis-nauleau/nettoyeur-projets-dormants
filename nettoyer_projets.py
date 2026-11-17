

import argparse                  # pour lire les options tapées dans le terminal
import os                        # pour parcourir les dossiers rapidement
import shutil                    # pour supprimer un dossier entier
import stat                      # pour rendre un fichier modifiable
import sys
import time
from datetime import datetime
from pathlib import Path


DOSSIER_A_SUPPRIMER = "node_modules"
JOURS_AVANT_DORMANT = 60
FICHIER_PROJET = "package.json"
DOSSIERS_IGNORES = {DOSSIER_A_SUPPRIMER, ".git", ".next", ".nuxt", ".venv", "venv",
                    "dist", "build", "__pycache__", ".turbo", ".cache"}
FICHIERS_LOCK = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock")

SECONDES_PAR_JOUR = 86400


def lisible(octets):
    """4300000 -> '4.1 Mo'"""
    for unite in ("o", "Ko", "Mo", "Go"):
        if octets < 1024:
            return f"{octets:.0f} {unite}" if unite == "o" else f"{octets:.1f} {unite}"
        octets /= 1024
    return f"{octets:.1f} To"


def derniere_activite(projet):
    """Renvoie la date (en secondes) du fichier le plus récemment modifié du projet.
    On saute les dossiers de DOSSIERS_IGNORES."""
    plus_recent = 0.0
    a_visiter = [str(projet)]            # liste de dossiers à explorer
    while a_visiter:
        courant = a_visiter.pop()
        try:
            with os.scandir(courant) as entrees:
                for entree in entrees:
                    if entree.is_dir(follow_symlinks=False):
                        if entree.name not in DOSSIERS_IGNORES:
                            a_visiter.append(entree.path)
                    else:
                        plus_recent = max(plus_recent, entree.stat(follow_symlinks=False).st_mtime)
        except OSError:
            pass                          # dossier illisible : on l'ignore
    if plus_recent == 0.0:                # projet sans fichier : on prend la date du dossier
        plus_recent = Path(projet).stat().st_mtime
    return plus_recent


def taille_dossier(dossier):
    """Additionne la taille de tous les fichiers d'un dossier (sans suivre les liens)."""
    total = 0
    a_visiter = [str(dossier)]
    while a_visiter:
        courant = a_visiter.pop()
        try:
            with os.scandir(courant) as entrees:
                for entree in entrees:
                    if entree.is_symlink():
                        continue
                    if entree.is_dir(follow_symlinks=False):
                        a_visiter.append(entree.path)
                    else:
                        total += entree.stat(follow_symlinks=False).st_size
        except OSError:
            pass
    return total


def trouver_projets(racine, jours):
    """Renvoie (liste des projets dormants avec leur dossier lourd, nombre de projets analysés)."""
    limite = time.time() - jours * SECONDES_PAR_JOUR     # tout ce qui est plus vieux = dormant
    dormants = []
    analyses = 0

    for dossier in sorted(racine.iterdir()):
        # Un "projet" = un sous-dossier direct qui contient FICHIER_PROJET
        if not dossier.is_dir() or not (dossier / FICHIER_PROJET).is_file():
            continue
        analyses += 1

        cible = dossier / DOSSIER_A_SUPPRIMER            # ex : F:\Projets\mon-site\node_modules
        if not cible.is_dir():
            continue                                     # rien à libérer ici

        derniere = derniere_activite(dossier)
        if derniere >= limite:
            continue                                     # projet encore actif : on n'y touche pas

        # La taille est lente à calculer : on ne le fait que pour les projets dormants
        dormants.append({
            "nom": dossier.name,
            "cible": cible,
            "derniere": derniere,
            "jours": int((time.time() - derniere) / SECONDES_PAR_JOUR),
            "taille": taille_dossier(cible),
            "lockfile": any((dossier / f).exists() for f in FICHIERS_LOCK),
        })
    return dormants, analyses


def rendre_modifiable(fonction, chemin, _info):
    """Appelée quand la suppression échoue : on rend le fichier modifiable et on réessaie.
    (Beaucoup de fichiers de node_modules sont en lecture seule sous Windows.)"""
    os.chmod(chemin, stat.S_IWRITE)
    fonction(chemin)


def supprimer(cible):
    """Supprime le dossier DOSSIER_A_SUPPRIMER d'un projet, et RIEN d'autre."""
    # GARDE-FOU : si le dossier n'a pas exactement le nom prévu, on refuse de supprimer.
    if cible.name != DOSSIER_A_SUPPRIMER:
        raise ValueError(f"Refus : ce dossier ne s'appelle pas '{DOSSIER_A_SUPPRIMER}'")

    # Le préfixe \\?\ autorise les chemins de plus de 260 caractères sous Windows
    chemin = "\\\\?\\" + str(cible.resolve()) if os.name == "nt" else str(cible)
    if sys.version_info >= (3, 12):
        shutil.rmtree(chemin, onexc=rendre_modifiable)
    else:
        shutil.rmtree(chemin, onerror=rendre_modifiable)


def main():
    parseur = argparse.ArgumentParser(
        description=f"Supprime le dossier {DOSSIER_A_SUPPRIMER} des projets dormants.")
    parseur.add_argument("racine", help="Dossier qui contient tes projets (ex : F:\\Projets)")
    parseur.add_argument("--jours", type=int, default=JOURS_AVANT_DORMANT,
                         help=f"Dormant après X jours sans modification (défaut : {JOURS_AVANT_DORMANT})")
    parseur.add_argument("--appliquer", action="store_true",
                         help="Supprime vraiment (sans cette option : simulation)")
    args = parseur.parse_args()

    racine = Path(args.racine)
    if not racine.is_dir():
        raise SystemExit("Dossier introuvable.")

    # ----- On rappelle clairement les règles avant de commencer -----
    print(f"Dossier analysé       : {racine}")
    print(f"Dossier qui sera supprimé : {DOSSIER_A_SUPPRIMER} (et rien d'autre)")
    print(f"Projet dormant si     : aucune modification depuis {args.jours} jours\n")

    dormants, analyses = trouver_projets(racine, args.jours)
    print(f"{analyses} projet(s) analysé(s).\n")

    if not dormants:
        print(f"Aucun projet dormant avec un dossier {DOSSIER_A_SUPPRIMER} à libérer.")
        return

    # ----- Le tableau -----
    print(f"{'Projet':<30} {'Dernière modif.':<16} {'Jours':>6} {DOSSIER_A_SUPPRIMER:>14}  Remarque")
    print("-" * 85)
    total = 0
    for p in sorted(dormants, key=lambda p: p["taille"], reverse=True):   # les plus gros d'abord
        date = datetime.fromtimestamp(p["derniere"]).strftime("%d/%m/%Y")
        remarque = "" if p["lockfile"] else "SANS lockfile (versions non garanties)"
        print(f"{p['nom']:<30} {date:<16} {p['jours']:>6} {lisible(p['taille']):>14}  {remarque}")
        total += p["taille"]
    print("-" * 85)
    print(f"{len(dormants)} projet(s) dormant(s), {lisible(total)} récupérables.\n")

    if not args.appliquer:
        print("SIMULATION : rien n'a été supprimé. Ajoute --appliquer pour supprimer.")
        return

    # ----- Suppression : on demande confirmation -----
    reponse = input(f"Supprimer {len(dormants)} dossier(s) {DOSSIER_A_SUPPRIMER} "
                    f"({lisible(total)}) ? Tape OUI : ")
    if reponse.strip() != "OUI":
        print("Annulé, rien n'a été supprimé.")
        return

    liberes = 0
    for p in dormants:
        try:
            supprimer(p["cible"])
            liberes += p["taille"]
            print(f"  supprimé : {p['cible']}")
        except Exception as erreur:
            # Souvent : un serveur de dev ou VS Code utilise encore le dossier
            print(f"  ECHEC    : {p['nom']} ({erreur})")
    print(f"\n{lisible(liberes)} libérés.")


if __name__ == "__main__":
    main()