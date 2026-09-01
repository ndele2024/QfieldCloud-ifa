"""Construction des requêtes de recherche d'unités d'échantillonnage.

Le module ne parle qu'à la grammaire du filtre — il ne touche ni à HTTP ni à la
connexion. Il produit un couple `(fragment SQL, paramètres)` que `views.py`
assemble avec le reste de la requête. Toutes les valeurs venues du client
passent en paramètres liés ; seuls le nom du schéma et le SRID (configuration
serveur, validés) sont concaténés.

Les quatre modes correspondent aux quatre critères de la fenêtre « Consulter
une UE » du plugin QField.
"""

from __future__ import annotations

from typing import Any

MODE_REGION = "region"
MODE_LCE = "lce"
MODE_CODE = "code"
MODE_EMPRISE = "emprise"

MODES = (MODE_REGION, MODE_LCE, MODE_CODE, MODE_EMPRISE)


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
    if mode == MODE_EMPRISE:
        return _predicat_emprise(schema, srid_metier, wkt)

    raise ValueError(f"Mode de recherche inconnu : {mode!r}")


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
            SELECT i.ing_no_plan_eau_offic, i.ing_nom_plan_eau
            FROM {schema}.infor_gener i
            WHERE i.une_code_ident = u.une_code_ident
              AND (
                    i.ing_no_plan_eau_offic IS NOT NULL
                 OR i.ing_nom_plan_eau IS NOT NULL
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
