"""Lecture du projet packagé : correspondances et passage en lecture seule.

Le XML des essais reprend la forme exacte que QFieldSync produit — c'est de
cette forme que dépend tout l'appariement « table métier → table du
GeoPackage », et elle n'est garantie par aucun contrat : elle est simplement
celle qu'écrit la version de libqfieldsync utilisée par le serveur.
"""

import io
import zipfile

from django.test import SimpleTestCase

from qfieldcloud.ifa import paquet
from qfieldcloud.ifa.exceptions import ProjetModeleInvalideError

COUCHE_HORS_LIGNE = """
  <maplayer readOnly="0" type="vector">
    <id>{identifiant}</id>
    <datasource>./data.gpkg|layername={hachage}</datasource>
    <layername>{nom}</layername>
    <customproperties>
      <Option type="Map">
        <Option name="isOfflineEditable" type="QString" value="true"/>
        <Option name="QFieldSync/sourceDataPrimaryKeys" type="QString" value="qgis_id"/>
        <Option name="remoteSource" type="QString"
                value="service='pg' key='qgis_id' srid=32187 table=&quot;{schema}&quot;.&quot;{table}&quot; (shape)"/>
      </Option>
    </customproperties>
  </maplayer>
"""

COUCHE_LOCALISEE = """
  <maplayer readOnly="1" type="vector">
    <id>referentiel_1</id>
    <datasource>localized:data/referentiels.gpkg|layername=activ_amena</datasource>
    <layername>activ_amena</layername>
    <customproperties>
      <Option type="Map">
        <Option name="QFieldSync/action" type="QString" value="no_action"/>
      </Option>
    </customproperties>
  </maplayer>
"""


def projet(*couches: str) -> str:
    return (
        '<?xml version="1.0"?>\n<qgis version="3.40.8">\n<projectlayers>'
        + "".join(couches)
        + "</projectlayers>\n</qgis>\n"
    )


def couche(nom, table, hachage, schema="ifa_qfield", identifiant=None):
    return COUCHE_HORS_LIGNE.format(
        identifiant=identifiant or f"{nom}_001",
        nom=nom,
        table=table,
        hachage=hachage,
        schema=schema,
    )


def archive(xml: str) -> bytes:
    tampon = io.BytesIO()

    with zipfile.ZipFile(tampon, "w") as sortie:
        sortie.writestr("projet.qgs", xml)
        sortie.writestr("projet.qgd", b"")

    return tampon.getvalue()


class CorrespondancesTestCase(SimpleTestCase):
    def test_couche_hors_ligne(self):
        trouvees = paquet.correspondances(
            projet(couche("mesurage", "mesurage", "c0913e60"))
        )

        self.assertEqual(len(trouvees), 1)
        self.assertEqual(trouvees[0].table_pg, "mesurage")
        self.assertEqual(trouvees[0].schema_pg, "ifa_qfield")
        self.assertEqual(trouvees[0].table_gpkg, "c0913e60")
        self.assertEqual(trouvees[0].cle, "qgis_id")
        self.assertEqual(trouvees[0].qualifie, "ifa_qfield.mesurage")

    def test_couche_localisee_ignoree(self):
        """Les référentiels partagés ne sont pas des couches hors ligne."""
        trouvees = paquet.correspondances(projet(COUCHE_LOCALISEE))

        self.assertEqual(trouvees, [])

    def test_couche_sans_source_distante_ignoree(self):
        sans_source = COUCHE_HORS_LIGNE.format(
            identifiant="x", nom="x", hachage="abc", schema="s", table="t"
        ).replace('name="remoteSource"', 'name="autreChose"')

        self.assertEqual(paquet.correspondances(projet(sans_source)), [])

    def test_sous_ensemble_dans_la_source(self):
        """`layername=` s'arrête au `|subset=` qui peut le suivre."""
        avec_filtre = couche("veget", "veget", "ad54240c").replace(
            "layername=ad54240c",
            "layername=ad54240c|subset=\"date_fin\" >= DATE('now')",
        )

        trouvees = paquet.correspondances(projet(avec_filtre))

        self.assertEqual(trouvees[0].table_gpkg, "ad54240c")

    def test_plusieurs_couches_sur_la_meme_table(self):
        """Le projet montre la même table sous plusieurs couches."""
        trouvees = paquet.correspondances(
            projet(
                couche("mesurage", "mesurage", "c0913e60", identifiant="a"),
                couche("mesurage (points)", "mesurage", "c0913e60", identifiant="b"),
            )
        )

        self.assertEqual(len(trouvees), 2)
        self.assertEqual({c.table_gpkg for c in trouvees}, {"c0913e60"})

    def test_xml_illisible(self):
        with self.assertRaises(ProjetModeleInvalideError):
            paquet.correspondances("<qgis><projectlayers>")


