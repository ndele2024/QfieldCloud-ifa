"""Création d'un projet de sondage : ce qui se décide sans la base.

Le curseur est simulé : ces essais tiennent l'ordre des opérations (verrou
consultatif, vérification du numéro et des types, puis `INSERT`), les valeurs
que le serveur fixe lui-même, l'association aux types d'UE, et le contrat de la
demande.
"""

import datetime
import uuid
from contextlib import contextmanager
from unittest import mock

from django.test import SimpleTestCase, override_settings

from qfieldcloud.ifa import db, projet_sonda
from qfieldcloud.ifa.exceptions import (
    FiltreInvalideError,
    ProjetExistantError,
    ProjetIntrouvableError,
    TypeUniteIntrouvableError,
    VersionProjetIntrouvableError,
)
from qfieldcloud.ifa.serializers import ProjetSondageSerializer

VERSION = "0679db91-b980-4f47-ad5c-150655b84ae4"
IPE = "f0758571-e68e-47f5-a3d5-9c865e3c61c9"
OG = "9ef3e818-e738-4131-8b69-73b2a506de44"
REFERENTIEL = {IPE: "Inventaire sur plan d'eau", OG: "Observation générale"}


class CurseurSimule:
    """Répond aux requêtes de `projet_sonda` d'après leur texte."""

    def __init__(self, existant=None, version=VERSION, referentiel=None):
        self.existant = existant
        self.version = version
        self.referentiel = REFERENTIEL if referentiel is None else referentiel
        self.requetes = []
        self.description = None
        self._lignes = []

    def execute(self, sql, parametres=None):
        self.requetes.append((sql, parametres))

        if "pg_advisory_xact_lock" in sql:
            self._rendre([], [])
        elif "FROM ifa_data.proje_sonda" in sql and "lower(btrim(pro_no))" in sql:
            colonnes = ["pro_code_ident", "pro_no", "pro_nom", "pro_an"]
            lignes = (
                [tuple(self.existant[c] for c in colonnes)] if self.existant else []
            )
            self._rendre(colonnes, lignes)
        elif "FROM ifa_data.type_unite_echan" in sql and "ANY(%s)" in sql:
            codes = parametres[0]
            self._rendre(
                ["tue_code_ident", "tue_nom"],
                [(c, self.referentiel[c]) for c in codes if c in self.referentiel],
            )
        elif "INTO ifa_data.proje_type_unite_echan" in sql:
            self._rendre([], [])
        elif "versi_type_unite_echan" in sql:
            self._rendre(["vet_code_ident"], [(self.version,)] if self.version else [])
        elif sql.lstrip().startswith("INSERT"):
            p = parametres
            colonnes = [
                "pro_code_ident", "pro_no", "pro_nom", "pro_an", "rad_no",
                "pro_descr", "pro_com", "pro_code_statu", "pro_date_statu",
                "pro_date_premi_mise_produ", "pro_ind_inven_norma",
                "pro_date_creat", "pro_code_utili_creat",
            ]  # fmt: skip
            maintenant = datetime.datetime(2026, 10, 5, 9, 30)
            self._rendre(
                colonnes,
                [
                    (
                        p["code"], p["numero"], p["nom"], p["an"], p["region"],
                        p["description"], p["commentaire"], p["statut"], maintenant,
                        maintenant if p["en_production"] else None,
                        p["normalise"], maintenant, p["utilisateur"],
                    )
                ],
            )  # fmt: skip
        else:
            raise AssertionError(f"requête inattendue : {sql}")

    def _rendre(self, colonnes, lignes):
        self.description = [(c,) for c in colonnes]
        self._lignes = list(lignes)

    def fetchone(self):
        return self._lignes[0] if self._lignes else None

    def fetchall(self):
        return list(self._lignes)

    def insertion(self):
        for sql, parametres in self.requetes:
            if "INTO ifa_data.proje_sonda" in sql:
                return parametres
        return None

    def associations(self):
        return [
            parametres
            for sql, parametres in self.requetes
            if "INTO ifa_data.proje_type_unite_echan" in sql
        ]


def demande(**surcharges):
    donnees = {
        "pro_no": "09-OG",
        "pro_nom": "Observations générales",
        "pro_an": 2026,
        "rad_no": "09",
        "pro_code_statu": projet_sonda.STATUT_ELABORATION,
        "pro_ind_inven_norma": False,
        "pro_descr": "",
        "pro_com": "",
        "types_ue": [
            {"tue_code_ident": IPE, "nb_impla_plani": 12, "nb_remes_plani": 24},
            {"tue_code_ident": OG, "nb_impla_plani": 1, "nb_remes_plani": 0},
        ],
    }
    donnees.update(surcharges)
    return donnees


