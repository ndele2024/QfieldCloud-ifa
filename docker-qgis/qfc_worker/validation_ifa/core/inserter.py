"""
core.inserter — Insertion des enregistrements validés dans PostgreSQL.

L'insertion se fait dans UNE SEULE transaction couvrant toutes les
couches : soit tout le lot est inséré, soit rien ne l'est (cohérent avec
la consigne "si toutes les données sont valides, elles sont insérées" —
une erreur d'insertion partielle laisserait la base dans un état
incohérent, pire qu'un rejet complet).

L'ordre d'insertion respecte la hiérarchie parent → enfant (mesurage en
premier) pour ne jamais violer une contrainte de clé étrangère.

Un enregistrement déjà présent en base est mis à jour plutôt que rejeté
(ON CONFLICT ... DO UPDATE) : un technicien qui pousse deux fois le même
mesurage depuis QField corrige ses données, il ne crée pas un doublon.
"""

from __future__ import annotations

from typing import Any

from .models import LayerSchema

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

# Couches produites par la validation elle-même : elles n'existent que dans le
# GeoPackage, comme restitution pour le technicien (cf.
# validate_ifa._write_rapport_to_gpkg côté QFieldCloud), et n'ont aucune table
# PostgreSQL correspondante. Sans cette exclusion, le rapport écrit au run
# précédent est relu par gpkg_reader et réinjecté ici : l'INSERT échoue sur une
# relation inexistante et annule tout le lot, à chaque synchronisation.
NON_INSERTABLE_TABLES = frozenset({"rapport_validation"})


def _conflict_clause(primary_key: list[str], columns: list[str], has_geom: bool) -> str:
    """Construit la clause ON CONFLICT ciblant la clé primaire de la table.

    Renvoie une chaîne vide (INSERT nu, donc erreur en cas de doublon) quand
    aucun rapprochement fiable n'est possible : table sans clé primaire, ou
    clé primaire que le GeoPackage ne fournit pas entièrement — typiquement
    une colonne à séquence, où chaque insertion crée légitimement une
    nouvelle ligne et où il n'y a donc pas de conflit à arbitrer.

    Les valeurs de mise à jour proviennent de EXCLUDED, la ligne proposée à
    l'insertion : la géométrie y est déjà convertie par ST_GeomFromText, il
    n'y a donc aucun paramètre supplémentaire à transmettre.
    """
    if not primary_key or not set(primary_key).issubset(columns):
        return ""

    target = ", ".join(f'"{c}"' for c in primary_key)
    updatable = [c for c in columns if c not in primary_key]
    if has_geom:
        updatable.append("shape")

    # Table entièrement composée de sa clé primaire : il n'y a rien à mettre
    # à jour, la ligne existante est déjà identique à celle proposée.
    if not updatable:
        return f" ON CONFLICT ({target}) DO NOTHING"

    assignments = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in updatable)
    return f" ON CONFLICT ({target}) DO UPDATE SET {assignments}"


def _insert_rows(cur, table: str, rows: list[dict[str, Any]], pg_schema: str,
                 primary_key: list[str] | None = None) -> int:
    """Insère tous les enregistrements de `rows` dans `pg_schema.table`, en
    mettant à jour ceux dont la clé primaire `primary_key` existe déjà.
    Toutes les lignes d'une même couche sont supposées avoir le même
    ensemble de colonnes (issu du schéma GeoPackage) ; la clé "geometry"
    (si le lecteur en fournit une, en WKT) est traduite en ST_GeomFromText
    si présente, sinon ignorée.

    Returns:
        Le nombre de lignes réellement affectées (insérées ou mises à jour).
    """
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

    on_conflict = _conflict_clause(primary_key or [], columns, has_geom)
    sql = (f'INSERT INTO {pg_schema}."{table}" ({col_list}{geom_col}) '
           f'VALUES ({placeholders}{geom_clause}){on_conflict}')

    count = 0
    for row in rows:
        values = [row.get(c) for c in columns]
        if has_geom:
            values.append(row.get("geometry"))
        cur.execute(sql, values)
        count += cur.rowcount
    return count


def insert_all(layers: dict[str, list[dict[str, Any]]], conn, pg_schema: str = "ifa_data",
               schemas: dict[str, LayerSchema] | None = None) -> dict[str, int]:
    """Insère toutes les couches de `layers` dans une unique transaction.

    Args:
        layers: { nom_couche: [enregistrements...] } (déjà validés —
            ce module ne revalide rien, voir engine.py pour l'orchestration).
        conn: connexion psycopg2/psycopg OUVERTE (autocommit désactivé ;
            ce module appelle conn.commit() lui-même en cas de succès, ou
            conn.rollback() et relève l'exception en cas d'échec).
        pg_schema: schéma PostgreSQL cible.
        schemas: { nom_couche: LayerSchema } issu de core.db_schema, dont la
            clé primaire sert de cible au ON CONFLICT. Sans lui, aucune
            couche n'est mise à jour : un doublon lève une erreur.

    Returns:
        { nom_couche: nombre de lignes insérées ou mises à jour }. Les
        couches de NON_INSERTABLE_TABLES sont ignorées et absentes du
        résultat.

    Raises:
        Toute exception levée par le driver (ex. psycopg2.Error) est
        propagée après rollback — l'appelant décide comment la rapporter.
        L'exception reçoit au passage un attribut `table_en_cours` nommant
        la table en cours d'insertion au moment de l'échec, pour que
        l'appelant puisse le mentionner dans son rapport (voir
        core/engine.py). Son TYPE reste inchangé : les appelants qui
        l'attrapent tel quel ne sont pas affectés.
    """
    cur = conn.cursor()
    counts: dict[str, int] = {}
    table_en_cours: str | None = None
    try:
        ordered = [t for t in INSERT_ORDER if t in layers] + \
                  [t for t in layers if t not in INSERT_ORDER]
        for table in ordered:
            if table in NON_INSERTABLE_TABLES:
                continue
            table_en_cours = table
            schema = (schemas or {}).get(table)
            counts[table] = _insert_rows(cur, table, layers[table], pg_schema,
                                         primary_key=schema.primary_key if schema else None)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        try:
            exc.table_en_cours = table_en_cours
        except AttributeError:
            pass  # exception exotique (__slots__) : l'information est perdue,
                  # ce qui ne doit jamais empêcher la remontée de l'erreur.
        raise
    finally:
        cur.close()
    return counts
