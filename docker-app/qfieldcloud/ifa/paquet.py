"""Lecture du projet QGIS packagé qui sert de modèle aux projets d'affichage.

Un projet packagé par QFieldSync garde la trace de ce dont il provient : pour
chaque couche convertie hors ligne, la propriété `remoteSource` conserve l'URI
PostgreSQL d'origine à côté de la source GeoPackage. C'est ce couple qui donne
la correspondance « table du schéma métier → table du `data.gpkg` », dont les
noms sont des empreintes hexadécimales calculées par QFieldSync :

    <datasource>./data.gpkg|layername=7d83cbe7…</datasource>
    <Option name="remoteSource" value="service='…' table=&quot;ifa_qfield&quot;.&quot;amenagement&quot; …"/>

Le fichier `.qgz` est une archive ZIP contenant un `.qgs` (du XML). On le lit
avec `ElementTree`, mais on le réécrit à coups d'expressions régulières :
sérialiser à nouveau l'arbre réordonnerait les attributs et normaliserait les
espaces de noms de tout le projet, pour un changement qui ne porte que sur un
attribut par couche.
"""

from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

from qfieldcloud.ifa.exceptions import ProjetModeleInvalideError

logger = logging.getLogger(__name__)

# `layername=` s'arrête au `|` suivant : une source GeoPackage peut porter un
# `|subset=…` derrière.
_RE_NOM_COUCHE = re.compile(r"layername=([^|]+)")
# Le `table=` de `remoteSource` est échappé (`&quot;`) puisqu'il vit dans un
# attribut XML ; `ElementTree` l'a déjà déséchappé quand on le lit ici.
_RE_TABLE_PG = re.compile(r'table="([^"]+)"\."([^"]+)"')
_RE_BALISE_COUCHE = re.compile(r"<maplayer\b[^>]*>")
_RE_LECTURE_SEULE = re.compile(r'\breadOnly="[^"]*"')
# Les variables de projet vivent dans l'arbre des propriétés, sous
# `properties/Variables` : deux listes parallèles, noms et valeurs.
_RE_VARIABLES = re.compile(r"<Variables>.*?</Variables>", re.DOTALL)
_RE_PROPRIETES = re.compile(r"<properties\s*(/?)>")
_RE_FIN_QGIS = re.compile(r"</qgis>")


@dataclass(frozen=True)
class Correspondance:
    """Une couche hors ligne du projet packagé."""

    id_couche: str
    nom: str
    table_gpkg: str
    schema_pg: str
    table_pg: str
    cle: str

    @property
    def qualifie(self) -> str:
        return f"{self.schema_pg}.{self.table_pg}"


@dataclass
class ProjetPackage:
    """Le `.qgz` packagé, ouvert."""

    archive: dict[str, bytes]
    nom_entree: str
    xml: str

    @property
    def correspondances(self) -> list[Correspondance]:
        return correspondances(self.xml)

    def octets(self) -> bytes:
        """Réécrit l'archive avec le XML courant."""
        tampon = io.BytesIO()

        with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as sortie:
            for nom, contenu in self.archive.items():
                sortie.writestr(
                    nom,
                    self.xml.encode("utf-8") if nom == self.nom_entree else contenu,
                )

        return tampon.getvalue()


def lire(donnees: bytes) -> ProjetPackage:
    """Ouvre un `.qgz` et en extrait le `.qgs`."""
    try:
        with zipfile.ZipFile(io.BytesIO(donnees)) as archive:
            contenu = {nom: archive.read(nom) for nom in archive.namelist()}
    except zipfile.BadZipFile as erreur:
        raise ProjetModeleInvalideError(
            "Le projet modèle n'est pas une archive .qgz lisible.",
        ) from erreur

    entrees = [nom for nom in contenu if nom.lower().endswith(".qgs")]

    if not entrees:
        raise ProjetModeleInvalideError(
            "Le projet modèle ne contient aucun fichier .qgs.",
        )

    return ProjetPackage(
        archive=contenu,
        nom_entree=entrees[0],
        xml=contenu[entrees[0]].decode("utf-8"),
    )


