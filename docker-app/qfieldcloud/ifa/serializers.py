"""Contrat d'entrée et de sortie des points d'accès IFA."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException
from rest_framework import serializers

from qfieldcloud.ifa.filtres import (
    MODE_BASSIN,
    MODE_CODE,
    MODE_EMPRISE,
    MODE_LCE,
    MODE_REGION,
    MODES,
)
from qfieldcloud.ifa.formulaire import (
    LONGUEUR_VARIABLE,
    VARIABLES_ATTENDUES,
)
from qfieldcloud.ifa.formulaire import MODES as MODES_FORMULAIRE
from qfieldcloud.ifa.verrou import LONGUEUR_RAISON, MODE_MODIFIABLE
from qfieldcloud.ifa.verrou import MODES as MODES_OUVERTURE

# Un polygone tracé au doigt sur un téléphone dépasse rarement quelques
# dizaines de sommets. La borne écarte les envois aberrants avant qu'ils
# n'atteignent PostGIS.
LONGUEUR_WKT_MAX = 100_000

TYPES_GEOMETRIE_ACCEPTES = ("Polygon", "MultiPolygon")


def valider_polygone(valeur: str) -> str:
    """Vérifie qu'un WKT est un polygone EPSG:4326 exploitable.

    La géométrie est relue par GEOS puis réémise : un envoi mal formé ressort
    en 400 explicite plutôt qu'en 500 déclenché par PostGIS, et le WKT qui part
    vers la base est celui que GEOS a validé.
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
            f"Zone invalide : un polygone est attendu, « {geometrie.geom_type} » reçu."
        )

    if geometrie.empty:
        raise serializers.ValidationError("La zone tracée est vide.")

    return geometrie.wkt


# Longueur minimale d'une recherche partielle — code d'unité, nom de bassin.
# Un seul caractère ramènerait une bonne partie des 142 000 unités : cela
# n'apprend rien à personne et fait travailler la base pour rien. Deux
# caractères laissent passer les types les plus courts (« OG », « PS »).
LONGUEUR_FRAGMENT_MIN = 2


def valider_critere(critere: dict[str, Any]) -> dict[str, Any]:
    """Vérifie un critère isolé et rend sa valeur nettoyée.

    Écrit une fois, appelé pour chacun des critères de la recherche comme pour
    ceux du bloc « Données à embarquer » : les deux fenêtres proposent les
    mêmes champs, et un message qui diffère d'un écran à l'autre pour la même
    saisie ferait douter le technicien de ce qu'il a tapé.
    """
    mode = critere["mode"]
    valeur = str(critere.get("valeur", "") or "").strip()

    if mode == MODE_EMPRISE:
        if not critere.get("wkt"):
            raise serializers.ValidationError(
                {"wkt": "Une zone est nécessaire pour ce critère."}
            )

        return critere

    if not valeur:
        raise serializers.ValidationError(
            {"valeur": "Ce critère de recherche demande une valeur."}
        )

    if mode == MODE_REGION and not valeur.isdigit():
        raise serializers.ValidationError(
            {"valeur": "Le code de région est composé de chiffres, ex. « 02 »."}
        )

    if mode == MODE_LCE and not valeur.isdigit():
        raise serializers.ValidationError(
            {"valeur": "Le n° de plan d'eau est composé de chiffres, ex. « 12777 »."}
        )

    if mode == MODE_CODE and len(valeur) < LONGUEUR_FRAGMENT_MIN:
        raise serializers.ValidationError(
            {
                "valeur": "Saisir au moins deux caractères pour rechercher "
                "un code d'unité."
            }
        )

    # Le nom de bassin est cherché par fragment, comme le code : la même borne
    # s'applique, et pour la même raison.
    if mode == MODE_BASSIN and len(valeur) < LONGUEUR_FRAGMENT_MIN:
        raise serializers.ValidationError(
            {
                "valeur": "Saisir au moins deux caractères pour rechercher "
                "un nom de bassin."
            }
        )

    critere["valeur"] = valeur

    return critere


