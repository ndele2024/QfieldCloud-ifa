#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remplace les parametres de connexion PostgreSQL en dur (host / port / dbname /
user / password / authcfg ...) des couches d'un projet QGIS (.qgz ou .qgs) par
un service PostgreSQL declare dans pg_service.conf.

Exemple :
    python qgz_use_pg_service.py \\
        "./formulaires/form ok/v8_default_config_pkey_ObvervationGenTest/v8_default_config_pkey_ObvervationGenTest.qgz" \\
        --service pg_service_local

Options :
    --dry-run       n'ecrit rien, affiche seulement ce qui serait modifie
    --out FICHIER   ecrit dans un nouveau fichier au lieu de modifier sur place
    --no-backup     ne cree pas de copie .bak
    --only-dbname X ne convertit que les sources dont dbname vaut X
    --keep-sslmode  conserve le parametre sslmode au lieu de le supprimer

Aucune dependance : bibliotheque standard uniquement (pas besoin de PyQGIS).
"""

import argparse
import os
import re
import shutil
import sys
import zipfile
from collections import Counter
from datetime import datetime

# Parametres de connexion retires de l'URI (le reste est conserve tel quel).
CONNECTION_KEYS = {
    "service", "dbname", "host", "hostaddr", "port", "user", "username",
    "password", "authcfg", "sslmode", "connect_timeout", "options",
    "requiressl", "krbsrvname", "gssencmode", "channel_binding",
    "sslcert", "sslkey", "sslrootcert", "target_session_attrs",
}

# Cles qui marquent la fin de la partie "connexion" de l'URI.
DATA_KEYS = {
    "key", "srid", "type", "table", "geometrycolumn", "sql", "selectatid",
    "estimatedmetadata", "checkPrimaryKeyUnicity", "schema",
}

# Emplacements du XML qui contiennent une URI de couche.
PAT_DATASOURCE = re.compile(r"(<datasource>)([^<]*)(</datasource>)")
PAT_ATTRIBUTE = re.compile(
    r'\b(source|dataSource|referencedLayerSource|referencingLayerSource)(=")([^"]*)(")')
PAT_OPTION = re.compile(
    r'(<Option name="(?:ReferencedLayerDataSource|LayerSource)"[^>]*?value=")([^"]*)(")')

TOKEN_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)=")
QUOTED_RE = re.compile(r"'((?:[^'\\]|\\.)*)'")
BARE_RE = re.compile(r"[^\s]*")


def parse_connection_prefix(uri):
    """Decoupe une URI PostgreSQL en (parametres de connexion, reste de l'URI).

    Retourne (None, None) si la chaine n'est pas une URI de couche PostgreSQL.
    """
    pos = 0
    params = []
    while True:
        m = TOKEN_RE.match(uri, pos)
        if not m or m.group(1) not in CONNECTION_KEYS:
            break
        vpos = m.end()
        if vpos < len(uri) and uri[vpos] == "'":
            vm = QUOTED_RE.match(uri, vpos)
            if not vm:
                return None, None
            value, end = vm.group(1), vm.end()
        else:
            vm = BARE_RE.match(uri, vpos)
            value, end = vm.group(0), vm.end()
        params.append((m.group(1), value))
        pos = end
    if not params:
        return None, None
    rest = uri[pos:].lstrip()
    # Garde-fou : une vraie URI de couche PostgreSQL enchaine sur key=/table=/sql=...
    first = TOKEN_RE.match(rest)
    if not first or first.group(1) not in DATA_KEYS:
        return None, None
    return params, rest


def rewrite_uri(uri, service, only_dbname=None, keep_sslmode=False, stats=None):
    params, rest = parse_connection_prefix(uri)
    if params is None:
        return uri, False
    values = dict(params)
    if only_dbname is not None and values.get("dbname") != only_dbname:
        if stats is not None:
            stats["ignorees"][values.get("dbname", "?")] += 1
        return uri, False
    if stats is not None:
        stats["converties"][(
            values.get("host", ""),
            values.get("dbname", ""),
            values.get("user", ""),
            "authcfg" if "authcfg" in values else "",
        )] += 1
    parts = ["service='%s'" % service]
    if keep_sslmode and "sslmode" in values:
        parts.append("sslmode=%s" % values["sslmode"])
    new_uri = " ".join(parts)
    if rest:
        new_uri += " " + rest
    return new_uri, new_uri != uri


def convert_xml(xml, service, only_dbname=None, keep_sslmode=False):
    stats = {"converties": Counter(), "ignorees": Counter(), "total": 0}

    def make_repl(value_index):
        def repl(m):
            groups = list(m.groups())
            new_uri, changed = rewrite_uri(groups[value_index], service,
                                           only_dbname, keep_sslmode, stats)
            if changed:
                stats["total"] += 1
                groups[value_index] = new_uri
            return "".join(groups)
        return repl

    xml = PAT_DATASOURCE.sub(make_repl(1), xml)
    xml = PAT_ATTRIBUTE.sub(make_repl(2), xml)
    xml = PAT_OPTION.sub(make_repl(1), xml)
    return xml, stats


def service_file_path():
    if os.environ.get("PGSERVICEFILE"):
        return os.environ["PGSERVICEFILE"]
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        return os.path.join(appdata, "postgresql", ".pg_service.conf") if appdata else None
    return os.path.join(os.path.expanduser("~"), ".pg_service.conf")


def check_service(service):
    path = service_file_path()
    if not path or not os.path.isfile(path):
        print("  ! pg_service.conf introuvable (%s) - verification ignoree." % path)
        return
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    if re.search(r"^\s*\[%s\]" % re.escape(service), content, re.M):
        print("  Service '%s' trouve dans %s" % (service, path))
    else:
        print("  ! Service '%s' ABSENT de %s" % (service, path))


def process_qgs_bytes(data, service, only_dbname, keep_sslmode):
    new_xml, stats = convert_xml(data.decode("utf-8"), service, only_dbname, keep_sslmode)
    return new_xml.encode("utf-8"), stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Bascule les couches PostgreSQL d'un projet QGIS vers un service PostgreSQL.")
    ap.add_argument("project", help="chemin du projet .qgz ou .qgs")
    ap.add_argument("--service", default="pg_service_local",
                    help="nom du service (defaut: pg_service_local)")
    ap.add_argument("--out", help="fichier de sortie (defaut: modification sur place)")
    ap.add_argument("--dry-run", action="store_true", help="n'ecrit rien")
    ap.add_argument("--no-backup", action="store_true", help="pas de copie de sauvegarde")
    ap.add_argument("--only-dbname", help="ne convertir que les sources ayant ce dbname")
    ap.add_argument("--keep-sslmode", action="store_true", help="conserver sslmode")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.project)
    if not os.path.isfile(src):
        sys.exit("Projet introuvable : %s" % src)
    dst = os.path.abspath(args.out) if args.out else src

    print("Projet        : %s" % src)
    print("Service cible : %s" % args.service)
    check_service(args.service)

    is_qgz = src.lower().endswith(".qgz")
    payload = {}
    new_entries = {}
    new_data = None
    stats_all = {"converties": Counter(), "ignorees": Counter(), "total": 0}

    if is_qgz:
        with zipfile.ZipFile(src, "r") as zin:
            infos = zin.infolist()
            payload = {i.filename: zin.read(i.filename) for i in infos}
        if not any(n.lower().endswith(".qgs") for n in payload):
            sys.exit("Aucun fichier .qgs dans %s" % src)
        for name in list(payload):
            if name.lower().endswith(".qgs"):
                data, stats = process_qgs_bytes(payload[name], args.service,
                                                args.only_dbname, args.keep_sslmode)
                new_entries[name] = data
                stats_all["converties"].update(stats["converties"])
                stats_all["ignorees"].update(stats["ignorees"])
                stats_all["total"] += stats["total"]
    else:
        with open(src, "rb") as fh:
            new_data, stats_all = process_qgs_bytes(fh.read(), args.service,
                                                    args.only_dbname, args.keep_sslmode)

    print("\nSources converties : %d" % stats_all["total"])
    for (host, dbname, user, auth), n in sorted(stats_all["converties"].items(),
                                                key=lambda x: -x[1]):
        print("  %4d x  host=%s dbname=%s user=%s %s"
              % (n, host or "-", dbname or "-", user or "-", auth))
    if stats_all["ignorees"]:
        print("Sources ignorees (dbname != --only-dbname) :")
        for dbname, n in stats_all["ignorees"].items():
            print("  %4d x  dbname=%s" % (n, dbname))

    if stats_all["total"] == 0:
        print("\nRien a modifier.")
        return 0
    if args.dry_run:
        print("\n[dry-run] Aucun fichier ecrit.")
        return 0

    if not args.no_backup and os.path.exists(dst):
        backup = "%s.%s.bak" % (dst, datetime.now().strftime("%Y%m%d_%H%M%S"))
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
