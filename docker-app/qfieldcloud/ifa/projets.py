"""Fabrique des projets QFieldCloud dérivés du projet modèle.

Deux fonctions du programme préparent un projet sous le compte de
l'utilisateur : « Ouvrir une UE » (`ouverture.py`) et « Créer une UE »
(`formulaire.py`). Elles ne diffèrent que par trois choses — le nom du projet,
les lignes versées dans son GeoPackage, et les variables posées dans le projet
QGIS. Tout le reste est le même travail, et il vit ici :

1. le **dernier paquet du projet modèle** est retrouvé : le `.qgz` que
   QFieldSync a produit, dont les couches pointent déjà sur `data.gpkg`, et ce
   GeoPackage. Pas les fichiers source du modèle — ceux-là sont branchés sur
   PostgreSQL, et un appareil de terrain n'atteint pas la base du ministère ;
2. ses fichiers sont recopiés sur le disque du conteneur ;
3. le GeoPackage est vidé, puis rempli de la sélection demandée ;
4. il est **renommé** `ifa_data.gpkg`, et le `.qgs` est retouché pour le suivre —
   plus les variables de projet, et la lecture seule s'il y a lieu ;
5. les fichiers deviennent ceux du projet de l'utilisateur, qui est relu puis
   packagé.

L'étape 4 n'est pas une coquetterie. Le projet livré sera repackagé — par nous,
et de toute façon par QField, qui demande un packaging à chaque ouverture d'un
projet infonuagique. Ses couches portent `QFieldSync/cloud_action = offline` :
le convertisseur hors ligne écrit alors son propre `data.gpkg` dans le dossier
d'export. Tant que le nôtre portait ce nom-là, les deux se disputaient la même
place et le projet sortait avec toutes ses couches métier invalides.

Une version précédente réglait cela en **figeant** les couches
(`cloud_action = no_action`), pour que le repackaging n'ait aucun effet. C'était
efficace et faux : QField cesse alors d'observer les couches, et le bouton de
synchronisation ne s'allume plus jamais. `paquet.renommer_geopackage()` porte le
détail, extrait du code de QField.

Un projet par utilisateur et par usage, réutilisé d'une fois sur l'autre :
l'appareil garde ses réglages et son cache de fonds de carte, et le compte de
l'utilisateur ne se remplit pas d'un projet par unité visitée. C'est aussi ce
qui impose le garde-fou de `verifier_travaux_termines()` : remplacer le
GeoPackage d'un projet qui porte encore des modifications non synchronisées les
effacerait sans que rien ne les rappelle.

**Les projets produits ne sont pas reliés à PostgreSQL.** Leurs couches sont
celles d'un paquet : elles vivent dans leur `data.gpkg`. Les modifications
faites sur le terrain reviennent donc dans ce GeoPackage, et leur report dans
`ifa_data` demande une étape distincte, qui n'existe pas encore.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.core.files import File as FichierDjango
from django.db import transaction

from qfieldcloud.core import permissions_utils
from qfieldcloud.core.models import (
    Delta,
    Job,
    PackageJob,
    Person,
    ProcessProjectfileJob,
    Project,
)
from qfieldcloud.core.utils2 import jobs
from qfieldcloud.filestorage.models import File, FileVersion
from qfieldcloud.ifa import gpkg, inventaires, paquet
from qfieldcloud.ifa.exceptions import (
    ProjetModeleInvalideError,
    TravauxNonSynchronisesError,
)

logger = logging.getLogger(__name__)

# Fichiers du paquet qui n'ont pas à devenir des fichiers du projet : la
# vignette est régénérée au packaging, et le fichier de deltas appartient à
# l'appareil qui l'a produit.
FICHIERS_IGNORES = ("deltafile.json",)
SUFFIXES_IGNORES = (".qgz.png", ".qgs.png")

# Statuts d'un delta encore en cours de route. Un delta en conflit ou en erreur
# n'est pas « en cours » : il ne partira plus tout seul, et bloquer sur lui
# empêcherait le technicien de reprendre son travail.
STATUTS_EN_COURS = (Delta.Status.PENDING, Delta.Status.STARTED)

# Nom que porte notre GeoPackage dans le projet de l'utilisateur. Le
# convertisseur hors ligne écrit toujours le sien sous `data.gpkg` : lui laisser
# ce nom-là, c'est le laisser écraser le nôtre au packaging. Voir
# `paquet.renommer_geopackage()`.
NOM_GEOPACKAGE = "ifa_data.gpkg"


@dataclass
class Preparation:
    """Ce qu'un projet préparé laisse à dire au client."""

    projet: Project
    travail: PackageJob
    lignes_par_table: dict[str, int] = field(default_factory=dict)

    @property
    def lignes(self) -> int:
        return sum(self.lignes_par_table.values())

    def en_dictionnaire(self) -> dict[str, Any]:
        return {
            "projet_id": str(self.projet.id),
            "projet_nom": self.projet.name,
            "projet_proprietaire": self.projet.owner.username,
            "travail_id": str(self.travail.id),
            "lignes": self.lignes,
            "tables": {
                table: nombre
                for table, nombre in sorted(self.lignes_par_table.items())
                if nombre
            },
        }


