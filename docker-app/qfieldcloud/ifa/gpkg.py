"""Remplissage du GeoPackage d'un projet d'affichage.

Le projet modèle est packagé par QFieldSync : ses couches PostgreSQL sont
devenues des tables d'un `data.gpkg`, aux noms hachés. Ouvrir une unité
d'échantillonnage consiste à reprendre ce GeoPackage — vide, puisque le projet
de saisie part d'un schéma sans données — et à y écrire les inventaires de
l'unité demandée.

Le remplissage passe par `sqlite3` de la bibliothèque standard : un GeoPackage
reste une base SQLite dont la spécification tient en trois tables de
métadonnées, et écrire des lignes n'en demande pas davantage. Seule la
géométrie demande un peu de soin — d'où `encoder_geometrie()`.

Une opération fait exception et passe par **GDAL** : `renommer_tables()`. Y
toucher à la main obligerait à reprendre `gpkg_contents`,
`gpkg_geometry_columns`, `gpkg_extensions`, l'index R-Tree et ses six
déclencheurs — une liste qui s'allonge à chaque version de la spécification.
Le pilote GPKG de GDAL le fait, et le fait juste.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import struct
import uuid
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# En-tête d'un blob « GeoPackage Binary » (OGC 12-128r18, §2.1.3) :
#   'GP' | version (0) | drapeaux | srs_id (int32) | [enveloppe] | WKB
#
# Les drapeaux disent comment lire la suite : bit 0 à 1 pour un en-tête en
# petit-boutien, bits 1 à 3 pour l'indicateur d'enveloppe (1 = XY, quatre
# flottants), bit 4 pour une géométrie vide.
_MAGIE = b"GP"
_VERSION = 0
_PETIT_BOUTIEN = 0x01
_ENVELOPPE_XY = 0x02
_VIDE = 0x10


def encoder_geometrie(
    wkb: bytes | memoryview | None,
    srs_id: int,
    enveloppe: tuple[float, float, float, float] | None = None,
) -> bytes | None:
    """Enrobe un WKB PostGIS (`ST_AsBinary`) dans un blob GeoPackage.

    L'enveloppe est facultative dans le format, mais elle ne l'est pas ici :
    les déclencheurs qui entretiennent l'index R-Tree appellent `ST_MinX` et
    consorts, et c'est dans l'en-tête que `_declarer_fonctions()` va les lire.
    Sans elle, il faudrait décoder le WKB — ou se passer d'index spatial.
    """
    if wkb is None:
        return None

    if isinstance(wkb, memoryview):
        wkb = wkb.tobytes()

    drapeaux = _PETIT_BOUTIEN
    bornes = b""

    if enveloppe is not None and None not in enveloppe:
        drapeaux |= _ENVELOPPE_XY
        # L'ordre du GeoPackage est minx, maxx, miny, maxy.
        bornes = struct.pack("<4d", *(float(valeur) for valeur in enveloppe))
    else:
        # Sans bornes, la géométrie est vide ou dégénérée : le dire évite que
        # les déclencheurs n'aillent chercher une enveloppe absente.
        drapeaux |= _VIDE

    return (
        _MAGIE + bytes([_VERSION, drapeaux]) + struct.pack("<i", srs_id) + bornes + wkb
    )


def _enveloppe(blob: bytes | None) -> tuple[float, float, float, float] | None:
    """Bornes portées par l'en-tête d'un blob GeoPackage, si elles y sont."""
    if not blob or len(blob) < 8 or blob[:2] != _MAGIE:
        return None

    drapeaux = blob[3]

    if drapeaux & _VIDE or not (drapeaux >> 1) & 0x07:
        return None

    return struct.unpack_from("<4d", blob, 8)


def _declarer_fonctions(connexion: sqlite3.Connection) -> None:
    """Fournit à SQLite les fonctions spatiales dont le GeoPackage a besoin.

    Un GeoPackage indexé porte des déclencheurs qui appellent `ST_IsEmpty`,
    `ST_MinX`, `ST_MaxX`, `ST_MinY` et `ST_MaxY` — des fonctions que GDAL et
    SpatiaLite enregistrent, mais que le module `sqlite3` de la bibliothèque
    standard ne connaît pas. Les déclarer ici laisse les déclencheurs faire
    leur travail : l'index R-Tree reste cohérent, et le schéma du fichier n'est
    pas touché.

    Elles se contentent de relire l'en-tête écrit par `encoder_geometrie()` :
    aucune n'a besoin de décoder la géométrie elle-même.
    """

    def est_vide(blob: bytes | None) -> int:
        return 0 if _enveloppe(blob) else 1

    def borne(indice: int):
        def lire(blob: bytes | None) -> float | None:
            bornes = _enveloppe(blob)
            return bornes[indice] if bornes else None

        return lire

    connexion.create_function("ST_IsEmpty", 1, est_vide)
    connexion.create_function("ST_MinX", 1, borne(0))
    connexion.create_function("ST_MaxX", 1, borne(1))
    connexion.create_function("ST_MinY", 1, borne(2))
    connexion.create_function("ST_MaxY", 1, borne(3))


def ouvrir(chemin: str) -> sqlite3.Connection:
    """Connexion au GeoPackage, prête pour un remplissage de masse."""
    connexion = sqlite3.connect(chemin)

    # Le fichier est un temporaire recréé à chaque ouverture d'unité : sa
    # durabilité n'a aucun intérêt, sa vitesse d'écriture en a une.
    connexion.execute("PRAGMA journal_mode = MEMORY")
    connexion.execute("PRAGMA synchronous = OFF")
    # Les déclencheurs entretiennent l'index R-Tree et les compteurs OGR.
    connexion.execute("PRAGMA foreign_keys = OFF")

    _declarer_fonctions(connexion)

    return connexion


def tables_de_donnees(connexion: sqlite3.Connection) -> set[str]:
    """Tables déclarées dans `gpkg_contents` (couches, pas métadonnées)."""
    return {
        ligne[0]
        for ligne in connexion.execute(
            "SELECT table_name FROM gpkg_contents "
            "WHERE data_type IN ('features', 'attributes')"
        )
    }


def colonnes(connexion: sqlite3.Connection, table: str) -> dict[str, str]:
    """Colonnes de la table, nom → type déclaré, dans l'ordre du schéma."""
    return {
        ligne[1]: (ligne[2] or "").upper()
        for ligne in connexion.execute(f'PRAGMA table_info("{_nom(table)}")')
    }


