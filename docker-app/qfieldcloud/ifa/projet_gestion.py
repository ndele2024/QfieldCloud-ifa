"""Consultation, modification et suppression d'un projet de sondage.

C'est le serveur de la fenêtre « Modifier / Afficher / Supprimer un projet ».
La création, elle, vit dans `projet_sonda.py`, dont ce module reprend les
contrôles (n° unique, types existants).

---------------------------------------------------------------------------
QUI PEUT QUOI — `droits()`
---------------------------------------------------------------------------
Est **administrateur** un superutilisateur de QFieldCloud, ou un membre de
rôle `admin` de l'organisation `IFA_ORGANISATION_ADMIN` (`ifa_team` par
défaut). `is_staff` n'en fait pas un : ce drapeau ouvre la page
d'administration Django, il ne dit rien du métier.

Modifier :
  * un projet **en production** (`Pr`) ne se modifie que par un
    administrateur ; pour les autres, la fenêtre est en lecture seule ;
  * un projet **déjà utilisé par une UE** — au moins un mesurage le
    référence — ne se modifie plus que dans son **nom** et sa
    **description**, administrateur compris : le reste (n°, région, année,
    statut, types…) qualifie des données déjà saisies.

Supprimer :
  * un administrateur supprime tout projet ;
  * un utilisateur standard ne supprime que **les projets qu'il a créés**
    (`pro_code_utili_creat`), et **pas en production** ;
  * dans tous les cas, le **mot de passe** de l'utilisateur est exigé et
    vérifié par le serveur ;
  * **aucun projet utilisé par une UE n'est supprimé, administrateur
    compris.** `mesurage.pro_code_ident` n'a pas de clé étrangère vers
    `proje_sonda` : la base laisserait faire, et les mesurages resteraient
    rattachés à un projet disparu. C'est une protection des données, pas une
    question de droits.

Les droits sont calculés ici et rendus au plugin, qui s'en sert pour
présenter la fenêtre (champs grisés, alertes). Ils sont **recalculés** à
chaque modification et suppression, dans la transaction qui écrit : le
plugin n'est pas une barrière.

---------------------------------------------------------------------------
« UTILISÉ PAR UNE UE »
---------------------------------------------------------------------------
Le seul lien entre une unité et un projet est `mesurage.pro_code_ident`.
`mesurage` n'a pas d'index sur cette colonne : compter les unités d'un projet
balaye la table (~350 ms sur 700 000 mesurages, autant pour la liste entière
grâce à un seul `DISTINCT`). `sql/index_recommandes.sql` propose l'index.

---------------------------------------------------------------------------
MODIFICATIONS CONCURRENTES
---------------------------------------------------------------------------
La demande de modification porte le `pro_date_maj` lu par la fenêtre. S'il a
changé depuis, quelqu'un d'autre a modifié le projet entre-temps : la demande
est refusée (409) plutôt que d'écraser son travail sans le voir.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from qfieldcloud.core.models import Organization, OrganizationMember
from qfieldcloud.core.permissions_utils import user_has_organization_roles
from qfieldcloud.ifa import db, projet_sonda, verrou
from qfieldcloud.ifa.exceptions import (
    FiltreInvalideError,
    ModificationRefuseeError,
    MotDePasseInvalideError,
    ProjetExistantError,
    ProjetIntrouvableError,
    ProjetModifieEntreTempsError,
    SuppressionRefuseeError,
)

logger = logging.getLogger(__name__)

STATUTS = (
    projet_sonda.STATUT_ELABORATION,
    projet_sonda.STATUT_PRODUCTION,
    projet_sonda.STATUT_TERMINE,
)

# Les champs qu'une modification peut toucher, dans l'ordre du formulaire.
CHAMPS = (
    "pro_no",
    "pro_nom",
    "pro_an",
    "rad_no",
    "pro_code_statu",
    "pro_ind_inven_norma",
    "types_ue",
    "pro_descr",
    "pro_com",
)

# Pseudo-champ : les nombres planifiés des types d'UE déjà associés, sans en
# ajouter ni en retirer. La demande les envoie dans `types_ue` ; une liste qui
# garde les mêmes types et ne change que leurs nombres compte comme ce champ.
NOMBRES_PLANIFIES = "types_ue_nombres"

# Tout ce qu'un projet libre de droits laisse modifier.
CHAMPS_TOUS = (*CHAMPS, NOMBRES_PLANIFIES)

# Ce qui reste modifiable d'un projet déjà utilisé par une UE : ni ses types
# (des mesurages en dépendent), mais leurs nombres planifiés, oui.
CHAMPS_PROJET_UTILISE = ("pro_nom", "pro_descr", NOMBRES_PLANIFIES)

LIBELLES = {
    "pro_no": "le n°",
    "pro_nom": "le nom",
    "pro_an": "l'année",
    "rad_no": "la région",
    "pro_code_statu": "le statut",
    "pro_ind_inven_norma": "l'indicateur d'inventaire normalisé",
    "types_ue": "les types d'UE",
    NOMBRES_PLANIFIES: "les nombres planifiés",
    "pro_descr": "la description",
    "pro_com": "le commentaire",
}

COLONNES_PROJET = """
    p.pro_code_ident, p.pro_no, p.pro_nom, p.pro_an, p.rad_no,
    p.pro_descr, p.pro_com, p.pro_code_statu, p.pro_date_statu,
    p.pro_date_premi_mise_produ, p.pro_ind_inven_norma,
    p.pro_date_creat, p.pro_code_utili_creat,
    p.pro_date_maj, p.pro_code_utili_maj