class LectureSeuleTestCase(SimpleTestCase):
    def test_attribut_existant_force(self):
        xml = paquet.passer_en_lecture_seule(
            projet(couche("mesurage", "mesurage", "c0913e60"))
        )

        self.assertIn('readOnly="1"', xml)
        self.assertNotIn('readOnly="0"', xml)

    def test_attribut_ajoute_quand_il_manque(self):
        sans_attribut = projet(couche("m", "m", "h")).replace(' readOnly="0"', "")

        xml = paquet.passer_en_lecture_seule(sans_attribut)

        self.assertEqual(xml.count('readOnly="1"'), 1)

    def test_toutes_les_couches_sont_touchees(self):
        xml = paquet.passer_en_lecture_seule(
            projet(
                couche("a", "a", "h1", identifiant="a"),
                couche("b", "b", "h2", identifiant="b"),
                COUCHE_LOCALISEE,
            )
        )

        self.assertEqual(xml.count('readOnly="1"'), 3)

    def test_le_reste_du_projet_est_intact(self):
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))
        apres = paquet.passer_en_lecture_seule(avant)

        self.assertIn("<datasource>./data.gpkg|layername=c0913e60</datasource>", apres)
        self.assertIn('name="remoteSource"', apres)
        self.assertEqual(len(avant.splitlines()), len(apres.splitlines()))


class RenommageGeoPackageTestCase(SimpleTestCase):
    """`renommer_geopackage()` — ce qui évite la collision au packaging.

    Le convertisseur hors ligne écrit toujours son GeoPackage sous `data.gpkg`.
    Notre copie remplie doit donc porter un autre nom, sans quoi les deux se
    disputent la même place et le projet livré sort avec toutes ses couches
    métier invalides.
    """

    def test_la_source_des_couches_suit(self):
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))
        apres = paquet.renommer_geopackage(avant, "data.gpkg", "ifa_data.gpkg")

        self.assertIn(
            "<datasource>./ifa_data.gpkg|layername=c0913e60</datasource>", apres
        )
        self.assertNotIn("./data.gpkg", apres)

    def test_toutes_les_references_suivent(self):
        """Le nom du GeoPackage ne vit pas que dans `<datasource>`.

        L'arbre des couches, les relations et les widgets « valeur relationnelle »
        désignent aussi leur source : le projet du modèle en porte 357
        occurrences pour 92 couches. En oublier une laisse une couche invalide.
        """
        avant = (
            "<datasource>./data.gpkg|layername=aaa</datasource>"
            '<layer-tree-layer source="./data.gpkg|layername=aaa" name="x"/>'
            '<Option name="Layer" value="./data.gpkg|layername=bbb" type="QString"/>'
        )
        apres = paquet.renommer_geopackage(avant, "data.gpkg", "ifa_data.gpkg")

        self.assertEqual(apres.count("./ifa_data.gpkg"), 3)
        self.assertEqual(apres.count("./data.gpkg"), 0)

    def test_les_couches_restent_hors_ligne(self):
        """C'est tout l'objet du changement : QField n'observe que celles-là.

        `QfCloudUtils::isCloudAction()` rend faux pour `no_action` et `remove`,
        et `QfLayerObserver` n'attache alors aucun écouteur : pas de delta, et
        le bouton de synchronisation reste éteint.
        """
        avant = projet(couche("mesurage", "mesurage", "c0913e60")).replace(
            '<Option name="isOfflineEditable" type="QString" value="true"/>',
            '<Option name="isOfflineEditable" type="QString" value="true"/>'
            '<Option name="QFieldSync/cloud_action" type="QString" value="offline"/>',
        )

        apres = paquet.renommer_geopackage(avant, "data.gpkg", "ifa_data.gpkg")

        self.assertIn(
            'name="QFieldSync/cloud_action" type="QString" value="offline"', apres
        )
        self.assertNotIn("no_action", apres)

    def test_un_nom_qui_ne_figure_pas_laisse_le_projet_intact(self):
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))

        self.assertEqual(
            paquet.renommer_geopackage(avant, "autre.gpkg", "ifa_data.gpkg"), avant
        )

    def test_les_correspondances_survivent_au_renommage(self):
        """Le remplissage du GeoPackage lit le projet après renommage."""
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))
        apres = paquet.renommer_geopackage(avant, "data.gpkg", "ifa_data.gpkg")

        correspondances = paquet.correspondances(apres)

        self.assertEqual(len(correspondances), 1)
        self.assertEqual(correspondances[0].table_gpkg, "c0913e60")


class RenommageCouchesTestCase(SimpleTestCase):
    """`renommer_couches()` — le projet suit les tables qui ont changé de nom."""

    def test_la_source_de_la_couche_suit(self):
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))
        apres = paquet.renommer_couches(avant, {"c0913e60": "mesurage"})

        self.assertIn("<datasource>./data.gpkg|layername=mesurage</datasource>", apres)
        self.assertNotIn("layername=c0913e60", apres)

    def test_toutes_les_references_suivent(self):
        """L'arbre des couches et les relations répètent la source."""
        avant = (
            "<datasource>./data.gpkg|layername=c0913e60</datasource>"
            '<layer-tree-layer source="./data.gpkg|layername=c0913e60" name="x"/>'
            '<Option name="Layer" value="./data.gpkg|layername=c0913e60"/>'
        )
        apres = paquet.renommer_couches(avant, {"c0913e60": "mesurage"})

        self.assertEqual(apres.count("layername=mesurage"), 3)
        self.assertEqual(apres.count("c0913e60"), 0)

    def test_une_empreinte_absente_ne_change_rien(self):
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))

        self.assertEqual(paquet.renommer_couches(avant, {"inconnue": "veget"}), avant)

    def test_les_correspondances_suivent(self):
        """Le remplissage lit le projet : il doit y retrouver ses tables."""
        avant = projet(couche("mesurage", "mesurage", "c0913e60"))
        apres = paquet.renommer_couches(avant, {"c0913e60": "mesurage"})

        correspondances = paquet.correspondances(apres)

        self.assertEqual(correspondances[0].table_gpkg, "mesurage")
        self.assertEqual(correspondances[0].table_pg, "mesurage")