def colonne_geometrie(
    connexion: sqlite3.Connection, table: str
) -> tuple[str, int] | None:
    """Colonne géométrique de la table et son SRID, ou `None` si attributaire."""
    ligne = connexion.execute(
        "SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
        (table,),
    ).fetchone()

    return (ligne[0], int(ligne[1])) if ligne else None


def vider(connexion: sqlite3.Connection, tables: set[str]) -> int:
    """Efface le contenu des tables données.

    Un simple `DELETE` : les déclencheurs du GeoPackage retirent au passage les
    entrées correspondantes de l'index R-Tree. `TRUNCATE` n'existe pas en
    SQLite, et l'optimisation « truncate » de `DELETE FROM` sans clause
    court-circuiterait justement ces déclencheurs.
    """
    total = 0

    for table in sorted(tables):
        curseur = connexion.execute(f'DELETE FROM "{_nom(table)}"')
        total += curseur.rowcount if curseur.rowcount > 0 else 0

    return total


def inserer(
    connexion: sqlite3.Connection,
    table: str,
    noms_colonnes: list[str],
    lignes: list[tuple[Any, ...]],
) -> int:
    """Insère des lignes déjà converties. `fid` est laissé à SQLite."""
    if not lignes:
        return 0

    colonnes_sql = ", ".join(f'"{_nom(nom)}"' for nom in noms_colonnes)
    valeurs_sql = ", ".join("?" * len(noms_colonnes))

    connexion.executemany(
        f'INSERT INTO "{_nom(table)}" ({colonnes_sql}) VALUES ({valeurs_sql})',
        lignes,
    )

    return len(lignes)


def recompter(connexion: sqlite3.Connection, tables: set[str]) -> None:
    """Remet à jour `gpkg_ogr_contents`, le compteur d'entités de GDAL.

    Les déclencheurs qui l'entretiennent incrémentent une valeur ; partant de
    `NULL`, ils laissent `NULL` — ce que GDAL interprète comme « inconnu » et
    corrige par un décompte complet. On lui épargne ce parcours.
    """
    existe = connexion.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gpkg_ogr_contents'"
    ).fetchone()

    if not existe:
        return

    for table in sorted(tables):
        nombre = connexion.execute(f'SELECT count(*) FROM "{_nom(table)}"').fetchone()[
            0
        ]
        connexion.execute(
            "UPDATE gpkg_ogr_contents SET feature_count = ? WHERE table_name = ?",
            (nombre, table),
        )


