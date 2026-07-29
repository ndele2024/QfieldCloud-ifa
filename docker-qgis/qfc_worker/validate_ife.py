"""
qfc_worker.validate_ife — Validation IFE post-application des deltas.

Appelé comme étape du workflow apply_deltas (voir commands/apply_deltas.py).

Flux :
  1. Chercher le GPKG IPE dans le répertoire de fichiers du projet
     (premier GPKG contenant la table "mesurage").
  2. Ajouter validation_ife/ au sys.path et importer le moteur.
  3. Ouvrir une connexion PostgreSQL (variables d'environnement VALIDATION_PG_*).
  4. Lancer engine.run() : validation + insertion si valide.
  5. Écrire la table rapport_validation dans le GPKG.
  6. Retourner un dict résumé (loggué dans le feedback du job QFieldCloud).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Chemin absolu vers validation_ife/ (relatif à ce fichier)
_VALIDATION_IFE_DIR = Path(__file__).parent / "validation_ife"


def _ensure_validation_path() -> None:
    """Ajoute validation_ife/ à sys.path si nécessaire."""
    p = str(_VALIDATION_IFE_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


_IPE_SIGNATURE_TABLES = frozenset({"mesurage", "infor_gener"})


def _find_ipe_gpkg(project_dir: Path) -> Path | None:
    """Cherche le GPKG IPE dans project_dir.

    Critère : fichier .gpkg contenant simultanément toutes les tables de
    _IPE_SIGNATURE_TABLES dans gpkg_contents. Un fond de carte ou un GPKG de
    référence ne possèdera pas l'ensemble de ces tables métier IFE — ce qui
    élimine les faux positifs quand un projet contient plusieurs GPKG.

    QFieldCloud peut suffixer les noms de tables avec un UUID lors du packaging
    (ex. mesurage_4f552916_c02c_43c8_bdac_48c7a363bb95). On accepte donc les
    noms exacts ET les noms préfixés par sig + "_".
    """
    for gpkg in sorted(project_dir.rglob("*.gpkg")):
        try:
            con = sqlite3.connect(str(gpkg))
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            all_tables = {row[0] for row in cur.fetchall()}
            con.close()
            matched = {
                sig
                for sig in _IPE_SIGNATURE_TABLES
                if any(t == sig or t.startswith(sig + "_") for t in all_tables)
            }
            if matched == _IPE_SIGNATURE_TABLES:
                logger.info("GPKG IPE trouvé : %s", gpkg)
                return gpkg
        except Exception as exc:
            logger.debug("Impossible de lire %s : %s", gpkg, exc)
    return None


def _write_rapport_to_gpkg(gpkg_path: Path, result: Any) -> None:
    """Écrit (ou remplace) la table rapport_validation dans le GPKG.

    La table est enregistrée dans gpkg_contents (type "attributes") afin
    d'être reconnue par QGIS Desktop et QField comme couche attributaire.
    """
    con = sqlite3.connect(str(gpkg_path))
    cur = con.cursor()

    # ── Créer/réinitialiser la table ──────────────────────────────────────
    cur.execute("DROP TABLE IF EXISTS rapport_validation")
    cur.execute("""
        CREATE TABLE rapport_validation (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            statut    TEXT    NOT NULL,
            couche    TEXT,
            code_regle TEXT,
            severite  TEXT,
            message   TEXT,
            champs    TEXT,
            enregistrement TEXT,
            genere_le TEXT    NOT NULL
        )
    """)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    statut = "VALIDE" if result.is_valid else "INVALIDE"

    # Ligne de résumé
    resume = (
        "Données valides — insérées en base."
        if result.is_valid and result.inserted
        else "Données valides (dry-run, non insérées)."
        if result.is_valid
        else f"{len(result.errors)} erreur(s), {len(result.warnings)} avertissement(s). Non insérées."
    )
    cur.execute(
        "INSERT INTO rapport_validation (statut, couche, code_regle, severite, message, champs, enregistrement, genere_le) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (statut, None, "RESUME", "info", resume, None, None, now_iso),
    )

    # Une ligne par anomalie
    for issue in result.issues:
        cur.execute(
            "INSERT INTO rapport_validation (statut, couche, code_regle, severite, message, champs, enregistrement, genere_le) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                statut,
                issue.layer,
                issue.code,
                issue.severity.value,
                issue.message,
                ", ".join(issue.fields) if issue.fields else None,
                json.dumps(issue.record, ensure_ascii=False) if issue.record else None,
                now_iso,
            ),
        )

    # ── Enregistrer dans gpkg_contents ────────────────────────────────────
    cur.execute(
        """
        INSERT OR REPLACE INTO gpkg_contents
            (table_name, data_type, identifier, description, last_change)
        VALUES (?, 'attributes', 'Rapport de validation', 'Rapport de validation IFE', ?)
        """,
        ("rapport_validation", now_iso),
    )

    con.commit()
    con.close()
    logger.info(
        f"rapport_validation écrit dans {gpkg_path} "
        f"({len(result.issues)} anomalie(s))"
    )


def _add_rapport_layer_to_qgs(project_dir: Path, gpkg_path: Path) -> None:
    """Injecte la couche rapport_validation dans le .qgs si elle est absente.

    Modifie le XML du projet directement (sans PyQGIS) pour ajouter :
      - un <maplayer> dans <projectlayers>
      - un <layer-tree-layer> dans le groupe racine <layer-tree-group>

    Le QGS modifié sera uploadé au même titre que le GPKG lors du Upload Project.
    Sur les syncs suivants la couche est déjà présente → aucune modification.
    """
    qgs_files = list(project_dir.glob("*.qgs"))
    if not qgs_files:
        logger.debug("Pas de .qgs dans %s — couche non ajoutée au projet", project_dir)
        return
    qgs_path = qgs_files[0]
    content = qgs_path.read_text(encoding="utf-8")

    datasource = f"./{gpkg_path.name}|layername=rapport_validation"

    if "layername=rapport_validation" in content:
        logger.info("Couche rapport_validation déjà présente dans %s", qgs_path.name)
        return

    layer_id = "rapport_validation_" + str(uuid.uuid4()).replace("-", "_")

    # ── Définition <maplayer> ──────────────────────────────────────────────
    maplayer = (
        '<maplayer type="vector" geometry="No geometry" autoRefreshEnabled="0" '
        'autoRefreshTime="0" hasScaleBasedVisibilityFlag="0" labelsEnabled="0" '
        'refreshOnNotifyEnabled="0" refreshOnNotifyMessage="">'
        f"<id>{layer_id}</id>"
        f"<datasource>{datasource}</datasource>"
        "<keywordList><value/></keywordList>"
        "<layername>rapport_validation</layername>"
        '<srs><spatialrefsys nativeFormat="Wkt"><wkt/><proj4/><srsid>0</srsid>'
        "<srid>0</srid><authid/><description/><projectionacronym/>"
        "<ellipsoidacronym/><geographicFlag>false</geographicFlag>"
        "</spatialrefsys></srs>"
        '<provider encoding="UTF-8">ogr</provider>'
        "<vectorjoins/><layerGeometryType>4</layerGeometryType>"
        "</maplayer>"
    )

    if "</projectlayers>" not in content:
        logger.warning("Tag </projectlayers> absent de %s — couche non ajoutée", qgs_path.name)
        return
    content = content.replace("</projectlayers>", maplayer + "</projectlayers>", 1)

    # ── Entrée dans le layer-tree ──────────────────────────────────────────
    lt_layer = (
        f'<layer-tree-layer checked="Qt::Checked" expanded="1" '
        f'id="{layer_id}" name="rapport_validation" '
        f'source="{datasource}" providerKey="ogr">'
        "<customproperties/></layer-tree-layer>"
    )
    # Insérer après </custom-order> (présent dans le groupe racine QGIS ≥ 3.x)
    if "</custom-order>" in content:
        content = content.replace("</custom-order>", "</custom-order>" + lt_layer, 1)
    else:
        content = content.replace("</layer-tree-group>", lt_layer + "</layer-tree-group>", 1)

    qgs_path.write_text(content, encoding="utf-8")
    logger.info("Couche rapport_validation ajoutée au projet %s", qgs_path.name)


def validate_ife_data(project_dir: Path) -> dict[str, Any]:
    """Valide le GPKG IPE et insère les données en BD si valide.

    Appelé comme méthode d'une Step dans le workflow apply_deltas.

    Args:
        project_dir: répertoire contenant les fichiers du projet QFieldCloud
            (WorkDirPath("files") dans le workflow).

    Returns:
        Dictionnaire résumé sérialisable (loggué dans feedback du job).
    """
    _ensure_validation_path()

    # ── 1. Trouver le GPKG ────────────────────────────────────────────────
    gpkg_path = _find_ipe_gpkg(project_dir)
    if gpkg_path is None:
        logger.warning(
            "validate_ife_data : aucun GPKG IPE trouvé dans %s — étape ignorée.",
            project_dir,
        )
        return {"skipped": True, "reason": "no_ipe_gpkg"}

    # ── 2. Connexion PostgreSQL ────────────────────────────────────────────
    # Les variables d'environnement VALIDATION_PG_* doivent être définies
    # comme secrets QFieldCloud (ou dans le docker-compose.override.local.yml).
    import config as ife_config  # importé depuis validation_ife/ via sys.path

    try:
        import psycopg2

        conn = psycopg2.connect(ife_config.get_dsn())
    except Exception as exc:
        logger.error("validate_ife_data : connexion PostgreSQL échouée : %s", exc)
        # Écrire un rapport d'erreur dans le GPKG pour que le technicien soit informé
        _write_error_to_gpkg(gpkg_path, f"Connexion BD impossible : {exc}")
        return {"skipped": False, "error": str(exc)}

    # ── 3. Validation + insertion ──────────────────────────────────────────
    try:
        from core import engine  # importé depuis validation_ife/core/

        result = engine.run(
            gpkg_path,
            conn,
            pg_schema=ife_config.PG_SCHEMA,
            apply=True,
        )
    except Exception as exc:
        logger.error("validate_ife_data : erreur moteur : %s", exc, exc_info=True)
        conn.close()
        _write_error_to_gpkg(gpkg_path, f"Erreur interne du moteur : {exc}")
        return {"skipped": False, "error": str(exc)}
    finally:
        conn.close()

    # ── 4. Écrire le rapport dans le GPKG ─────────────────────────────────
    try:
        _write_rapport_to_gpkg(gpkg_path, result)
    except Exception as exc:
        logger.error("validate_ife_data : écriture rapport échouée : %s", exc)

    # ── 5. Ajouter la couche au projet QGS si absente ─────────────────────
    try:
        _add_rapport_layer_to_qgs(project_dir, gpkg_path)
    except Exception as exc:
        logger.warning("Impossible d'ajouter rapport_validation au QGS : %s", exc)

    # ── 6. Écrire le JSON pour le plugin QField ───────────────────────────
    try:
        _write_rapport_json(project_dir, gpkg_path, result)
    except Exception as exc:
        logger.warning("Impossible d'écrire rapport_ife.json : %s", exc)

    return {
        "skipped": False,
        "gpkg": str(gpkg_path),
        "is_valid": result.is_valid,
        "inserted": result.inserted,
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "layers_processed": result.layers_processed,
    }


def _write_rapport_json(project_dir: Path, gpkg_path: Path, result: Any) -> None:
    """Écrit rapport_ife.json à la racine du projet pour le plugin QField."""
    payload = result.to_dict()
    payload["gpkg"] = gpkg_path.name
    payload["genere_le"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json_path = project_dir / "rapport_ife.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("rapport_ife.json écrit dans %s", project_dir)


def _write_error_to_gpkg(gpkg_path: Path, message: str) -> None:
    """Écrit une ligne d'erreur technique dans rapport_validation."""
    try:
        con = sqlite3.connect(str(gpkg_path))
        cur = con.cursor()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        cur.execute("DROP TABLE IF EXISTS rapport_validation")
        cur.execute("""
            CREATE TABLE rapport_validation (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                statut    TEXT    NOT NULL,
                couche    TEXT,
                code_regle TEXT,
                severite  TEXT,
                message   TEXT,
                champs    TEXT,
                enregistrement TEXT,
                genere_le TEXT    NOT NULL
            )
        """)
        cur.execute(
            "INSERT INTO rapport_validation (statut, couche, code_regle, severite, message, champs, enregistrement, genere_le) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("ERREUR_SYSTEME", None, "SYSTEM", "error", message, None, None, now_iso),
        )
        cur.execute(
            """
            INSERT OR REPLACE INTO gpkg_contents
                (table_name, data_type, identifier, description, last_change)
            VALUES (?, 'attributes', 'Rapport de validation', 'Rapport de validation IFE', ?)
            """,
            ("rapport_validation", now_iso),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("Impossible d'écrire l'erreur dans le GPKG : %s", exc)
