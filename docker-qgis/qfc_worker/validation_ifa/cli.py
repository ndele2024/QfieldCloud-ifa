"""
cli.py — Point d'entrée pour exécuter la validation/insertion de façon
isolée (hors conteneur QFieldCloud), depuis la ligne de commande.

Usage :
    python cli.py CHEMIN.gpkg [options]

Options :
    --report CHEMIN.json   Chemin de sortie du rapport JSON
                            (défaut : <gpkg>_report.json, même dossier).
    --dry-run               Valide sans jamais insérer en base, même si
                            tout est valide (utile pour tester un lot).
    --schema NOM            Schéma PostgreSQL cible (défaut : config.PG_SCHEMA).

Codes de sortie :
    0  validation réussie (et insertion effectuée si --dry-run absent)
    1  validation échouée (au moins une erreur bloquante)
    2  erreur d'exécution (fichier introuvable, connexion BD impossible, etc.)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2

import config
from core import engine, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validation et insertion d'un GeoPackage IPE.")
    parser.add_argument("gpkg", type=Path, help="Chemin du fichier GeoPackage à traiter.")
    parser.add_argument("--report", type=Path, default=None, help="Chemin du rapport JSON de sortie.")
    parser.add_argument("--dry-run", action="store_true", help="Valide sans insérer en base.")
    parser.add_argument("--schema", default=config.PG_SCHEMA, help="Schéma PostgreSQL cible.")
    args = parser.parse_args(argv)

    if not args.gpkg.exists():
        print(f"Erreur : fichier introuvable : {args.gpkg}", file=sys.stderr)
        return 2

    report_path = args.report or args.gpkg.with_suffix("").with_name(args.gpkg.stem + "_report.json")

    try:
        conn = psycopg2.connect(config.get_dsn())
    except Exception as exc:
        print(f"Erreur de connexion à PostgreSQL : {exc}", file=sys.stderr)
        return 2

    try:
        result = engine.run(args.gpkg, conn, pg_schema=args.schema, apply=not args.dry_run)
    finally:
        conn.close()

    report.save_report(result, report_path)
    print(report.report_summary(result))
    print(f"\nRapport détaillé : {report_path}")

    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