def renommer_tables(chemin: str, renommages: dict[str, str]) -> dict[str, str]:
    """Rend aux tables du GeoPackage leur nom métier. Rend ce qui a été fait.

    ---------------------------------------------------------------------------
    POURQUOI
    ---------------------------------------------------------------------------
    QFieldSync nomme les tables du GeoPackage par une empreinte de leur source :

        01cc1aa29a7eb404546021831f4943c7c9621632992f5bd6f2d99b5ab6c4bc78

    C'est sans importance pour QField, qui suit les couches du projet. Mais
    l'étape de validation et d'insertion du flux `delta_apply` reconnaît un
    GeoPackage IFE **à ses noms de tables** — elle cherche `mesurage` et
    `infor_gener` — et passe son chemin quand elle ne les trouve pas. Rendre
    leur nom aux tables suffit à ce qu'elle voie enfin le fichier.

    Rien ne se perd au passage : la correspondance empreinte → table métier est
    bijective, et c'est le projet lui-même qui la porte
    (`paquet.correspondances()`).

    ---------------------------------------------------------------------------
    POURQUOI GDAL
    ---------------------------------------------------------------------------
    Renommer une table d'un GeoPackage n'est pas un `ALTER TABLE` : il faut
    suivre `gpkg_contents`, `gpkg_geometry_columns`, `gpkg_extensions`, l'index
    R-Tree et ses déclencheurs, et ce que la spécification y ajoutera demain. Le
    pilote GPKG de GDAL le fait depuis la 3.5 (`OGRLayer::Rename()`), et c'est
    la seule raison pour laquelle ce module dépend de GDAL.

    Un renommage refusé n'interrompt pas la préparation : le projet reste
    utilisable, seule la validation ne verra pas la table. Le journal le dit.
    """
    if not renommages:
        return {}

    # Import local : le reste du module n'a besoin que de `sqlite3`, et une
    # installation sans les liaisons Python de GDAL doit encore pouvoir servir
    # une recherche d'unités.
    from osgeo import gdal, ogr

    gdal.UseExceptions()

    source = gdal.OpenEx(chemin, gdal.OF_VECTOR | gdal.OF_UPDATE)

    if source is None:
        logger.warning("[IFA] GeoPackage illisible par GDAL : %s", chemin)
        return {}

    faits: dict[str, str] = {}

    try:
        for ancien in sorted(renommages):
            nouveau = renommages[ancien]

            if ancien == nouveau:
                continue

            couche = source.GetLayerByName(ancien)

            if couche is None:
                logger.warning("[IFA] table absente du GeoPackage : %s", ancien[:12])
                continue

            try:
                couche.Rename(nouveau)
            except (RuntimeError, ogr.OGRError) as erreur:
                logger.warning(
                    "[IFA] renommage refuse %s → %s : %s", ancien[:12], nouveau, erreur
                )
                continue

            faits[ancien] = nouveau
    finally:
        # Ferme le jeu de données : c'est la fermeture qui écrit.
        source = None

    logger.info("[IFA] %s table(s) renommee(s) dans le GeoPackage", len(faits))

    return faits


def convertir(valeur: Any) -> Any:
    """Valeur PostgreSQL → valeur acceptée par le pilote `sqlite3`.

    SQLite ne connaît que cinq types de stockage. Les dates partent en texte
    ISO 8601, forme que le pilote GeoPackage de QGIS relit sans ambiguïté ; les
    décimaux exacts deviennent des flottants, ce que le GeoPackage stocke de
    toute façon (`REAL`).
    """
    if valeur is None or isinstance(valeur, (int, float, str, bytes)):
        return valeur

    if isinstance(valeur, bool):
        return int(valeur)

    if isinstance(valeur, Decimal):
        return float(valeur)

    if isinstance(valeur, (datetime.datetime, datetime.date, datetime.time)):
        return valeur.isoformat()

    if isinstance(valeur, uuid.UUID):
        return str(valeur)

    if isinstance(valeur, memoryview):
        return valeur.tobytes()

    return str(valeur)


def _nom(identifiant: str) -> str:
    """Identifiant SQLite échappé pour une interpolation entre guillemets.

    Les noms de tables viennent du projet packagé (empreintes hexadécimales) et
    les noms de colonnes du schéma métier : aucun n'est saisi par un client.
    Le doublement des guillemets reste la précaution qui coûte le moins cher.
    """
    return identifiant.replace('"', '""')
