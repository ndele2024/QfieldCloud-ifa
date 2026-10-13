"""Contrat d'entrée et de sortie des points d'accès IFA."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException
from rest_framework import serializers

from qfieldcloud.ifa import projet_gestion, projet_sonda
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


class TypeUeProjetSerializer(serializers.Serializer):
    """Un type d'UE ajouté au projet, et ce qui est planifié pour lui."""

    tue_code_ident = serializers.CharField(
        trim_whitespace=True,
        max_length=40,
        help_text="Identifiant du type, tel que rendu par `GET types-ue/`",
        error_messages={
            "required": "Un type d'UE est sans identifiant.",
            "blank": "Un type d'UE est sans identifiant.",
            "max_length": "Identifiant de type d'UE trop long.",
        },
    )
    # Les deux nombres sont exigés : ajouter un type à un projet, c'est dire ce
    # qu'on y planifie.
    nb_impla_plani = serializers.IntegerField(
        min_value=projet_sonda.NB_IMPLA_MIN,
        max_value=projet_sonda.NB_PLANI_MAX,
        help_text="Nombre d'implantations planifiées — au moins une",
        error_messages={
            "required": "Indiquez le nombre d'implantations planifiées.",
            "null": "Indiquez le nombre d'implantations planifiées.",
            "invalid": "Le nombre d'implantations planifiées doit être un entier.",
            "min_value": (
                f"Le nombre d'implantations planifiées doit être d'au moins "
                f"{projet_sonda.NB_IMPLA_MIN}."
            ),
            "max_value": (
                f"Le nombre d'implantations planifiées ne peut pas dépasser "
                f"{projet_sonda.NB_PLANI_MAX}."
            ),
        },
    )
    nb_remes_plani = serializers.IntegerField(
        min_value=projet_sonda.NB_REMES_MIN,
        max_value=projet_sonda.NB_PLANI_MAX,
        help_text="Nombre de remesurages planifiés — zéro ou plus",
        error_messages={
            "required": "Indiquez le nombre de remesurages planifiés.",
            "null": "Indiquez le nombre de remesurages planifiés.",
            "invalid": "Le nombre de remesurages planifiés doit être un entier.",
            "min_value": (
                "Le nombre de remesurages planifiés ne peut pas être négatif."
            ),
            "max_value": (
                f"Le nombre de remesurages planifiés ne peut pas dépasser "
                f"{projet_sonda.NB_PLANI_MAX}."
            ),
        },
    )


