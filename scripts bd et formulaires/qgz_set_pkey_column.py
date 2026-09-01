#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remplace la cle primaire QGIS (`key='a,b,c'`) des couches PostgreSQL d'un projet
QGIS (.qgz ou .qgs) par une colonne unique mono-colonne (defaut: qgis_id).

QFieldSync ne sait pas copier hors ligne une couche dont la cle primaire est
composite : elle est ecartee du packaging et reste connectee a PostgreSQL. Ce
script bascule toutes les URI sur une colonne technique unique.

    # 1. generer le DDL a passer sur la base
    python qgz_set_pkey_column.py "<projet>.qgz" --sql > add_qgis_id.sql

    # 2. une fois la colonne creee et le projet rouvert : reecrire les cles
    python qgz_set_pkey_column.py "<projet>.qgz" --dry-run
    python qgz_set_pkey_column.py "<projet>.qgz"

Options :
    --column NOM     nom de la colonne (defaut: qgis_id)
    --sql            n'ecrit rien : affiche le DDL PostgreSQL et s'arrete
    --dry-run        n'ecrit rien : affiche ce qui serait modifie
    --out FICHIER    ecrit dans un nouveau fichier au lieu de modifier sur place
    --backup-dir REP dossier des sauvegardes (defaut: ./qgz_backups)
    --no-backup      ne cree pas de sauvegarde

Les sauvegardes sont ecrites HORS du dossier du projet, pour ne pas etre
televersees vers QFieldCloud avec celui-ci.

Aucune dependance : bibliotheque standard uniquement.
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from collections import Counter, OrderedDict
from datetime import datetime

# Emplacements du XML qui contiennent une URI de couche (memes que la bascule
# vers le service : <datasource>, layer-tree, relations, valeurs relationnelles).
PAT_DATASOURCE = re.compile(r"(<datasource>)([^<]*)(</datasource>)")
PAT_ATTRIBUTE = re.compile(
    r'\b(source|dataSource|referencedLayerSource|referencingLayerSource)(=")([^"]*)(")')
PAT_OPTION = re.compile(
    r'(<Option name="(?:ReferencedLayerDataSource|LayerSource)"[^>]*?value=")([^"]*)(")')

KEY_RE = re.compile(r"key='((?:[^'\\]|\\.)*)'")
# table="schema"."table" en texte brut ou echappe dans un attribut
TABLE_RE = re.compile(r'table=(?:"|&quot;)([^"&]+)(?:"|&quot;)\.(?:"|&quot;)([^"&]+)(?:"|&quot;)')
IS_PG_RE = re.compile(r"^\s*(?:service|dbname|host|hostaddr|port|user|password|authcfg)=")


def is_postgres_uri(uri):
    """Vrai si la chaine est une URI de couche PostgreSQL (et pas un chemin GPKG…)."""
    return bool(IS_PG_RE.match(uri)) and TABLE_RE.search(uri) is not None


def rewrite_uri(uri, column, stats=None, is_layer=False):
    if not is_postgres_uri(uri):
        return uri, False
    m = KEY_RE.search(uri)
    if not m:
        if stats is not None:
            stats["sans_key"] += 1
        return uri, False
    if stats is not None:
        stats["cles"][m.group(1)] += 1
        table = TABLE_RE.search(uri)
        if table:
            qualified = "%s.%s" % table.groups()
            # Seules les couches reelles (<datasource>) donnent lieu a du DDL ;
            # les URI des relations / listes de valeurs peuvent etre perimees.
            target = stats["tables"] if is_layer else stats["tables_ref"]
            target[qualified] = len(m.group(1).split(","))
    new_uri = uri[:m.start()] + "key='%s'" % column + uri[m.end():]
    return new_uri, new_uri != uri


def convert_xml(xml, column):
    stats = {"cles": Counter(), "tables": OrderedDict(), "tables_ref": OrderedDict(),
             "sans_key": 0, "total": 0}

    def make_repl(value_index, is_layer=False):
        def repl(m):
            groups = list(m.groups())
            new_uri, changed = rewrite_uri(groups[value_index], column, stats, is_layer)
            if changed:
                stats["total"] += 1
                groups[value_index] = new_uri
            return "".join(groups)
        return repl

    xml = PAT_DATASOURCE.sub(make_repl(1, is_layer=True), xml)
    xml = PAT_ATTRIBUTE.sub(make_repl(2), xml)
    xml = PAT_OPTION.sub(make_repl(1), xml)
    return xml, stats