class VariablesTestCase(SimpleTestCase):
    """Les variables de projet posées dans le `.qgs` livré.

    Elles alimentent les valeurs par défaut du formulaire QGIS. Le projet de
    saisie étant un autre projet que celui où le technicien a rempli la
    fenêtre, elles doivent voyager avec lui.
    """

    def test_insertion_dans_les_proprietes_existantes(self):
        xml = (
            '<?xml version="1.0"?>\n<qgis version="3.40.8">'
            "<properties><Gui><a>1</a></Gui></properties></qgis>"
        )
        apres = paquet.definir_variables(xml, {"code_region": "02"})

        self.assertIn('<variableNames type="QStringList">', apres)
        self.assertIn("<value>code_region</value>", apres)
        self.assertIn("<value>02</value>", apres)
        # Ce qui était là reste là.
        self.assertIn("<Gui><a>1</a></Gui>", apres)

    def test_remplacement_du_bloc_existant(self):
        xml = (
            '<?xml version="1.0"?>\n<qgis><properties><Variables>'
            '<variableNames type="QStringList"><value>ancienne</value></variableNames>'
            '<variableValues type="QStringList"><value>x</value></variableValues>'
            "</Variables></properties></qgis>"
        )
        apres = paquet.definir_variables(xml, {"code_lce": "12777"})

        self.assertNotIn("ancienne", apres)
        self.assertIn("<value>code_lce</value>", apres)
        self.assertEqual(apres.count("<Variables>"), 1)

    def test_proprietes_auto_fermantes(self):
        xml = '<?xml version="1.0"?>\n<qgis><properties/></qgis>'
        apres = paquet.definir_variables(xml, {"code_region": "02"})

        self.assertNotIn("<properties/>", apres)
        self.assertIn("<properties><Variables>", apres)

    def test_projet_sans_proprietes(self):
        xml = '<?xml version="1.0"?>\n<qgis><projectlayers/></qgis>'
        apres = paquet.definir_variables(xml, {"code_region": "02"})

        self.assertIn("<properties><Variables>", apres)
        self.assertTrue(apres.rstrip().endswith("</qgis>"))

    def test_noms_et_valeurs_dans_le_meme_ordre(self):
        apres = paquet.definir_variables(
            "<qgis><properties/></qgis>",
            {"code_region": "02", "code_lce": "12777"},
        )

        noms = apres.split("</variableNames>")[0]
        valeurs = apres.split("</variableNames>")[1]

        # Tri par nom : « code_lce » avant « code_region », des deux côtés.
        self.assertLess(noms.index("code_lce"), noms.index("code_region"))
        self.assertLess(valeurs.index("12777"), valeurs.index("02"))

    def test_echappement_xml(self):
        apres = paquet.definir_variables(
            "<qgis><properties/></qgis>", {"type_formulaire": "Pêche & relevé <2>"}
        )

        self.assertIn("<value>Pêche &amp; relevé &lt;2&gt;</value>", apres)

    def test_sans_variables_le_projet_ne_bouge_pas(self):
        xml = "<qgis><properties/></qgis>"

        self.assertEqual(paquet.definir_variables(xml, {}), xml)


class ArchiveTestCase(SimpleTestCase):
    def test_lecture_et_reecriture(self):
        xml = projet(couche("mesurage", "mesurage", "c0913e60"))
        lu = paquet.lire(archive(xml))

        self.assertEqual(lu.nom_entree, "projet.qgs")
        self.assertEqual(len(lu.correspondances), 1)

        lu.xml = paquet.passer_en_lecture_seule(lu.xml)
        relu = paquet.lire(lu.octets())

        self.assertIn('readOnly="1"', relu.xml)
        # Les autres entrées de l'archive traversent la réécriture.
        self.assertIn("projet.qgd", relu.archive)

    def test_archive_invalide(self):
        with self.assertRaises(ProjetModeleInvalideError):
            paquet.lire(b"ceci n'est pas un zip")

    def test_archive_sans_projet(self):
        tampon = io.BytesIO()

        with zipfile.ZipFile(tampon, "w") as sortie:
            sortie.writestr("lisez-moi.txt", "rien ici")

        with self.assertRaises(ProjetModeleInvalideError):
            paquet.lire(tampon.getvalue())
