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
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


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


def read_layer(gpkg_path: str | Path, layer: str) -> list[dict[str, Any]]:
    """Lit une couche et la retourne comme liste de dict.

    Les colonnes géométriques (binary GPKG) sont silencieusement exclues.
    Toutes les autres colonnes sont retournées avec leur type Python natif
    (int, float, str, None) — aucune dépendance NumPy/pandas."""
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
        records.append(record)

    con.close()
    return records


def read_gpkg(
    gpkg_path: str | Path,
    layers: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Lit toutes les couches demandées d'un GeoPackage.

    Args:
        gpkg_path: chemin du fichier .gpkg.
        layers: couches à lire ; si None, lit TOUTES les couches présentes.

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
        layer: read_layer(gpkg_path, layer)
        for layer in target_layers
        if layer in available
    }
