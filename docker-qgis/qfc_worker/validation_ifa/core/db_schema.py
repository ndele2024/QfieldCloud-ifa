"""
core.db_schema — Introspection PostgreSQL : génère automatiquement les
règles "imposées par la BD" (clé primaire, NOT NULL, plages numériques
via CHECK, valeurs ENUM) sans qu'un développeur ait à les recopier en
Python. Si un collègue ajoute une contrainte CHECK ou un NOT NULL côté
base de données, elle est automatiquement prise en compte ici — aucune
modification de ce dépôt n'est nécessaire pour ce type de règle.

Fonctions exposées :
  - load_schema(conn, tables) -> dict[str, LayerSchema]
  - check_db_rules(layer, rows, schema) -> list[ValidationIssue]
  - column_label(layer, column) -> str  (libellé lisible d'une colonne)
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

import config

from .models import LayerSchema, Severity, ValidationIssue

# Motifs de contraintes CHECK reconnus, ex. générés par :
#   CHECK (col >= 0)
#   CHECK (col <= 100)
#   CHECK (col >= 0 AND col <= 100)
#   CHECK (col BETWEEN 0 AND 100)
_RE_GTE = re.compile(r"\(?\"?(?P<col>\w+)\"?\s*>=\s*(?P<val>-?\d+(\.\d+)?)\)?")
_RE_LTE = re.compile(r"\(?\"?(?P<col>\w+)\"?\s*<=\s*(?P<val>-?\d+(\.\d+)?)\)?")
_RE_BETWEEN = re.compile(
    r"\"?(?P<col>\w+)\"?\s+BETWEEN\s+(?P<low>-?\d+(\.\d+)?)\s+AND\s+(?P<high>-?\d+(\.\d+)?)",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _load_column_aliases() -> dict[str, dict[str, str]]:
    """Charge { table: { colonne: alias } } depuis le fichier JSON généré par
    generate_column_aliases.py (voir config.COLUMN_ALIASES_PATH).

    Mis en cache : le fichier ne change pas pendant l'exécution, inutile de
    le relire pour chaque enregistrement validé.

    Si le fichier est absent ou illisible, retourne un dictionnaire vide :
    les messages retomberont alors sur le nom brut des colonnes (voir
    column_label). Une table de libellés manquante ne doit jamais empêcher
    une validation de s'exécuter.
    """
    try:
        with open(config.COLUMN_ALIASES_PATH, encoding="utf-8") as fichier:
            return json.load(fichier).get("tables", {})
    except (OSError, ValueError):
        return {}


def column_label(layer: str, column: str) -> str:
    """Libellé lisible d'une colonne, pour les messages destinés à
    l'utilisateur (ex. "ing_date_debut_inven" -> "Date du début de
    l'inventaire"). Retombe sur le nom brut de la colonne si aucun alias
    n'est connu.

    Le libellé dépend du COUPLE (table, colonne) : plusieurs colonnes
    portent un nom différent selon la table (ex. efa_code = « Espèce » dans
    detail_speci mais « Espèce visée » dans peche_exper), d'où le paramètre
    `layer`.
    """
    alias = _load_column_aliases().get(layer.lower(), {}).get(column.lower())
    return alias or column


def _parse_numeric_ranges(check_clause: str) -> dict[str, tuple[float | None, float | None]]:
    """Extrait les plages numériques (min, max) d'une clause CHECK brute
    (telle que retournée par pg_get_constraintdef). Best-effort : les
    contraintes qui ne correspondent à aucun des motifs ci-dessus sont
    simplement ignorées (pas d'erreur — elles ne génèrent juste pas de
    règle automatique ; un avertissement est laissé au niveau appelant)."""
    ranges: dict[str, tuple[float | None, float | None]] = {}

    m = _RE_BETWEEN.search(check_clause)
    if m:
        ranges[m.group("col")] = (float(m.group("low")), float(m.group("high")))
        return ranges

    low_match = _RE_GTE.search(check_clause)
    high_match = _RE_LTE.search(check_clause)
    col = None
    low = high = None
    if low_match:
        col = low_match.group("col")
        low = float(low_match.group("val"))
    if high_match:
        col = col or high_match.group("col")
        high = float(high_match.group("val"))
    if col:
        ranges[col] = (low, high)
    return ranges


def load_schema(conn, tables: list[str], pg_schema: str = "ifa_data") -> dict[str, LayerSchema]:
    """Charge les métadonnées de validation pour chaque table de `tables`.

    Args:
        conn: connexion psycopg2/psycopg ouverte.
        tables: noms de tables (sans le schéma) à introspecter.
        pg_schema: schéma PostgreSQL contenant ces tables.

    Returns:
        { nom_table: LayerSchema }. Une table absente de la base est
        simplement omise du résultat (un avertissement est laissé à la
        charge de l'appelant — voir engine.py).
    """
    cur = conn.cursor()
    result: dict[str, LayerSchema] = {}

    for table in tables:
        cur.execute("""
            SELECT column_name, is_nullable, column_default, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
        """, (pg_schema, table))
        cols = cur.fetchall()
        if not cols:
            continue

        schema = LayerSchema(table=table)

        # NOT NULL sans valeur par défaut serveur (séquence, now(), etc.) :
        # ce sont les seules colonnes que l'UTILISATEUR doit avoir remplies.
        for col_name, is_nullable, col_default, _udt in cols:
            if is_nullable == "NO" and not col_default:
                schema.not_null_columns.append(col_name)

        # Clé primaire — via pg_constraint (fiable pour les clés composites,
        # contrairement à information_schema.key_column_usage qui peut
        # produire un produit cartésien sur les contraintes composites).
        cur.execute("""
            SELECT a.attname
            FROM pg_constraint c
            JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
            WHERE c.contype = 'p' AND c.conrelid = (
                quote_ident(%s) || '.' || quote_ident(%s)
            )::regclass
            ORDER BY k.ord
        """, (pg_schema, table))
        schema.primary_key = [r[0] for r in cur.fetchall()]

        # Contraintes CHECK -> plages numériques (col >= a AND col <= b, etc.)
        cur.execute("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            WHERE c.contype = 'c' AND c.conrelid = (
                quote_ident(%s) || '.' || quote_ident(%s)
            )::regclass
        """, (pg_schema, table))
        for (check_def,) in cur.fetchall():
            schema.numeric_ranges.update(_parse_numeric_ranges(check_def))

        # Valeurs ENUM par colonne
        cur.execute("""
            SELECT col.column_name, e.enumlabel
            FROM information_schema.columns col
            JOIN pg_type t ON t.typname = col.udt_name
            JOIN pg_enum e ON e.enumtypid = t.oid
            WHERE col.table_schema = %s AND col.table_name = %s
            ORDER BY col.column_name, e.enumsortorder
        """, (pg_schema, table))
        for col_name, label in cur.fetchall():
            schema.enum_values.setdefault(col_name, set()).add(label)

        result[table] = schema

    cur.close()
    return result