def correspondances(xml: str) -> list[Correspondance]:
    """Couches hors ligne du projet, avec leur table d'origine et sa cible."""
    try:
        racine = ET.fromstring(xml)
    except ET.ParseError as erreur:
        raise ProjetModeleInvalideError(
            "Le projet modèle contient un XML illisible.",
        ) from erreur

    trouvees: list[Correspondance] = []

    for couche in racine.findall(".//maplayer"):
        proprietes = _proprietes(couche)

        if proprietes.get("isOfflineEditable") != "true":
            continue

        nom_gpkg = _RE_NOM_COUCHE.search(couche.findtext("datasource") or "")
        table_pg = _RE_TABLE_PG.search(proprietes.get("remoteSource", ""))

        if not (nom_gpkg and table_pg):
            # Une couche hors ligne dont on ne sait pas d'où elle vient ne peut
            # pas être remplie : on la signale plutôt que de la remplir de
            # travers.
            logger.warning(
                "[IFA] couche hors ligne sans correspondance : %s",
                couche.findtext("layername"),
            )
            continue

        trouvees.append(
            Correspondance(
                id_couche=couche.findtext("id") or "",
                nom=couche.findtext("layername") or "",
                table_gpkg=nom_gpkg.group(1),
                schema_pg=table_pg.group(1),
                table_pg=table_pg.group(2),
                cle=proprietes.get("QFieldSync/sourceDataPrimaryKeys", ""),
            )
        )

    return trouvees


def renommer_geopackage(xml: str, ancien: str, nouveau: str) -> str:
    """Fait pointer les couches du projet sur un GeoPackage d'un autre nom.

    ---------------------------------------------------------------------------
    POURQUOI RENOMMER
    ---------------------------------------------------------------------------
    Le projet livré sera repackagé — par nous, et de toute façon par QField, qui
    demande un packaging à chaque ouverture d'un projet infonuagique. Ses couches
    portent `QFieldSync/cloud_action = offline`, l'ordre de les convertir hors
    ligne : le convertisseur écrit alors un **nouveau** `data.gpkg` dans le
    dossier d'export. Tant que notre GeoPackage rempli s'appelait lui aussi
    `data.gpkg`, les deux se disputaient le même nom au même endroit, et le
    projet livré sortait avec toutes ses couches métier invalides.

    Le renommer suffit à séparer les deux : le convertisseur lit notre
    `ifa_data.gpkg` et écrit son `data.gpkg`, les lignes passent de l'un à
    l'autre, et le paquet reste cohérent.

    ---------------------------------------------------------------------------
    POURQUOI PAS FIGER LES COUCHES
    ---------------------------------------------------------------------------
    La version précédente prenait le chemin inverse : passer `cloud_action` à
    `no_action` pour que le repackaging n'ait aucun effet. Cela marchait, au prix
    d'une conséquence qui n'a été comprise qu'en la vivant — **QField cesse alors
    d'observer les couches**, et plus aucune modification n'est enregistrée :

        // QField, src/core/utils/qfcloudutils.cpp
        bool QfCloudUtils::isCloudAction( const QgsMapLayer *layer ) {
          const QString layerAction( layer->customProperty(
              "QFieldSync/cloud_action" ).toString().toUpper() );
          if ( layerAction == "NO_ACTION" || layerAction == "REMOVE" )
            return false;
          return true;
        }

        // src/core/qfieldcloud/qflayerobserver.cpp
        if ( !vl->readOnly() && QfCloudUtils::isCloudAction( vl ) )

    Le technicien saisissait, le GeoPackage se remplissait, et le bouton de
    synchronisation restait éteint : pas d'observateur, pas de delta.

    ---------------------------------------------------------------------------
    CE QUE CELA COÛTE
    ---------------------------------------------------------------------------
    Le packaging refait une conversion hors ligne complète — quatre-vingt-douze
    couches d'un GeoPackage de vingt mégaoctets — au lieu d'une simple copie. En
    échange, le projet livré est un projet infonuagique ordinaire, que QField
    suit comme les autres.

    Aucune dérive de génération en génération : chaque préparation repart du
    paquet du **projet modèle** (voir `projets.preparer()`), jamais du projet de
    l'utilisateur. Le `remoteSource` que le convertisseur réécrit dans le paquet
    livré ne revient donc jamais alimenter `correspondances()`.
    """
    return xml.replace(f"./{ancien}", f"./{nouveau}")


