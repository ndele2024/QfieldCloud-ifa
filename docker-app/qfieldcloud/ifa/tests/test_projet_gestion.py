"""Modifier, afficher, supprimer un projet : les règles, sans la base.

Ce qui se casse sans bruit, ce sont les droits : un utilisateur qui modifie un
projet en production, ou qui supprime celui d'un collègue, ne déclenche aucune
erreur — seulement un dégât. Ces essais tiennent la grille des droits, la
détection des changements réels, et l'ordre des vérifications de la
suppression.
"""

from unittest import mock

from django.test import SimpleTestCase

from qfieldcloud.ifa import db, projet_gestion, projet_sonda
from qfieldcloud.ifa.exceptions import (
    ModificationRefuseeError,
    MotDePasseInvalideError,
)
from qfieldcloud.ifa.serializers import (
    ModificationProjetSerializer,
    SuppressionProjetSerializer,
)

IPE = "f0758571-e68e-47f5-a3d5-9c865e3c61c9"
OG = "9ef3e818-e738-4131-8b69-73b2a506de44"


def projet(statut="El", createur="kamdo1", **autres):
    donnees = {
        "pro_code_ident": "uuid-projet",
        "pro_no": "09-OG",
        "pro_nom": "Observations générales",
        "pro_an": 2024,
        "rad_no": "09",
        "pro_descr": "",
        "pro_com": "",
        "pro_code_statu": statut,
        "pro_ind_inven_norma": "N",
        "pro_code_utili_creat": createur,
        "types_ue": [
            {
                "tue_code_ident": IPE,
                "tue_nom": "Inventaire sur plan d'eau",
                "nb_impla_plani": 12,
                "nb_remes_plani": 2,
            }
        ],
    }
    donnees.update(autres)
    return donnees


class DroitsModificationTestCase(SimpleTestCase):
    def test_production_reservee_a_l_admin(self):
        standard = projet_gestion.droits(projet("Pr"), "kamdo1", False, 0)
        self.assertFalse(standard["modifiable"])
        self.assertEqual(standard["champs_modifiables"], [])
        self.assertIn("administrateur", standard["raison_modification"])

        admin = projet_gestion.droits(projet("Pr"), "chef", True, 0)
        self.assertTrue(admin["modifiable"])
        self.assertEqual(admin["champs_modifiables"], list(projet_gestion.CHAMPS_TOUS))

    def test_hors_production_tout_est_modifiable(self):
        for statut in ("El", "Te"):
            with self.subTest(statut=statut):
                d = projet_gestion.droits(projet(statut), "autre", False, 0)
                self.assertTrue(d["modifiable"])
                self.assertEqual(
                    d["champs_modifiables"], list(projet_gestion.CHAMPS_TOUS)
                )

    def test_projet_utilise_nom_description_et_nombres(self):
        """Même pour un administrateur : le reste qualifie des données saisies."""
        for admin in (False, True):
            with self.subTest(admin=admin):
                d = projet_gestion.droits(projet("El"), "kamdo1", admin, 3)
                self.assertTrue(d["modifiable"])
                self.assertEqual(
                    d["champs_modifiables"],
                    ["pro_nom", "pro_descr", "types_ue_nombres"],
                )
                self.assertIn("3 unité(s)", d["raison_modification"])

    def test_utilise_et_en_production_admin_nom_description_et_nombres(self):
        d = projet_gestion.droits(projet("Pr"), "chef", True, 5)
        self.assertEqual(
            d["champs_modifiables"], ["pro_nom", "pro_descr", "types_ue_nombres"]
        )
        self.assertIn("nombres planifiés", d["raison_modification"])


