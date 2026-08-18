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

Les erreurs de COMMUNICATION avec PostgreSQL (lecture du schéma, insertion)
ne remontent pas sous forme d'exception : elles sont converties en anomalies
du rapport (voir issue_base_de_donnees). Le rapport JSON est ainsi toujours
produit et se suffit à lui-même pour diagnostiquer un incident, sans avoir à
consulter les journaux du conteneur.
"""

from __future__ import annotations

from pathlib import Path

from . import db_schema, gpkg_reader, inserter
from .models import (
    LAYER_BASE_DE_DONNEES,
    Severity,
    ValidationIssue,
    ValidationReport,
)
from .registry import discover_rules, get_rules
from .rule_base import RuleContext, RuleKind


def decrire_exception(exc: BaseException) -> str:
    """Résume une exception du driver en une ligne exploitable dans un
    rapport : type + message, replié sur une seule ligne (les messages
    psycopg2 sont souvent multilignes et contiennent des indentations)."""
    detail = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def issue_base_de_donnees(code: str, message: str, *, rule_name: str,
                           exc: BaseException | None = None) -> ValidationIssue:
    """Construit une anomalie signalant un problème de communication avec
    PostgreSQL. Utilisée par ce module ET par cli.py (échec de connexion),
    pour que toutes les erreurs de base de données aient la même forme dans
    le rapport."""
    if exc is not None:
        message = f"{message}. Détail technique : {decrire_exception(exc)}"
    return ValidationIssue(
        layer=LAYER_BASE_DE_DONNEES, severity=Severity.ERROR, code=code,
        message=message, fields=[], record={}, rule_name=rule_name,
    )


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

    report = ValidationReport(
        source=str(gpkg_path),
        layers_processed=list(layers.keys()),
        record_counts={name: len(rows) for name, rows in layers.items()},
    )

    # Lecture du schéma PostgreSQL. En cas d'échec (connexion perdue, droits
    # insuffisants, schéma inexistant...), on n'interrompt pas le traitement :
    # les règles métier sont tout de même appliquées, ce qui donne à
    # l'utilisateur un retour utile sur sa saisie. L'anomalie ajoutée ici
    # rend le rapport invalide, ce qui empêche l'insertion plus bas — on
    # n'insère jamais des données dont les contraintes de la base n'ont pas
    # pu être vérifiées.
    #
    # `Exception` est volontairement large : ce module ne dépend d'aucun
    # driver précis (psycopg2 n'est jamais importé ici) et le rapport doit
    # être produit quoi qu'il arrive. Le type réel de l'exception figure
    # dans le message, donc une erreur de programmation reste visible.
    try:
        schemas = db_schema.load_schema(conn, list(layers.keys()), pg_schema=pg_schema)
    except Exception as exc:
        schemas = {}
        report.issues.append(issue_base_de_donnees(
            "DB_SCHEMA_INDISPONIBLE",
            (
                f"Impossible de lire le schéma PostgreSQL « {pg_schema} ». Les règles "
                "déduites de la base (NOT NULL, plages, valeurs autorisées) n'ont pas pu "
                "être appliquées et aucune donnée n'a été insérée"
            ),
            rule_name="engine.load_schema", exc=exc,
        ))

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
        try:
            # `schemas` fournit la clé primaire de chaque table, qui sert de
            # cible au ON CONFLICT : sans lui, un second envoi du même
            # mesurage échouerait sur doublon au lieu de le mettre à jour.
            inserter.insert_all(layers, conn, pg_schema=pg_schema, schemas=schemas)
            report.inserted = True
        except Exception as exc:
            # insert_all a déjà annulé la transaction (rollback) : la base est
            # intacte. On signale l'échec dans le rapport plutôt que de laisser
            # l'exception remonter, sinon aucun rapport ne serait produit et
            # l'incident ne serait visible que dans les journaux du conteneur.
            table = getattr(exc, "table_en_cours", None)
            precision = f" lors de l'insertion dans la table « {table} »" if table else ""
            report.issues.append(issue_base_de_donnees(
                "DB_INSERTION_ECHOUEE",
                (
                    f"Les données sont valides mais leur insertion en base a échoué{precision}. "
                    "La transaction a été annulée : aucune donnée n'a été insérée"
                ),
                rule_name="engine.insert_all", exc=exc,
            ))

    return report