"""


# =============================================================================
#  Droits
# =============================================================================
def est_admin(utilisateur: Any) -> bool:
    """Superutilisateur, ou administrateur de l'organisation IFA."""
    if getattr(utilisateur, "is_superuser", False):
        return True

    nom = (getattr(settings, "IFA_ORGANISATION_ADMIN", "") or "").strip()
    if not nom:
        return False

    organisation = Organization.objects.filter(username=nom).first()
    if organisation is None:
        return False

    return user_has_organization_roles(
        utilisateur, organisation, [OrganizationMember.Roles.ADMIN]
    )


def est_createur(projet: dict[str, Any], nom_utilisateur: str) -> bool:
    """L'utilisateur a-t-il créé ce projet ?"""
    return meme_auteur(projet.get("pro_code_utili_creat"), nom_utilisateur)


def meme_auteur(code_utilisateur: str | None, nom_utilisateur: str) -> bool:
    """Le code d'auteur d'une ligne (`*_code_utili_creat`) désigne-t-il l'utilisateur ?

    Le code porte le nom tronqué à 20 caractères — comme à l'écriture — et,
    pour le fonds hérité, le code Oracle de l'agent : la comparaison ignore la
    casse. Sert aussi aux unités (`unite_gestion.py`).
    """
    auteur = (code_utilisateur or "").strip().lower()
    nom = (nom_utilisateur or "")[: verrou.LONGUEUR_UTILISATEUR].strip().lower()
    return bool(auteur) and auteur == nom


def droits(
    projet: dict[str, Any], nom_utilisateur: str, admin: bool, nb_unites: int
) -> dict[str, Any]:
    """Ce que l'utilisateur peut faire de ce projet, et pourquoi pas le reste."""
    en_production = projet.get("pro_code_statu") == projet_sonda.STATUT_PRODUCTION
    utilise = nb_unites > 0
    createur = est_createur(projet, nom_utilisateur)

    # ---- Modification -------------------------------------------------------
    if en_production and not admin:
        modifiable = False
        champs: list[str] = []
        raison_modification = (
            "Ce projet est en production : seul un administrateur peut le modifier."
        )
    elif utilise:
        modifiable = True
        champs = list(CHAMPS_PROJET_UTILISE)
        raison_modification = (
            f"Ce projet est utilisé par {nb_unites} unité(s) d'échantillonnage : "
            "seuls son nom, sa description et les nombres planifiés de ses "
            "types d'UE sont modifiables."
        )
    else:
        modifiable = True
        champs = list(CHAMPS_TOUS)
        raison_modification = ""

    # ---- Suppression --------------------------------------------------------
    if utilise:
        supprimable = False
        raison_suppression = (
            f"Ce projet est utilisé par {nb_unites} unité(s) d'échantillonnage : "
            "il ne peut pas être supprimé, sans quoi leurs mesurages resteraient "
            "rattachés à un projet disparu."
        )
    elif admin:
        supprimable = True
        raison_suppression = ""
    elif not createur:
        supprimable = False
        raison_suppression = (
            "Seul le créateur du projet ({qui}) ou un administrateur peut le "
            "supprimer.".format(qui=projet.get("pro_code_utili_creat") or "inconnu")
        )
    elif en_production:
        supprimable = False
        raison_suppression = (
            "Ce projet est en production : il ne peut plus être supprimé que "
            "par un administrateur."
        )
    else:
        supprimable = True
        raison_suppression = ""

    return {
        "admin": admin,
        "createur": createur,
        "utilise": utilise,
        "nb_unites": nb_unites,
        "modifiable": modifiable,
        "champs_modifiables": champs,
        "raison_modification": raison_modification,
        "supprimable": supprimable,
        "raison_suppression": raison_suppression,
    }