class CritereSerializer(serializers.Serializer):
    """Un critère de recherche : un mode, et ce sur quoi il porte.

    L'emprise porte un `wkt` ; tous les autres modes portent une `valeur`.
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

    def validate_wkt(self, valeur: str) -> str:
        return valider_polygone(valeur)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        return valider_critere(donnees)


class CritereFormulaireSerializer(CritereSerializer):
    """Même critère, sans le mode `code`.

    On ne choisit pas les données à embarquer à partir d'un fragment de code
    d'unité existante : ce serait retenir un lot d'unités sur une ressemblance
    de nommage, ce qui ne désigne rien sur le terrain.
    """

    mode = serializers.ChoiceField(
        choices=MODES_FORMULAIRE,
        error_messages={
            "invalid_choice": (
                "Critère de sélection inconnu : « {input} ». "
                f"Attendu : {', '.join(MODES_FORMULAIRE)}."
            ),
        },
    )


def normaliser_criteres(donnees: dict[str, Any], message_vide: str) -> dict[str, Any]:
    """Rassemble les critères d'une demande, quel que soit son format.

    Deux formats cohabitent. Celui d'aujourd'hui porte une liste `criteres` :
    la fenêtre en laisse cocher plusieurs, et le serveur les croise. Celui
    d'avant portait un `mode` et une `valeur` à plat — les plugins déjà
    installés sur les appareils l'envoient encore, et refuser leur requête les
    priverait de la recherche entière pour un changement de forme. Il est donc
    relu comme un critère unique.

    Un même mode n'est accepté qu'une fois : deux régions croisées par `AND`
    ne rendraient jamais rien, et c'est le genre de filtre qui se lit comme
    une panne du serveur plutôt que comme une erreur de saisie.
    """
    criteres = list(donnees.get("criteres") or [])

    if not criteres:
        mode = donnees.get("mode")

        if not mode:
            raise serializers.ValidationError({"criteres": message_vide})

        unique: dict[str, Any] = {
            "mode": mode,
            "valeur": donnees.get("valeur", ""),
        }

        # Le WKT n'accompagne que l'emprise : le porter vide sur les autres
        # modes laisserait croire, à la relecture d'un journal, qu'une zone a
        # été envoyée puis perdue.
        if donnees.get("wkt"):
            unique["wkt"] = donnees["wkt"]

        criteres = [valider_critere(unique)]

    modes_vus: list[str] = []

    for critere in criteres:
        mode = critere["mode"]

        if mode in modes_vus:
            raise serializers.ValidationError(
                {
                    "criteres": f"Le critère « {mode} » est envoyé deux fois : "
                    "un seul de chaque par recherche."
                }
            )

        modes_vus.append(mode)

    donnees["criteres"] = criteres
    # Conservé pour les réponses et les journaux : le premier critère retenu.
    donnees["mode"] = criteres[0]["mode"]

    return donnees


class RechercheUnitesSerializer(serializers.Serializer):
    """Filtre de recherche envoyé par la fenêtre « Consulter une UE ».

    Les critères cochés se croisent : une unité doit satisfaire **tous** ceux
    qui sont envoyés. C'est le sens d'un formulaire de recherche — chaque
    critère ajouté resserre la liste.

    `mode`, `valeur`, `wkt` et `bbox` à plat restent acceptés : c'est la forme
    qu'envoient les plugins déjà installés (voir `normaliser_criteres`).
    """

    criteres = CritereSerializer(many=True, required=False)

    mode = serializers.ChoiceField(
        choices=MODES,
        required=False,
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
        return valider_polygone(valeur)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        donnees = normaliser_criteres(
            donnees, "Choisissez au moins un critère de recherche."
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
    ing_nom_bassi = serializers.CharField(help_text="Nom du bassin versant")
    latitude = serializers.FloatField(
        allow_null=True, help_text="Latitude du dernier mesurage localisé (EPSG:4326)"
    )
    longitude = serializers.FloatField(
        allow_null=True, help_text="Longitude du dernier mesurage localisé (EPSG:4326)"
    )


class CritereAppliqueSerializer(serializers.Serializer):
    """Un critère tel que le serveur l'a retenu, rendu au client.

    Le WKT d'une emprise n'y figure pas : il pèse jusqu'à 100 ko et le client
    le possède déjà — le réémettre à chaque page le ferait voyager autant de
    fois qu'il y a de pages, sur une liaison de terrain.
    """

    mode = serializers.ChoiceField(choices=MODES)
    valeur = serializers.CharField(
        allow_blank=True, help_text="Vide pour une emprise tracée"
    )


class ResultatRechercheSerializer(serializers.Serializer):
    """Enveloppe paginée renvoyée par la recherche."""

    # Le premier critère retenu. Conservé pour les clients antérieurs à la
    # recherche multicritère, qui lisent encore ce champ.
    mode = serializers.ChoiceField(choices=MODES)
    criteres = CritereAppliqueSerializer(
        many=True, help_text="Les critères croisés, dans l'ordre reçu"
    )
    filtre = serializers.CharField(help_text="Les critères en une ligne lisible")
    total = serializers.IntegerField(help_text="Unités correspondant au filtre")
    limite = serializers.IntegerField()
    decalage = serializers.IntegerField()
    tronque = serializers.BooleanField(
        help_text="Vrai s'il reste des unités au-delà de cette page"
    )
    resultats = UniteEchantillonnageSerializer(many=True)


class OuvrirUniteSerializer(serializers.Serializer):
    """Demande d'ouverture d'une unité dans QField.

    Le code de l'unité est porté par l'URL ; il ne se répète pas ici.

    La raison du verrouillage est saisie par le technicien dans une petite
    fenêtre avant l'envoi. Elle n'a de sens qu'en mode modifiable : c'est elle
    que verra le collègue à qui l'unité sera refusée, et elle est donc exigée.
    En consultation, rien n'est écrit dans la base métier — une raison envoyée
    par mégarde y est simplement ignorée.
    """

    mode = serializers.ChoiceField(
        choices=MODES_OUVERTURE,
        error_messages={
            "invalid_choice": (
                "Mode d'ouverture inconnu : « {input} ». "
                f"Attendu : {', '.join(MODES_OUVERTURE)}."
            ),
        },
    )
    raison = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=LONGUEUR_RAISON,
    )

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        raison = (donnees.get("raison") or "").strip()

        if donnees["mode"] == MODE_MODIFIABLE and not raison:
            raise serializers.ValidationError(
                "Indiquez la raison du verrouillage avant d'ouvrir l'unité."
            )

        donnees["raison"] = raison if donnees["mode"] == MODE_MODIFIABLE else ""

        return donnees


class UniteVerrouSerializer(serializers.Serializer):
    """État de verrou d'une unité, tel que la base le porte."""

    une_code_ident = serializers.CharField()
    une_ind_verro = serializers.CharField()
    une_nom_propr_verro = serializers.CharField()
    une_date_verro = serializers.CharField()
    une_raiso_verro = serializers.CharField()


