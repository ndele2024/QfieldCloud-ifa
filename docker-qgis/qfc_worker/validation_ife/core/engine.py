"""
core.engine — Orchestrateur principal : lecture du GeoPackage, application
des règles (automatiques + personnalisées), décision d'insertion, rapport.

C'est le SEUL module qui connaît l'ordre des opérations ; les modules
db_schema/gpkg_reader/inserter/registry n'ont aucune dépendance entre eux
et pourraient être réutilisés indépendamment (ex. un futur outil qui ne
ferait QUE valider sans jamais insérer).

Déroulement de `run()` :
  1. Lecture du GeoPackage -> { couche: [enregistrements] }.
  2. Chargement des métadonnées PostgreSQL (NOT NULL, plages, ENUM, PK)
     pour chaque couche présente.
  3. Règles automatiques issues du schéma (core.db_schema).
  4. Règles personnalisées TRANSFORM (peuvent modifier les enregistrements),
     puis VALIDATION, dans cet ordre, couche par couche.
  5. S'il n'y a AUCUNE erreur bloquante (des avertissements n'empêchent
     pas l'insertion) : insertion en base dans une seule transaction.
  6. Construction et retour du ValidationReport (toujours produit, que
     l'insertion ait eu lieu ou non).
"""

from __future__ import annotations

from pathlib import Path

from . import db_schema, gpkg_reader, inserter
from .models import ValidationReport
from .registry import discover_rules, get_rules
from .rule_base import RuleContext, RuleKind


def run(
    gpkg_path: str | Path,
    conn,
    *,
    pg_schema: str = "ifa_data",
    tables: list[str] | None = None,
    apply: bool = True,
) -> ValidationReport:
    """Exécute le pipeline complet de validation (+ insertion) pour un GeoPackage.

    Args:
        gpkg_path: chemin du fichier .gpkg à traiter.
        conn: connexion psycopg2/psycopg OUVERTE vers la base PostgreSQL
            (utilisée pour l'introspection du schéma ET pour l'insertion).
        pg_schema: schéma PostgreSQL cible (ex. "ifa_data").
        tables: liste explicite des couches à traiter ; si None, traite
            toutes les couches présentes dans le GeoPackage.
        apply: si False, exécute la validation seule (utile pour un essai
            "à blanc" / dry-run) sans jamais insérer, même si tout est valide.

    Returns:
        Un ValidationReport complet (voir core.models), qu'il y ait eu
        insertion ou non.
    """
    discover_rules()

    gpkg_path = Path(gpkg_path)
    layers = gpkg_reader.read_gpkg(gpkg_path, layers=tables)

    schemas = db_schema.load_schema(conn, list(layers.keys()), pg_schema=pg_schema)

    report = ValidationReport(
        source=str(gpkg_path),
        layers_processed=list(layers.keys()),
        record_counts={name: len(rows) for name, rows in layers.items()},
    )

    # 1. Règles automatiques (schéma PostgreSQL)
    for layer_name, rows in layers.items():
        schema = schemas.get(layer_name)
        if schema is None:
            continue  # table absente de la base — rien à introspecter
        report.issues.extend(db_schema.check_db_rules(layer_name, rows, schema))

    # 2. Règles personnalisées : TRANSFORM d'abord (peuvent modifier les
    #    lignes), puis VALIDATION — toujours dans cet ordre pour qu'une
    #    valeur par défaut posée par un transform soit prise en compte par
    #    les validations qui suivent (ex. date par défaut puis bornage).
    for layer_name, rows in layers.items():
        for kind in (RuleKind.TRANSFORM, RuleKind.VALIDATION):
            for rule in get_rules(layer_name, kind=kind):
                for row in rows:
                    ctx = RuleContext(layer=layer_name, row=row, all_rows=rows,
                                       layers=layers, schemas=schemas)
                    report.issues.extend(rule.run(ctx))

        # RuleKind.LAYER : une seule évaluation par couche, même à zéro ligne
        # (une VALIDATION classique ne serait jamais invoquée dans ce cas,
        # puisque la boucle `for row in rows` ci-dessus ne s'exécuterait pas).
        for rule in get_rules(layer_name, kind=RuleKind.LAYER):
            ctx = RuleContext(layer=layer_name, row={}, all_rows=rows,
                               layers=layers, schemas=schemas)
            report.issues.extend(rule.run(ctx))

    if report.is_valid and apply:
        inserter.insert_all(layers, conn, pg_schema=pg_schema)
        report.inserted = True

    return report