class ProjetSondageSerializer(serializers.Serializer):
    """Demande de création d'un projet de sondage — « Créer un projet ».

    Chaque champ porte la longueur de sa colonne dans `proje_sonda` et des
    messages en français : ceux de DRF arriveraient en anglais dans la fenêtre
    du plugin. L'identifiant, les dates, l'utilisateur et la version de type
    sont fixés par le serveur, jamais par le client.
    """

    pro_no = serializers.CharField(
        trim_whitespace=True,
        max_length=projet_sonda.LONGUEUR_NUMERO,
        help_text="N° du projet, unique, ex. 09-OG",
        error_messages={
            "required": "Le n° du projet est obligatoire.",
            "blank": "Le n° du projet est obligatoire.",
            "max_length": (
                f"Le n° du projet ne peut pas dépasser "
                f"{projet_sonda.LONGUEUR_NUMERO} caractères."
            ),
        },
    )
    pro_nom = serializers.CharField(
        trim_whitespace=True,
        max_length=projet_sonda.LONGUEUR_NOM,
        help_text="Nom du projet",
        error_messages={
            "required": "Le nom du projet est obligatoire.",
            "blank": "Le nom du projet est obligatoire.",
            "max_length": (
                f"Le nom du projet ne peut pas dépasser "
                f"{projet_sonda.LONGUEUR_NOM} caractères."
            ),
        },
    )
    pro_an = serializers.IntegerField(
        help_text="Année du projet",
        error_messages={
            "required": "L'année du projet est obligatoire.",
            "invalid": "L'année du projet doit être un nombre, ex. 2026.",
            "null": "L'année du projet est obligatoire.",
        },
    )
    # Exigée, bien que nullable dans le schéma : c'est la région du projet qui
    # range ses unités dans la recherche par région, et qui le fait apparaître
    # dans la liste de « Créer une UE ».
    rad_no = serializers.ChoiceField(
        choices=projet_sonda.REGIONS,
        help_text="Région administrative (type énuméré `region`)",
        error_messages={
            "required": "La région du projet est obligatoire.",
            "invalid_choice": "Région inconnue : « {input} ».",
        },
    )
    pro_code_statu = serializers.ChoiceField(
        choices=projet_sonda.STATUTS_CREATION,
        default=projet_sonda.STATUT_ELABORATION,
        help_text="« El » (en élaboration) ou « Pr » (en production)",
        error_messages={
            "invalid_choice": (
                "Statut de création inconnu : « {input} ». Un projet naît en "
                "élaboration (El) ou en production (Pr)."
            ),
        },
    )
    pro_ind_inven_norma = serializers.BooleanField(
        default=False, help_text="Inventaire normalisé"
    )
    pro_descr = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=projet_sonda.LONGUEUR_DESCRIPTION,
        error_messages={
            "max_length": (
                f"La description ne peut pas dépasser "
                f"{projet_sonda.LONGUEUR_DESCRIPTION} caractères."
            ),
        },
    )
    pro_com = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=projet_sonda.LONGUEUR_COMMENTAIRE,
        error_messages={
            "max_length": (
                f"Le commentaire ne peut pas dépasser "
                f"{projet_sonda.LONGUEUR_COMMENTAIRE} caractères."
            ),
        },
    )

    # Au moins un type : un projet qui ne prévoit aucun type d'UE ne pourrait
    # recevoir aucune unité.
    types_ue = TypeUeProjetSerializer(
        many=True,
        allow_empty=False,
        max_length=projet_sonda.TYPES_MAX,
        help_text="Types d'UE prévus par le projet — au moins un",
        error_messages={
            "required": "Choisissez au moins un type d'UE pour le projet.",
            "empty": "Choisissez au moins un type d'UE pour le projet.",
            "not_a_list": "Les types d'UE doivent être envoyés en liste.",
            "max_length": (
                f"Un projet ne peut pas prévoir plus de "
                f"{projet_sonda.TYPES_MAX} types d'UE."
            ),
        },
    )

    def validate_types_ue(self, types: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # La clé primaire de l'association est le couple (projet, type) : un
        # doublon ferait échouer l'`INSERT` en « base indisponible ».
        vus: set[str] = set()

        for type_ue in types:
            code = type_ue["tue_code_ident"]
            if code in vus:
                raise serializers.ValidationError(
                    "Un même type d'UE est choisi deux fois."
                )
            vus.add(code)

        return types

    def validate_pro_an(self, valeur: int) -> int:
        maximum = projet_sonda.annee_max()

        if not projet_sonda.ANNEE_MIN <= valeur <= maximum:
            raise serializers.ValidationError(
                f"L'année du projet doit être comprise entre "
                f"{projet_sonda.ANNEE_MIN} et {maximum}."
            )

        return valeur


class TypeUeAssocieSerializer(serializers.Serializer):
    """Un type d'UE tel qu'associé au projet créé."""

    tue_code_ident = serializers.CharField()
    tue_nom = serializers.CharField()
    nb_impla_plani = serializers.IntegerField()
    nb_remes_plani = serializers.IntegerField()


class TypeUeSerializer(serializers.Serializer):
    """Un type d'UE du référentiel."""

    tue_code_ident = serializers.CharField()
    tue_nom = serializers.CharField()
    tue_descr = serializers.CharField()


class TypesUeSerializer(serializers.Serializer):
    """La liste des types d'UE qu'un projet peut prévoir."""

    types = TypeUeSerializer(many=True)


class TypesDuProjetSerializer(serializers.Serializer):
    """Les types d'UE prévus par un projet — vide s'il n'en prévoit aucun."""

    pro_code_ident = serializers.CharField()
    pro_no = serializers.CharField()
    pro_nom = serializers.CharField()
    types = TypeUeAssocieSerializer(many=True)


class ProjetSondageCreeSerializer(serializers.Serializer):
    """Ce que le plugin reçoit une fois le projet inscrit."""

    pro_code_ident = serializers.CharField(help_text="Identifiant (UUID)")
    pro_no = serializers.CharField()
    pro_nom = serializers.CharField()
    pro_an = serializers.IntegerField()
    rad_no = serializers.CharField()
    pro_descr = serializers.CharField()
    pro_com = serializers.CharField()
    pro_code_statu = serializers.CharField()
    pro_date_statu = serializers.CharField()
    pro_date_premi_mise_produ = serializers.CharField(
        help_text="Vide tant que le projet n'est pas passé en production"
    )
    pro_ind_inven_norma = serializers.CharField(help_text="« O » ou « N »")
    pro_date_creat = serializers.CharField()
    pro_code_utili_creat = serializers.CharField()
    types_ue = TypeUeAssocieSerializer(
        many=True, help_text="Les types d'UE écrits dans proje_type_unite_echan"
    )


class ModificationProjetSerializer(ProjetSondageSerializer):
    """Demande de modification d'un projet — « Modifier un projet ».

    Utilisé en `partial=True` : seuls les champs envoyés sont validés, avec les
    mêmes règles qu'à la création. Le statut accepte ici « Te » (terminé).

    `pro_date_maj` est la date de dernière mise à jour lue par la fenêtre : le
    serveur refuse la modification si elle a changé depuis.
    """

    pro_code_statu = serializers.ChoiceField(
        choices=projet_gestion.STATUTS,
        help_text="« El » (en élaboration), « Pr » (en production), « Te » (terminé)",
        error_messages={
            "invalid_choice": "Statut inconnu : « {input} ».",
        },
    )
    pro_date_maj = serializers.CharField(
        allow_blank=True,
        trim_whitespace=True,
        max_length=40,
        help_text="pro_date_maj lu avant modification — contrôle de concurrence",
    )


class SuppressionProjetSerializer(serializers.Serializer):
    """Demande de suppression d'un projet ou d'une unité : le mot de passe de
    l'utilisateur."""

    mot_de_passe = serializers.CharField(
        trim_whitespace=False,
        max_length=256,
        style={"input_type": "password"},
        error_messages={
            "required": "Saisissez votre mot de passe pour confirmer la suppression.",
            "blank": "Saisissez votre mot de passe pour confirmer la suppression.",
        },
    )


class DroitsProjetSerializer(serializers.Serializer):
    """Ce que l'appelant peut faire du projet, et pourquoi pas le reste."""

    admin = serializers.BooleanField()
    createur = serializers.BooleanField()
    utilise = serializers.BooleanField()
    nb_unites = serializers.IntegerField()
    modifiable = serializers.BooleanField()
    champs_modifiables = serializers.ListField(child=serializers.CharField())
    raison_modification = serializers.CharField()
    supprimable = serializers.BooleanField()
    raison_suppression = serializers.CharField()


class DroitsUniteSerializer(serializers.Serializer):
    """Ce que l'appelant peut faire de l'unité (« Consulter une UE »)."""

    admin = serializers.BooleanField()
    createur = serializers.BooleanField()
    diffusee = serializers.BooleanField()
    verrouillee_par_un_autre = serializers.BooleanField()
    supprimable = serializers.BooleanField()
    raison_suppression = serializers.CharField()


class UniteDetailSerializer(serializers.Serializer):
    """Une unité, ce que sa suppression emporterait, et les droits."""

    une_code_ident = serializers.CharField()
    tue_nom = serializers.CharField()
    une_ind_verro = serializers.CharField()
    une_nom_propr_verro = serializers.CharField()
    une_date_creat = serializers.CharField()
    une_code_utili_creat = serializers.CharField()
    une_date_maj = serializers.CharField()
    une_code_utili_maj = serializers.CharField()
    nb_mesurages = serializers.IntegerField()
    nb_enregistrements = serializers.IntegerField()
    tables = serializers.DictField(child=serializers.IntegerField())
    droits = DroitsUniteSerializer()


class SuppressionUniteFaiteSerializer(serializers.Serializer):
    supprime = serializers.BooleanField()
    une_code_ident = serializers.CharField()
    nb_mesurages = serializers.IntegerField()
    nb_enregistrements = serializers.IntegerField()
    tables = serializers.DictField(child=serializers.IntegerField())


class ProjetDetailSerializer(ProjetSondageCreeSerializer):
    """Un projet, ses types d'UE, son usage et les droits de l'appelant."""

    pro_date_maj = serializers.CharField()
    pro_code_utili_maj = serializers.CharField()
    nb_unites = serializers.IntegerField()
    droits = DroitsProjetSerializer()


class ListeProjetsSerializer(serializers.Serializer):
    """Tous les projets de sondage, pour « Modifier / Afficher un projet »."""

    admin = serializers.BooleanField(help_text="L'appelant est-il administrateur ?")
    utilisateur = serializers.CharField()
    projets = ProjetDetailSerializer(many=True)


class SuppressionFaiteSerializer(serializers.Serializer):
    supprime = serializers.BooleanField()
    pro_code_ident = serializers.CharField()
    pro_no = serializers.CharField()
    types_supprimes = serializers.IntegerField()
