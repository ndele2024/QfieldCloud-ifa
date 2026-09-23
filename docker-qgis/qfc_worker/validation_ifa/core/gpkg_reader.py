"""
core.gpkg_reader — Lecture d'un GeoPackage (.gpkg) via sqlite3 (stdlib).

Un GeoPackage EST du SQLite standard : la bibliothèque standard `sqlite3`
suffit à le lire, sans aucune dépendance à geopandas/fiona/GDAL. Ce lecteur
est ainsi identique à la version déployée dans QFieldCloud
(docker-qgis/qfc_worker/validation_ifa/core/gpkg_reader.py), où les
bibliothèques GIS Python ne sont pas installées.

Les géométries binaires GPKG (GeoPackageBinary) sont ignorées : le moteur
de validation n'effectue aucune opération géométrique (les règles métier IPE
sont purement attributaires). La clé "geometry" est absente des enregistrements
retournés, ce que le moteur tolère sans modification.

Filtrage des inventaires déjà validés : un inventaire (identifié par
« une_code_ident ») dont un mesurage porte mes_ind_valid = 'O' a déjà passé
la validation lors d'une synchronisation précédente. Tous ses enregistrements,
dans TOUTES les couches, sont écartés de la lecture (voir
inventaires_valides / read_gpkg). Après une validation réussie, le moteur
marque les inventaires traités via marquer_inventaires_valides.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

# Couche, colonne et valeur qui signalent un inventaire déjà validé.
TABLE_MESURAGE = "mesurage"
CHAMP_INVENTAIRE = "une_code_ident"
CHAMP_VALIDE = "mes_ind_valid"
VALEUR_VALIDE = "O"


def list_layers(gpkg_path: str | Path) -> list[str]:
    """Retourne la liste des couches déclarées dans gpkg_contents."""
    con = sqlite3.connect(str(gpkg_path))
    cur = con.cursor()
    cur.execute("SELECT table_name FROM gpkg_contents ORDER BY table_name")
    tables = [row[0] for row in cur.fetchall()]
    con.close()
    return tables


def _geom_columns(con: sqlite3.Connection) -> dict[str, str]:
    """Retourne un dict {table_name: geom_column_name} pour toutes les tables
    géométriques déclarées dans gpkg_geometry_columns."""
    try:
        cur = con.cursor()
        cur.execute("SELECT table_name, column_name FROM gpkg_geometry_columns")
        return {row[0]: row[1] for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return {}


def _colonnes(con: sqlite3.Connection, table: str) -> set[str]:
    """Noms des colonnes de `table` (ensemble vide si la table n'existe pas)."""
    return {row[1] for row in con.execute(f'PRAGMA table_info("{table}")')}


def inventaires_valides(gpkg_path: str | Path) -> set[str]:
    """Retourne les « une_code_ident » dont au moins un mesurage porte
    mes_ind_valid = 'O' (comparaison insensible à la casse et aux espaces).

    Ensemble vide si le GeoPackage n'a pas de couche mesurage, ou si celle-ci
    n'a pas les colonnes attendues : rien n'est alors filtré."""
    con = sqlite3.connect(str(gpkg_path))
    try:
        if not {CHAMP_INVENTAIRE, CHAMP_VALIDE} <= _colonnes(con, TABLE_MESURAGE):
            return set()
        cur = con.execute(
            f'SELECT DISTINCT "{CHAMP_INVENTAIRE}" FROM "{TABLE_MESURAGE}" '
            f'WHERE UPPER(TRIM("{CHAMP_VALIDE}")) = ? AND "{CHAMP_INVENTAIRE}" IS NOT NULL',
            (VALEUR_VALIDE,),
        )
        return {row[0] for row in cur.fetchall()}
    finally:
        con.close()


def marquer_inventaires_valides(gpkg_path: str | Path, codes: Iterable[str]) -> int:
    """Passe mes_ind_valid à 'O' pour tous les mesurages des inventaires
    `codes` dans la couche mesurage du GeoPackage.

    Returns:
        Le nombre de lignes modifiées (0 si la couche ou la colonne est
        absente du GeoPackage, ou si `codes` est vide).
    """
    codes = sorted(set(codes))
    if not codes:
        return 0
    con = sqlite3.connect(str(gpkg_path))
    try:
        if not {CHAMP_INVENTAIRE, CHAMP_VALIDE} <= _colonnes(con, TABLE_MESURAGE):
            return 0
        marqueurs = ", ".join("?" for _ in codes)
        cur = con.execute(
            f'UPDATE "{TABLE_MESURAGE}" SET "{CHAMP_VALIDE}" = ? '
            f'WHERE "{CHAMP_INVENTAIRE}" IN ({marqueurs})',
            (VALEUR_VALIDE, *codes),
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def read_layer(gpkg_path: str | Path, layer: str,
               exclure_inventaires: set[str] | None = None) -> list[dict[str, Any]]:
    """Lit une couche et la retourne comme liste de dict.

    Les colonnes géométriques (binary GPKG) sont silencieusement exclues.
    Toutes les autres colonnes sont retournées avec leur type Python natif
    (int, float, str, None) — aucune dépendance NumPy/pandas.

    Les enregistrements dont « une_code_ident » figure dans
    `exclure_inventaires` sont écartés (les couches sans cette colonne,
    ex. « projet », sont lues en entier)."""
    con = sqlite3.connect(str(gpkg_path))
    geom_cols = _geom_columns(con)
    geom_col = geom_cols.get(layer)  # None si la couche n'a pas de géométrie

    cur = con.cursor()
    cur.execute(f'SELECT * FROM "{layer}"')

    col_names = [desc[0] for desc in cur.description]
    records: list[dict[str, Any]] = []

    for row in cur.fetchall():
        record: dict[str, Any] = {}
        for col, val in zip(col_names, row):
            if col == geom_col:
                continue  # ignorer la géométrie binaire
            record[col] = val  # None, int, float ou str — sqlite3 natif
        if exclure_inventaires and record.get(CHAMP_INVENTAIRE) in exclure_inventaires:
            continue
        records.append(record)

    con.close()
    return records


def read_gpkg(
    gpkg_path: str | Path,
    layers: list[str] | None = None,
    exclure_inventaires: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Lit toutes les couches demandées d'un GeoPackage.

    Args:
        gpkg_path: chemin du fichier .gpkg.
        layers: couches à lire ; si None, lit TOUTES les couches présentes.
        exclure_inventaires: « une_code_ident » dont les enregistrements
            sont écartés dans toutes les couches (typiquement le résultat
            de inventaires_valides).

    Returns:
        { nom_couche: [enregistrements...] }. Une couche demandée mais
        absente du fichier est simplement omise.
    """
    gpkg_path = Path(gpkg_path)
    if not gpkg_path.exists():
        raise FileNotFoundError(f"GeoPackage introuvable : {gpkg_path}")

    available = set(list_layers(gpkg_path))
    target_layers = layers if layers is not None else sorted(available)

    return {
        layer: read_layer(gpkg_path, layer, exclure_inventaires)
        for layer in target_layers
        if layer in available
    }
