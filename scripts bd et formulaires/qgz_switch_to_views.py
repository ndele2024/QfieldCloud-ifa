#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bascule les couches PostgreSQL d'un projet QGIS vers des VUES auto-modifiables,
afin que QFieldSync puisse les convertir hors ligne.

Pourquoi : le fournisseur PostgreSQL de QGIS impose la PRIMARY KEY declaree de la
table et ecrase le `key=` du projet. Quand cette cle est composite, libqfieldsync
leve `UnsupportedPrimaryKeyError`, met la couche en `no_action` ET en lecture
seule. Une VUE n'a pas de cle primaire declaree : QGIS respecte alors le `key=`
de l'URI, ici la colonne technique mono-colonne `qgis_id`.

    # 1. generer le DDL des vues
    python qgz_switch_to_views.py "<projet>.qgz" --sql > views_qfield.sql

    # 2. une fois les vues creees : repointer le projet
    python qgz_switch_to_views.py "<projet>.qgz" --dry-run
    python qgz_switch_to_views.py "<projet>.qgz"

Options :
    --from-schema NOM  schema source (defaut: ifa_structure)
    --to-schema NOM    schema des vues (defaut: ifa_qfield)
    --column NOM       colonne cle exposee par les vues (defaut: qgis_id)
    --grant ROLE       ajoute les GRANT pour ce role dans le DDL
    --sql              affiche le DDL et s'arrete
    --dry-run          n'ecrit rien
    --backup-dir REP   dossier des sauvegardes (defaut: ./qgz_backups)
    --no-backup        pas de sauvegarde

Aucune dependance : bibliotheque standard uniquement.
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from collections import OrderedDict
from datetime import datetime

PAT_DATASOURCE = re.compile(r"(<datasource>)([^<]*)(</datasource>)")
PAT_ATTRIBUTE = re.compile(
    r'\b(source|dataSource|referencedLayerSource|referencingLayerSource)(=")([^"]*)(")')
PAT_OPTION = re.compile(
    r'(<Option name="(?:ReferencedLayerDataSource|LayerSource)"[^>]*?value=")([^"]*)(")')

KEY_RE = re.compile(r"key='((?:[^'\\]|\\.)*)'")
IS_PG_RE = re.compile(r"^\s*(?:service|dbname|host|hostaddr|port|user|password|authcfg)=")


def table_re(schema):
    """table="schema"."x" en texte brut ou echappe (&quot;) dans un attribut."""
    q = r'(?:"|&quot;)'
    return re.compile(r'(table=%s)(%s)(%s\.%s)([^"&]+)(%s)' % (q, re.escape(schema), q, q, q))


def rewrite_uri(uri, from_schema, to_schema, column, stats):
    if not IS_PG_RE.match(uri):
        return uri, False
    m = table_re(from_schema).search(uri)
    if not m:
        return uri, False
    table = m.group(4)
    new_uri = uri[:m.start(2)] + to_schema + uri[m.end(2):]
    k = KEY_RE.search(new_uri)
    if k:
        new_uri = new_uri[:k.start()] + "key='%s'" % column + new_uri[k.end():]
        stats["cles"] += 1
    stats["tables"][table] = stats["tables"].get(table, 0) + 1
    return new_uri, new_uri != uri


def convert_xml(xml, from_schema, to_schema, column):
    stats = {"tables": OrderedDict(), "cles": 0, "total": 0}

    def make_repl(idx):
        def repl(m):
            g = list(m.groups())
            new_uri, changed = rewrite_uri(g[idx], from_schema, to_schema, column, stats)
            if changed:
                stats["total"] += 1
                g[idx] = new_uri
            return "".join(g)
        return repl

    xml = PAT_DATASOURCE.sub(make_repl(1), xml)
    xml = PAT_ATTRIBUTE.sub(make_repl(2), xml)
    xml = PAT_OPTION.sub(make_repl(1), xml)
    return xml, stats


