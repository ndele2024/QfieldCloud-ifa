"""Supprimer une unité d'échantillonnage — « Consulter une UE ».

Une unité ne vit pas seule : ses **mesurages** et toutes les données de terrain
qui en dépendent (pêches, captures, habitat, physico-chimie…) portent son code
dans 42 tables de `ifa_data`. La supprimer, c'est supprimer tout cela, dans une
seule transaction : rien ne doit rester orphelin, et rien ne doit partir si une
seule table refuse.

---------------------------------------------------------------------------
LES DROITS — même logique que les projets (`projet_gestion.py`)
---------------------------------------------------------------------------
    verrouillée par un autre   personne, administrateur compris — une équipe
                               travaille dessus ; elle doit d'abord la rendre
    administrateur             toute unité
    utilisateur standard       les unités qu'il a créées, tant que leurs
                               données ne sont pas diffusées

* **Créateur** : `une_code_utili_creat`, comparé comme pour un projet (nom
  QFieldCloud tronqué à 20 caractères, casse ignorée — `projet_gestion.meme_auteur`).
* **Diffusée** : au moins un mesurage porte `une_etat_diffu = 'D'`. C'est le
  pendant du projet « en production » : des données publiées ne disparaissent
  que par la main d'un administrateur. Tout le fonds hérité est diffusé ; une
  unité créée dans « Créer une UE » ne l'est pas tant qu'elle n'a pas été
  validée et diffusée.
* **Administrateur** : `projet_gestion.est_admin` — rôle `admin` dans
  l'organisation `IFA_ORGANISATION_ADMIN`, ou superutilisateur.
* **Verrou** : une unité tenue par l'utilisateur lui-même reste supprimable
  — c'est le cas d'une unité créée par erreur dans « Créer une UE », qui naît
  verrouillée à son nom.

Le mot de passe de l'utilisateur est exigé et vérifié **avant** toute lecture.

---------------------------------------------------------------------------
L'ORDRE DE SUPPRESSION
---------------------------------------------------------------------------
Les clés étrangères de `ifa_data` sont toutes en `NO ACTION` : un parent ne
part qu'une fois ses enfants partis. `NIVEAUX` range les tables des feuilles
vers la racine ; il suit le graphe des clés étrangères relevé sur la base
(voir les tests). Toutes ces tables portent `une_code_ident`, ce qui permet de
supprimer par simple égalité, sans jointure.

Une table de `ifa_data` qui porte `une_code_ident` sans figurer ici — ajoutée
au schéma après ce module — n'est jamais vidée à l'aveugle : si elle contient
des lignes de l'unité, la suppression est refusée (`TablesInconnuesError`).
"""

from __future__ import annotations

import logging
from typing import Any

from qfieldcloud.ifa import db, projet_gestion, verrou
from qfieldcloud.ifa.exceptions import (
    FiltreInvalideError,
    MotDePasseInvalideError,
    SuppressionRefuseeError,
    TablesInconnuesError,
    UniteIntrouvableError,
)

logger = logging.getLogger(__name__)

LONGUEUR_CODE = 40

DIFFUSE = "D"

# Les tables des données de terrain d'une unité, des feuilles vers la racine.
# Chaque niveau ne dépend que des niveaux suivants.
NIVEAUX: tuple[tuple[str, ...], ...] = (
    # → detail_speci
    ("anoma_speci",),
    # → pose_levee_filet
    ("denom_espec", "detail_speci"),
    # → peche_exper, amenagement, analy_physi_chimi, carac_envir_lotiq,
    #   descr_habit, ensemencement, habitat, recol_peche_sport
    (
        "pose_levee_filet",
        "espec_amena",
        "profi_mesur",
        "resul_analy_physi_chimi",
        "titra_alcal",
        "facie",
        "forme_envir_struc",
        "geome_longi",
        "geome_trans",
        "granu_lit",
        "mobilite",
        "trans_vites",
        "veget",
        "forme_descr_habit",
        "marqu_ensem",
        "espec_habit",
        "forme_eleme_habit",
        "recou_espec_veget_aquat",
        "descr_speci_peche_sport",
    ),
    # → mesurage
    (
        "amenagement",
        "analy_physi_chimi",
        "autre_obser_fauni",
        "carac_envir_lotiq",
        "descr_habit",
        "detai_speci_mosa",
        "ensemencement",
        "equipe",
        "habitat",
        "infor_gener",
        "infor_peche_sport",
        "labo_obser",
        "peche_exper",
        "perturbation",
        "plan_eau_conve",
        "quota_peche_sport",
        "recol_peche_sport",
        "resea_suivi_angui",
        "suiv_tempe",
        "suivi_recru_mosa",
    ),
    ("mesurage",),
)