class CreerTestCase(SimpleTestCase):
    def creer(self, curseur, donnees=None, utilisateur="ifauser"):
        @contextmanager
        def ecriture():
            yield curseur

        with (
            mock.patch.object(db, "schema", return_value="ifa_data"),
            mock.patch.object(db, "curseur_ecriture", ecriture),
        ):
            return projet_sonda.creer(donnees or demande(), utilisateur)

    def test_le_verrou_precede_la_verification(self):
        """Sans verrou d'abord, deux créations du même n° passeraient."""
        curseur = CurseurSimule()
        self.creer(curseur)

        self.assertIn("pg_advisory_xact_lock", curseur.requetes[0][0])
        self.assertIn("lower(btrim(pro_no))", curseur.requetes[1][0])

    def test_numero_deja_pris(self):
        curseur = CurseurSimule(
            existant={
                "pro_code_ident": "x",
                "pro_no": "09-og",
                "pro_nom": "09-Observations générales",
                "pro_an": 2024,
            }
        )

        with self.assertRaises(ProjetExistantError) as erreur:
            self.creer(curseur)

        self.assertIn("09-Observations générales", erreur.exception.message)
        self.assertIsNone(curseur.insertion(), "rien ne doit être écrit")
        self.assertEqual(curseur.associations(), [])

    def test_valeurs_fixees_par_le_serveur(self):
        curseur = CurseurSimule()
        projet = self.creer(curseur, utilisateur="un_nom_bien_plus_long_que_20")

        insere = curseur.insertion()
        uuid.UUID(insere["code"])
        self.assertEqual(insere["version"], VERSION)
        self.assertEqual(len(insere["utilisateur"]), 20)
        self.assertEqual(projet["pro_code_utili_creat"], insere["utilisateur"])

    def test_textes_vides_ecrits_nuls(self):
        curseur = CurseurSimule()
        projet = self.creer(curseur)

        insere = curseur.insertion()
        self.assertIsNone(insere["description"])
        self.assertIsNone(insere["commentaire"])
        # …mais jamais `null` dans la réponse au plugin.
        self.assertEqual(projet["pro_descr"], "")

    def test_en_elaboration(self):
        curseur = CurseurSimule()
        projet = self.creer(curseur)

        self.assertFalse(curseur.insertion()["en_production"])
        self.assertEqual(projet["pro_date_premi_mise_produ"], "")
        self.assertEqual(projet["pro_ind_inven_norma"], "N")

    def test_en_production_date_la_mise_en_production(self):
        curseur = CurseurSimule()
        projet = self.creer(
            curseur,
            demande(
                pro_code_statu=projet_sonda.STATUT_PRODUCTION, pro_ind_inven_norma=True
            ),
        )

        self.assertTrue(curseur.insertion()["en_production"])
        self.assertNotEqual(projet["pro_date_premi_mise_produ"], "")
        self.assertEqual(projet["pro_ind_inven_norma"], "O")

    def test_une_ligne_par_type(self):
        curseur = CurseurSimule()
        self.creer(curseur)

        lignes = curseur.associations()
        self.assertEqual([ligne["type"] for ligne in lignes], [IPE, OG])
        self.assertEqual(
            {ligne["projet"] for ligne in lignes},
            {curseur.insertion()["code"]},
            "toutes rattachées au projet qui vient d'être écrit",
        )
        self.assertEqual(lignes[0]["implantations"], 12)
        self.assertEqual(lignes[0]["remesurages"], 24)
        self.assertEqual(lignes[1]["remesurages"], 0)

    def test_les_types_sont_rendus_avec_leur_libelle(self):
        projet = self.creer(CurseurSimule())

        self.assertEqual(
            projet["types_ue"][0],
            {
                "tue_code_ident": IPE,
                "tue_nom": "Inventaire sur plan d'eau",
                "nb_impla_plani": 12,
                "nb_remes_plani": 24,
            },
        )

    def test_type_inconnu_n_ecrit_rien(self):
        """Pas de projet orphelin des types qu'on a voulu lui donner."""
        curseur = CurseurSimule(referentiel={IPE: "Inventaire sur plan d'eau"})

        with self.assertRaises(TypeUniteIntrouvableError) as erreur:
            self.creer(curseur)

        self.assertIn(OG, erreur.exception.message)
        self.assertIsNone(curseur.insertion())
        self.assertEqual(curseur.associations(), [])

    def test_type_projet_exclu_de_la_verification(self):
        curseur = CurseurSimule()
        self.creer(curseur)

        parametres = next(p for sql, p in curseur.requetes if "ANY(%s)" in sql)
        self.assertEqual(parametres[1], projet_sonda.TYPE_PROJET_NOM)