def emit_sql(tables, from_schema, to_schema, column, grant_role):
    lines = [
        "-- Vues auto-modifiables pour le packaging hors ligne QFieldSync.",
        "-- Generees le %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "--",
        "-- Une vue n'a pas de PRIMARY KEY declaree : QGIS respecte donc le",
        "-- `key='%s'` de l'URI au lieu d'imposer la cle composite de la table." % column,
        "-- `SELECT *` sur une seule table reste auto-modifiable en PostgreSQL :",
        "-- les INSERT / UPDATE / DELETE de la synchro QField passent directement.",
        "--",
        "-- Pour tout annuler : DROP SCHEMA %s CASCADE;" % to_schema,
        "",
        "BEGIN;",
        "",
        "CREATE SCHEMA IF NOT EXISTS %s;" % to_schema,
        "",
    ]
    for t in tables:
        lines.append('CREATE OR REPLACE VIEW %s."%s" AS SELECT * FROM %s."%s";'
                     % (to_schema, t, from_schema, t))
    if grant_role:
        # Le role n'existe que sur le serveur : on ne veut pas casser le script en local.
        lines += [
            "",
            "DO $$ BEGIN",
            "  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '%s') THEN" % grant_role,
            "    EXECUTE 'GRANT USAGE ON SCHEMA %s TO %s';" % (to_schema, grant_role),
            "    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %s TO %s';"
            % (to_schema, grant_role),
            "  END IF;",
            "END $$;",
        ]
    lines += ["", "COMMIT;"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Repointe les couches PostgreSQL d'un projet QGIS vers des vues.")
    ap.add_argument("project", help="chemin du projet .qgz")
    ap.add_argument("--from-schema", default="ifa_structure")
    ap.add_argument("--to-schema", default="ifa_qfield")
    ap.add_argument("--column", default="qgis_id")
    ap.add_argument("--grant", help="role a qui accorder les droits sur les vues")
    ap.add_argument("--sql", action="store_true", help="afficher le DDL et s'arreter")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backup-dir", default=os.path.join(os.getcwd(), "qgz_backups"))
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.project)
    if not os.path.isfile(src) or not src.lower().endswith(".qgz"):
        sys.exit("Projet .qgz introuvable : %s" % src)

    with zipfile.ZipFile(src, "r") as zin:
        payload = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    names = [n for n in payload if n.lower().endswith(".qgs")]
    if not names:
        sys.exit("Aucun fichier .qgs dans %s" % src)

    xml = payload[names[0]].decode("utf-8")
    new_xml, stats = convert_xml(xml, args.from_schema, args.to_schema, args.column)

    if args.sql:
        print(emit_sql(list(stats["tables"]), args.from_schema, args.to_schema,
                       args.column, args.grant))
        return 0

    print("Projet : %s" % src)
    print("Schema : %s  ->  %s     cle : %s" % (args.from_schema, args.to_schema, args.column))
    print("\nURI repointees : %d  (%d tables, %d cles reecrites)"
          % (stats["total"], len(stats["tables"]), stats["cles"]))
    if stats["total"] == 0:
        print("\nRien a modifier.")
        return 0
    if args.dry_run:
        print("\n[dry-run] Aucun fichier ecrit.")
        return 0

    if not args.no_backup:
        if not os.path.isdir(args.backup_dir):
            os.makedirs(args.backup_dir)
        backup = os.path.join(
            args.backup_dir,
            "%s.%s.bak" % (os.path.basename(src), datetime.now().strftime("%Y%m%d_%H%M%S")))
        shutil.copy2(src, backup)
        print("\nSauvegarde : %s" % backup)

    tmp = src + ".tmp"
    with zipfile.ZipFile(src, "r") as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = new_xml.encode("utf-8") if info.filename == names[0] \
                else payload[info.filename]
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    os.replace(tmp, src)
    print("Ecrit : %s" % src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