# =============================================================================
#  Lecture
# =============================================================================
def lister(utilisateur: Any) -> dict[str, Any]:
    """Tous les projets, avec leur nombre d'unités et les droits de l'appelant.

    Pas de pagination : le fonds compte quelques centaines de projets, et la
    fenêtre filtre elle-même la liste à la frappe.
    """
    schema = db.schema()
    admin = est_admin(utilisateur)

    with db.curseur() as cur:
        cur.execute(
            f"""
            SELECT {COLONNES_PROJET}, coalesce(u.nb_unites, 0) AS nb_unites
              FROM {schema}.proje_sonda p
              LEFT JOIN (
                    SELECT pro_code_ident, count(*) AS nb_unites
                      FROM (
                            SELECT DISTINCT pro_code_ident, une_code_ident
                              FROM {schema}.mesurage
                             WHERE pro_code_ident IS NOT NULL
                           ) s
                     GROUP BY pro_code_ident
                   ) u ON u.pro_code_ident = p.pro_code_ident
             ORDER BY p.pro_an DESC NULLS LAST, lower(p.pro_no)
            """
        )
        lignes = db.lignes_en_dictionnaires(cur)

    projets = []
    for ligne in lignes:
        projet = normaliser(ligne)
        projet["nb_unites"] = int(ligne["nb_unites"])
        projet["droits"] = droits(
            projet, utilisateur.username, admin, projet["nb_unites"]
        )
        projets.append(projet)

    return {"admin": admin, "utilisateur": utilisateur.username, "projets": projets}


def lire(pro_code_ident: str, utilisateur: Any) -> dict[str, Any]:
    """Un projet, ses types d'UE, son nombre d'unités et les droits."""
    code = valider_code(pro_code_ident)
    schema = db.schema()
    admin = est_admin(utilisateur)

    with db.curseur() as cur:
        ligne = projet_par_code(cur, schema, code)
        nb_unites = nombre_unites(cur, schema, code)
        types = projet_sonda.types_associes(cur, schema, code)

    projet = normaliser(ligne)
    projet["types_ue"] = types
    projet["nb_unites"] = nb_unites
    projet["droits"] = droits(projet, utilisateur.username, admin, nb_unites)
    return projet