def emit_sql(tables, column):
    lines = [
        "-- Colonne technique mono-colonne pour le packaging hors ligne QFieldSync.",
        "-- Generee le %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "-- ATTENTION : ces ordres supposent des TABLES. Pour une VUE, ajouter la",
        "-- colonne a la table sous-jacente puis l'exposer dans la vue.",
        "",
        "BEGIN;",
        "",
    ]
    for qualified, nb_pk in tables.items():
        schema, table = qualified.split(".", 1)
        lines.append('-- %s (cle actuelle : %d colonne%s)'
                     % (qualified, nb_pk, "s" if nb_pk > 1 else ""))
        lines.append('ALTER TABLE "%s"."%s"' % (schema, table))
        lines.append('  ADD COLUMN IF NOT EXISTS %s bigint GENERATED ALWAYS AS IDENTITY;'
                     % column)
        lines.append('CREATE UNIQUE INDEX IF NOT EXISTS %s_%s_uidx'
                     % (table, column))
        lines.append('  ON "%s"."%s" (%s);' % (schema, table, column))
        lines.append("")
    lines.append("COMMIT;")
    return "\n".join(lines)


def process_qgs_bytes(data, column):
    new_xml, stats = convert_xml(data.decode("utf-8"), column)
    return new_xml.encode("utf-8"), stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Bascule la cle primaire QGIS des couches PostgreSQL sur une colonne unique.")
    ap.add_argument("project", help="chemin du projet .qgz ou .qgs")
    ap.add_argument("--column", default="qgis_id", help="nom de la colonne (defaut: qgis_id)")
    ap.add_argument("--sql", action="store_true", help="afficher le DDL PostgreSQL et s'arreter")
    ap.add_argument("--dry-run", action="store_true", help="n'ecrit rien")
    ap.add_argument("--out", help="fichier de sortie (defaut: modification sur place)")
    ap.add_argument("--backup-dir", default=os.path.join(os.getcwd(), "qgz_backups"),
                    help="dossier des sauvegardes (defaut: ./qgz_backups)")
    ap.add_argument("--no-backup", action="store_true", help="pas de sauvegarde")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.project)
    if not os.path.isfile(src):
        sys.exit("Projet introuvable : %s" % src)
    dst = os.path.abspath(args.out) if args.out else src

    is_qgz = src.lower().endswith(".qgz")
    payload = {}
    new_entries = {}
    new_data = None
    stats_all = {"cles": Counter(), "tables": OrderedDict(), "tables_ref": OrderedDict(),
                 "sans_key": 0, "total": 0}

    if is_qgz:
        with zipfile.ZipFile(src, "r") as zin:
            payload = {i.filename: zin.read(i.filename) for i in zin.infolist()}
        names = [n for n in payload if n.lower().endswith(".qgs")]
        if not names:
            sys.exit("Aucun fichier .qgs dans %s" % src)
    else:
        with open(src, "rb") as fh:
            payload = {os.path.basename(src): fh.read()}
        names = list(payload)

    for name in names:
        data, stats = process_qgs_bytes(payload[name], args.column)
        new_entries[name] = data
        stats_all["cles"].update(stats["cles"])
        stats_all["tables"].update(stats["tables"])
        stats_all["tables_ref"].update(stats["tables_ref"])
        stats_all["sans_key"] += stats["sans_key"]
        stats_all["total"] += stats["total"]
    if not is_qgz:
        new_data = new_entries[names[0]]

    if args.sql:
        print(emit_sql(stats_all["tables"], args.column))
        return 0

    print("Projet  : %s" % src)
    print("Colonne : %s" % args.column)
    print("\nSources PostgreSQL reecrites : %d  (%d tables distinctes)"
          % (stats_all["total"], len(stats_all["tables"])))
    composites = sum(n for k, n in stats_all["cles"].items() if len(k.split(",")) > 1)
    simples = stats_all["total"] - composites
    print("  dont cles composites : %d" % composites)
    print("  dont cles simples    : %d" % simples)
    if stats_all["sans_key"]:
        print("  ! %d URI PostgreSQL sans key= (ignorees)" % stats_all["sans_key"])
    orphelines = [t for t in stats_all["tables_ref"] if t not in stats_all["tables"]]
    if orphelines:
        print("\nTables citees uniquement par des relations / listes de valeurs")
        print("(hors DDL, probablement des references perimees) :")
        for t in orphelines:
            print("  %s" % t)

    if stats_all["total"] == 0:
        print("\nRien a modifier.")
        return 0
    if args.dry_run:
        print("\n[dry-run] Aucun fichier ecrit.")
        return 0

    if not args.no_backup and os.path.exists(dst):
        if not os.path.isdir(args.backup_dir):
            os.makedirs(args.backup_dir)
        backup = os.path.join(
            args.backup_dir,
            "%s.%s.bak" % (os.path.basename(dst), datetime.now().strftime("%Y%m%d_%H%M%S")))
        shutil.copy2(dst, backup)
        print("\nSauvegarde : %s" % backup)

    tmp = dst + ".tmp"
    if is_qgz:
        with zipfile.ZipFile(src, "r") as zin, \
                zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zout.writestr(zi, new_entries.get(info.filename, payload[info.filename]))
    else:
        with open(tmp, "wb") as fh:
            fh.write(new_data)
    os.replace(tmp, dst)
    print("Ecrit : %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
