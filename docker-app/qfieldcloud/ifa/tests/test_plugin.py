"""Distribution du plugin QField : contrôle des dépôts et adresses publiques."""

import io
import shutil
import tempfile
import zipfile

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from qfieldcloud.ifa import plugin


def metadonnees(version: str = "0.2.0") -> bytes:
    return f"name=IFA 2.0 — Menu\nversion={version}\nicon=icon.svg\n".encode()


def archive(version: str | None = "0.2.0", main: bool = True) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as zf:
        if main:
            zf.writestr("main.qml", "import QtQuick\nItem {}\n")
        if version is not None:
            zf.writestr("metadata.txt", metadonnees(version))
    return tampon.getvalue()


class MetadonneesTests(SimpleTestCase):
    def test_lit_la_version(self):
        self.assertEqual(plugin.version_de(plugin.lire_metadonnees(metadonnees("1.4.0"))), "1.4.0")

    def test_tolere_le_bom_et_les_espaces(self):
        valeurs = plugin.lire_metadonnees("﻿ version = 0.3 \n".encode())
        self.assertEqual(plugin.version_de(valeurs), "0.3")

    def test_refuse_une_version_illisible(self):
        with self.assertRaises(plugin.PluginInvalideError):
            plugin.version_de(plugin.lire_metadonnees(b"version=beta\n"))

    def test_refuse_une_version_absente(self):
        with self.assertRaises(plugin.PluginInvalideError):
            plugin.version_de(plugin.lire_metadonnees(b"name=x\n"))

    def test_compare_nombre_par_nombre(self):
        self.assertEqual(plugin.comparer_versions("0.10.0", "0.9.0"), 1)
        self.assertEqual(plugin.comparer_versions("0.2", "0.2.0"), 0)
        self.assertEqual(plugin.comparer_versions("0.1.9", "0.2.0"), -1)


class VerificationTests(SimpleTestCase):
    def test_accepte_une_construction_coherente(self):
        self.assertEqual(plugin.verifier(archive("0.2.0"), metadonnees("0.2.0")), "0.2.0")

    def test_accepte_une_archive_sans_metadata_interne(self):
        self.assertEqual(plugin.verifier(archive(None), metadonnees("0.2.0")), "0.2.0")

    def test_refuse_une_archive_sans_main_qml(self):
        with self.assertRaisesMessage(plugin.PluginInvalideError, "main.qml"):
            plugin.verifier(archive(main=False), metadonnees())

    def test_refuse_deux_versions_differentes(self):
        with self.assertRaisesMessage(plugin.PluginInvalideError, "0.1.0"):
            plugin.verifier(archive("0.1.0"), metadonnees("0.2.0"))

    def test_refuse_ce_qui_n_est_pas_un_zip(self):
        with self.assertRaisesMessage(plugin.PluginInvalideError, ".zip"):
            plugin.verifier(b"pas un zip", metadonnees())


class AdressesPubliquesTests(TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="ifa-plugin-")
        self.reglages = override_settings(MEDIA_ROOT=self.dossier)
        self.reglages.enable()

    def tearDown(self):
        self.reglages.disable()
        shutil.rmtree(self.dossier, ignore_errors=True)

    def test_404_tant_que_rien_n_est_publie(self):
        self.assertIsNone(plugin.publie())
        self.assertEqual(self.client.get(reverse("ifa_plugin_metadonnees")).status_code, 404)
        self.assertEqual(self.client.get(reverse("ifa_plugin_archive")).status_code, 404)

    def test_sert_la_version_publiee_sans_authentification(self):
        plugin.publier(archive("0.2.0"), metadonnees("0.2.0"))

        reponse = self.client.get(reverse("ifa_plugin_metadonnees"))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b"version=0.2.0", b"".join(reponse.streaming_content))
        self.assertEqual(reponse["Cache-Control"], "no-store")

        reponse = self.client.get(reverse("ifa_plugin_archive"))
        self.assertEqual(reponse.status_code, 200)
        # QField nomme le dossier du plugin d'après ce nom de fichier.
        self.assertIn(f'filename="{plugin.NOM_ARCHIVE}"', reponse["Content-Disposition"])

        self.assertEqual(plugin.publie().version, "0.2.0")

    def test_l_adresse_porte_le_nom_du_dossier_du_plugin(self):
        self.assertTrue(reverse("ifa_plugin_archive").endswith(f"/plugin/{plugin.NOM_PLUGIN}.zip"))


class PageAdminTests(TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="ifa-plugin-")
        self.reglages = override_settings(MEDIA_ROOT=self.dossier)
        self.reglages.enable()

    def tearDown(self):
        self.reglages.disable()
        shutil.rmtree(self.dossier, ignore_errors=True)

    def connecter_admin(self):
        from qfieldcloud.core.models import Person
        from qfieldcloud.core.tests.utils import setup_subscription_plans

        # Créer un compte crée son abonnement : il faut les formules.
        setup_subscription_plans()
        admin = Person.objects.create_superuser(
            username="admin_plugin", email="admin_plugin@example.com", password="x"
        )
        self.client.force_login(admin)

    def deposer(self, version: str, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(
            reverse("admin:ifa_plugin"),
            {
                "archive": SimpleUploadedFile("ifa_menu.zip", archive(version)),
                "metadonnees": SimpleUploadedFile("metadata.txt", metadonnees(version)),
                **extra,
            },
        )

    def test_reservee_au_personnel(self):
        # Sans session : renvoi vers la connexion, jamais la page.
        reponse = self.client.get(reverse("admin:ifa_plugin"))
        self.assertEqual(reponse.status_code, 302)

    def test_affiche_la_page(self):
        self.connecter_admin()
        reponse = self.client.get(reverse("admin:ifa_plugin"))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "Aucune version publiée")

    def test_publie_une_version(self):
        self.connecter_admin()
        reponse = self.deposer("0.2.0")
        self.assertRedirects(reponse, reverse("admin:ifa_plugin"), fetch_redirect_response=False)
        self.assertEqual(plugin.publie().version, "0.2.0")

    def test_refuse_une_version_qui_n_avance_pas(self):
        self.connecter_admin()
        self.deposer("0.2.0")
        reponse = self.deposer("0.2.0")
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, "pas plus récente")

    def test_forcer_permet_de_revenir_en_arriere(self):
        self.connecter_admin()
        self.deposer("0.3.0")
        self.deposer("0.2.0", forcer="1")
        self.assertEqual(plugin.publie().version, "0.2.0")
