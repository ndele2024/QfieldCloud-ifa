from django.test import SimpleTestCase, override_settings

from qfieldcloud.ifa.serializers import (
    OuvrirUniteSerializer,
    PreparerFormulaireSerializer,
    RechercheUnitesSerializer,
)

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

    # ---- Critères multiples -------------------------------------------------

    def test_la_forme_a_plat_devient_un_critere_unique(self):
        """Les plugins déjà installés envoient encore `mode` et `valeur`."""
        valide, filtre = self.valider({"mode": "region", "valeur": "02"})

        self.assertTrue(valide, filtre.errors)
        self.assertEqual(
            filtre.validated_data["criteres"], [{"mode": "region", "valeur": "02"}]
        )

    def test_plusieurs_criteres_sont_retenus_dans_l_ordre(self):
        valide, filtre = self.valider(
            {
                "criteres": [
                    {"mode": "region", "valeur": "02"},
                    {"mode": "bassin", "valeur": "Saguenay"},
                ]
            }
        )

        self.assertTrue(valide, filtre.errors)
        modes = [c["mode"] for c in filtre.validated_data["criteres"]]
        self.assertEqual(modes, ["region", "bassin"])

    def test_le_mode_a_plat_reste_rendu_pour_les_clients_anterieurs(self):
        valide, filtre = self.valider(
            {"criteres": [{"mode": "bassin", "valeur": "Saguenay"}]}
        )

        self.assertTrue(valide, filtre.errors)
        self.assertEqual(filtre.validated_data["mode"], "bassin")

    def test_aucun_critere_refuse(self):
        valide, filtre = self.valider({})

        self.assertFalse(valide)
        self.assertIn("criteres", filtre.errors)

    def test_liste_de_criteres_vide_refusee(self):
        valide, filtre = self.valider({"criteres": []})

        self.assertFalse(valide)
        self.assertIn("criteres", filtre.errors)

    def test_deux_fois_le_meme_mode_refuse(self):
        """Deux régions croisées par `AND` ne rendraient jamais rien."""
        valide, filtre = self.valider(
            {
                "criteres": [
                    {"mode": "region", "valeur": "02"},
                    {"mode": "region", "valeur": "09"},
                ]
            }
        )

        self.assertFalse(valide)
        self.assertIn("criteres", filtre.errors)

    def test_un_critere_invalide_refuse_toute_la_recherche(self):
        valide, filtre = self.valider(
            {
                "criteres": [
                    {"mode": "region", "valeur": "02"},
                    {"mode": "lce", "valeur": "douze-mille"},
                ]
            }
        )

        self.assertFalse(valide)

    def test_l_emprise_se_croise_avec_un_autre_critere(self):
        valide, filtre = self.valider(
            {
                "criteres": [
                    {"mode": "emprise", "wkt": CARRE},
                    {"mode": "bassin", "valeur": "Saguenay"},
                ]
            }
        )

        self.assertTrue(valide, filtre.errors)
        self.assertTrue(filtre.validated_data["criteres"][0]["wkt"].startswith("POLY"))

    # ---- Bassin -------------------------------------------------------------

    def test_bassin_accepte_un_fragment(self):
        for saisie in ("Saguenay", "sague", "du Nord"):
            valide, filtre = self.valider({"mode": "bassin", "valeur": saisie})
            self.assertTrue(valide, f"{saisie} refusé : {filtre.errors}")

    def test_bassin_refuse_une_saisie_d_un_seul_caractere(self):
        valide, filtre = self.valider({"mode": "bassin", "valeur": "S"})

        self.assertFalse(valide)
        self.assertIn("valeur", filtre.errors)

    def test_bassin_exige_une_valeur(self):
        valide, filtre = self.valider({"mode": "bassin"})

        self.assertFalse(valide)
        self.assertIn("valeur", filtre.errors)


class OuvrirUniteSerializerTestCase(SimpleTestCase):
    def valider(self, donnees):
        demande = OuvrirUniteSerializer(data=donnees)
        return demande.is_valid(), demande

    def test_mode_modifiable_exige_une_raison(self):
        valide, demande = self.valider({"mode": "modifiable"})

        self.assertFalse(valide)
        self.assertIn("Indiquez la raison", str(demande.errors))

    def test_raison_vide_refusee_en_mode_modifiable(self):
        valide, _ = self.valider({"mode": "modifiable", "raison": "   "})

        self.assertFalse(valide)

    def test_mode_modifiable_avec_raison(self):
        valide, demande = self.valider(
            {"mode": "modifiable", "raison": "  Saisie en cours  "}
        )

        self.assertTrue(valide, demande.errors)
        self.assertEqual(demande.validated_data["raison"], "Saisie en cours")

    def test_consultation_sans_raison(self):
        valide, demande = self.valider({"mode": "consultation"})

        self.assertTrue(valide, demande.errors)
        self.assertEqual(demande.validated_data["raison"], "")

    def test_consultation_ignore_la_raison_envoyee(self):
        """Rien n'est écrit dans la base en consultation : la raison n'a pas de sens."""
        valide, demande = self.valider(
            {"mode": "consultation", "raison": "verrouillage"}
        )

        self.assertTrue(valide, demande.errors)
        self.assertEqual(demande.validated_data["raison"], "")

    def test_mode_inconnu(self):
        valide, demande = self.valider({"mode": "verrouille", "raison": "x"})

        self.assertFalse(valide)
        self.assertIn("mode", demande.errors)

    def test_raison_trop_longue(self):
        valide, demande = self.valider({"mode": "modifiable", "raison": "x" * 501})

        self.assertFalse(valide)
        self.assertIn("raison", demande.errors)


