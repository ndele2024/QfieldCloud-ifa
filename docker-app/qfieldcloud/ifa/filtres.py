"""Construction des requêtes de recherche d'unités d'échantillonnage.

Le module ne parle qu'à la grammaire du filtre — il ne touche ni à HTTP ni à la
connexion. Il produit un couple `(fragment SQL, paramètres)` que `views.py`
assemble avec le reste de la requête. Toutes les valeurs venues du client
passent en paramètres liés ; seuls le nom du schéma et le SRID (configuration
serveur, validés) sont concaténés.

Les cinq modes correspondent aux cinq critères de la fenêtre « Consulter
une UE » du plugin QField. Ils ne s'excluent pas : la fenêtre laisse en
sélectionner plusieurs, et `predicats()` les assemble en **conjonction** — une
unité doit satisfaire tous les critères cochés pour figurer dans le résultat.
C'est le sens attendu d'un formulaire de recherche : cocher « région 02 » puis
« bassin Saguenay » resserre la liste, il ne l'élargit pas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MODE_REGION = "region"
MODE_LCE = "lce"
MODE_BASSIN = "bassin"
MODE_CODE = "code"
MODE_EMPRISE = "emprise"

MODES = (MODE_REGION, MODE_LCE, MODE_BASSIN, MODE_CODE, MODE_EMPRISE)


def predicat(
    mode: str,
    schema: str,
    srid_metier: int,
    valeur: str = "",
    wkt: str = "",
) -> tuple[str, list[Any]]:
    """Fragment de `WHERE` portant sur `u` (alias de `unite_echan`)."""
    if mode == MODE_CODE:
        return _predicat_code(valeur)
    if mode == MODE_REGION:
        return _predicat_region(schema, valeur)
    if mode == MODE_LCE:
        return _predicat_lce(schema, valeur)
    if mode == MODE_BASSIN:
        return _predicat_bassin(schema, valeur)
    if mode == MODE_EMPRISE:
        return _predicat_emprise(schema, srid_metier, wkt)

    raise ValueError(f"Mode de recherche inconnu : {mode!r}")


def predicats(
    criteres: Sequence[Mapping[str, Any]],
    schema: str,
    srid_metier: int,
) -> tuple[str, list[Any]]:
    """Conjonction des critères retenus, sous la forme `(fragment, paramètres)`.

    Chaque critère est un dictionnaire `{mode, valeur}` — ou `{mode, wkt}` pour
    l'emprise —, déjà validé par le sérialiseur. Les fragments sont
    parenthésés avant d'être joints par `AND` : chacun est un `EXISTS` ou une
    comparaison simple aujourd'hui, mais un fragment futur contenant un `OR`
    changerait sinon le sens de toute la clause.

    L'ordre est celui du client. Il ne change rien au résultat, mais il rend
    les requêtes reproductibles — et donc lisibles dans les journaux et dans un
    `EXPLAIN`.
    """
    if not criteres:
        raise ValueError("Au moins un critère de recherche est attendu.")

    fragments: list[str] = []
    parametres: list[Any] = []

    for critere in criteres:
        fragment, valeurs = predicat(
            mode=critere["mode"],
            schema=schema,
            srid_metier=srid_metier,
            valeur=str(critere.get("valeur", "") or ""),
            wkt=str(critere.get("wkt", "") or ""),
        )
        fragments.append(f"({fragment})")
        parametres.extend(valeurs)

    return "\n          AND ".join(fragments), parametres


def _predicat_code(valeur: str) -> tuple[str, list[Any]]:
    """Fragment de code d'unité, n'importe où dans le code.

    La recherche est volontairement partielle : un technicien connaît rarement
    le code entier. Il tape le n° du plan d'eau (« 12777 »), le type
    (« ANRO »), ou le début du code (« 02-127 ») — et attend la liste de ce qui
    correspond, pas un « aucun résultat » parce qu'il manquait un segment.

    La comparaison ignore aussi la casse. La grande majorité des codes sont en
    capitales, mais quelques familles historiques (réseau ANRO) portent des
    minuscules : les chercher tels quels écarterait des unités pourtant
    valides.

    Le balayage complet que cela impose coûte de 45 à 90 millisecondes sur
    142 000 lignes. Un index trigramme (`pg_trgm`) le ramènerait à quelques
    millisecondes, mais demanderait une extension sur la base du ministère —
    voir `sql/index_recommandes.sql`.
    """
    return "u.une_code_ident ILIKE %s", [f"%{_echapper_like(valeur.strip())}%"]


def _echapper_like(valeur: str) -> str:
    """Neutralise les jokers de `LIKE` dans une saisie d'utilisateur.

    Sans cela, un « % » tapé par mégarde ramènerait la table entière, et un
    « _ » remplacerait silencieusement n'importe quel caractère — deux
    comportements que personne n'a demandés et que rien n'expliquerait à
    l'écran. Le caractère d'échappement est la barre oblique inverse, valeur
    par défaut de PostgreSQL.
    """
    return valeur.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _predicat_region(schema: str, valeur: str) -> tuple[str, list[Any]]:
    """Région administrative du projet de sondage rattaché à l'unité.

    La région n'est pas une colonne d'`unite_echan`. Le préfixe du code
    (« 02-… ») s'en approche mais ment : plus de 5 000 unités portent un préfixe
    différent de la région de leur projet. La source qui fait foi est
    `proje_sonda.rad_no`, atteinte par les mesurages de l'unité.
    """
    fragment = f"""EXISTS (
            SELECT 1
            FROM {schema}.mesurage m
            JOIN {schema}.proje_sonda p ON p.pro_code_ident = m.pro_code_ident
            WHERE m.une_code_ident = u.une_code_ident
              AND p.rad_no::text = %s
        )"""
    return fragment, [valeur.strip()]


def _predicat_lce(schema: str, valeur: str) -> tuple[str, list[Any]]:
    """N° de plan d'eau (code LCE).

    Le numéro est stocké avec des zéros de tête (« 00256 ») alors que le
    technicien saisit « 256 ». On compare donc les deux côtés dézérotés. Le
    numéro officiel (`ing_no_plan_eau_offic`, renseigné 9 fois sur 10) et le
    numéro saisi (`ing_no_plan_eau`) sont interrogés tous les deux : ils
    diffèrent sur une partie du fonds.
    """
    numero = valeur.strip().lstrip("0")
    fragment = f"""EXISTS (
            SELECT 1
            FROM {schema}.infor_gener i
            WHERE i.une_code_ident = u.une_code_ident
              AND (
                    ltrim(i.ing_no_plan_eau_offic, '0') = %s
                 OR ltrim(i.ing_no_plan_eau, '0') = %s
              )
        )"""
    return fragment, [numero, numero]


def _predicat_bassin(schema: str, valeur: str) -> tuple[str, list[Any]]:
    """Nom du bassin versant (`infor_gener.ing_nom_bassi`).

    La recherche est partielle et insensible à la casse, comme celle par code
    d'unité, et pour la même raison : le nom est un texte libre du fonds
    hérité, saisi au fil des années sans référentiel fermé. On y trouve aussi
    bien « Saguenay » que « SAGUENAY (BASSIN) » ; exiger la forme exacte
    reviendrait à n'offrir le critère qu'à ceux qui connaissent déjà la
    graphie stockée.

    Le nom n'est pas une colonne d'`unite_echan` : il est porté par les
    `infor_gener` de l'unité, comme le n° de plan d'eau — d'où le même
    `EXISTS`, qui répond dès la première ligne trouvée.
    """
    fragment = f"""EXISTS (
            SELECT 1
            FROM {schema}.infor_gener i
            WHERE i.une_code_ident = u.une_code_ident
              AND i.ing_nom_bassi ILIKE %s
        )"""
    return fragment, [f"%{_echapper_like(valeur.strip())}%"]


def _predicat_emprise(schema: str, srid_metier: int, wkt: str) -> tuple[str, list[Any]]:
    """Zone tracée sur la carte, en EPSG:4326.

    Le polygone est reprojeté vers le SRID des données (`shape`) plutôt que
    l'inverse : transformer 638 000 points à chaque recherche interdirait
    l'usage de l'index GiST, transformer le seul polygone du filtre le
    préserve.
    """
    fragment = f"""EXISTS (
            SELECT 1
            FROM {schema}.infor_gener i
            WHERE i.une_code_ident = u.une_code_ident
              AND i.shape IS NOT NULL
              AND ST_Intersects(
                    i.shape,
                    ST_Transform(ST_GeomFromText(%s, 4326), {int(srid_metier)})
              )
        )"""
    return fragment, [wkt]


def libelle_critere(critere: Mapping[str, Any]) -> str:
    """Un critère en quelques mots, pour les messages et le journal."""
    mode = critere["mode"]
    valeur = str(critere.get("valeur", "") or "").strip()

    if mode == MODE_REGION:
        return f"région {valeur}"
    if mode == MODE_LCE:
        return f"plan d'eau n° {valeur}"
    if mode == MODE_BASSIN:
        return f"bassin « {valeur} »"
    if mode == MODE_CODE:
        return f"code contenant « {valeur} »"

    return "emprise tracée"


def libelle_criteres(criteres: Sequence[Mapping[str, Any]]) -> str:
    """Le filtre entier en une ligne.

    Les critères sont joints par « et » et non par une virgule : c'est bien
    une conjonction, et la phrase doit dire au technicien pourquoi sa liste
    s'est resserrée.
    """
    if not criteres:
        return "aucun critère"

    return " et ".join(libelle_critere(critere) for critere in criteres)


def resume(criteres: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Les critères tels qu'on les renvoie au client, sans leur géométrie.

    Le WKT d'une emprise pèse jusqu'à 100 ko : le réémettre dans chaque page
    de résultats ferait voyager le polygone autant de fois qu'il y a de pages,
    sur une liaison de terrain, pour une information que le client possède
    déjà. Le mode et sa valeur suffisent à ce qu'il vérifie ce qui a été
    appliqué.
    """
    return [
        {
            "mode": critere["mode"],
            "valeur": str(critere.get("valeur", "") or "").strip(),
        }
        for critere in criteres
    ]