def renommer_couches(xml: str, renommages: dict[str, str]) -> str:
    """Fait suivre au projet les tables du GeoPackage qui ont été renommées.

    Le nom de la table vit dans le `layername=` de la source, et la source ne
    vit pas que dans `<datasource>` : l'arbre des couches, les relations et les
    widgets « valeur relationnelle » la répètent. Le projet modèle en compte
    357 occurrences pour 92 couches — en oublier une laisse une couche
    invalide, d'où la substitution sur tout le document plutôt que couche par
    couche.

    Les empreintes font soixante-quatre caractères hexadécimaux : `layername=`
    suivi de l'une d'elles ne peut désigner rien d'autre.
    """
    for ancien, nouveau in renommages.items():
        if ancien == nouveau:
            continue

        xml = xml.replace(f"layername={ancien}", f"layername={nouveau}")

    return xml


def definir_variables(xml: str, variables: dict[str, str]) -> str:
    """Pose les variables de projet QGIS du projet livré.

    Les valeurs par défaut des formulaires IFA lisent des variables de projet
    (`@code_region`, `@une_code_ident`, …). Tant que la saisie se faisait dans
    le projet déjà ouvert, le plugin les posait lui-même par
    `QgsProject.setCustomVariables()`. « Créer une UE » ouvre désormais un
    *autre* projet : les variables doivent donc voyager avec lui, et c'est ici
    qu'elles y entrent.

    QGIS les range dans l'arbre des propriétés, sous `properties/Variables`,
    en deux listes parallèles — `variableNames` et `variableValues`. Le bloc
    existant est remplacé en entier : les variables qu'un projet modèle
    porterait déjà n'ont pas à survivre à une préparation qui les redéfinit.
    """
    if not variables:
        return xml

    bloc = _bloc_variables(variables)

    if _RE_VARIABLES.search(xml):
        return _RE_VARIABLES.sub(lambda _: bloc, xml, count=1)

    proprietes = _RE_PROPRIETES.search(xml)

    if proprietes:
        # `<properties/>` — un projet sans aucune propriété — n'a pas de
        # contenu où insérer : la balise est rouverte autour du bloc.
        if proprietes.group(1):
            remplacement = f"<properties>{bloc}</properties>"
            return xml[: proprietes.start()] + remplacement + xml[proprietes.end() :]

        return xml[: proprietes.end()] + bloc + xml[proprietes.end() :]

    fin = _RE_FIN_QGIS.search(xml)

    if not fin:
        raise ProjetModeleInvalideError(
            "Le projet modèle n'a pas de balise </qgis> : variables non posées.",
        )

    return xml[: fin.start()] + f"<properties>{bloc}</properties>" + xml[fin.start() :]


def _bloc_variables(variables: dict[str, str]) -> str:
    """Le bloc `<Variables>` correspondant, noms et valeurs dans le même ordre."""
    noms = sorted(variables)

    lignes = ['<Variables><variableNames type="QStringList">']
    lignes += [f"<value>{escape(nom)}</value>" for nom in noms]
    lignes.append('</variableNames><variableValues type="QStringList">')
    lignes += [f"<value>{escape(str(variables[nom]))}</value>" for nom in noms]
    lignes.append("</variableValues></Variables>")

    return "".join(lignes)


def passer_en_lecture_seule(xml: str) -> str:
    """Marque toutes les couches du projet comme non modifiables.

    Le projet d'affichage en consultation appartient à l'utilisateur : les
    droits de QFieldCloud ne peuvent donc pas l'empêcher d'y écrire. C'est
    l'attribut `readOnly` de chaque couche qui verrouille l'édition dans
    QField — le même que QFieldSync pose sur les couches qu'il n'a pas su
    convertir.
    """

    def reecrire(correspondance: re.Match[str]) -> str:
        balise = correspondance.group(0)

        if _RE_LECTURE_SEULE.search(balise):
            return _RE_LECTURE_SEULE.sub('readOnly="1"', balise, count=1)

        return balise[:-1].rstrip() + ' readOnly="1">'

    return _RE_BALISE_COUCHE.sub(reecrire, xml)


def _proprietes(couche: ET.Element) -> dict[str, str]:
    """Propriétés personnalisées d'une couche, nom → valeur."""
    proprietes: dict[str, str] = {}
    bloc = couche.find("customproperties")

    if bloc is None:
        return proprietes

    for option in bloc.iter("Option"):
        nom = option.get("name")
        valeur = option.get("value")

        if nom and valeur is not None:
            proprietes[nom] = valeur

    return proprietes