# =============================================================================
#  Modification
# =============================================================================
def modifier(
    pro_code_ident: str, demande: dict[str, Any], utilisateur: Any
) -> dict[str, Any]:
    """Applique les changements demandés, si les droits le permettent.

    `demande` est la sortie validée de `ModificationProjetSerializer` : seuls
    les champs envoyés y figurent, plus `pro_date_maj`. Un champ envoyé mais
    identique à la base n'est pas un changement — il ne demande aucun droit.
    """
    code = valider_code(pro_code_ident)
    schema = db.schema()
    admin = est_admin(utilisateur)
    nom = utilisateur.username
    code_utilisateur = nom[: verrou.LONGUEUR_UTILISATEUR]

    with db.curseur_ecriture() as cur:
        # Même verrou que la création : le n° reste unique même quand deux
        # personnes renomment ou créent en même temps.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [projet_sonda.CLE_VERROU_NUMERO],
        )
        ligne = projet_par_code(cur, schema, code, pour_modifier=True)
        actuel = normaliser(ligne)

        if (demande.get("pro_date_maj") or "") != actuel["pro_date_maj"]:
            raise ProjetModifieEntreTempsError(
                "Le projet {no} a été modifié par {qui} depuis son ouverture. "
                "Rouvrez-le pour voir ses nouvelles valeurs.".format(
                    no=actuel["pro_no"],
                    qui=actuel["pro_code_utili_maj"] or "quelqu'un d'autre",
                ),
            )

        actuel["types_ue"] = projet_sonda.types_associes(cur, schema, code)
        nb_unites = nombre_unites(cur, schema, code)
        permis = droits(actuel, nom, admin, nb_unites)

        changements = changements_effectifs(actuel, demande)
        if not changements:
            logger.info("[IFA] projet %s : aucune modification", actuel["pro_no"])
        else:
            verifier_droits_modification(changements, permis)
            ecrire_modification(
                cur, schema, code, actuel, changements, code_utilisateur
            )

    if changements:
        logger.info(
            "[IFA] projet %s modifie par %s : %s",
            actuel["pro_no"],
            code_utilisateur,
            ", ".join(sorted(changements)),
        )

    return lire(code, utilisateur)


def changements_effectifs(
    actuel: dict[str, Any], demande: dict[str, Any]
) -> dict[str, Any]:
    """Les champs demandés dont la valeur diffère de la base."""
    changements = {}

    for champ in CHAMPS:
        if champ not in demande:
            continue

        valeur = demande[champ]

        if champ == "types_ue":
            if _cle_types(valeur) != _cle_types(actuel["types_ue"]):
                # Mêmes types, autres nombres : un droit plus large suffit.
                memes_types = _codes_types(valeur) == _codes_types(actuel["types_ue"])
                changements[NOMBRES_PLANIFIES if memes_types else champ] = valeur
        elif champ == "pro_ind_inven_norma":
            if bool(valeur) != (actuel[champ] == projet_sonda.OUI):
                changements[champ] = valeur
        elif champ == "pro_an":
            if int(valeur) != actuel[champ]:
                changements[champ] = valeur
        elif (valeur or "") != (actuel[champ] or ""):
            changements[champ] = valeur

    return changements


def verifier_droits_modification(
    changements: dict[str, Any], permis: dict[str, Any]
) -> None:
    """Lève si l'un des changements n'est pas permis."""
    if not permis["modifiable"]:
        raise ModificationRefuseeError(permis["raison_modification"])

    refuses = [c for c in changements if c not in permis["champs_modifiables"]]
    if refuses:
        raise ModificationRefuseeError(
            "{raison} Modification refusée pour {champs}.".format(
                raison=permis["raison_modification"],
                champs=", ".join(LIBELLES[c] for c in refuses),
            ),
        )


