import datetime
from decimal import Decimal

from django.test import SimpleTestCase

from qfieldcloud.ifa.views import normaliser_unite

LIGNE_SQL = {
    "une_code_ident": "02-12777-IPE",
    "tue_code_ident": "f0758571-e68e-47f5-a3d5-9c865e3c61c9",
    "tue_nom": "Inventaire sur plan d'eau",
    "une_ind_verro": "N",
    "une_nom_propr_verro": None,
    "une_date_verro": None,
    "une_raiso_verro": None,
    "une_date_creat": datetime.datetime(2009, 10, 21, 14, 52, 56),
    "une_code_utili_creat": "ifa0t2",
    "une_date_maj": datetime.datetime(2025, 4, 3, 12, 31, 7),
    "une_code_utili_maj": "kamdo1",
    "rad_no": "02",
    "ing_no_plan_eau_offic": "12777",
    "ing_nom_plan_eau": "ILETS, LAC DES  ",
    "latitude": Decimal("48.429444"),
    "longitude": Decimal("-70.079722"),
}


class NormalisationTestCase(SimpleTestCase):
    def test_les_colonnes_du_contrat_sont_toutes_presentes(self):
        unite = normaliser_unite(LIGNE_SQL)

        for champ in (
            "une_code_ident",
            "tue_code_ident",
            "tue_nom",
            "une_ind_verro",
            "une_nom_propr_verro",
            "une_date_creat",
            "une_code_utili_creat",
            "une_date_maj",
            "une_code_utili_maj",
        ):
            self.assertIn(champ, unite)

    def test_les_valeurs_absentes_sortent_en_chaines_vides(self):
        """Un `null` deviendrait le texte « null » dans une cellule du tableau."""
        unite = normaliser_unite(LIGNE_SQL)

        self.assertEqual(unite["une_nom_propr_verro"], "")
        self.assertEqual(unite["une_raiso_verro"], "")
        self.assertEqual(unite["une_date_verro"], "")

    def test_l_indicateur_de_verrou_vaut_n_par_defaut(self):
        unite = normaliser_unite({**LIGNE_SQL, "une_ind_verro": None})

        self.assertEqual(unite["une_ind_verro"], "N")

    def test_les_horodatages_sortent_en_iso_sans_fuseau(self):
        """Le schéma hérité stocke l'heure locale de saisie, sans fuseau.

        Y coller un « Z » afficherait une heure fausse.
        """
        unite = normaliser_unite(LIGNE_SQL)

        self.assertEqual(unite["une_date_creat"], "2009-10-21T14:52:56")
        self.assertNotIn("Z", unite["une_date_maj"])

    def test_les_coordonnees_restent_nulles_quand_l_unite_n_est_pas_localisee(self):
        """Un zéro placerait l'unité au large du golfe de Guinée."""
        unite = normaliser_unite({**LIGNE_SQL, "latitude": None, "longitude": None})

        self.assertIsNone(unite["latitude"])
        self.assertIsNone(unite["longitude"])

    def test_les_coordonnees_sortent_en_nombres(self):
        unite = normaliser_unite(LIGNE_SQL)

        self.assertIsInstance(unite["latitude"], float)
        self.assertAlmostEqual(unite["longitude"], -70.079722, places=6)

    def test_les_libelles_sont_deshabilles_de_leurs_espaces(self):
        unite = normaliser_unite(LIGNE_SQL)

        self.assertEqual(unite["ing_nom_plan_eau"], "ILETS, LAC DES")
