from django.test import SimpleTestCase

from qfieldcloud.ifa import filtres

SCHEMA = "ifa_data"
SRID = 32187


class FiltresTestCase(SimpleTestCase):
    def test_code_cherche_un_fragment_sans_tenir_compte_de_la_casse(self):
        fragment, parametres = filtres.predicat(
            mode=filtres.MODE_CODE,
            schema=SCHEMA,
            srid_metier=SRID,
            valeur="  02-12777-ipe ",
        )

        self.assertEqual(fragment, "u.une_code_ident ILIKE %s")
        self.assertEqual(parametres, ["%02-12777-ipe%"])

    def test_code_accepte_un_fragment_partiel(self):
        """Le technicien connaît rarement le code entier."""
        _, parametres = filtres.predicat(
            mode=filtres.MODE_CODE, schema=SCHEMA, srid_metier=SRID, valeur="12777"
        )

        self.assertEqual(parametres, ["%12777%"])

    def test_code_neutralise_les_jokers_de_like(self):
        """Un « % » tapé par mégarde ramènerait la table entière."""
        _, parametres = filtres.predicat(
            mode=filtres.MODE_CODE, schema=SCHEMA, srid_metier=SRID, valeur="02_1%"
        )

        self.assertEqual(parametres, [r"%02\_1\%%"])

    def test_region_interroge_le_projet_et_non_le_prefixe_du_code(self):
        fragment, parametres = filtres.predicat(
            mode=filtres.MODE_REGION,
            schema=SCHEMA,
            srid_metier=SRID,
            valeur="02",
        )

        self.assertIn("proje_sonda", fragment)
        self.assertIn("p.rad_no::text = %s", fragment)
        # Le préfixe du code d'unité ment sur la région : il ne doit pas
        # servir de critère.
        self.assertNotIn("une_code_ident LIKE", fragment)
        self.assertEqual(parametres, ["02"])

    def test_lce_compare_des_numeros_dezerotes(self):
        fragment, parametres = filtres.predicat(
            mode=filtres.MODE_LCE,
            schema=SCHEMA,
            srid_metier=SRID,
            valeur="00256",
        )

        self.assertIn("ltrim(i.ing_no_plan_eau_offic, '0') = %s", fragment)
        self.assertIn("ltrim(i.ing_no_plan_eau, '0') = %s", fragment)
        self.assertEqual(parametres, ["256", "256"])

    def test_emprise_reprojette_le_polygone_vers_le_srid_metier(self):
        wkt = "POLYGON((-71 48, -70 48, -70 49, -71 49, -71 48))"
        fragment, parametres = filtres.predicat(
            mode=filtres.MODE_EMPRISE,
            schema=SCHEMA,
            srid_metier=SRID,
            wkt=wkt,
        )

        # C'est le polygone du filtre qui est transformé, jamais la colonne
        # `shape` : l'inverse condamnerait l'index GiST.
        self.assertIn(f"ST_Transform(ST_GeomFromText(%s, 4326), {SRID})", fragment)
        self.assertIn("ST_Intersects(", fragment)
        self.assertEqual(parametres, [wkt])

    def test_mode_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            filtres.predicat(
                mode="departement",
                schema=SCHEMA,
                srid_metier=SRID,
                valeur="02",
            )

    def test_les_requetes_portent_le_schema_configure(self):
        fragment, _ = filtres.predicat(
            mode=filtres.MODE_CODE, schema=SCHEMA, srid_metier=SRID, valeur="02-1-IPE"
        )

        self.assertIn(
            f"FROM {SCHEMA}.unite_echan u", filtres.requete_page(SCHEMA, fragment)
        )
        self.assertIn(
            f"FROM {SCHEMA}.unite_echan u",
            filtres.requete_denombrement(SCHEMA, fragment),
        )

    def test_la_page_pagine_avant_de_joindre(self):
        """La pagination doit s'appliquer sur `unite_echan` seule.

        Enrichir d'abord et paginer ensuite ferait porter les jointures sur
        les milliers de lignes d'un filtre par région.
        """
        fragment, _ = filtres.predicat(
            mode=filtres.MODE_REGION, schema=SCHEMA, srid_metier=SRID, valeur="02"
        )
        requete = filtres.requete_page(SCHEMA, fragment)

        position_limite = requete.index("LIMIT %s OFFSET %s")
        position_jointure = requete.index("LEFT JOIN LATERAL")

        self.assertLess(position_limite, position_jointure)