def ecrire_modification(
    cur: Any,
    schema: str,
    code: str,
    actuel: dict[str, Any],
    changements: dict[str, Any],
    code_utilisateur: str,
) -> None:
    """Écrit les changements, déjà autorisés, dans la transaction ouverte."""
    if "pro_no" in changements:
        existant = projet_sonda.projet_par_numero(cur, schema, changements["pro_no"])
        if existant is not None and existant["pro_code_ident"] != code:
            raise ProjetExistantError(
                "Le n° de projet « {no} » est déjà porté par le projet « {nom} » "
                "({an}). Choisissez un autre numéro.".format(
                    no=changements["pro_no"],
                    nom=existant["pro_nom"] or existant["pro_no"],
                    an=existant["pro_an"] or "année inconnue",
                ),
            )

    # Lève si un type est inconnu, avant toute écriture.
    if NOMBRES_PLANIFIES in changements:
        changements = {**changements, "types_ue": changements[NOMBRES_PLANIFIES]}

    if "types_ue" in changements:
        projet_sonda.noms_des_types(
            cur, schema, [t["tue_code_ident"] for t in changements["types_ue"]]
        )

    # Les noms de colonnes viennent de `CHAMPS`, jamais de la demande : seules
    # les valeurs voyagent en paramètres.
    affectations = []
    valeurs: dict[str, Any] = {"code": code, "utilisateur": code_utilisateur}

    for champ in ("pro_no", "pro_nom", "pro_an", "rad_no", "pro_descr", "pro_com"):
        if champ in changements:
            affectations.append(f"{champ} = %({champ})s")
            valeur = changements[champ]
            # Un texte vidé redevient NULL, comme à la création.
            valeurs[champ] = None if valeur == "" else valeur

    if "pro_ind_inven_norma" in changements:
        affectations.append("pro_ind_inven_norma = %(normalise)s")
        valeurs["normalise"] = (
            projet_sonda.OUI if changements["pro_ind_inven_norma"] else projet_sonda.NON
        )

    if "pro_code_statu" in changements:
        statut = changements["pro_code_statu"]
        affectations.append("pro_code_statu = %(statut)s")
        affectations.append("pro_date_statu = LOCALTIMESTAMP")
        # La première mise en production se date une fois pour toutes.
        affectations.append(
            "pro_date_premi_mise_produ = CASE WHEN %(en_production)s "
            "THEN coalesce(pro_date_premi_mise_produ, LOCALTIMESTAMP) "
            "ELSE pro_date_premi_mise_produ END"
        )
        valeurs["statut"] = statut
        valeurs["en_production"] = statut == projet_sonda.STATUT_PRODUCTION

    affectations.append("pro_date_maj = LOCALTIMESTAMP")
    affectations.append("pro_code_utili_maj = %(utilisateur)s")

    cur.execute(
        f"""
        UPDATE {schema}.proje_sonda
           SET {", ".join(affectations)}
         WHERE pro_code_ident = %(code)s
        """,
        valeurs,
    )

    if "types_ue" in changements:
        remplacer_types(
            cur, schema, code, actuel["types_ue"], changements["types_ue"],
            code_utilisateur,
        )  # fmt: skip


def remplacer_types(
    cur: Any,
    schema: str,
    code: str,
    anciens: list[dict[str, Any]],
    nouveaux: list[dict[str, Any]],
    code_utilisateur: str,
) -> None:
    """Fait de la liste des types celle demandée : retire, met à jour, ajoute.

    Les lignes inchangées ne sont pas touchées — leur date de création et de
    mise à jour reste celle d'origine.
    """
    avant = {t["tue_code_ident"]: t for t in anciens}
    apres = {t["tue_code_ident"]: t for t in nouveaux}

    retires = [c for c in avant if c not in apres]
    if retires:
        cur.execute(
            f"""
            DELETE FROM {schema}.proje_type_unite_echan
             WHERE pro_code_ident = %s AND tue_code_ident = ANY(%s)
            """,
            [code, retires],
        )

    for type_code, demande in apres.items():
        if type_code not in avant:
            projet_sonda.associer_types(cur, schema, code, [demande], code_utilisateur)
            continue

        ancien = avant[type_code]
        if (ancien["nb_impla_plani"], ancien["nb_remes_plani"]) == (
            demande["nb_impla_plani"],
            demande["nb_remes_plani"],
        ):
            continue

        cur.execute(
            f"""
            UPDATE {schema}.proje_type_unite_echan
               SET ptu_nb_impla_plani = %(implantations)s,
                   ptu_nb_remes_plani = %(remesurages)s,
                   ptu_date_maj = LOCALTIMESTAMP,
                   ptu_code_utili_maj = %(utilisateur)s
             WHERE pro_code_ident = %(projet)s AND tue_code_ident = %(type)s
            """,
            {
                "implantations": demande["nb_impla_plani"],
                "remesurages": demande["nb_remes_plani"],
                "utilisateur": code_utilisateur,
                "projet": code,
                "type": type_code,
            },
        )