def preparer(
    utilisateur: Person,
    nom: str,
    description: str,
    selection: inventaires.Selection,
    lecture_seule: bool = False,
    variables: dict[str, str] | None = None,
    paquet_modele: PackageJob | None = None,
) -> Preparation:
    """Prépare le projet `nom` de l'utilisateur et en constitue le paquet."""
    if paquet_modele is None:
        paquet_modele = dernier_paquet(projet_modele())

    fichiers = fichiers_du_paquet(paquet_modele)
    projet = projet_de_utilisateur(utilisateur, nom, description)

    verifier_travaux_termines(projet)

    dossier = tempfile.mkdtemp(prefix="ifa-projet-")

    try:
        chemins = _ecrire_localement(fichiers, dossier)
        modele_qgz, chemin_qgz = _projet_qgis(chemins)
        chemin_gpkg = _geopackage(chemins)

        lignes = inventaires.remplir(chemin_gpkg, modele_qgz.correspondances, selection)

        # Les tables reprennent leur nom métier : c'est à cela que l'étape de
        # validation du flux `delta_apply` reconnaît un GeoPackage IFE.
        renommages = gpkg.renommer_tables(
            chemin_gpkg, _tables_metier(modele_qgz.correspondances)
        )
        modele_qgz.xml = paquet.renommer_couches(modele_qgz.xml, renommages)

        # Notre GeoPackage prend un nom à lui. Sans cela, le packaging écrirait
        # son propre `data.gpkg` au même endroit que le nôtre, et le projet
        # livré sortirait avec toutes ses couches métier invalides — voir
        # `paquet.renommer_geopackage()`, qui dit aussi pourquoi on ne fige plus
        # les couches.
        ancien_nom = os.path.basename(chemin_gpkg)
        _renommer_geopackage(chemins, chemin_gpkg)
        modele_qgz.xml = paquet.renommer_geopackage(
            modele_qgz.xml, ancien_nom, NOM_GEOPACKAGE
        )

        if variables:
            modele_qgz.xml = paquet.definir_variables(modele_qgz.xml, variables)

        if lecture_seule:
            modele_qgz.xml = paquet.passer_en_lecture_seule(modele_qgz.xml)

        with open(chemin_qgz, "wb") as sortie:
            sortie.write(modele_qgz.octets())

        travail = _enregistrer(projet, utilisateur, chemins)
    finally:
        _nettoyer(dossier)

    logger.info(
        "[IFA] projet %s prepare pour %s (%s lignes, projet %s, travail %s)",
        nom,
        utilisateur.username,
        sum(lignes.values()),
        projet.id,
        travail.id,
    )

    return Preparation(projet=projet, travail=travail, lignes_par_table=lignes)


def projet_modele() -> Project:
    """Projet dont le dernier paquet sert de patron aux projets dérivés."""
    requete = Project.objects.all()

    if settings.IFA_PROJET_MODELE_ID:
        projet = requete.filter(id=settings.IFA_PROJET_MODELE_ID).first()
    else:
        projet = requete.filter(
            name=settings.IFA_PROJET_MODELE_NOM,
            owner__username=settings.IFA_PROJET_MODELE_PROPRIETAIRE,
        ).first()

    if projet is None:
        raise ProjetModeleInvalideError(
            "Le projet modèle IFA est introuvable sur ce serveur "
            f"({settings.IFA_PROJET_MODELE_PROPRIETAIRE}/"
            f"{settings.IFA_PROJET_MODELE_NOM}).",
        )

    return projet


def dernier_paquet(modele: Project) -> PackageJob:
    """Dernier packaging réussi du projet modèle.

    `Project.last_package_job` existe dans le modèle mais n'est renseigné nulle
    part dans ce dépôt : s'y fier reviendrait à ne jamais trouver de paquet. On
    interroge donc les travaux eux-mêmes, en ne retenant que ceux qui se sont
    terminés — un packaging échoué n'a pas produit de fichiers.
    """
    dernier = (
        PackageJob.objects.filter(project=modele, status=Job.Status.FINISHED)
        .order_by("-finished_at", "-created_at")
        .first()
    )

    if dernier is None:
        raise ProjetModeleInvalideError(
            f"Le projet modèle « {modele.name} » n'a pas de packaging réussi : "
            "packagez-le une fois avant de préparer un projet.",
        )

    return dernier