class DroitsSuppressionTestCase(SimpleTestCase):
    def test_createur_hors_production(self):
        d = projet_gestion.droits(projet("El", createur="kamdo1"), "KAMDO1", False, 0)
        self.assertTrue(d["createur"], "la casse ne compte pas")
        self.assertTrue(d["supprimable"])

    def test_autre_utilisateur_refuse_et_createur_nomme(self):
        d = projet_gestion.droits(projet("El", createur="kamdo1"), "robma8", False, 0)
        self.assertFalse(d["supprimable"])
        self.assertIn("kamdo1", d["raison_suppression"])

    def test_createur_en_production_refuse(self):
        d = projet_gestion.droits(projet("Pr", createur="kamdo1"), "kamdo1", False, 0)
        self.assertFalse(d["supprimable"])
        self.assertIn("production", d["raison_suppression"])

    def test_admin_supprime_tout(self):
        for statut in ("El", "Pr", "Te"):
            with self.subTest(statut=statut):
                d = projet_gestion.droits(projet(statut, createur="x"), "chef", True, 0)
                self.assertTrue(d["supprimable"])

    def test_projet_utilise_jamais_supprime(self):
        """Pas de clé étrangère : les mesurages resteraient orphelins."""
        for admin in (False, True):
            with self.subTest(admin=admin):
                d = projet_gestion.droits(projet("El"), "kamdo1", admin, 1)
                self.assertFalse(d["supprimable"])
                self.assertIn("utilisé", d["raison_suppression"])

    def test_createur_inconnu(self):
        d = projet_gestion.droits(projet("El", createur=""), "", False, 0)
        self.assertFalse(d["createur"], "deux vides ne font pas un créateur")
        self.assertFalse(d["supprimable"])

    def test_nom_tronque_comme_a_l_ecriture(self):
        nom = "un_nom_bien_plus_long_que_20"
        self.assertTrue(
            projet_gestion.est_createur({"pro_code_utili_creat": nom[:20]}, nom)
        )


class ChangementsTestCase(SimpleTestCase):
    def test_valeurs_identiques_ne_sont_pas_des_changements(self):
        actuel = projet()
        demande = {
            "pro_no": "09-OG",
            "pro_nom": "Observations générales",
            "pro_an": 2024,
            "pro_descr": "",
            "pro_ind_inven_norma": False,
            "types_ue": [
                {"tue_code_ident": IPE, "nb_impla_plani": 12, "nb_remes_plani": 2}
            ],
        }
        self.assertEqual(projet_gestion.changements_effectifs(actuel, demande), {})

    def test_changements_detectes(self):
        actuel = projet()
        demande = {
            "pro_nom": "Nouveau nom",
            "pro_ind_inven_norma": True,
            "types_ue": [
                {"tue_code_ident": IPE, "nb_impla_plani": 13, "nb_remes_plani": 2}
            ],
        }
        self.assertEqual(
            set(projet_gestion.changements_effectifs(actuel, demande)),
            {"pro_nom", "pro_ind_inven_norma", "types_ue_nombres"},
        )

    def test_memes_types_autres_nombres(self):
        """Seuls les nombres changent : le changement s'appelle ainsi."""
        demande = {
            "types_ue": [
                {"tue_code_ident": IPE, "nb_impla_plani": 12, "nb_remes_plani": 5}
            ]
        }
        self.assertEqual(
            list(projet_gestion.changements_effectifs(projet(), demande)),
            ["types_ue_nombres"],
        )

    def test_type_ajoute_ou_retire_reste_un_changement_de_types(self):
        ajout = {
            "types_ue": [
                {"tue_code_ident": IPE, "nb_impla_plani": 12, "nb_remes_plani": 2},
                {"tue_code_ident": OG, "nb_impla_plani": 1, "nb_remes_plani": 0},
            ]
        }
        remplacement = {
            "types_ue": [
                {"tue_code_ident": OG, "nb_impla_plani": 12, "nb_remes_plani": 2}
            ]
        }
        for demande in (ajout, remplacement, {"types_ue": []}):
            with self.subTest(demande=demande):
                self.assertEqual(
                    list(projet_gestion.changements_effectifs(projet(), demande)),
                    ["types_ue"],
                )

    def test_ordre_des_types_indifferent(self):
        actuel = projet(
            types_ue=[
                {"tue_code_ident": IPE, "nb_impla_plani": 1, "nb_remes_plani": 0},
                {"tue_code_ident": OG, "nb_impla_plani": 2, "nb_remes_plani": 1},
            ]
        )
        demande = {"types_ue": list(reversed(actuel["types_ue"]))}
        self.assertEqual(projet_gestion.changements_effectifs(actuel, demande), {})