# Toutes les tables de données, dans l'ordre de suppression ; l'unité vient
# après elles.
TABLES_DONNEES: tuple[str, ...] = tuple(t for niveau in NIVEAUX for t in niveau)
TABLE_UNITE = "unite_echan"


# =============================================================================
#  Droits
# =============================================================================
def droits(
    unite: dict[str, Any], nom_utilisateur: str, admin: bool, diffusee: bool
) -> dict[str, Any]:
    """Ce que l'utilisateur peut faire de cette unité, et pourquoi pas."""
    createur = projet_gestion.meme_auteur(
        unite.get("une_code_utili_creat"), nom_utilisateur
    )
    tenue_par_un_autre = verrou.tenue_par_un_autre(unite, nom_utilisateur)

    if tenue_par_un_autre:
        supprimable = False
        raison = (
            "L'unité {code} est verrouillée par {qui} : elle ne peut pas être "
            "supprimée tant que son détenteur ne l'a pas rendue.".format(
                code=unite["une_code_ident"],
                qui=unite.get("une_nom_propr_verro") or "un autre utilisateur",
            )
        )
    elif admin:
        supprimable = True
        raison = ""
    elif not createur:
        supprimable = False
        raison = (
            "Seul le créateur de l'unité ({qui}) ou un administrateur peut la "
            "supprimer.".format(qui=unite.get("une_code_utili_creat") or "inconnu")
        )
    elif diffusee:
        supprimable = False
        raison = (
            "Les données de cette unité sont diffusées : elle ne peut plus être "
            "supprimée que par un administrateur."
        )
    else:
        supprimable = True
        raison = ""

    return {
        "admin": admin,
        "createur": createur,
        "diffusee": diffusee,
        "verrouillee_par_un_autre": tenue_par_un_autre,
        "supprimable": supprimable,
        "raison_suppression": raison,
    }


# =============================================================================
#  Lecture
# =============================================================================
def lire(une_code_ident: str, utilisateur: Any) -> dict[str, Any]:
    """L'unité, ce que sa suppression emporterait, et les droits de l'appelant."""
    code = valider_code(une_code_ident)
    schema = db.schema()
    admin = projet_gestion.est_admin(utilisateur)

    with db.curseur() as cur:
        unite = unite_par_code(cur, schema, code)
        comptes = compter(cur, schema, code)
        diffusee = est_diffusee(cur, schema, code)

    return {
        **normaliser(unite),
        "nb_mesurages": comptes.get("mesurage", 0),
        "nb_enregistrements": sum(comptes.values()),
        "tables": comptes,
        "droits": droits(unite, utilisateur.username, admin, diffusee),
    }


# =============================================================================
#  Suppression
# =============================================================================
def supprimer(
    une_code_ident: str, utilisateur: Any, mot_de_passe: str
) -> dict[str, Any]:
    """Supprime l'unité et toutes ses données, si les droits le permettent."""
    code = valider_code(une_code_ident)

    if not mot_de_passe or not utilisateur.check_password(mot_de_passe):
        logger.warning(
            "[IFA] suppression de l'unite %s : mot de passe refuse pour %s",
            code,
            utilisateur.username,
        )
        raise MotDePasseInvalideError(
            "Mot de passe incorrect : l'unité n'a pas été supprimée."
        )

    schema = db.schema()
    admin = projet_gestion.est_admin(utilisateur)
    code_utilisateur = utilisateur.username[: verrou.LONGUEUR_UTILISATEUR]

    with db.curseur_ecriture() as cur:
        # La ligne verrouillée jusqu'à la fin : ni verrou posé, ni ouverture
        # entre la vérification des droits et la suppression.
        unite = unite_par_code(cur, schema, code, pour_supprimer=True)
        permis = droits(
            unite, utilisateur.username, admin, est_diffusee(cur, schema, code)
        )

        if not permis["supprimable"]:
            raise SuppressionRefuseeError(permis["raison_suppression"])

        verifier_tables_inconnues(cur, schema, code)

        supprimees: dict[str, int] = {}
        for table in TABLES_DONNEES:
            cur.execute(
                f"DELETE FROM {schema}.{table} WHERE une_code_ident = %s", [code]
            )
            if cur.rowcount:
                supprimees[table] = cur.rowcount

        cur.execute(
            f"DELETE FROM {schema}.{TABLE_UNITE} WHERE une_code_ident = %s", [code]
        )

    nb_mesurages = supprimees.get("mesurage", 0)
    nb_enregistrements = sum(supprimees.values())

    logger.warning(
        "[IFA] unite %s supprimee par %s%s : %s mesurage(s), %s enregistrement(s) %s",
        code,
        code_utilisateur,
        " (administrateur)" if admin else "",
        nb_mesurages,
        nb_enregistrements,
        supprimees,
    )

    return {
        "supprime": True,
        "une_code_ident": code,
        "nb_mesurages": nb_mesurages,
        "nb_enregistrements": nb_enregistrements,
        "tables": supprimees,
    }