class PreparerFormulaireSerializerTestCase(SimpleTestCase):
    """Le filtre du bloc « Donnees a embarquer » et le contexte de l'unite."""

    def valider(self, donnees):
        complet = {"une_code_ident": "02-12777-IPE", "type_ue": "Inventaire"}
        complet.update(donnees)
        demande = PreparerFormulaireSerializer(data=complet)
        return demande.is_valid(), demande

    def test_region_valide(self):
        valide, demande = self.valider(
            {
                "mode": "region",
                "valeur": "02",
                "variables": {"code_region": "02", "une_code_ident": "02-12777-IPE"},
            }
        )

        self.assertTrue(valide, demande.errors)
        self.assertEqual(demande.validated_data["variables"]["code_region"], "02")

    def test_emprise_sans_polygone(self):
        valide, demande = self.valider({"mode": "emprise"})

        self.assertFalse(valide)
        self.assertIn("wkt", demande.errors)

    def test_emprise_avec_polygone(self):
        valide, demande = self.valider({"mode": "emprise", "wkt": CARRE})

        self.assertTrue(valide, demande.errors)
        self.assertTrue(demande.validated_data["wkt"].startswith("POLYGON"))

    def test_le_mode_code_n_a_pas_cours(self):
        """On ne cree pas une unite a partir d'un fragment de code existant."""
        valide, demande = self.valider({"mode": "code", "valeur": "12777"})

        self.assertFalse(valide)
        self.assertIn("mode", demande.errors)

    def test_region_non_numerique(self):
        valide, demande = self.valider({"mode": "region", "valeur": "Saguenay"})

        self.assertFalse(valide)
        self.assertIn("valeur", demande.errors)

    def test_lce_non_numerique(self):
        valide, _ = self.valider({"mode": "lce", "valeur": "12777A"})

        self.assertFalse(valide)

    def test_variables_facultatives(self):
        valide, demande = self.valider({"mode": "lce", "valeur": "12777"})

        self.assertTrue(valide, demande.errors)
        self.assertEqual(demande.validated_data.get("variables", {}), {})

    def test_variable_trop_longue(self):
        valide, demande = self.valider(
            {"mode": "lce", "valeur": "12777", "variables": {"code_lce": "x" * 500}}
        )

        self.assertFalse(valide)
        self.assertIn("variables", demande.errors)

    def test_polygone_illisible(self):
        valide, demande = self.valider({"mode": "emprise", "wkt": "PAS DU WKT"})

        self.assertFalse(valide)
        self.assertIn("wkt", demande.errors)

    def test_identifiant_exige(self):
        demande = PreparerFormulaireSerializer(
            data={"type_ue": "Inventaire", "mode": "lce", "valeur": "12777"}
        )

        self.assertFalse(demande.is_valid())
        self.assertIn("une_code_ident", demande.errors)

    def test_type_exige(self):
        demande = PreparerFormulaireSerializer(
            data={
                "une_code_ident": "02-12777-IPE",
                "mode": "lce",
                "valeur": "12777",
            }
        )

        self.assertFalse(demande.is_valid())
        self.assertIn("type_ue", demande.errors)

    def test_identifiant_trop_long(self):
        valide, demande = self.valider(
            {"une_code_ident": "x" * 41, "mode": "lce", "valeur": "12777"}
        )

        self.assertFalse(valide)
        self.assertIn("une_code_ident", demande.errors)

    # ---- Critères multiples -------------------------------------------------

    def test_criteres_croises(self):
        """Un bassin *dans* une région : c'est ce qui ramène la sélection.

        Seul, un filtre par région dépasse le plafond d'unités ; croisé avec
        un bassin, il redevient embarquable sur un appareil de terrain.
        """
        valide, demande = self.valider(
            {
                "criteres": [
                    {"mode": "region", "valeur": "02"},
                    {"mode": "bassin", "valeur": "Saguenay"},
                ]
            }
        )

        self.assertTrue(valide, demande.errors)
        self.assertEqual(len(demande.validated_data["criteres"]), 2)

    def test_le_bassin_est_accepte(self):
        valide, demande = self.valider({"mode": "bassin", "valeur": "Saguenay"})

        self.assertTrue(valide, demande.errors)

    def test_le_mode_code_n_a_pas_cours_dans_la_liste(self):
        valide, demande = self.valider(
            {"criteres": [{"mode": "code", "valeur": "12777"}]}
        )

        self.assertFalse(valide)

    def test_aucun_critere_refuse(self):
        valide, demande = self.valider({})

        self.assertFalse(valide)
        self.assertIn("criteres", demande.errors)
