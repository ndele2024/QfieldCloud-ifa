#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Embarque dans le projet QGIS des GeoPackage aujourd'hui references en
`localized:` (dossier *shared datasets* de QField) : les fichiers sont copies
dans le dossier du projet et les URI passent en chemin relatif.

    localized:data/referentiels.gpkg|layername=zone|subset=...
 -> ./data/referentiels.gpkg|layername=zone|subset=...

Le fichier etant alors dans le dossier de projet QFieldCloud, il est televerse,
empaquete et telecharge avec le projet : plus de
`PackagePreventionReason.LOCALIZED_PATH` au packaging.

    python qgz_embed_localized.py "<projet>.qgz" --files referentiels.gpkg regio_s.gpkg --dry-run
    python qgz_embed_localized.py "<projet>.qgz" --files referentiels.gpkg regio_s.gpkg

Options :
    --files A.gpkg B.gpkg  fichiers a embarquer (defaut: tous ceux trouves)
    --source-dir REP       ou lire les .gpkg (defaut: dossier parent du projet)
    --to-localized         operation inverse : rebascule en `localized:`
    --dry-run              n'ecrit rien
    --no-copy              ne copie pas les fichiers, reecrit seulement les URI
    --backup-dir REP       dossier des sauvegardes (defaut: ./qgz_backups)
    --no-backup            pas de sauvegarde

Aucune dependance : bibliotheque standard uniquement.
"""

import argparse
import os
import re
import shutil
import sqlite3
import sys
import zipfile
from collections import OrderedDict
from datetime import datetime

LOCALIZED_RE = re.compile(r"localized:(data/([^|\"<&]+\.gpkg))")
EMBEDDED_RE = re.compile(r"\./(data/([^|\"<&]+\.gpkg))")
# layername d'une URI, en texte brut ou echappe
LAYERNAME_RE = r"\|layername=([^|\"<&]+)"


def scan(xml, pattern):
    """{'data/x.gpkg': {'nb': n, 'layers': set()}} pour un motif d'URI donne."""
    found = OrderedDict()
    for m in pattern.finditer(xml):
        rel = m.group(1)
        entry = found.setdefault(rel, {"nb": 0, "layers": set()})
        entry["nb"] += 1
        tail = xml[m.end():m.end() + 300]
        ln = re.match(LAYERNAME_RE, tail)
        if ln:
            entry["layers"].add(ln.group(1))
    return found


def gpkg_tables(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Embarque des GeoPackage `localized:` dans le dossier du projet QGIS.")
    ap.add_argument("project", help="chemin du projet .qgz")
    ap.add_argument("--files", nargs="*", help="noms des .gpkg a traiter (defaut: tous)")
    ap.add_argument("--source-dir", help="dossier source des .gpkg (defaut: parent du projet)")
    ap.add_argument("--to-localized", action="store_true", help="operation inverse")
    ap.add_argument("--dry-run", action="store_true", help="n'ecrit rien")
    ap.add_argument("--no-copy", action="store_true", help="ne pas copier les fichiers")
    ap.add_argument("--backup-dir", default=os.path.join(os.getcwd(), "qgz_backups"),
                    help="dossier des sauvegardes (defaut: ./qgz_backups)")
    ap.add_argument("--no-backup", action="store_true", help="pas de sauvegarde")
    args = ap.parse_args(argv)

    src = os.path.abspath(args.project)
    if not os.path.isfile(src) or not src.lower().endswith(".qgz"):
        sys.exit("Projet .qgz introuvable : %s" % src)
    project_dir = os.path.dirname(src)
    source_dir = os.path.abspath(args.source_dir) if args.source_dir \
        else os.path.dirname(project_dir)

    with zipfile.ZipFile(src, "r") as zin:
        payload = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    names = [n for n in payload if n.lower().endswith(".qgs")]
    if not names:
        sys.exit("Aucun fichier .qgs dans %s" % src)

    pattern = EMBEDDED_RE if args.to_localized else LOCALIZED_RE
    sens = "embarque -> localized" if args.to_localized else "localized -> embarque"
    print("Projet  : %s" % src)
    print("Sens    : %s" % sens)

    xml = payload[names[0]].decode("utf-8")
    found = scan(xml, pattern)
    if not found:
        print("\nAucune reference correspondante. Rien a faire.")
        return 0

    selected = []
    print("\nReferences trouvees :")
    for rel, info in found.items():
        base = os.path.basename(rel)
        keep = (args.files is None) or (base in args.files)
        print("  %-28s %4d occurrence(s), %3d couche(s)  %s"
              % (rel, info["nb"], len(info["layers"]), "->  traite" if keep else "->  ignore"))
        if keep:
            selected.append(rel)
    if args.files:
        inconnus = [f for f in args.files if f not in {os.path.basename(r) for r in found}]
        if inconnus:
            sys.exit("Fichier(s) demande(s) mais absent(s) du projet : %s" % ", ".join(inconnus))
    if not selected:
        print("\nAucun fichier selectionne.")
        return 0

    # Controle du contenu des GeoPackage (sens aller uniquement)
    copies = []
    if not args.to_localized:
        print("\nControle des GeoPackage :")
        for rel in selected:
            base = os.path.basename(rel)
            origin = os.path.join(source_dir, base)
            if not os.path.isfile(origin):
                sys.exit("  ! Introuvable : %s" % origin)
            have = gpkg_tables(origin)
            missing = sorted(n for n in found[rel]["layers"] if n not in have)
            size_mo = os.path.getsize(origin) / 1048576.0
            print("  %-24s %6.1f Mo, %3d tables, couches manquantes : %s"
                  % (base, size_mo, len(have), ", ".join(missing) if missing else "aucune"))
            if missing:
                sys.exit("  ! Abandon : des couches du projet sont absentes du GeoPackage.")
            copies.append((origin, os.path.join(project_dir, os.path.dirname(rel), base)))

    total = 0
    for rel in selected:
        if args.to_localized:
            old, new = "./" + rel, "localized:" + rel
        else:
            old, new = "localized:" + rel, "./" + rel
        total += xml.count(old)
        xml = xml.replace(old, new)
    print("\nURI reecrites : %d" % total)

    if args.dry_run:
        if copies:
            print("\n[dry-run] Copies prevues :")
            for o, d in copies:
                print("  %s\n    -> %s" % (o, d))
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

    if copies and not args.no_copy:
        for origin, dest in copies:
            dest_dir = os.path.dirname(dest)
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir)
            shutil.copy2(origin, dest)
            print("Copie : %s (%.1f Mo)" % (dest, os.path.getsize(dest) / 1048576.0))

    tmp = src + ".tmp"
    with zipfile.ZipFile(src, "r") as zin, \
            zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = xml.encode("utf-8") if info.filename == names[0] else payload[info.filename]
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
    os.replace(tmp, src)
    print("Ecrit : %s" % src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
