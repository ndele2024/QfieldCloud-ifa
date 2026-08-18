"""
config.py — Paramètres de connexion et constantes du programme.

Tout est surchargeable par variable d'environnement, pour permettre une
exécution isolée (valeurs codées ci-dessous, identiques aux autres
scripts du projet) ET une exécution future dans le conteneur QFieldCloud
(qui injecte ses propres paramètres de connexion via l'environnement —
voir README.md, section "Intégration QFieldCloud").
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

PG_HOST = os.environ.get("VALIDATION_PG_HOST", "localhost")
PG_PORT = os.environ.get("VALIDATION_PG_PORT", "5432")
PG_DB = os.environ.get("VALIDATION_PG_DB", "ifa")
PG_USER = os.environ.get("VALIDATION_PG_USER", "postgres")
PG_PASS = os.environ.get("VALIDATION_PG_PASS", "ndele")
PG_SCHEMA = os.environ.get("VALIDATION_PG_SCHEMA", "ifa_data")

# Liste des tables/couches IPE connues, dans l'ordre hiérarchique
# parent -> enfant (doit rester synchronisée avec IPE_TABLE_ORDER de
# generate_ipe_form.py et extract_ipe_subset.py si le schéma évolue).
IPE_TABLES = [
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


# Fichiers de référence LCE (Liste des cours d'eau/lacs) utilisés par
# rules/infor_gener.py::no_plan_eau_officiel_verifie_et_recopie pour
# vérifier/compléter le "No du plan d'eau officiel".
LAC_LCE_PATH = os.environ.get("VALIDATION_LAC_LCE_PATH", str(BASE_DIR / "lac_LCE.txt"))
COURS_EAU_LCE_PATH = os.environ.get("VALIDATION_COURS_EAU_LCE_PATH", str(BASE_DIR / "cours_eau_LCE.txt"))

# Alias (libellés lisibles) des colonnes de la base, utilisés par
# core/db_schema.py dans les messages d'erreur à destination de
# l'utilisateur. Généré depuis "table-colonne-allias.xlsx" par
# generate_column_aliases.py — relancer ce script si le classeur change.
COLUMN_ALIASES_PATH = os.environ.get(
    "VALIDATION_COLUMN_ALIASES_PATH", str(BASE_DIR / "column_aliases.json")
)


def get_dsn() -> str:
    """Chaîne de connexion psycopg2 construite depuis les paramètres ci-dessus."""
    return f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} user={PG_USER} password={PG_PASS}"
