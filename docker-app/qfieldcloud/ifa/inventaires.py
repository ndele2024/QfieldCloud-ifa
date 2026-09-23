"""Copie d'un sous-ensemble du schéma métier dans un GeoPackage.

Le projet modèle a été packagé sur les vues `ifa_qfield`, qui ne portent pas de
données : elles servent la saisie d'une nouvelle unité. Les inventaires déjà
réalisés vivent dans le schéma métier (`ifa_data`). Le remplissage lit donc
toujours `settings.IFA_DB_SCHEMA`, quel que soit le schéma que le projet modèle
nommait — c'est la même table, au même nom, dans le schéma qui a les lignes.

Ce qu'il faut copier n'est pas toujours la même chose. « Ouvrir une UE » ne
demande qu'une unité ; « Créer une UE » embarque celles d'une région, d'un plan
d'eau ou d'une emprise tracée. Les deux se disent avec le même objet, une
`Selection` : un fragment de `WHERE` portant sur `une_code_ident`, ses
paramètres, et le plafond de lignes qu'on s'autorise. Le reste du module ne
connaît que cela.

Les tables sont appariées par nom, et les colonnes par intersection : le
GeoPackage produit par QFieldSync porte exactement les colonnes de la couche,
`qgis_id` compris. Copier `qgis_id` n'est pas une commodité — c'est la clé que
QField inscrit dans ses deltas, donc ce qui permettra de retrouver la ligne
d'origine dans PostgreSQL.

Trois tables du projet n'ont pas de colonne `une_code_ident` : ce sont des
référentiels (`proje_sonda`, `type_unite_echan`, `versi_type_unite_echan`).
Elles sont copiées en entier — sans elles, les listes déroulantes des
formulaires seraient vides.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from qfieldcloud.ifa import db, gpkg
from qfieldcloud.ifa.exceptions import FiltreInvalideError
from qfieldcloud.ifa.paquet import Correspondance

logger = logging.getLogger(__name__)

# Colonne de rattachement d'un inventaire à son unité.
COLONNE_UNITE = "une_code_ident"

# La clé primaire du GeoPackage est gérée par SQLite : la reprendre de
# PostgreSQL ferait entrer en collision deux tables qui n'ont pas la même
# histoire.
COLONNE_FID = "fid"

# Les lignes sont remontées par paquets : une unité tient largement en mémoire,
# mais rien n'oblige à charger d'un coup les référentiels.
TAILLE_LOT = 2000


@dataclass(frozen=True)
class Selection:
    """Les lignes à embarquer, dites en SQL.

    `condition` est un fragment de `WHERE` portant sur la table copiée — il ne
    s'applique qu'aux tables qui ont une colonne `une_code_ident`. Les trois
    référentiels qui n'en ont pas (`proje_sonda`, `type_unite_echan`,
    `versi_type_unite_echan`) sont copiés en entier quelle que soit la
    sélection : sans eux, les listes déroulantes des formulaires seraient
    vides.

    `lignes_max` est un garde-fou, pas une pagination : il n'écrête pas le
    résultat, il interrompt le remplissage. Un filtre qui n'a pas mordu doit
    échouer bruyamment plutôt que de fabriquer un GeoPackage de plusieurs
    gigaoctets qu'un appareil de terrain ne téléchargera jamais.
    """

    libelle: str
    lignes_max: int
    condition: str = ""
    parametres: list[Any] = field(default_factory=list)

    @classmethod
    def pour_unite(cls, une_code_ident: str, lignes_max: int) -> Selection:
        """Les inventaires d'une seule unité — « Ouvrir une UE »."""
        return cls(
            libelle=f"unité {une_code_ident}",
            lignes_max=lignes_max,
            condition=f'"{COLONNE_UNITE}" = %s',
            parametres=[une_code_ident],
        )

    @classmethod
    def pour_unites(
        cls, codes: Sequence[str], libelle: str, lignes_max: int
    ) -> Selection:
        """Les inventaires d'une liste d'unités — « Créer une UE ».

        Le filtre est un `= ANY(%s)` et non un `IN (SELECT …)` : la liste des
        unités a déjà été résolue une fois, en amont. La rejouer dans chacune
        des trente-sept tables referait autant de fois la jointure qui la
        produit — un quart de seconde par table pour un filtre par région.
        """
        return cls(
            libelle=libelle,
            lignes_max=lignes_max,
            condition=f'"{COLONNE_UNITE}" = ANY(%s)',
            parametres=[list(codes)],
        )