def projet_de_utilisateur(utilisateur: Person, nom: str, description: str) -> Project:
    """Retrouve ou crée le projet `nom` chez l'utilisateur.

    Le nom est fixe : deux projets ne peuvent pas le porter en même temps chez
    le même propriétaire, et le technicien retrouve toujours le même projet
    dans son écran « Projets », d'une unité à la suivante.
    """
    projet = Project.objects.filter(name=nom, owner=utilisateur).first()

    if projet is None:
        projet = Project.objects.create(
            name=nom,
            owner=utilisateur,
            description=description,
            is_public=False,
        )
        logger.info("[IFA] projet cree : %s/%s", utilisateur.username, nom)
    elif projet.description != description:
        projet.description = description
        projet.save(update_fields=["description"])

    return projet


def verifier_travaux_termines(projet: Project) -> None:
    """Refuse d'écraser un projet dont les modifications n'ont pas été appliquées."""
    en_cours = Delta.objects.filter(
        project=projet, last_status__in=STATUTS_EN_COURS
    ).count()

    if en_cours:
        raise TravauxNonSynchronisesError(
            f"Le projet « {projet.name} » porte {en_cours} modification(s) non "
            "encore appliquée(s) : synchronisez-les avant d'en préparer un "
            "nouveau contenu.",
        )


def fichiers_du_paquet(paquet_modele: PackageJob) -> list[File]:
    """Fichiers du paquet, vignette et fichier de deltas exclus."""
    fichiers = [
        fichier
        for fichier in File.objects.filter(
            project_id=paquet_modele.project_id,
            file_type=File.FileType.PACKAGE_FILE,
            package_job=paquet_modele,
        ).select_related("latest_version")
        if not _est_ignore(fichier.name)
    ]

    if not any(est_projet_qgis(fichier.name) for fichier in fichiers):
        raise ProjetModeleInvalideError(
            f"Le paquet de « {paquet_modele.project.name} » ne contient pas de "
            "projet QGIS : relancez son packaging.",
        )

    return fichiers


def _ecrire_localement(fichiers: list[File], dossier: str) -> dict[str, str]:
    """Recopie les fichiers du paquet sur le disque du conteneur.

    Le GeoPackage pèse une vingtaine de mégaoctets et doit être ouvert par
    SQLite : il lui faut un vrai fichier, et le lire par blocs évite de le
    charger entièrement en mémoire.
    """
    chemins: dict[str, str] = {}

    for fichier in fichiers:
        chemin = os.path.join(dossier, os.path.basename(fichier.name))

        with fichier.latest_version.content.open("rb") as source:
            with open(chemin, "wb") as destination:
                for bloc in source.chunks():
                    destination.write(bloc)

        chemins[fichier.name] = chemin

    return chemins


def _projet_qgis(chemins: dict[str, str]) -> tuple[paquet.ProjetPackage, str]:
    for nom, chemin in chemins.items():
        if est_projet_qgis(nom):
            with open(chemin, "rb") as source:
                return paquet.lire(source.read()), chemin

    raise ProjetModeleInvalideError("Le paquet modèle ne contient pas de projet QGIS.")


def _tables_metier(
    correspondances: list[paquet.Correspondance],
) -> dict[str, str]:
    """Empreinte de table → nom métier, pour les tables qui en ont un seul.

    La correspondance est bijective sur le fonds actuel — trente-sept tables,
    trente-sept empreintes. Une collision resterait pourtant possible si le
    projet modèle exposait deux fois la même table métier sous deux sources
    différentes : renommer les deux donnerait deux tables du même nom, que le
    GeoPackage refuse. On laisse alors les deux sous leur empreinte, et on le
    dit — mieux vaut une validation qui ignore ces tables qu'un GeoPackage à
    moitié renommé.
    """
    par_table: dict[str, set[str]] = {}

    for correspondance in correspondances:
        par_table.setdefault(correspondance.table_pg, set()).add(
            correspondance.table_gpkg
        )

    renommages: dict[str, str] = {}

    for table_pg, empreintes in par_table.items():
        if len(empreintes) > 1:
            logger.warning(
                "[IFA] %s empreintes pour la table %s : renommage abandonne pour elle",
                len(empreintes),
                table_pg,
            )
            continue

        renommages[empreintes.pop()] = table_pg

    return renommages