class DeverrouillageSerializer(serializers.Serializer):
    """Ce que rend le déverrouillage d'une unité.

    La demande, elle, n'a pas de corps : le code de l'unité est porté par
    l'URL, et le détenteur est celui qui appelle.
    """

    unite = UniteVerrouSerializer(help_text="État de verrou après l'appel")
    deverrouille = serializers.BooleanField(
        help_text="Faux si l'unité n'était pas verrouillée — rien à faire"
    )


class PreparerFormulaireSerializer(serializers.Serializer):
    """Demande de préparation du projet de saisie — « Créer une UE ».

    Le corps porte trois choses : l'**unité à créer**, qui sera inscrite dans
    `unite_echan` et verrouillée ; le **filtre** des données à embarquer (le
    bloc « Données à embarquer » de la fenêtre) ; et le **contexte** de la
    saisie, qui deviendra les variables du projet QGIS livré.

    `une_code_ident` et `type_ue` sont repris dans `variables`, mais ils sont
    aussi demandés à part, et exigés : ce qui entre dans la base métier ne doit
    pas dépendre d'un dictionnaire libre dont les clés inconnues sont ignorées.

    Le mode `code` de la recherche n'a pas cours ici : on ne crée pas une unité
    à partir d'un fragment de code d'unité existante.

    Les critères se croisent comme ceux de la recherche : n'embarquer que les
    unités d'un bassin *dans* une région donnée est précisément ce qui ramène
    une sélection à la taille d'un appareil de terrain.
    """

    # Longueur de `unite_echan.une_code_ident` dans le schéma hérité.
    #
    # Les messages sont écrits ici plutôt que laissés à DRF : les siens sont en
    # anglais (« This field is required. ») et arriveraient tels quels dans la
    # fenêtre du plugin, sur un écran de terrain.
    une_code_ident = serializers.CharField(
        trim_whitespace=True,
        max_length=40,
        help_text="Identifiant de la nouvelle unité, ex. 02-12777-IPE",
        error_messages={
            "required": "L'identifiant de la nouvelle unité est absent.",
            "blank": "L'identifiant de la nouvelle unité est absent.",
            "max_length": "L'identifiant ne peut pas dépasser 40 caractères.",
        },
    )
    # Le libellé du type, pas son identifiant : la liste des types est encore
    # codée en dur dans le plugin, et ce sont les libellés qui y sont écrits.
    type_ue = serializers.CharField(
        trim_whitespace=True,
        max_length=100,
        help_text="Libellé du type d'UE, ex. « Inventaire sur plan d'eau »",
        error_messages={
            "required": "Le type de la nouvelle unité n'est pas précisé.",
            "blank": "Le type de la nouvelle unité n'est pas précisé.",
            "max_length": "Le libellé du type d'UE est trop long.",
        },
    )
    criteres = CritereFormulaireSerializer(many=True, required=False)

    # Forme à plat, envoyée par les plugins déjà installés. Voir
    # `normaliser_criteres`.
    mode = serializers.ChoiceField(
        choices=MODES_FORMULAIRE,
        required=False,
        error_messages={
            "invalid_choice": (
                "Critère de sélection inconnu : « {input} ». "
                f"Attendu : {', '.join(MODES_FORMULAIRE)}."
            ),
        },
    )
    valeur = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, max_length=64
    )
    wkt = serializers.CharField(
        required=False, allow_blank=True, max_length=LONGUEUR_WKT_MAX
    )
    # Comme pour la recherche : acceptée pour ne pas faire échouer la requête,
    # mais la sélection porte sur le polygone lui-même.
    bbox = serializers.ListField(
        child=serializers.FloatField(),
        required=False,
        min_length=4,
        max_length=4,
    )
    # Les valeurs par défaut du formulaire QGIS lisent des variables de projet.
    # Tant que la saisie se faisait dans le projet déjà ouvert, le plugin les
    # posait lui-même ; le projet livré étant un autre projet, elles doivent
    # voyager avec la demande. Les noms inconnus sont ignorés côté serveur
    # (voir `formulaire.VARIABLES_ATTENDUES`).
    variables = serializers.DictField(
        child=serializers.CharField(
            allow_blank=True, trim_whitespace=True, max_length=LONGUEUR_VARIABLE
        ),
        required=False,
        help_text=f"Variables de projet : {', '.join(VARIABLES_ATTENDUES)}",
    )

    def validate_wkt(self, valeur: str) -> str:
        return valider_polygone(valeur)

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        return normaliser_criteres(
            donnees,
            "Choisissez au moins un critère pour les données à embarquer.",
        )