def remplir(
    chemin_gpkg: str,
    correspondances: Iterable[Correspondance],
    selection: Selection,
) -> dict[str, int]:
    """Vide le GeoPackage puis y écrit les lignes de la sélection.

    Renvoie le nombre de lignes écrites, par table métier.
    """
    liste = _dedupliquer(correspondances)
    schema = db.schema()
    connexion = gpkg.ouvrir(chemin_gpkg)

    try:
        disponibles = gpkg.tables_de_donnees(connexion)
        cibles = {c.table_gpkg for c in liste} & disponibles

        effacees = gpkg.vider(connexion, cibles)
        logger.info("[IFA] %s lignes effacees dans le GeoPackage", effacees)

        with db.curseur() as cur:
            structure = _structure_postgresql(cur, schema, {c.table_pg for c in liste})
            ecrites = _copier(
                cur,
                connexion,
                schema,
                structure,
                liste,
                disponibles,
                selection,
            )

        gpkg.recompter(connexion, cibles)
        connexion.commit()
    finally:
        connexion.close()

    return ecrites


def _dedupliquer(correspondances: Iterable[Correspondance]) -> list[Correspondance]:
    """Une entrée par table du GeoPackage.

    Le projet compte 92 couches pour 37 tables : plusieurs couches montrent la
    même table sous des filtres ou des symbologies différents, et QFieldSync
    les a toutes converties vers la même table du `data.gpkg`. Les copier une
    fois par couche y écrirait chaque ligne autant de fois.
    """
    retenues: dict[str, Correspondance] = {}

    for correspondance in correspondances:
        connue = retenues.get(correspondance.table_gpkg)

        if connue is None:
            retenues[correspondance.table_gpkg] = correspondance
        elif connue.table_pg != correspondance.table_pg:
            logger.warning(
                "[IFA] deux tables sources pour %s : %s et %s — %s retenue",
                correspondance.table_gpkg[:12],
                connue.qualifie,
                correspondance.qualifie,
                connue.qualifie,
            )

    return list(retenues.values())


def _copier(
    cur: Any,
    connexion: Any,
    schema: str,
    structure: dict[str, dict[str, str]],
    correspondances: list[Correspondance],
    disponibles: set[str],
    selection: Selection,
) -> dict[str, int]:
    ecrites: dict[str, int] = {}
    total = 0

    for correspondance in correspondances:
        table_pg = correspondance.table_pg
        table_gpkg = correspondance.table_gpkg

        if table_gpkg not in disponibles:
            logger.warning(
                "[IFA] table absente du GeoPackage modele : %s (%s)",
                table_gpkg[:12],
                table_pg,
            )
            continue

        colonnes_pg = structure.get(table_pg)

        if not colonnes_pg:
            logger.warning("[IFA] table absente du schema %s : %s", schema, table_pg)
            continue

        colonnes_gpkg = gpkg.colonnes(connexion, table_gpkg)
        geometrie = gpkg.colonne_geometrie(connexion, table_gpkg)

        communes = [
            nom
            for nom in colonnes_gpkg
            if nom != COLONNE_FID
            and nom in colonnes_pg
            and not (geometrie and nom == geometrie[0])
        ]

        if not communes:
            logger.warning("[IFA] aucune colonne commune pour %s", table_pg)
            continue

        nombre = _copier_table(
            cur,
            connexion,
            schema,
            table_pg,
            table_gpkg,
            communes,
            geometrie,
            _colonne_geometrie(colonnes_pg),
            selection if COLONNE_UNITE in colonnes_pg else None,
        )

        ecrites[table_pg] = nombre
        total += nombre

        if total > selection.lignes_max:
            raise FiltreInvalideError(
                f"La sélection ({selection.libelle}) porte plus de "
                f"{selection.lignes_max} enregistrements : préparation "
                "interrompue. Restreignez les données à embarquer.",
            )

    logger.info(
        "[IFA] %s : %s lignes ecrites dans %s tables",
        selection.libelle,
        total,
        len([n for n in ecrites.values() if n]),
    )

    return ecrites