# =============================================================================
#  Outils
# =============================================================================
def valider_code(une_code_ident: str) -> str:
    code = (une_code_ident or "").strip()
    if not code or len(code) > LONGUEUR_CODE:
        raise FiltreInvalideError(
            "Le code d'unité d'échantillonnage est absent ou trop long."
        )
    return code


def unite_par_code(
    cur: Any, schema: str, code: str, pour_supprimer: bool = False
) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT u.une_code_ident, u.tue_code_ident, t.tue_nom,
               coalesce(u.une_ind_verro, 'N') AS une_ind_verro,
               coalesce(u.une_nom_propr_verro, '') AS une_nom_propr_verro,
               u.une_date_verro, u.une_raiso_verro,
               u.une_date_creat, u.une_code_utili_creat,
               u.une_date_maj, u.une_code_utili_maj
          FROM {schema}.unite_echan u
          LEFT JOIN {schema}.type_unite_echan t
            ON t.tue_code_ident = u.tue_code_ident
         WHERE u.une_code_ident = %s
         {"FOR UPDATE OF u" if pour_supprimer else ""}
        """,
        [code],
    )
    lignes = db.lignes_en_dictionnaires(cur)
    if not lignes:
        raise UniteIntrouvableError(f"L'unité {code} n'existe pas dans la base IFA.")
    return lignes[0]


def compter(cur: Any, schema: str, code: str) -> dict[str, int]:
    """Lignes de l'unité dans chaque table de données, sans les tables vides.

    Une seule requête : chaque table porte `une_code_ident` en tête de sa clé
    primaire, chaque comptage passe par l'index.
    """
    morceaux = [
        f"SELECT %s::text AS t, count(*) AS n FROM {schema}.{table} "
        "WHERE une_code_ident = %s"
        for table in TABLES_DONNEES
    ]
    parametres: list[Any] = []
    for table in TABLES_DONNEES:
        parametres += [table, code]

    cur.execute(" UNION ALL ".join(morceaux), parametres)
    return {table: int(n) for table, n in cur.fetchall() if n}


def est_diffusee(cur: Any, schema: str, code: str) -> bool:
    cur.execute(
        f"""
        SELECT EXISTS (
            SELECT 1 FROM {schema}.mesurage
             WHERE une_code_ident = %s AND une_etat_diffu = %s
        )
        """,
        [code, DIFFUSE],
    )
    return bool(cur.fetchone()[0])


def verifier_tables_inconnues(cur: Any, schema: str, code: str) -> None:
    """Refuse si une table que ce module ignore contient des lignes de l'unité."""
    cur.execute(
        """
        SELECT c.table_name
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = %s
           AND c.column_name = 'une_code_ident'
           AND t.table_type = 'BASE TABLE'
        """,
        [schema],
    )
    connues = {*TABLES_DONNEES, TABLE_UNITE}
    inconnues = sorted(nom for (nom,) in cur.fetchall() if nom not in connues)

    occupees = []
    for table in inconnues:
        # Le nom vient du catalogue, pas de la demande.
        cur.execute(
            f'SELECT EXISTS (SELECT 1 FROM {schema}."{table}" '
            "WHERE une_code_ident = %s)",
            [code],
        )
        if cur.fetchone()[0]:
            occupees.append(table)

    if occupees:
        logger.error(
            "[IFA] suppression de l'unite %s bloquee : tables inconnues %s",
            code,
            occupees,
        )
        raise TablesInconnuesError(
            "L'unité {code} a des données dans {tables}, que la suppression ne "
            "sait pas traiter : rien n'a été supprimé. Signalez-le à "
            "l'administrateur de la base.".format(code=code, tables=", ".join(occupees))
        )


def normaliser(unite: dict[str, Any]) -> dict[str, Any]:
    def texte(v: Any) -> str:
        return "" if v is None else str(v).strip()

    def date(v: Any) -> str:
        return "" if v is None else v.isoformat()

    return {
        "une_code_ident": texte(unite["une_code_ident"]),
        "tue_nom": texte(unite["tue_nom"]),
        "une_ind_verro": texte(unite["une_ind_verro"]).upper() or "N",
        "une_nom_propr_verro": texte(unite["une_nom_propr_verro"]),
        "une_date_creat": date(unite["une_date_creat"]),
        "une_code_utili_creat": texte(unite["une_code_utili_creat"]),
        "une_date_maj": date(unite["une_date_maj"]),
        "une_code_utili_maj": texte(unite["une_code_utili_maj"]),
    }