class FormulaireSerializer(serializers.Serializer):
    """Ce que le plugin reçoit une fois le projet de saisie préparé."""

    # Le premier critère retenu — conservé pour les clients antérieurs.
    mode = serializers.ChoiceField(choices=MODES_FORMULAIRE)
    criteres = CritereAppliqueSerializer(
        many=True, help_text="Les critères croisés, dans l'ordre reçu"
    )
    filtre = serializers.CharField(help_text="Le filtre retenu, en une ligne")
    unites = serializers.IntegerField(
        help_text="Unités embarquées dans le GeoPackage, la nouvelle comprise"
    )
    projet_id = serializers.CharField(help_text="Identifiant du projet QFieldCloud")
    projet_nom = serializers.CharField(help_text="Nom du projet de saisie")
    projet_proprietaire = serializers.CharField(
        help_text="Compte propriétaire du projet — celui de l'utilisateur"
    )
    travail_id = serializers.CharField(
        help_text="Travail de packaging à attendre avant le téléchargement"
    )
    lignes = serializers.IntegerField(
        help_text="Enregistrements écrits dans le GeoPackage"
    )
    tables = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Détail par table métier, tables vides omises",
    )
    unite = UniteVerrouSerializer(
        help_text="L'unité créée dans la base métier, et son verrou"
    )


class OuvertureSerializer(serializers.Serializer):
    """Ce que le plugin reçoit une fois le projet d'affichage préparé."""

    mode = serializers.ChoiceField(choices=MODES_OUVERTURE)
    projet_id = serializers.CharField(help_text="Identifiant du projet QFieldCloud")
    projet_nom = serializers.CharField(help_text="Nom du projet d'affichage")
    projet_proprietaire = serializers.CharField(
        help_text="Compte propriétaire du projet — celui de l'utilisateur"
    )
    travail_id = serializers.CharField(
        help_text="Travail de packaging à attendre avant le téléchargement"
    )
    lignes = serializers.IntegerField(
        help_text="Enregistrements écrits dans le GeoPackage"
    )
    tables = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Détail par table métier, tables vides omises",
    )
    unite = UniteVerrouSerializer(
        help_text="État de verrou de l'unité après l'ouverture"
    )