def _copier_table(
    cur: Any,
    connexion: Any,
    schema: str,
    table_pg: str,
    table_gpkg: str,
    colonnes: list[str],
    geometrie_gpkg: tuple[str, int] | None,
    colonne_geometrie_pg: str | None,
    selection: Selection | None,
) -> int:
    """Lit une table du schéma métier et écrit ses lignes dans le GeoPackage.

    `selection` à `None` copie la table entière : c'est le cas des trois
    référentiels, qui n'ont pas de colonne `une_code_ident` sur laquelle
    filtrer.
    """
    avec_geometrie = bool(geometrie_gpkg and colonne_geometrie_pg)
    colonnes_lues = [f'"{_ident(nom)}"' for nom in colonnes]
    colonnes_cibles = list(colonnes)
    srid = geometrie_gpkg[1] if geometrie_gpkg else 0

    if avec_geometrie:
        colonnes_lues.extend(_expressions_geometrie(colonne_geometrie_pg, srid))
        colonnes_cibles.append(geometrie_gpkg[0])

    requete = f'SELECT {", ".join(colonnes_lues)} FROM {schema}."{_ident(table_pg)}"'
    parametres: list[Any] = []

    if selection is not None and selection.condition:
        requete += f" WHERE {selection.condition}"
        parametres.extend(selection.parametres)

    cur.execute(requete, parametres)

    nombre = 0

    while True:
        lot = cur.fetchmany(TAILLE_LOT)

        if not lot:
            break

        converties = [_convertir_ligne(ligne, avec_geometrie, srid) for ligne in lot]
        nombre += gpkg.inserer(connexion, table_gpkg, colonnes_cibles, converties)

    return nombre


def _convertir_ligne(
    ligne: tuple[Any, ...], avec_geometrie: bool, srid: int
) -> tuple[Any, ...]:
    if not avec_geometrie:
        return tuple(gpkg.convertir(valeur) for valeur in ligne)

    attributs = ligne[:-5]
    geometrie, minx, maxx, miny, maxy = ligne[-5:]

    return (
        *(gpkg.convertir(valeur) for valeur in attributs),
        gpkg.encoder_geometrie(geometrie, srid, (minx, maxx, miny, maxy)),
    )


def _expressions_geometrie(colonne: str, srid_cible: int) -> list[str]:
    """La géométrie en WKB, suivie de ses quatre bornes.

    PostGIS calcule l'enveloppe bien mieux qu'on ne la recalculerait : elle
    part avec la géométrie et se retrouve dans l'en-tête du blob GeoPackage,
    où les déclencheurs de l'index R-Tree iront la lire (voir
    `gpkg._declarer_fonctions`).

    La reprojection ne sert à rien aujourd'hui — schéma métier et projet sont
    tous deux en EPSG:32187 — mais elle évite qu'un changement de SRID d'un
    côté ne dépose silencieusement les géométries au mauvais endroit.
    """
    reference = f'"{_ident(colonne)}"'

    if srid_cible and srid_cible != settings.IFA_DB_SRID:
        reference = f"ST_Transform({reference}, {int(srid_cible)})"

    return [
        f"ST_AsBinary({reference})",
        f"ST_XMin({reference})",
        f"ST_XMax({reference})",
        f"ST_YMin({reference})",
        f"ST_YMax({reference})",
    ]


def _structure_postgresql(
    cur: Any, schema: str, tables: set[str]
) -> dict[str, dict[str, str]]:
    """Colonnes des tables demandées, table → {colonne: type PostgreSQL}."""
    if not tables:
        return {}

    cur.execute(
        """
        SELECT c.relname, a.attname, t.typname
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_type t ON t.oid = a.atttypid
         WHERE n.nspname = %s
           AND c.relname = ANY(%s)
           AND c.relkind IN ('r', 'v', 'm', 'f', 'p')
           AND a.attnum > 0
           AND NOT a.attisdropped
         ORDER BY c.relname, a.attnum
        """,
        [schema, sorted(tables)],
    )

    structure: dict[str, dict[str, str]] = {}

    for table, colonne, type_pg in cur.fetchall():
        structure.setdefault(table, {})[colonne] = type_pg

    return structure


def _colonne_geometrie(colonnes: dict[str, str]) -> str | None:
    """Première colonne de type `geometry` de la table, s'il y en a une."""
    for nom, type_pg in colonnes.items():
        if type_pg == "geometry":
            return nom

    return None


def _ident(identifiant: str) -> str:
    return identifiant.replace('"', '""')