def requete_denombrement(schema: str, fragment: str) -> str:
    """Nombre total d'unités correspondant au filtre, pagination comprise."""
    return f"""
        SELECT count(*)
        FROM {schema}.unite_echan u
        WHERE {fragment}
    """


def requete_page(schema: str, fragment: str) -> str:
    """Une page de résultats, enrichie des libellés utiles à l'affichage.

    La pagination s'applique d'abord, sur la seule table `unite_echan` : les
    jointures d'enrichissement ne portent ensuite que sur les lignes affichées,
    et non sur les milliers de lignes que peut renvoyer un filtre par région.

    Chaque enrichissement prend le mesurage le plus récent *qui porte
    l'information* : le dernier mesurage d'une unité a souvent une géométrie
    nulle ou un plan d'eau non renseigné, et se contenter de lui laisserait des
    colonnes vides sans raison.
    """
    return f"""
        SELECT
            u.une_code_ident,
            u.tue_code_ident,
            t.tue_nom,
            u.une_ind_verro,
            u.une_nom_propr_verro,
            u.une_date_verro,
            u.une_raiso_verro,
            u.une_date_creat,
            u.une_code_utili_creat,
            u.une_date_maj,
            u.une_code_utili_maj,
            reg.rad_no,
            eau.ing_no_plan_eau_offic,
            eau.ing_nom_plan_eau,
            eau.ing_nom_bassi,
            pos.latitude,
            pos.longitude
        FROM (
            SELECT u.une_code_ident
            FROM {schema}.unite_echan u
            WHERE {fragment}
            ORDER BY u.une_code_ident
            LIMIT %s OFFSET %s
        ) page
        JOIN {schema}.unite_echan u ON u.une_code_ident = page.une_code_ident
        LEFT JOIN {schema}.type_unite_echan t
               ON t.tue_code_ident = u.tue_code_ident
        LEFT JOIN LATERAL (
            SELECT i.ing_no_plan_eau_offic, i.ing_nom_plan_eau, i.ing_nom_bassi
            FROM {schema}.infor_gener i
            WHERE i.une_code_ident = u.une_code_ident
              AND (
                    i.ing_no_plan_eau_offic IS NOT NULL
                 OR i.ing_nom_plan_eau IS NOT NULL
                 OR i.ing_nom_bassi IS NOT NULL
              )
            ORDER BY i.mes_no_seq DESC
            LIMIT 1
        ) eau ON TRUE
        LEFT JOIN LATERAL (
            SELECT ST_Y(g.point) AS latitude, ST_X(g.point) AS longitude
            FROM (
                SELECT ST_Transform(i.shape, 4326) AS point
                FROM {schema}.infor_gener i
                WHERE i.une_code_ident = u.une_code_ident
                  AND i.shape IS NOT NULL
                ORDER BY i.mes_no_seq DESC
                LIMIT 1
            ) g
        ) pos ON TRUE
        LEFT JOIN LATERAL (
            SELECT p.rad_no
            FROM {schema}.mesurage m
            JOIN {schema}.proje_sonda p ON p.pro_code_ident = m.pro_code_ident
            WHERE m.une_code_ident = u.une_code_ident
            ORDER BY m.mes_no_seq DESC
            LIMIT 1
        ) reg ON TRUE
        ORDER BY u.une_code_ident
    """