def check_db_rules(layer: str, rows: list[dict], schema: LayerSchema) -> list[ValidationIssue]:
    """Applique les règles automatiquement déduites du schéma PostgreSQL à
    chaque enregistrement de `rows`. Couvre : NOT NULL, plages numériques
    (CHECK), appartenance à un ENUM. Ne couvre PAS les clés étrangères
    inter-tables (gérées par les relations applicatives, pas par ce module).

    Les messages désignent les colonnes par leur ALIAS métier (voir
    column_label) plutôt que par leur nom technique : « Date du début de
    l'inventaire » est exploitable par la personne qui a saisi le
    formulaire, « ing_date_debut_inven » ne l'est pas. En revanche le champ
    `fields` de chaque anomalie continue de porter le nom TECHNIQUE de la
    colonne : il est lu par l'interface (QField/QGIS) pour mettre le bon
    champ en évidence dans le formulaire, et doit donc rester stable."""
    issues: list[ValidationIssue] = []

    for row in rows:
        key = {f: row.get(f) for f in (schema.primary_key or []) if f in row}

        for col in schema.not_null_columns:
            value = row.get(col)
            if value is None or (isinstance(value, float) and value != value):
                issues.append(ValidationIssue(
                    layer=layer, severity=Severity.ERROR, code="DB_NOT_NULL",
                    message=(
                        f"Le champ « {column_label(layer, col)} » est obligatoire "
                        "(contrainte NOT NULL)."
                    ),
                    fields=[col], record=key, rule_name="db_schema.not_null",
                ))

        for col, (low, high) in schema.numeric_ranges.items():
            value = row.get(col)
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if low is not None and value < low:
                issues.append(ValidationIssue(
                    layer=layer, severity=Severity.ERROR, code="DB_RANGE_MIN",
                    message=(
                        f"Le champ « {column_label(layer, col)} » doit être supérieur ou égal "
                        f"à {low} (valeur saisie : {value})."
                    ),
                    fields=[col], record=key, rule_name="db_schema.range",
                ))
            if high is not None and value > high:
                issues.append(ValidationIssue(
                    layer=layer, severity=Severity.ERROR, code="DB_RANGE_MAX",
                    message=(
                        f"Le champ « {column_label(layer, col)} » doit être inférieur ou égal "
                        f"à {high} (valeur saisie : {value})."
                    ),
                    fields=[col], record=key, rule_name="db_schema.range",
                ))

        for col, allowed in schema.enum_values.items():
            value = row.get(col)
            if value is not None and value not in allowed:
                issues.append(ValidationIssue(
                    layer=layer, severity=Severity.ERROR, code="DB_ENUM_INVALID",
                    message=(
                        f"La valeur « {value} » du champ « {column_label(layer, col)} » "
                        "n'est pas une valeur autorisée."
                    ),
                    fields=[col], record=key, rule_name="db_schema.enum",
                ))

    return issues
