"""
core.inserter — Insertion des enregistrements validés dans PostgreSQL.

L'insertion se fait dans UNE SEULE transaction couvrant toutes les
couches : soit tout le lot est inséré, soit rien ne l'est (cohérent avec
la consigne "si toutes les données sont valides, elles sont insérées" —
une erreur d'insertion partielle laisserait la base dans un état
incohérent, pire qu'un rejet complet).

L'ordre d'insertion respecte la hiérarchie parent → enfant (mesurage en
premier) pour ne jamais violer une contrainte de clé étrangère.
"""

from __future__ import annotations

from typing import Any

# Ordre d'insertion : un parent doit toujours être inséré avant ses enfants.
# Tenu en synchronisation avec IPE_TABLE_ORDER de generate_ipe_form.py /
# extract_ipe_subset.py — si la hiérarchie des tables IPE change côté base
# de données, répercuter le changement ici également.
INSERT_ORDER = [
    "mesurage", "infor_gener", "equipe",
    "amenagement", "espec_amena",
    "analy_physi_chimi", "profi_mesur", "resul_analy_physi_chimi",
    "autre_obser_fauni",
    "descr_habit", "forme_descr_habit",
    "habitat", "espec_habit", "forme_eleme_habit",
    "peche_exper", "pose_levee_filet", "denom_espec", "detail_speci",
    "perturbation",
    "ensemencement", "marqu_ensem",
]


def _insert_rows(cur, table: str, rows: list[dict[str, Any]], pg_schema: str) -> int:
    """Insère tous les enregistrements de `rows` dans `pg_schema.table`.
    Toutes les lignes d'une même couche sont supposées avoir le même
    ensemble de colonnes (issu du schéma GeoPackage) ; la clé "geometry"
    (ajoutée par gpkg_reader, en WKT) est traduite en ST_GeomFromText si
    présente, sinon ignorée."""
    if not rows:
        return 0

    # Exclure "fid" : c'est la clé primaire propre au GeoPackage (ajoutée pour
    # rendre les couches modifiables dans QField). Elle n'existe pas dans les
    # tables PostgreSQL, qui gèrent leur propre identité.
    columns = [c for c in rows[0].keys() if c not in ("geometry", "fid")]
    has_geom = "geometry" in rows[0]

    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    geom_clause = ', ST_GeomFromText(%s, 32187)' if has_geom else ""
    geom_col = ', "shape"' if has_geom else ""

    sql = f'INSERT INTO {pg_schema}."{table}" ({col_list}{geom_col}) VALUES ({placeholders}{geom_clause})'

    count = 0
    for row in rows:
        values = [row.get(c) for c in columns]
        if has_geom:
            values.append(row.get("geometry"))
        cur.execute(sql, values)
        count += 1
    return count


def insert_all(layers: dict[str, list[dict[str, Any]]], conn, pg_schema: str = "ifa_data") -> dict[str, int]:
    """Insère toutes les couches de `layers` dans une unique transaction.

    Args:
        layers: { nom_couche: [enregistrements...] } (déjà validés —
            ce module ne revalide rien, voir engine.py pour l'orchestration).
        conn: connexion psycopg2/psycopg OUVERTE (autocommit désactivé ;
            ce module appelle conn.commit() lui-même en cas de succès, ou
            conn.rollback() et relève l'exception en cas d'échec).
        pg_schema: schéma PostgreSQL cible.

    Returns:
        { nom_couche: nombre de lignes insérées }.

    Raises:
        Toute exception levée par le driver (ex. psycopg2.Error) est
        propagée après rollback — l'appelant décide comment la rapporter.
    """
    cur = conn.cursor()
    counts: dict[str, int] = {}
    try:
        ordered = [t for t in INSERT_ORDER if t in layers] + \
                  [t for t in layers if t not in INSERT_ORDER]
        for table in ordered:
            counts[table] = _insert_rows(cur, table, layers[table], pg_schema)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return counts
