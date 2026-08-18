"""
generate_column_aliases.py — Convertit "table-colonne-allias.xlsx" en un
fichier JSON de configuration (column_aliases.json) lu à l'exécution par
core/db_schema.py pour produire des messages d'erreur lisibles.

POURQUOI un JSON intermédiaire plutôt qu'une lecture directe du .xlsx :
  - lire un .xlsx demande une bibliothèque tierce (openpyxl/pandas) ; le
    programme doit pouvoir tourner dans le conteneur QFieldCloud avec le
    moins de dépendances possible. Le JSON se lit avec le module `json` de
    la bibliothèque standard.
  - le classeur est une donnée de référence qui ne change qu'occasionnellement :
    le relire à chaque validation serait du gaspillage.

Ce script n'a lui non plus AUCUNE dépendance : un fichier .xlsx est une
archive ZIP de documents XML, que `zipfile` + `xml.etree` savent déjà lire.

Usage (à relancer si le classeur est mis à jour) :

    python generate_column_aliases.py
    python generate_column_aliases.py --xlsx autre.xlsx --out autre.json
"""

from __future__ import annotations

import argparse
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Colonnes attendues dans la première feuille du classeur.
COLONNE_TABLE = "A"
COLONNE_CHAMP = "B"
COLONNE_ALIAS = "C"


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Table des chaînes partagées du classeur (les cellules texte d'un
    .xlsx référencent un index dans cette table plutôt que le texte lui-même)."""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    racine = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.iter(f"{NS}t"))
        for si in racine.iter(f"{NS}si")
    ]


def _valeur_cellule(cellule: ET.Element, shared: list[str]) -> str:
    """Texte d'une cellule, en résolvant les deux formes de stockage du
    format xlsx : référence à la table partagée (t="s") ou texte en ligne."""
    type_cellule = cellule.get("t")
    valeur = cellule.find(f"{NS}v")
    if type_cellule == "s":
        return shared[int(valeur.text)] if valeur is not None else ""
    if type_cellule == "inlineStr":
        return "".join(t.text or "" for t in cellule.iter(f"{NS}t"))
    return valeur.text if valeur is not None else ""


def lire_classeur(chemin_xlsx: str | Path) -> dict[str, dict[str, str]]:
    """Lit le classeur et retourne { table: { colonne: alias } }.

    Les noms de table et de colonne sont normalisés en minuscules, pour
    correspondre aux noms utilisés partout ailleurs dans le programme
    (couches du GeoPackage, clés des enregistrements, schéma PostgreSQL).

    L'alias dépend du COUPLE (table, colonne) et non de la seule colonne :
    plusieurs colonnes portent un libellé différent selon la table
    (ex. EFA_CODE = « Espèce » dans DETAIL_SPECI mais « Espèce visée » dans
    PECHE_EXPER). D'où l'imbrication à deux niveaux.
    """
    with zipfile.ZipFile(chemin_xlsx) as archive:
        shared = _shared_strings(archive)
        feuille = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

        alias_par_table: dict[str, dict[str, str]] = {}
        for index, ligne in enumerate(feuille.iter(f"{NS}row")):
            cellules = {
                cellule.get("r").rstrip("0123456789"): _valeur_cellule(cellule, shared)
                for cellule in ligne.iter(f"{NS}c")
            }
            table = cellules.get(COLONNE_TABLE, "").strip()
            champ = cellules.get(COLONNE_CHAMP, "").strip()
            alias = cellules.get(COLONNE_ALIAS, "").strip()

            if index == 0:
                continue  # ligne d'en-tête
            if not table or not champ or not alias:
                continue  # ligne incomplète : rien d'exploitable

            alias_par_table.setdefault(table.lower(), {})[champ.lower()] = alias

    return alias_par_table


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--xlsx", default="table-colonne-allias.xlsx",
                          help="classeur source (défaut : table-colonne-allias.xlsx)")
    parseur.add_argument("--out", default="column_aliases.json",
                          help="fichier JSON à produire (défaut : column_aliases.json)")
    args = parseur.parse_args()

    alias_par_table = lire_classeur(args.xlsx)

    contenu = {
        "_commentaire": (
            "Généré par generate_column_aliases.py à partir de "
            f"{Path(args.xlsx).name} — ne pas modifier à la main, "
            "relancer le script si le classeur change."
        ),
        "tables": alias_par_table,
    }
    Path(args.out).write_text(
        json.dumps(contenu, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    nb_alias = sum(len(colonnes) for colonnes in alias_par_table.values())
    print(f"{args.out} : {len(alias_par_table)} tables, {nb_alias} alias.")


if __name__ == "__main__":
    main()