class TypesDisponiblesTestCase(SimpleTestCase):
    def test_libelles_nettoyes_sans_null(self):
        curseur = mock.MagicMock()
        curseur.description = [("tue_code_ident",), ("tue_nom",), ("tue_descr",)]
        curseur.fetchall.return_value = [(IPE, "Inventaire sur plan d'eau", None)]

        @contextmanager
        def lecture():
            yield curseur

        with (
            mock.patch.object(db, "schema", return_value="ifa_data"),
            mock.patch.object(db, "curseur", lecture),
        ):
            types = projet_sonda.types_disponibles()

        self.assertEqual(
            types,
            [
                {
                    "tue_code_ident": IPE,
                    "tue_nom": "Inventaire sur plan d'eau",
                    "tue_descr": "",
                }
            ],
        )
        sql, parametres = curseur.execute.call_args[0]
        self.assertIn("<> lower(%s)", sql)
        self.assertEqual(parametres, [projet_sonda.TYPE_PROJET_NOM])


class TypesDuProjetTestCase(SimpleTestCase):
    """Ce que « Créer une UE » reçoit pour restreindre ses types."""

    def appeler(self, pro_no, projet, associations=()):
        curseur = mock.MagicMock()
        reponses = []
        if projet is not None:
            reponses.append(
                (
                    ["pro_code_ident", "pro_no", "pro_nom", "pro_an"],
                    [(projet, "09-OG", "Observations générales", 2024)],
                )
            )
        else:
            reponses.append((["pro_code_ident", "pro_no", "pro_nom", "pro_an"], []))
        reponses.append(
            (
                [
                    "tue_code_ident",
                    "tue_nom",
                    "ptu_nb_impla_plani",
                    "ptu_nb_remes_plani",
                ],
                list(associations),
            )
        )

        def execute(sql, parametres=None):
            colonnes, lignes = reponses.pop(0)
            curseur.description = [(c,) for c in colonnes]
            curseur.fetchall.return_value = lignes

        curseur.execute.side_effect = execute

        @contextmanager
        def lecture():
            yield curseur

        with (
            mock.patch.object(db, "schema", return_value="ifa_data"),
            mock.patch.object(db, "curseur", lecture),
        ):
            return projet_sonda.types_du_projet(pro_no)

    def test_types_du_projet(self):
        resultat = self.appeler(
            " 09-og ",
            "uuid-projet",
            [(IPE, "Inventaire sur plan d'eau", 12, 3)],
        )

        self.assertEqual(resultat["pro_no"], "09-OG")
        self.assertEqual(
            resultat["types"],
            [
                {
                    "tue_code_ident": IPE,
                    "tue_nom": "Inventaire sur plan d'eau",
                    "nb_impla_plani": 12,
                    "nb_remes_plani": 3,
                }
            ],
        )

    def test_projet_sans_type_rend_une_liste_vide(self):
        """Les projets hérités : le plugin proposera alors tous les types."""
        self.assertEqual(self.appeler("09-OG", "uuid-projet")["types"], [])

    def test_projet_inconnu(self):
        with self.assertRaises(ProjetIntrouvableError):
            self.appeler("ZZ-INCONNU", None)

    def test_numero_absent_ou_trop_long(self):
        for numero in ("", "   ", "x" * 21):
            with self.subTest(numero=numero):
                with self.assertRaises(FiltreInvalideError):
                    projet_sonda.types_du_projet(numero)


class VersionTestCase(SimpleTestCase):
    @override_settings(IFA_PROJET_VERSION_TYPE="  config-version  ")
    def test_la_configuration_prime(self):
        curseur = CurseurSimule()
        self.assertEqual(
            projet_sonda.version_projet(curseur, "ifa_data"), "config-version"
        )
        self.assertEqual(curseur.requetes, [], "la base n'est pas interrogée")

    @override_settings(IFA_PROJET_VERSION_TYPE="")
    def test_aucune_version_en_production(self):
        with self.assertRaises(VersionProjetIntrouvableError):
            projet_sonda.version_projet(CurseurSimule(version=None), "ifa_data")