def _renommer_geopackage(chemins: dict[str, str], chemin: str) -> str:
    """Renomme le GeoPackage sur le disque, et dans la liste des fichiers.

    Les clés de `chemins` deviennent les noms des fichiers du projet : renommer
    l'entrée suffit à ce que le fichier soit versé sous son nouveau nom, et à ce
    que `_retirer_fichiers_projet_obsoletes()` retire l'ancien `data.gpkg` des
    projets préparés avant ce changement — il resterait sinon dans le projet, où
    le packaging le confondrait avec le sien.
    """
    dossier = os.path.dirname(chemin)
    cible = os.path.join(dossier, NOM_GEOPACKAGE)

    if os.path.abspath(cible) == os.path.abspath(chemin):
        return chemin

    os.replace(chemin, cible)

    for nom, valeur in list(chemins.items()):
        if valeur == chemin:
            del chemins[nom]

    chemins[NOM_GEOPACKAGE] = cible

    return cible


def _geopackage(chemins: dict[str, str]) -> str:
    for nom, chemin in chemins.items():
        if nom.lower().endswith(".gpkg"):
            return chemin

    raise ProjetModeleInvalideError(
        "Le paquet modèle ne contient pas de GeoPackage : le projet modèle "
        "n'a pas été converti hors ligne.",
    )


def _enregistrer(
    projet: Project, utilisateur: Person, chemins: dict[str, str]
) -> PackageJob:
    """Verse les fichiers dans le projet de l'utilisateur et demande son packaging."""
    taille = sum(os.path.getsize(chemin) for chemin in chemins.values())
    permissions_utils.check_can_upload_file(projet, None, taille)

    _retirer_fichiers_projet_obsoletes(
        projet,
        {os.path.basename(nom) for nom in chemins},
    )

    with transaction.atomic():
        for nom, chemin in chemins.items():
            nom_fichier = os.path.basename(nom)

            with open(chemin, "rb") as source:
                FileVersion.objects.add_version(
                    project=projet,
                    filename=nom_fichier,
                    content=FichierDjango(source, name=nom_fichier),
                    file_type=File.FileType.PROJECT_FILE,
                    uploaded_by=utilisateur,
                )

            if est_projet_qgis(nom_fichier):
                projet.the_qgis_file_name = nom_fichier

        projet.save(update_fields=["the_qgis_file_name"], recompute_storage=True)

        _relire_le_projet(projet, utilisateur)

        return jobs.repackage(projet, utilisateur)


def _retirer_fichiers_projet_obsoletes(projet: Project, conserves: set[str]) -> None:
    """Retire du projet les fichiers que le paquet ne fournit plus.

    Le projet est réutilisé d'une préparation à la suivante, et tout ce qu'il
    contient part au packaging puis sur l'appareil. Un fichier laissé par une
    préparation précédente — ou par une version antérieure de ce module —
    continuerait donc d'être livré, sans que plus rien ne le remplisse.
    """
    obsoletes = File.objects.filter(
        project=projet,
        file_type=File.FileType.PROJECT_FILE,
    ).exclude(name__in=conserves)

    for fichier in obsoletes:
        nom = fichier.name

        # `File.delete()` effacerait les lignes des versions en masse, sans
        # passer par `FileVersion.delete()` : les objets resteraient dans le
        # stockage sans plus rien pour les désigner.
        for version in fichier.versions.all():
            version.delete()

        fichier.delete()

        logger.info("[IFA] fichier projet obsolete retire : %s", nom)


def _relire_le_projet(projet: Project, utilisateur: Person) -> None:
    """Demande au travailleur QGIS de relire le projet, s'il ne le fait pas déjà.

    C'est ce travail qui renseigne l'étendue, les couches et la vignette du
    projet. Le téléversement ordinaire d'un fichier le déclenche (voir
    `filestorage.view_helpers.upload_project_file_version`) ; ici, les fichiers
    n'arrivent pas par une requête de téléversement.
    """
    en_cours = ProcessProjectfileJob.objects.filter(
        project=projet,
        created_by=utilisateur,
        status__in=[Job.Status.PENDING, Job.Status.QUEUED, Job.Status.STARTED],
    ).exists()

    if not en_cours:
        ProcessProjectfileJob.objects.create(project=projet, created_by=utilisateur)


def _nettoyer(dossier: str) -> None:
    for nom in os.listdir(dossier):
        try:
            os.remove(os.path.join(dossier, nom))
        except OSError:
            logger.warning("[IFA] fichier temporaire non supprime : %s", nom)

    try:
        os.rmdir(dossier)
    except OSError:
        logger.warning("[IFA] dossier temporaire non supprime : %s", dossier)


def est_projet_qgis(nom: str) -> bool:
    return nom.lower().endswith((".qgs", ".qgz"))


def _est_ignore(nom: str) -> bool:
    base = os.path.basename(nom).lower()

    return base in FICHIERS_IGNORES or base.endswith(SUFFIXES_IGNORES)
