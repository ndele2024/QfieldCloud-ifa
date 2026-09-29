"""Distribution du plugin QField « IFA 2.0 — Menu ».

Le serveur garde **la** version publiée du plugin — une archive `.zip` et son
`metadata.txt` — et la sert à deux adresses publiques :

    GET /api/v1/ifa/plugin/metadata.txt    la version publiée
    GET /api/v1/ifa/plugin/ifa_menu.zip    l'archive, pour `installFromUrl()`

Au démarrage, le plugin lit `metadata.txt`, compare la version à la sienne et
propose la mise à jour ; QField télécharge alors l'archive par
`pluginManager.installFromUrl()`. Voir `formulaires/plugins/ifa_menu/`
(`ServiceMiseAJour.qml`).

Pourquoi publiques : `installFromUrl()` télécharge sans le jeton du plugin, et
la lecture de la version au démarrage ne doit pas réclamer de mot de passe.
Le plugin ne contient ni secret ni donnée — seulement son code QML.

Pourquoi un nom d'archive fixe : QField nomme le dossier du plugin installé
d'après le nom du fichier téléchargé (sans suffixe de version), et c'est ce
nom qui sert d'identifiant (`uuid`) au plugin. Servi sous un autre nom, le
plugin mis à jour s'installerait à côté de l'ancien au lieu de le remplacer.

Les fichiers vivent dans `MEDIA_ROOT/ifa_plugin/`, sur le volume `media_volume`
du conteneur `app` : ils survivent aux reconstructions d'image.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass

from django.conf import settings
from django.core.files.storage import FileSystemStorage

# Nom du dossier du plugin sur l'appareil — donc de l'archive servie. Doit
# rester celui qu'installe `install.py` (défaut : « ifa_menu »).
NOM_PLUGIN = getattr(settings, "IFA_PLUGIN_NOM", "ifa_menu")

NOM_ARCHIVE = f"{NOM_PLUGIN}.zip"
NOM_METADONNEES = "metadata.txt"

# Une archive de plugin QML pèse quelques centaines de kilo-octets.
TAILLE_ARCHIVE_MAX = 20 * 1024 * 1024
TAILLE_METADONNEES_MAX = 64 * 1024

_VERSION = re.compile(r"^\d+(\.\d+){0,3}$")


class PluginInvalideError(ValueError):
    """Les fichiers déposés ne forment pas un plugin publiable."""


@dataclass(frozen=True)
class PluginPublie:
    version: str
    nom: str
    taille_archive: int
    publie_le: float  # horodatage POSIX de l'archive


def stockage() -> FileSystemStorage:
    return FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "ifa_plugin"))


# ---------------------------------------------------------------------------
#  Lecture de metadata.txt
# ---------------------------------------------------------------------------
def lire_metadonnees(contenu: bytes) -> dict[str, str]:
    """`cle=valeur` par ligne, comme QField le lit. Les lignes vides ou sans
    `=` sont ignorées ; la première occurrence d'une clé l'emporte."""
    try:
        texte = contenu.decode("utf-8-sig")
    except UnicodeDecodeError as erreur:
        raise PluginInvalideError("metadata.txt n'est pas encodé en UTF-8.") from erreur

    valeurs: dict[str, str] = {}

    for ligne in texte.splitlines():
        if "=" not in ligne or ligne.lstrip().startswith(("#", ";", "[")):
            continue
        cle, _, valeur = ligne.partition("=")
        valeurs.setdefault(cle.strip().lower(), valeur.strip())

    return valeurs


def version_de(metadonnees: dict[str, str]) -> str:
    version = metadonnees.get("version", "")

    if not _VERSION.match(version):
        raise PluginInvalideError(
            f"Version absente ou illisible dans metadata.txt : « {version} ». "
            "Attendu : des nombres séparés par des points, par exemple 0.2.0."
        )

    return version


def comparer_versions(a: str, b: str) -> int:
    """-1, 0 ou 1, en comparant nombre par nombre (0.10.0 > 0.9.0)."""
    pa = [int(x) for x in a.split(".")]
    pb = [int(x) for x in b.split(".")]
    longueur = max(len(pa), len(pb))
    pa += [0] * (longueur - len(pa))
    pb += [0] * (longueur - len(pb))
    return (pa > pb) - (pa < pb)


# ---------------------------------------------------------------------------
#  Contrôle des fichiers déposés
# ---------------------------------------------------------------------------
def verifier(archive: bytes, metadonnees: bytes) -> str:
    """Contrôle l'archive et metadata.txt, et rend la version publiée.

    Refuse ce que QField refuserait ou installerait de travers : une archive
    illisible, sans `main.qml` à la racine, ou dont le `metadata.txt` intérieur
    ne porte pas la même version que celui déposé à côté — les appareils
    compareraient une version et en installeraient une autre, et la
    proposeraient alors indéfiniment.
    """
    if len(archive) > TAILLE_ARCHIVE_MAX:
        raise PluginInvalideError("L'archive dépasse 20 Mo : ce n'est pas un plugin QML.")

    if len(metadonnees) > TAILLE_METADONNEES_MAX:
        raise PluginInvalideError("metadata.txt dépasse 64 Ko.")

    version = version_de(lire_metadonnees(metadonnees))

    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            noms = set(zf.namelist())

            if "main.qml" not in noms:
                raise PluginInvalideError(
                    "L'archive ne contient pas main.qml à sa racine. Produisez-la "
                    "avec « python install.py --zip »."
                )

            if NOM_METADONNEES in noms:
                interne = version_de(lire_metadonnees(zf.read(NOM_METADONNEES)))
                if interne != version:
                    raise PluginInvalideError(
                        f"L'archive annonce la version {interne}, metadata.txt la "
                        f"version {version}. Déposez les deux fichiers d'une même "
                        "construction."
                    )
    except zipfile.BadZipFile as erreur:
        raise PluginInvalideError("Le fichier déposé n'est pas une archive .zip valide.") from erreur

    return version


# ---------------------------------------------------------------------------
#  Publication
# ---------------------------------------------------------------------------
def publier(archive: bytes, metadonnees: bytes) -> str:
    """Vérifie puis remplace la version publiée. Rend la nouvelle version."""
    version = verifier(archive, metadonnees)
    depot = stockage()

    # L'archive d'abord, metadata.txt ensuite : c'est metadata.txt que les
    # appareils lisent pour décider d'installer. Dans l'ordre inverse, un
    # appareil pourrait voir la nouvelle version annoncée et télécharger
    # l'ancienne archive.
    _remplacer(depot, NOM_ARCHIVE, archive)
    _remplacer(depot, NOM_METADONNEES, metadonnees)

    return version


def _remplacer(depot: FileSystemStorage, nom: str, contenu: bytes) -> None:
    os.makedirs(depot.location, exist_ok=True)
    chemin = depot.path(nom)
    provisoire = chemin + ".part"

    with open(provisoire, "wb") as sortie:
        sortie.write(contenu)

    # Remplacement atomique : un appareil qui télécharge au même instant
    # reçoit l'ancien fichier ou le nouveau, jamais un mélange.
    os.replace(provisoire, chemin)


def publie() -> PluginPublie | None:
    """La version actuellement servie, ou None si rien n'a été déposé."""
    depot = stockage()

    if not (depot.exists(NOM_ARCHIVE) and depot.exists(NOM_METADONNEES)):
        return None

    with depot.open(NOM_METADONNEES, "rb") as fichier:
        metadonnees = lire_metadonnees(fichier.read())

    try:
        version = version_de(metadonnees)
    except PluginInvalideError:
        version = "?"

    return PluginPublie(
        version=version,
        nom=metadonnees.get("name", NOM_PLUGIN),
        taille_archive=depot.size(NOM_ARCHIVE),
        publie_le=os.path.getmtime(depot.path(NOM_ARCHIVE)),
    )