class SerializerTestCase(SimpleTestCase):
    def valider(self, **surcharges):
        donnees = demande(**surcharges)
        for cle in [c for c, v in donnees.items() if v is None]:
            del donnees[cle]
        return ProjetSondageSerializer(data=donnees)

    def test_valeurs_par_defaut(self):
        s = ProjetSondageSerializer(
            data={
                "pro_no": " 09-OG ",
                "pro_nom": "OG",
                "pro_an": 2026,
                "rad_no": "09",
                "types_ue": [
                    {"tue_code_ident": IPE, "nb_impla_plani": 1, "nb_remes_plani": 0}
                ],
            }
        )
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["pro_no"], "09-OG")
        self.assertEqual(s.validated_data["pro_code_statu"], "El")
        self.assertFalse(s.validated_data["pro_ind_inven_norma"])

    def test_numero_obligatoire_message_francais(self):
        s = self.valider(pro_no="   ")
        self.assertFalse(s.is_valid())
        self.assertIn("obligatoire", str(s.errors["pro_no"][0]))

    def test_numero_trop_long(self):
        self.assertFalse(self.valider(pro_no="x" * 21).is_valid())

    def test_annee_hors_bornes(self):
        self.assertFalse(self.valider(pro_an=1900).is_valid())
        self.assertFalse(self.valider(pro_an=projet_sonda.annee_max() + 1).is_valid())
        self.assertTrue(self.valider(pro_an=projet_sonda.annee_max()).is_valid())

    def test_region_hors_type(self):
        s = self.valider(rad_no="18")
        self.assertFalse(s.is_valid())
        self.assertIn("Région inconnue", str(s.errors["rad_no"][0]))

    def test_regions_speciales_acceptees(self):
        self.assertTrue(self.valider(rad_no="DFA").is_valid())

    def test_un_projet_ne_nait_pas_termine(self):
        self.assertFalse(
            self.valider(pro_code_statu=projet_sonda.STATUT_TERMINE).is_valid()
        )

    def test_au_moins_un_type(self):
        for types in ([], None):
            with self.subTest(types=types):
                s = self.valider(types_ue=types)
                self.assertFalse(s.is_valid())
                self.assertIn("au moins un type", str(s.errors["types_ue"]))

    def type_ue(self, **surcharges):
        type_ue = {"tue_code_ident": IPE, "nb_impla_plani": 12, "nb_remes_plani": 2}
        type_ue.update(surcharges)
        return {c: v for c, v in type_ue.items() if v is not ...}

    def test_type_en_double(self):
        s = self.valider(types_ue=[self.type_ue(), self.type_ue()])
        self.assertFalse(s.is_valid())
        self.assertIn("deux fois", str(s.errors["types_ue"]))

    def test_nombres_planifies_obligatoires(self):
        """Ajouter un type, c'est dire ce qu'on y planifie."""
        for champ, mot in (
            ("nb_impla_plani", "implantations"),
            ("nb_remes_plani", "remesurages"),
        ):
            for valeur in (..., None):
                with self.subTest(champ=champ, valeur=valeur):
                    s = self.valider(types_ue=[self.type_ue(**{champ: valeur})])
                    self.assertFalse(s.is_valid())
                    self.assertIn(mot, str(s.errors["types_ue"]))

    def test_au_moins_une_implantation(self):
        s = self.valider(types_ue=[self.type_ue(nb_impla_plani=0)])
        self.assertFalse(s.is_valid())
        self.assertIn("au moins 1", str(s.errors["types_ue"]))

    def test_zero_remesurage_accepte(self):
        s = self.valider(types_ue=[self.type_ue(nb_remes_plani=0)])
        self.assertTrue(s.is_valid(), s.errors)

    def test_remesurages_negatifs(self):
        s = self.valider(types_ue=[self.type_ue(nb_remes_plani=-1)])
        self.assertFalse(s.is_valid())
        self.assertIn("négatif", str(s.errors["types_ue"]))

    def test_borne_superieure(self):
        s = self.valider(
            types_ue=[self.type_ue(nb_impla_plani=projet_sonda.NB_PLANI_MAX + 1)]
        )
        self.assertFalse(s.is_valid())
