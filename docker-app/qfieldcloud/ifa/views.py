"""Points d'accès IFA — recherche d'unités d'échantillonnage."""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from typing import Any

from django.conf import settings
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, views
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from qfieldcloud.ifa import db, filtres
from qfieldcloud.ifa.exceptions import FiltreInvalideError
from qfieldcloud.ifa.serializers import (
    RechercheUnitesSerializer,
    ResultatRechercheSerializer,
)

logger = logging.getLogger(__name__)


@extend_schema_view(
    post=extend_schema(
        description=(
            "Recherche les unités d'échantillonnage du programme IFA selon un "
            "critère unique : région administrative, n° de plan d'eau (LCE), "
            "fragment de code d'unité, ou zone tracée sur la carte."
        ),
        request=RechercheUnitesSerializer,
        responses={200: ResultatRechercheSerializer},
    ),
)
class RechercheUnitesView(views.APIView):
    """`POST /api/v1/ifa/unites/recherche/`.

    Le verbe est POST bien qu'il s'agisse d'une lecture : le filtre par zone
    transporte un polygone en WKT, qui ne tient pas raisonnablement dans une
    chaîne de requête.

    La réponse est paginée. Ce n'est pas une précaution de principe :
    `unite_echan` compte 142 000 lignes et un filtre par région en renvoie
    plusieurs milliers — tout envoyer d'un coup ferait plusieurs mégaoctets sur
    une liaison de terrain, pour un tableau dont l'utilisateur ne lira que les
    premières lignes.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = RechercheUnitesSerializer

    def post(self, request: Request) -> Response:
        filtre = RechercheUnitesSerializer(data=request.data)

        if not filtre.is_valid():
            # `raise_exception=True` remonterait une ValidationError de DRF, que
            # le gestionnaire d'erreurs de QFieldCloud réduit à « API Error » :
            # le technicien verrait un message qui ne lui dit pas quoi corriger.
            raise FiltreInvalideError(premier_message(filtre.errors))

        demande = filtre.validated_data

        mode = demande["mode"]
        limite = demande["limite"]
        decalage = demande["decalage"]

        schema = db.schema()
        fragment, parametres = filtres.predicat(
            mode=mode,
            schema=schema,
            srid_metier=settings.IFA_DB_SRID,
            valeur=demande.get("valeur", ""),
            wkt=demande.get("wkt", ""),
        )

        with db.curseur() as cur:
            cur.execute(filtres.requete_denombrement(schema, fragment), parametres)
            total = cur.fetchone()[0]

            lignes: list[dict[str, Any]] = []
            if total and decalage < total:
                cur.execute(
                    filtres.requete_page(schema, fragment),
                    [*parametres, limite, decalage],
                )
                lignes = db.lignes_en_dictionnaires(cur)

        logger.info(
            "[IFA] recherche d'unités mode=%s total=%s rendues=%s",
            mode,
            total,
            len(lignes),
        )

        return Response(
            {
                "mode": mode,
                "total": total,
                "limite": limite,
                "decalage": decalage,
                "tronque": decalage + len(lignes) < total,
                "resultats": [normaliser_unite(ligne) for ligne in lignes],
            },
            status=status.HTTP_200_OK,
        )


def premier_message(erreurs: Any) -> str:
    """Extrait un message affichable de l'arbre d'erreurs d'un sérialiseur.

    Les erreurs de DRF sont imbriquées (dictionnaire de champs → liste de
    messages). La fenêtre du plugin n'a qu'une ligne pour l'afficher : on rend
    le premier message rencontré, qui est celui du champ fautif.
    """
    if isinstance(erreurs, dict):
        for valeur in erreurs.values():
            message = premier_message(valeur)
            if message:
                return message
        return ""

    if isinstance(erreurs, (list, tuple)):
        for element in erreurs:
            message = premier_message(element)
            if message:
                return message
        return ""

    return str(erreurs).strip()


def normaliser_unite(ligne: dict[str, Any]) -> dict[str, Any]:
    """Met une ligne SQL à la forme attendue par le plugin QField.

    Le plugin affiche les valeurs telles quelles : un `null` y deviendrait le
    texte « null » dans une cellule du tableau. Les chaînes absentes sortent
    donc vides, et seules les coordonnées gardent le droit d'être nulles — une
    unité sans mesurage localisé n'a pas de position, et un zéro mentirait.
    """
    return {
        "une_code_ident": _texte(ligne["une_code_ident"]),
        "tue_code_ident": _texte(ligne["tue_code_ident"]),
        "tue_nom": _texte(ligne["tue_nom"]),
        # Le fonds hérité laisse l'indicateur à NULL sur quelques unités ;
        # l'absence de verrou est le cas normal.
        "une_ind_verro": _texte(ligne["une_ind_verro"]).upper() or "N",
        "une_nom_propr_verro": _texte(ligne["une_nom_propr_verro"]),
        "une_date_verro": _horodatage(ligne["une_date_verro"]),
        "une_raiso_verro": _texte(ligne["une_raiso_verro"]),
        "une_date_creat": _horodatage(ligne["une_date_creat"]),
        "une_code_utili_creat": _texte(ligne["une_code_utili_creat"]),
        "une_date_maj": _horodatage(ligne["une_date_maj"]),
        "une_code_utili_maj": _texte(ligne["une_code_utili_maj"]),
        "rad_no": _texte(ligne["rad_no"]),
        "ing_no_plan_eau": _texte(ligne["ing_no_plan_eau_offic"]),
        "ing_nom_plan_eau": _texte(ligne["ing_nom_plan_eau"]),
        "latitude": _nombre(ligne["latitude"]),
        "longitude": _nombre(ligne["longitude"]),
    }


def _texte(valeur: Any) -> str:
    return "" if valeur is None else str(valeur).strip()


def _horodatage(valeur: Any) -> str:
    """Horodatage ISO 8601, sans fuseau.

    Les colonnes du schéma hérité sont des `timestamp without time zone` :
    elles portent l'heure locale de saisie, sans indication de fuseau. Y
    coller un « Z » afficherait une heure fausse ; on rend donc l'horodatage
    tel qu'il est stocké. Le plugin n'en montre que la partie date.
    """
    if valeur is None:
        return ""
    if isinstance(valeur, datetime.datetime | datetime.date):
        return valeur.isoformat()
    return str(valeur)


def _nombre(valeur: Any) -> float | None:
    if valeur is None:
        return None
    if isinstance(valeur, Decimal):
        return float(valeur)
    return float(valeur)
