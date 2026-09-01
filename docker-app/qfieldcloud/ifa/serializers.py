"""Contrat d'entrée et de sortie des points d'accès IFA."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException
from rest_framework import serializers

from qfieldcloud.ifa.filtres import (
    MODE_CODE,
    MODE_EMPRISE,
    MODE_LCE,
    MODE_REGION,
    MODES,
)

# Un polygone tracé au doigt sur un téléphone dépasse rarement quelques
# dizaines de sommets. La borne écarte les envois aberrants avant qu'ils
# n'atteignent PostGIS.
LONGUEUR_WKT_MAX = 100_000

TYPES_GEOMETRIE_ACCEPTES = ("Polygon", "MultiPolygon")


class RechercheUnitesSerializer(serializers.Serializer):
    """Filtre de recherche envoyé par la fenêtre « Consulter une UE ».

    Un seul critère à la fois — c'est ainsi que la fenêtre est construite, et
    croiser deux critères changerait le sens du décompte affiché.
    """

    mode = serializers.ChoiceField(
        choices=MODES,
        error_messages={
            "invalid_choice": (
                "Critère de recherche inconnu : « {input} ». "
                f"Attendu : {', '.join(MODES)}."
            ),
        },
    )
    valeur = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, max_length=64
    )
    wkt = serializers.CharField(
        required=False, allow_blank=True, max_length=LONGUEUR_WKT_MAX
    )
    # La fenêtre transmet aussi la boîte englobante de l'emprise. Elle est
    # acceptée pour ne pas faire échouer la requête, mais la recherche se fait
    # sur le polygone lui-même : filtrer sur la boîte ramènerait des unités
    # situées hors de la zone tracée.
    bbox = serializers.ListField(
        child=serializers.FloatField(),
        required=False,
        min_length=4,
        max_length=4,
    )
    limite = serializers.IntegerField(required=False, min_value=1)
    decalage = serializers.IntegerField(required=False, min_value=0)

    def validate_limite(self, valeur: int) -> int:
        return min(valeur, settings.IFA_RECHERCHE_LIMITE_MAX)

    def validate_wkt(self, valeur: str) -> str:
        """Vérifie que le WKT est un polygone EPSG:4326 exploitable.

        La géométrie est relue par GEOS puis réémise : un envoi mal formé
        ressort en 400 explicite plutôt qu'en 500 déclenché par PostGIS, et le
        WKT qui part vers la base est celui que GEOS a validé.
        """
        if not valeur:
            return valeur

        try:
            geometrie = GEOSGeometry(valeur, srid=4326)
        except (GEOSException, ValueError, TypeError) as erreur:
            raise serializers.ValidationError(
                "Zone illisible : un polygone en WKT (EPSG:4326) est attendu."
            ) from erreur

        if geometrie.geom_type not in TYPES_GEOMETRIE_ACCEPTES:
            raise serializers.ValidationError(
                "Zone invalide : un polygone est attendu, "
                f"« {geometrie.geom_type} » reçu."
            )

        if geometrie.empty:
            raise serializers.ValidationError("La zone tracée est vide.")

        return geometrie.wkt

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        mode = donnees["mode"]
        valeur = donnees.get("valeur", "")

        if mode == MODE_EMPRISE:
            if not donnees.get("wkt"):
                raise serializers.ValidationError(
                    {"wkt": "Une zone est nécessaire pour ce mode de recherche."}
                )
        elif not valeur:
            raise serializers.ValidationError(
                {"valeur": "Ce mode de recherche demande une valeur."}
            )

        if mode == MODE_REGION and not valeur.isdigit():
            raise serializers.ValidationError(
                {"valeur": "Le code de région est composé de chiffres, ex. « 02 »."}
            )

        if mode == MODE_LCE and not valeur.isdigit():
            raise serializers.ValidationError(
                {
                    "valeur": "Le n° de plan d'eau est composé de chiffres, "
                    "ex. « 12777 »."
                }
            )

        # La recherche par code est partielle : un seul caractère ramènerait
        # une bonne partie des 142 000 unités, ce qui n'apprend rien à personne
        # et fait travailler la base pour rien. Deux caractères suffisent à
        # laisser passer les types les plus courts (« OG », « PS »).
        if mode == MODE_CODE and len(valeur) < 2:
            raise serializers.ValidationError(
                {
                    "valeur": "Saisir au moins deux caractères pour rechercher "
                    "un code d'unité."
                }
            )

        donnees.setdefault("limite", settings.IFA_RECHERCHE_LIMITE_DEFAUT)
        donnees.setdefault("decalage", 0)

        return donnees


class UniteEchantillonnageSerializer(serializers.Serializer):
    """Une unité telle que la fenêtre « Consulter une UE » l'affiche.

    Ce sérialiseur ne sert qu'à décrire la réponse dans le schéma OpenAPI : les
    lignes sont construites en SQL et normalisées dans `views.py`, sans passer
    par l'ORM.
    """

    une_code_ident = serializers.CharField(
        help_text="Code de l'unité, ex. 02-12777-IPE"
    )
    tue_code_ident = serializers.CharField(help_text="Identifiant du type d'UE")
    tue_nom = serializers.CharField(help_text="Libellé du type d'UE")
    une_ind_verro = serializers.CharField(help_text="« O » si l'unité est verrouillée")
    une_nom_propr_verro = serializers.CharField(help_text="Détenteur du verrou")
    une_date_verro = serializers.CharField(help_text="Pose du verrou (ISO 8601)")
    une_raiso_verro = serializers.CharField(help_text="Motif du verrou")
    une_date_creat = serializers.CharField(help_text="Création (ISO 8601)")
    une_code_utili_creat = serializers.CharField(help_text="Auteur de la création")
    une_date_maj = serializers.CharField(help_text="Dernière mise à jour (ISO 8601)")
    une_code_utili_maj = serializers.CharField(help_text="Auteur de la mise à jour")
    rad_no = serializers.CharField(help_text="Région administrative du projet")
    ing_no_plan_eau = serializers.CharField(help_text="N° officiel du plan d'eau")
    ing_nom_plan_eau = serializers.CharField(help_text="Nom du plan d'eau")
    latitude = serializers.FloatField(
        allow_null=True, help_text="Latitude du dernier mesurage localisé (EPSG:4326)"
    )
    longitude = serializers.FloatField(
        allow_null=True, help_text="Longitude du dernier mesurage localisé (EPSG:4326)"
    )


class ResultatRechercheSerializer(serializers.Serializer):
    """Enveloppe paginée renvoyée par la recherche."""

    mode = serializers.ChoiceField(choices=MODES)
    total = serializers.IntegerField(help_text="Unités correspondant au filtre")
    limite = serializers.IntegerField()
    decalage = serializers.IntegerField()
    tronque = serializers.BooleanField(
        help_text="Vrai s'il reste des unités au-delà de cette page"
    )
    resultats = UniteEchantillonnageSerializer(many=True)
