"""Déverrouillage d'une unité : la règle, sans la base.

L'`UPDATE` demande PostgreSQL. Ce qui se décide ici, c'est à qui l'on accorde
de relâcher un verrou — et le fait qu'une unité déjà libre ne soit pas une
erreur.
"""

from unittest import mock

from django.test import SimpleTestCase

from qfieldcloud.ifa import verrou
from qfieldcloud.ifa.exceptions import UniteVerrouilleeError


def ligne(verrouillee="O", proprietaire="ifauser", raison="Saisie en cours"):
    return {
        "une_code_ident": "02-12777-IPE",
        "une_ind_verro": verrouillee,
        "une_nom_propr_verro": proprietaire,
        "une_date_verro": "",
        "une_raiso_verro": raison,
    }


class RelacherTestCase(SimpleTestCase):
    def test_son_propre_verrou_tombe(self):
        with mock.patch.object(verrou, "lire", return_value=ligne()) as lire:
            with mock.patch.object(verrou, "lever", return_value=True) as lever:
                resultat = verrou.relacher("02-12777-IPE", "ifauser")

        self.assertTrue(resultat["deverrouille"])
        lever.assert_called_once_with("02-12777-IPE", "ifauser")
        # Une relecture après l'UPDATE : la réponse rend l'état réel.
        self.assertEqual(lire.call_count, 2)

    def test_unite_deja_libre_n_est_pas_une_erreur(self):
        """Le résultat voulu est déjà là : le dire par une erreur serait absurde."""
        libre = ligne(verrouillee="N", proprietaire="", raison="")

        with mock.patch.object(verrou, "lire", return_value=libre):
            with mock.patch.object(verrou, "lever") as lever:
                resultat = verrou.relacher("02-12777-IPE", "ifauser")

        self.assertFalse(resultat["deverrouille"])
        lever.assert_not_called()

    def test_verrou_d_un_autre_refuse(self):
        with mock.patch.object(
            verrou, "lire", return_value=ligne(proprietaire="kamdo1")
        ):
            with mock.patch.object(verrou, "lever") as lever:
                with self.assertRaises(UniteVerrouilleeError) as erreur:
                    verrou.relacher("02-12777-IPE", "ifauser")

        lever.assert_not_called()
        self.assertIn("kamdo1", erreur.exception.message)


class TenueParUnAutreTestCase(SimpleTestCase):
    def test_soi_meme(self):
        self.assertFalse(verrou.tenue_par_un_autre(ligne(), "ifauser"))

    def test_quelqu_un_d_autre(self):
        self.assertTrue(
            verrou.tenue_par_un_autre(ligne(proprietaire="kamdo1"), "ifauser")
        )

    def test_non_verrouillee(self):
        self.assertFalse(
            verrou.tenue_par_un_autre(
                ligne(verrouillee="N", proprietaire=""), "ifauser"
            )
        )
