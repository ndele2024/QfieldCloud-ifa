"""
core.gpkg_reader — Lecture d'un GeoPackage (.gpkg) en mémoire, sans
dépendance à PyQGIS.

Pourquoi pas PyQGIS ici : ce programme doit pouvoir tourner plus tard dans
le conteneur QFieldCloud, qui ne fournit PAS les bibliothèques QGIS (c'est
un environnement Django/Python "nu"). On utilise donc uniquement des
bibliothèques disponibles via pip : `geopandas` (qui s'appuie sur `pyogrio`
ou `fiona`/GDAL pour le format GeoPackage).

Les géométries sont converties en WKT (texte) pour rester facilement
sérialisables (JSON, dict Python simples) ; le moteur de règles n'a besoin
des géométries que ponctuellement (ex. filtre spatial), pas de manipulation
géométrique avancée.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import fiona


def list_layers(gpkg_path: str | Path) -> list[str]:
    """Retourne la liste des couches (tables) présentes dans le GeoPackage."""
    return list(fiona.listlayers(str(gpkg_path)))


def _clean_value(value: Any) -> Any:
    """Normalise une valeur issue de GeoPandas/NumPy vers un type Python
    natif JSON-sérialisable, et convertit NaN -> None (GeoPandas utilise
    NaN pour représenter les cellules NULL sur les colonnes numériques)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):  # types numpy (int64, float64, bool_...)
        return value.item()
    return value


def read_layer(gpkg_path: str | Path, layer: str) -> list[dict[str, Any]]:
    """Lit une couche du GeoPackage et la retourne comme une liste de dict
    (un dict par enregistrement). La géométrie, si présente, est exposée
    sous la clé "geometry" en WKT (chaîne) plutôt qu'en objet Shapely."""
    gdf = gpd.read_file(str(gpkg_path), layer=layer)
    records: list[dict[str, Any]] = []
    has_geom = "geometry" in gdf.columns

    for _, row in gdf.iterrows():
        record = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            record[col] = _clean_value(row[col])
        if has_geom and row["geometry"] is not None:
            record["geometry"] = row["geometry"].wkt
        else:
            record["geometry"] = None
        records.append(record)

    return records


def read_gpkg(gpkg_path: str | Path, layers: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Lit toutes les couches demandées d'un GeoPackage.

    Args:
        gpkg_path: chemin du fichier .gpkg.
        layers: couches à lire ; si None, lit TOUTES les couches présentes
            dans le fichier (utile pour un GeoPackage dont on ne connaît
            pas le contenu exact à l'avance).

    Returns:
        { nom_couche: [enregistrements...] }. Une couche demandée mais
        absente du fichier est simplement omise (voir engine.py pour le
        traitement de cet écart).
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