class VerificationModificationTestCase(SimpleTestCase):
    def test_champ_hors_droits_refuse_et_nomme(self):
        permis = projet_gestion.droits(projet("El"), "kamdo1", False, 4)

        with self.assertRaises(ModificationRefuseeError) as erreur:
            projet_gestion.verifier_droits_modification(
                {"pro_nom": "x", "rad_no": "02"}, permis
            )

        self.assertIn("la région", erreur.exception.message)
        self.assertNotIn("le nom", erreur.exception.message.split("refusée pour")[1])

    def test_nom_et_description_passent_sur_un_projet_utilise(self):
        permis = projet_gestion.droits(projet("El"), "kamdo1", False, 4)
        projet_gestion.verifier_droits_modification(
            {"pro_nom": "x", "pro_descr": "y"}, permis
        )

    def test_nombres_planifies_passent_sur_un_projet_utilise(self):
        for admin in (False, True):
            with self.subTest(admin=admin):
                permis = projet_gestion.droits(projet("El"), "kamdo1", admin, 4)
                projet_gestion.verifier_droits_modification(
                    {"types_ue_nombres": [], "pro_nom": "x"}, permis
                )

    def test_types_refuses_sur_un_projet_utilise(self):
        permis = projet_gestion.droits(projet("El"), "chef", True, 4)
        with self.assertRaises(ModificationRefuseeError) as erreur:
            projet_gestion.verifier_droits_modification({"types_ue": []}, permis)
        self.assertIn("les types d'UE", erreur.exception.message)

    def test_nombres_refuses_en_production_pour_un_standard(self):
        permis = projet_gestion.droits(projet("Pr"), "kamdo1", False, 4)
        with self.assertRaises(ModificationRefuseeError):
            projet_gestion.verifier_droits_modification(
                {"types_ue_nombres": []}, permis
            )

    def test_projet_en_production_standard(self):
        permis = projet_gestion.droits(projet("Pr"), "kamdo1", False, 0)
        with self.assertRaises(ModificationRefuseeError):
            projet_gestion.verifier_droits_modification({"pro_descr": "x"}, permis)


class SuppressionTestCase(SimpleTestCase):
    def test_mot_de_passe_verifie_avant_la_base(self):
        utilisateur = mock.Mock(username="kamdo1")
        utilisateur.check_password.return_value = False

        with (
            mock.patch.object(db, "curseur_ecriture") as ecriture,
            mock.patch.object(projet_gestion, "est_admin") as admin,
        ):
            with self.assertRaises(MotDePasseInvalideError):
                projet_gestion.supprimer("uuid-projet", utilisateur, "faux")

        ecriture.assert_not_called()
        admin.assert_not_called()

    def test_mot_de_passe_vide(self):
        utilisateur = mock.Mock(username="kamdo1")
        with self.assertRaises(MotDePasseInvalideError):
            projet_gestion.supprimer("uuid-projet", utilisateur, "")
        utilisateur.check_password.assert_not_called()

    def test_le_refus_n_est_pas_un_401(self):
        """Un 401 ferait rejouer la requête par SessionCloud."""
        self.assertEqual(MotDePasseInvalideError.status_code, 403)


class SerializersTestCase(SimpleTestCase):
    def test_modification_partielle(self):
        s = ModificationProjetSerializer(
            data={"pro_nom": "Nouveau", "pro_date_maj": "2026-10-05T09:30:00"},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(set(s.validated_data), {"pro_nom", "pro_date_maj"})

    def test_statut_termine_accepte_en_modification(self):
        s = ModificationProjetSerializer(
            data={"pro_code_statu": projet_sonda.STATUT_TERMINE, "pro_date_maj": ""},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)

    def test_nom_vide_refuse(self):
        s = ModificationProjetSerializer(
            data={"pro_nom": "  ", "pro_date_maj": ""}, partial=True
        )
        self.assertFalse(s.is_valid())

    def test_mot_de_passe_exige(self):
        s = SuppressionProjetSerializer(data={"mot_de_passe": ""})
        self.assertFalse(s.is_valid())
        self.assertIn("mot de passe", str(s.errors["mot_de_passe"][0]))

    def test_mot_de_passe_non_rogne(self):
        """Un espace dans un mot de passe en fait partie."""
        s = SuppressionProjetSerializer(data={"mot_de_passe": " secret "})
        self.assertTrue(s.is_valid())
        self.assertEqual(s.validated_data["mot_de_passe"], " secret ")