# =============================================================================
#  Suppression
# =============================================================================
def supprimer(
    pro_code_ident: str, utilisateur: Any, mot_de_passe: str
) -> dict[str, Any]:
    """Supprime le projet et ses types d'UE, si les droits le permettent.

    Le mot de passe est vérifié **avant** toute lecture de la base : une
    suppression demandée par un appareil laissé ouvert ne doit rien apprendre
    à qui l'a ramassé.
    """
    code = valider_code(pro_code_ident)

    if not mot_de_passe or not utilisateur.check_password(mot_de_passe):
        logger.warning(
            "[IFA] suppression du projet %s : mot de passe refuse pour %s",
            code,
            utilisateur.username,
        )
        raise MotDePasseInvalideError()

    schema = db.schema()
    admin = est_admin(utilisateur)
    code_utilisateur = utilisateur.username[: verrou.LONGUEUR_UTILISATEUR]

    with db.curseur_ecriture() as cur:
        ligne = projet_par_code(cur, schema, code, pour_modifier=True)
        projet = normaliser(ligne)
        nb_unites = nombre_unites(cur, schema, code)
        permis = droits(projet, utilisateur.username, admin, nb_unites)

        if not permis["supprimable"]:
            raise SuppressionRefuseeError(permis["raison_suppression"])

        cur.execute(
            f"DELETE FROM {schema}.proje_type_unite_echan WHERE pro_code_ident = %s",
            [code],
        )
        types_supprimes = cur.rowcount
        cur.execute(
            f"DELETE FROM {schema}.proje_sonda WHERE pro_code_ident = %s", [code]
        )

    logger.warning(
        "[IFA] projet %s (%s) supprime par %s%s, avec %s type(s) d'UE",
        projet["pro_no"],
        code,
        code_utilisateur,
        " (administrateur)" if admin else "",
        types_supprimes,
    )

    return {
        "supprime": True,
        "pro_code_ident": code,
        "pro_no": projet["pro_no"],
        "types_supprimes": types_supprimes,
    }


# =============================================================================
#  Outils
# =============================================================================
def valider_code(pro_code_ident: str) -> str:
    code = (pro_code_ident or "").strip()
    if not code or len(code) > 40:
        raise FiltreInvalideError("L'identifiant du projet est absent ou trop long.")
    return code


def projet_par_code(
    cur: Any, schema: str, code: str, pour_modifier: bool = False
) -> dict[str, Any]:
    """La ligne du projet, ou `ProjetIntrouvableError`.

    `pour_modifier` pose un `FOR UPDATE` : la ligne est tenue jusqu'à la fin de
    la transaction, le temps de vérifier les droits puis d'écrire.
    """
    cur.execute(
        f"""
        SELECT {COLONNES_PROJET}
          FROM {schema}.proje_sonda p
         WHERE p.pro_code_ident = %s
         {"FOR UPDATE" if pour_modifier else ""}
        """,
        [code],
    )
    lignes = db.lignes_en_dictionnaires(cur)

    if not lignes:
        raise ProjetIntrouvableError(
            "Ce projet n'existe plus dans la base IFA : il a peut-être été supprimé."
        )

    return lignes[0]


def nombre_unites(cur: Any, schema: str, code: str) -> int:
    """Unités d'échantillonnage dont au moins un mesurage référence le projet."""
    cur.execute(
        f"""
        SELECT count(*)
          FROM (
                SELECT DISTINCT une_code_ident
                  FROM {schema}.mesurage
                 WHERE pro_code_ident = %s
               ) s
        """,
        [code],
    )
    return int(cur.fetchone()[0])


def normaliser(ligne: dict[str, Any]) -> dict[str, Any]:
    """La ligne du projet pour le plugin, avec sa dernière mise à jour."""
    projet = projet_sonda.normaliser(ligne)
    projet["pro_date_maj"] = projet_sonda._horodatage(ligne["pro_date_maj"])
    projet["pro_code_utili_maj"] = projet_sonda._texte(ligne["pro_code_utili_maj"])
    return projet


def _codes_types(types: list[dict[str, Any]]) -> set[str]:
    return {t["tue_code_ident"] for t in types}


def _cle_types(types: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    return sorted(
        (str(t["tue_code_ident"]), int(t["nb_impla_plani"]), int(t["nb_remes_plani"]))
        for t in types
    )
