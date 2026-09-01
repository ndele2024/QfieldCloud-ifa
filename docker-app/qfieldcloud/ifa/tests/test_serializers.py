from django.test import SimpleTestCase, override_settings

from qfieldcloud.ifa.serializers import RechercheUnitesSerializer

CARRE = "POLYGON((-71 48, -70 48, -70 49, -71 49, -71 48))"


class RechercheUnitesSerializerTestCase(SimpleTestCase):
    def valider(self, donnees):
        filtre = RechercheUnitesSerializer(data=donnees)
        return filtre.is_valid(), filtre

    def test_region_valide(self):
        valide, filtre = self.valider({"mode": "region", "valeur": "02"})

        self.assertTrue(valide, filtre.errors)
        self.assertEqual(filtre.validated_data["decalage"], 0)
        self.assertGreater(filtre.validated_data["limite"], 0)

    def test_region_refuse_une_valeur_non_numerique(self):
        valide, filtre = self.valider({"mode": "region", "valeur": "Saguenay"})

        self.assertFalse(valide)
        self.assertIn("valeur", filtre.errors)

    def test_lce_refuse_une_valeur_non_numerique(self):
        valide, _ = self.valider({"mode": "lce", "valeur": "12777A"})

        self.assertFalse(valide)

    def test_valeur_obligatoire_hors_mode_emprise(self):
        valide, filtre = self.valider({"mode": "code"})

        self.assertFalse(valide)
        self.assertIn("valeur", filtre.errors)

    def test_code_accepte_n_importe_quel_texte(self):
        """La recherche par code est partielle, pas un code complet."""
        for saisie in ("12777", "ANRO", "02-127", "og"):
            valide, filtre = self.valider({"mode": "code", "valeur": saisie})
            self.assertTrue(valide, f"{saisie} refusé : {filtre.errors}")

    def test_code_refuse_une_saisie_d_un_seul_caractere(self):
        """Un caractère ramènerait une bonne partie des 142 000 unités."""
        valide, filtre = self.valider({"mode": "code", "valeur": "0"})

        self.assertFalse(valide)
        self.assertIn("valeur", filtre.errors)

    def test_emprise_exige_une_zone(self):
        valide, filtre = self.valider({"mode": "emprise"})

        self.assertFalse(valide)
        self.assertIn("wkt", filtre.errors)

    def test_emprise_accepte_un_polygone(self):
        valide, filtre = self.valider({"mode": "emprise", "wkt": CARRE})

        self.assertTrue(valide, filtre.errors)
        self.assertTrue(filtre.validated_data["wkt"].startswith("POLYGON"))

    def test_emprise_refuse_un_wkt_illisible(self):
        valide, filtre = self.valider({"mode": "emprise", "wkt": "PAS DU WKT"})

        self.assertFalse(valide)
        self.assertIn("wkt", filtre.errors)

    def test_emprise_refuse_une_geometrie_qui_n_est_pas_un_polygone(self):
        valide, filtre = self.valider({"mode": "emprise", "wkt": "POINT(-71 48)"})

        self.assertFalse(valide)
        self.assertIn("wkt", filtre.errors)

    def test_bbox_accepte_mais_sans_effet_sur_le_filtre(self):
        valide, filtre = self.valider(
            {"mode": "emprise", "wkt": CARRE, "bbox": [-71, 48, -70, 49]}
        )

        self.assertTrue(valide, filtre.errors)

    @override_settings(IFA_RECHERCHE_LIMITE_MAX=50)
    def test_la_limite_est_plafonnee(self):
        """Un client ne doit pas pouvoir demander la table entière."""
        valide, filtre = self.valider(
            {"mode": "region", "valeur": "02", "limite": 100000}
        )

        self.assertTrue(valide, filtre.errors)
        self.assertEqual(filtre.validated_data["limite"], 50)

    def test_mode_inconnu_refuse(self):
        valide, filtre = self.valider({"mode": "departement", "valeur": "02"})

        self.assertFalse(valide)
        self.assertIn("mode", filtre.errors)
