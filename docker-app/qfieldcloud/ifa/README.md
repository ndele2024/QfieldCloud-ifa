# `qfieldcloud.ifa` — points d'accès du programme IFA 2.0

Cette application sert les points d'accès `/api/v1/ifa/` que le plugin QField
« IFA 2.0 — Menu » interroge. Elle lit la **base métier du ministère** — pas les
projets QFieldCloud.

---

## 1. Pourquoi une base à part, et sans ORM

La base `ifa` (schéma `ifa_data`) préexiste à QFieldCloud, d'autres applications
l'alimentent, et QFieldCloud n'en est pas propriétaire. Trois règles en
découlent, appliquées dans `db.py` :

1. **Aucun modèle Django.** Le schéma hérité ne se plie pas aux conventions de
   l'ORM (clés composites, types énumérés, colonnes `shape` en EPSG:32187), et
   surtout : le décrire en modèles inviterait tôt ou tard une migration à s'y
   appliquer. Tout passe par du SQL brut, paramétré.
2. **Transaction en lecture seule par défaut.** `db.curseur()` ouvre un
   `SET TRANSACTION READ ONLY` : même un défaut de programmation ne peut pas
   écrire dans la base de production. Une seule exception,
   `db.curseur_ecriture()`, sert à toutes les écritures du programme : le
   **verrouillage** d'une unité (`verrou.py`, quatre colonnes) et la
   **création** d'une nouvelle unité (`unite.py`), sur `unite_echan` ; la
   **création** d'un projet de sondage et de ses types d'UE
   (`projet_sonda.py`), puis sa **modification** et sa **suppression**
   (`projet_gestion.py`), sur `proje_sonda` et `proje_type_unite_echan` ; la
   **suppression** d'une unité et de toutes ses données de terrain
   (`unite_gestion.py`, §15). Le compte PostgreSQL du serveur a donc besoin de
   ces droits, et d'eux seuls :

   ```sql
   GRANT UPDATE, INSERT ON ifa_data.unite_echan TO ifauser;
   GRANT INSERT, UPDATE, DELETE ON ifa_data.proje_sonda TO ifauser;
   GRANT SELECT, INSERT, UPDATE, DELETE
       ON ifa_data.proje_type_unite_echan TO ifauser;
   -- Supprimer une unité (`unite_gestion.py`) : l'unité et ses données de
   -- terrain, dans les 44 tables qui portent `une_code_ident`.
   DO $$
   DECLARE t record;
   BEGIN
       FOR t IN SELECT c.table_name
                  FROM information_schema.columns c
                  JOIN information_schema.tables x USING (table_schema, table_name)
                 WHERE c.table_schema = 'ifa_data'
                   AND c.column_name = 'une_code_ident'
                   AND x.table_type = 'BASE TABLE'
       LOOP
           EXECUTE format('GRANT DELETE ON ifa_data.%I TO ifauser', t.table_name);
       END LOOP;
   END $$;
   ```
3. **Aucune migration.** `routers.IfaDatabaseRouter` renvoie `False` pour
   `allow_migrate` sur l'alias `ifa`, et `settings.DATABASES["ifa"]["TEST"]`
   vaut `{"MIRROR": "default"}` pour que le lanceur de tests ne crée jamais de
   base `test_ifa` sur le serveur du ministère.

## 2. Configuration

L'alias réutilise les variables `VALIDATION_PG_*`, déjà celles du conteneur
`qgis` pour la validation des livraisons — une seule base, un seul jeu de
paramètres, aucune chance de les voir diverger.

| Variable | Défaut | Rôle |
|---|---|---|
| `VALIDATION_PG_HOST` | *(vide)* | Hôte. **Vide : l'alias n'est pas déclaré** et les points d'accès répondent 503. |
| `VALIDATION_PG_PORT` | `5432` | Port. |
| `VALIDATION_PG_DB` | `ifa` | Base. |
| `VALIDATION_PG_USER` | `postgres` | Utilisateur. Un compte en lecture seule suffit. |
| `VALIDATION_PG_PASS` | *(vide)* | Mot de passe. |
| `VALIDATION_PG_SCHEMA` | `ifa_data` | Schéma métier. |
| `IFA_DB_SRID` | `32187` | SRID des colonnes `shape`. |
| `IFA_DB_STATEMENT_TIMEOUT_MS` | `20000` | Délai maximal d'une requête. |
| `IFA_RECHERCHE_LIMITE_DEFAUT` | `200` | Taille de page par défaut. |
| `IFA_RECHERCHE_LIMITE_MAX` | `1000` | Plafond qu'un client peut demander. |
| `IFA_PROJET_MODELE_ID` | *(vide)* | Projet modèle, par identifiant. Prioritaire sur le couple nom/propriétaire. |
| `IFA_PROJET_MODELE_PROPRIETAIRE` | `ifa_team` | Compte propriétaire du projet modèle. |
| `IFA_PROJET_MODELE_NOM` | `v8_default_config_pkey_ObvervationGenTest` | Nom du projet modèle. |
| `IFA_PROJET_AFFICHAGE_MODIFIABLE` | `affichage_UE_IFA_RW` | Nom du projet d'affichage modifiable. |
| `IFA_PROJET_AFFICHAGE_CONSULTATION` | `affichage_UE_IFA_R` | Nom du projet d'affichage en consultation. |
| `IFA_OUVERTURE_LIGNES_MAX` | `200000` | Garde-fou du remplissage d'une unité. |
| `IFA_PROJET_FORMULAIRE` | `formulaire_UE_IFA` | Nom du projet de saisie d'une nouvelle unité. |
| `IFA_FORMULAIRE_UNITES_MAX` | `2000` | Unités qu'un filtre de création peut embarquer. |
| `IFA_FORMULAIRE_LIGNES_MAX` | `300000` | Garde-fou du remplissage d'une création. |
| `IFA_PROJET_VERSION_TYPE` | *(vide)* | Version de type (`vet_code_ident`) des projets de sondage créés. Vide : la version en production du type « Type Projet » — voir §11. |
| `IFA_ORGANISATION_ADMIN` | valeur de `IFA_PROJET_MODELE_PROPRIETAIRE` (`ifa_team`) | Organisation dont les membres de rôle `admin` administrent les projets de sondage — voir §14. |

En développement local sous Docker Desktop, `VALIDATION_PG_HOST` vaut
`host.docker.internal`. Sur un hôte Linux, cette adresse n'est pas résolue
d'office : passer l'IP de la passerelle Docker, ou ajouter un `extra_hosts` au
service `app`.

## 3. `POST /api/v1/ifa/unites/recherche/`

Recherche les unités d'échantillonnage selon **un ou plusieurs** critères
croisés. Authentification requise (`Authorization: Token …`).

Le verbe est POST bien qu'il s'agisse d'une lecture : le filtre par zone
transporte un polygone en WKT, qui ne tient pas raisonnablement dans une chaîne
de requête.

### Requête

```json
{
  "criteres": [
    { "mode": "region",  "valeur": "02" },
    { "mode": "bassin",  "valeur": "Saguenay" }
  ],
  "limite": 200,
  "decalage": 0
}
```

Les cinq critères disponibles :

| `mode` | Porte sur | Comparaison |
|---|---|---|
| `region` | `proje_sonda.rad_no`, par les mesurages de l'unité | égalité |
| `lce` | `infor_gener.ing_no_plan_eau_offic` et `ing_no_plan_eau` | égalité, numéros dézérotés |
| `bassin` | `infor_gener.ing_nom_bassi` | fragment, casse ignorée (2 caractères minimum) |
| `code` | `unite_echan.une_code_ident` | fragment, casse ignorée (2 caractères minimum) |
| `emprise` | `infor_gener.shape` | `ST_Intersects` avec le polygone, en `wkt` |

Les critères envoyés se **croisent** (`AND`) : une unité doit les satisfaire
tous. Chaque critère ajouté resserre donc la liste — c'est ce qui rend la
recherche par région praticable, puisque seule elle rend plus de douze mille
unités. Un même mode ne peut figurer qu'une fois : deux régions croisées par
`AND` ne rendraient jamais rien, et un résultat vide se lirait comme une panne
plutôt que comme une erreur de saisie.

Les modes `bassin` et `code` sont des **recherches partielles** : la saisie est
cherchée n'importe où dans la colonne, sans tenir compte de la casse. Pour le
bassin, c'est la seule forme praticable — `ing_nom_bassi` est un texte libre du
fonds hérité, où « Saguenay » et « SAGUENAY (BASSIN) » coexistent.

La forme à plat d'avant la recherche multicritère reste acceptée, pour les
plugins déjà installés sur les appareils :

```json
{ "mode": "region", "valeur": "02" }
```

Elle est relue comme un critère unique.

`limite` (défaut 200, plafond 1000) et `decalage` (défaut 0) complètent le
filtre. `bbox` est acceptée mais **ignorée** : la recherche porte sur le
polygone lui-même, filtrer sur la boîte englobante ramènerait des unités hors
de la zone tracée.

### Réponse

```json
{
  "mode": "region",
  "criteres": [
    { "mode": "region", "valeur": "02" },
    { "mode": "bassin", "valeur": "Saguenay" }
  ],
  "filtre": "région 02 et bassin « Saguenay »",
  "total": 12561,
  "limite": 200,
  "decalage": 0,
  "tronque": true,
  "resultats": [
    {
      "une_code_ident": "02-12777-IPE",
      "tue_code_ident": "f0758571-e68e-47f5-a3d5-9c865e3c61c9",
      "tue_nom": "Inventaire sur plan d'eau",
      "une_ind_verro": "N",
      "une_nom_propr_verro": "",
      "une_date_verro": "",
      "une_raiso_verro": "",
      "une_date_creat": "2009-10-21T14:52:56",
      "une_code_utili_creat": "ifa0t2",
      "une_date_maj": "2025-04-03T12:31:07",
      "une_code_utili_maj": "kamdo1",
      "rad_no": "02",
      "ing_no_plan_eau": "12777",
      "ing_nom_plan_eau": "ILETS, LAC DES",
      "ing_nom_bassi": "SAGUENAY",
      "latitude": 48.196709,
      "longitude": -71.233353
    }
  ]
}
```

`mode` reprend le **premier** critère : il n'est là que pour les clients
antérieurs à la recherche multicritère. `criteres` rend la liste appliquée,
sans le WKT d'une éventuelle emprise — il pèse jusqu'à 100 ko, et le réémettre
à chaque page le ferait voyager autant de fois qu'il y a de pages. `filtre` en
donne la version lisible, affichable telle quelle.

Les chaînes absentes sortent vides plutôt que `null` : le plugin affiche les
valeurs telles quelles, et un `null` deviendrait le texte « null » dans une
cellule du tableau. Seules les coordonnées gardent le droit d'être nulles — une
unité sans mesurage localisé n'a pas de position, et un zéro la placerait au
large du golfe de Guinée.

Les horodatages sortent en ISO 8601 **sans fuseau** : les colonnes du schéma
hérité sont des `timestamp without time zone` portant l'heure locale de saisie.
Y coller un `Z` afficherait une heure fausse.

### Erreurs

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Filtre incomplet, mode inconnu, WKT illisible. Le `message` est rédigé pour être affiché tel quel. |
| 401 | `not_authenticated` | Jeton absent, expiré ou révoqué. |
| 503 | `ifa_base_indisponible` | Base non configurée, injoignable, ou requête au-delà du délai. |

QFieldCloud réduit hors mode DEBUG le détail des erreurs à `{code, message}`
(voir `qfieldcloud.core.rest_utils`). Une `ValidationError` de DRF arriverait
donc chez le client sous le seul libellé « API Error » : les erreurs de cette
application passent par `exceptions.py`, qui porte le message utile dans
`message`.

## 4. `POST /api/v1/ifa/unites/<une_code_ident>/ouvrir/`

Prépare, sous le compte de l'utilisateur, un projet QFieldCloud qui ne contient
que l'unité demandée, et déclenche son packaging.

### Requête

```json
{ "mode": "modifiable",   "raison": "Saisie des données de terrain en cours" }
{ "mode": "consultation" }
```

`mode` vaut `modifiable` ou `consultation`. La `raison` est **exigée** en mode
modifiable — c'est ce que liront les autres équipes en tentant d'ouvrir la même
unité — et ignorée en consultation, où rien n'est écrit dans la base métier.

### Ce que fait le serveur

Les points 2 à 7 sont la mécanique commune à toutes les préparations de projet
et vivent dans `projets.py` ; `ouverture.py` ne porte plus que le verrou et le
choix du nom de projet. Le point d'accès de création (§5) emprunte la même
mécanique.

1. **Verrouillage** (mode modifiable seulement). `UPDATE unite_echan` de
   `une_ind_verro`, `une_nom_propr_verro`, `une_date_verro`, `une_raiso_verro`,
   `une_date_maj` et `une_code_utili_maj`. La condition de non-conflit est dans
   l'`UPDATE` lui-même : deux ouvertures simultanées ne peuvent pas réussir
   toutes les deux. Reprendre son propre verrou est permis.
2. **Projet d'affichage.** Retrouvé ou créé chez l'utilisateur, sous un nom fixe
   par mode. Il est refusé s'il porte encore des modifications non appliquées :
   son GeoPackage va être remplacé.
3. **Copie du modèle.** Les fichiers du *dernier paquet* du projet modèle — le
   `.qgz` produit par QFieldSync, dont les couches pointent déjà sur
   `data.gpkg`, et ce GeoPackage. Pas les fichiers source du modèle : ceux-là
   sont branchés sur PostgreSQL.
4. **Remplissage.** Le GeoPackage est vidé, puis rempli des inventaires de
   l'unité lus dans `IFA_DB_SCHEMA`. Les tables sont appariées par nom, les
   colonnes par intersection ; les trois référentiels sans `une_code_ident`
   (`proje_sonda`, `type_unite_echan`, `versi_type_unite_echan`) sont copiés en
   entier, sans quoi les listes déroulantes des formulaires seraient vides.
5. **Lecture seule** (mode consultation). Toutes les couches passent en
   `readOnly="1"`. Le projet appartenant à l'utilisateur, les droits de
   QFieldCloud ne peuvent pas l'en empêcher : c'est l'attribut de couche qui
   verrouille l'édition dans QField.
6. **Renommage.** Les tables reprennent leur **nom métier** (`mesurage`,
   `infor_gener`, …) à la place de l'empreinte que leur donne QFieldSync —
   c'est à cela que l'étape de validation du flux `delta_apply` reconnaît un
   GeoPackage IFE. Puis le fichier lui-même devient `ifa_data.gpkg`, et les
   sources des couches suivent les deux changements.

   Le renommage du fichier n'est pas une coquetterie. Le projet livré sera
   repackagé — par nous, et de toute façon par QField, qui demande un packaging
   à chaque ouverture d'un projet infonuagique. Ses couches portant `cloud_action = offline`, le
   convertisseur hors ligne écrit alors **son propre `data.gpkg`** dans le
   dossier d'export : tant que le nôtre portait ce nom-là, les deux se
   disputaient la même place et le projet sortait avec toutes ses couches
   métier invalides.

   > **Ne pas figer les couches.** Une version précédente réglait la collision
   > en passant `QFieldSync/cloud_action` et `QFieldSync/action` à `no_action`,
   > pour que le repackaging n'ait aucun effet. C'était efficace et faux :
   > `QfCloudUtils::isCloudAction()` rend faux pour `no_action`, et
   > `QfLayerObserver` n'attache alors **aucun écouteur** à la couche. Le
   > technicien saisissait, le GeoPackage se remplissait, et le bouton de
   > synchronisation restait éteint : pas d'observateur, pas de delta. Voir
   > `paquet.renommer_geopackage()`, qui cite le code de QField.

   Le renommage a un effet de bord heureux : le convertisseur ne recopie pas
   notre fichier de vingt mégaoctets, il écrit un GeoPackage neuf ne contenant
   que les lignes sélectionnées. Un paquet mesuré à **0,7 Mo** au lieu de 22.
7. **Packaging.** Un `ProcessProjectfileJob` puis un `PackageJob`. La réponse
   revient avant la fin de ce dernier ; `travail_id` désigne le travail que le
   client doit attendre.

### Réponse

```json
{
  "mode": "modifiable",
  "projet_id": "…", "projet_nom": "affichage_UE_IFA_RW", "projet_proprietaire": "…",
  "travail_id": "…",
  "lignes": 3639,
  "tables": { "mesurage": 132, "denom_espec": 2753 },
  "unite": { "une_code_ident": "…", "une_ind_verro": "O", "une_nom_propr_verro": "…",
             "une_date_verro": "…", "une_raiso_verro": "…" }
}
```

### Erreurs

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Mode inconnu, raison absente en mode modifiable, unité au volume aberrant. |
| 404 | `ifa_unite_introuvable` | Le code d'unité n'existe pas. |
| 409 | `ifa_unite_verrouillee` | L'unité est tenue par quelqu'un d'autre. Le message nomme le détenteur. |
| 409 | `ifa_travaux_non_synchronises` | Le projet d'affichage porte des modifications non appliquées. |
| 503 | `ifa_projet_modele_invalide` | Projet modèle absent, jamais packagé, ou paquet illisible. |

Si la préparation échoue après la pose du verrou, celui-ci est relâché : une
unité ne doit pas rester tenue par une ouverture qui n'a jamais abouti.

### Le format GeoPackage, écrit à la main

`gpkg.py` écrit le fichier avec le `sqlite3` de la bibliothèque standard : un
GeoPackage reste une base SQLite dont la spécification tient en trois tables de
métadonnées, et écrire des lignes n'en demande pas davantage. Deux points
méritent attention.

**L'en-tête des géométries.** Un blob GeoPackage est un WKB précédé de
`GP | version | drapeaux | srs_id`, et facultativement de l'enveloppe. Ici elle
n'est pas facultative : PostGIS la calcule (`ST_XMin` et consorts) et elle part
avec la géométrie.

**Les déclencheurs de l'index R-Tree** appellent `ST_IsEmpty`, `ST_MinX`,
`ST_MaxX`, `ST_MinY` et `ST_MaxY` — des fonctions que GDAL enregistre et que
`sqlite3` ne connaît pas. Sans elles, la moindre insertion échoue sur
`no such function: ST_IsEmpty`. `gpkg._declarer_fonctions()` les déclare ; elles
se contentent de relire l'enveloppe de l'en-tête, sans décoder la géométrie.
L'index reste ainsi entretenu par le fichier lui-même.

**Une opération échappe à la règle et passe par GDAL** : le renommage des
tables (`gpkg.renommer_tables()`). Le faire à la main obligerait à suivre
`gpkg_contents`, `gpkg_geometry_columns`, `gpkg_extensions`, l'index R-Tree et
ses déclencheurs — une liste qui s'allonge à chaque version de la
spécification. `OGRLayer::Rename()` le fait depuis GDAL 3.5, et c'est la seule
raison pour laquelle l'application dépend des liaisons Python de GDAL
(`gdal==3.10.3` dans `requirements.in`, à tenir alignée sur le GDAL du
conteneur).

### Pourquoi les tables reprennent leur nom métier

QFieldSync nomme les tables du GeoPackage par une empreinte de leur source —
soixante-quatre caractères hexadécimaux. C'est sans importance pour QField, qui
suit les couches du projet, mais **l'étape de validation et d'insertion du flux
`delta_apply` reconnaît un GeoPackage IFE à ses noms de tables** : elle cherche
`mesurage` et `infor_gener`, et passe son chemin quand elle ne les trouve pas.
Aucun projet de cette famille n'avait donc jamais été validé.

`projets._tables_metier()` tire la correspondance du projet lui-même — la même
que celle qui sert au remplissage — puis `gpkg.renommer_tables()` la joue et
`paquet.renommer_couches()` fait suivre les sources des couches. Le paquet
livré à QField, lui, repasse par le convertisseur, qui rehache les noms : sans
conséquence, puisque le projet livré et son GeoPackage restent cohérents entre
eux.

Deux empreintes pour une même table métier laisseraient deux tables du même nom,
que le GeoPackage refuse : ce cas est détecté et les tables concernées gardent
leur empreinte, en le disant au journal.

### Ce que cette conception ne fait pas

**Le projet d'affichage n'est pas relié à PostgreSQL.** Ses couches vivent dans
son GeoPackage. Les modifications faites sur le terrain repartent donc en
deltas, que QFieldCloud applique à ce GeoPackage — et c'est l'étape de
validation et d'insertion du flux d'application des deltas qui les reporte
ensuite dans le schéma métier. Ces points d'accès s'arrêtent à la livraison du
projet ; ils ne participent pas au retour.

> Les couches du projet livré doivent donc rester **suivies** par QField :
> `readOnly` à `0` et `cloud_action` différent de `no_action`, faute de quoi
> rien ne repart (voir le point 6 du §4). C'est la raison d'être du renommage du
> GeoPackage.

**Le déverrouillage est à la main du détenteur, et de lui seul** (§6). Une unité
tenue par un technicien parti en congé ne se libère pas depuis le terrain : il
faudra pour cela un point d'accès distinct, réservé à un rôle d'administration.
Une unité créée puis abandonnée est dans le même cas — elle reste tenue par son
auteur, avec la raison « nouvelle Unité d'échantillonnage ».

**`qgis_id` n'est copié que si la table métier le porte.** Sur le fonds de
développement, seules quatre tables de `ifa_data` l'ont — les 33 autres l'ont
dans `ifa_structure`. Le remplissage s'en accommode (l'intersection de colonnes
l'ignore alors), mais la clé qui permettrait de retrouver la ligne d'origine
manque tant que `add_qgis_id.sql` n'a pas été passé sur le schéma qui porte les
données.

## 5. `POST /api/v1/ifa/formulaire/preparer/`

**Crée l'unité d'échantillonnage dans la base métier**, puis prépare sous le
compte de l'utilisateur le projet dans lequel il la saisira :
`formulaire_UE_IFA`.

C'est la contrepartie du point d'accès précédent. Là où « ouvrir » embarque une
unité connue, « préparer » inscrit une unité neuve et embarque le *contexte* que
le technicien a choisi dans le bloc « Données à embarquer » de la fenêtre
« Créer une UE ».

### Requête

```json
{
  "une_code_ident": "02-12777-IPE",
  "type_ue": "Inventaire sur plan d'eau",
  "criteres": [{ "mode": "lce", "valeur": "12777" }],
  "variables": { … }
}
```

`mode` vaut `region`, `lce`, `bassin` ou `emprise` — ce dernier portant `wkt` (et une
`bbox` acceptée puis ignorée, pour la même raison qu'en §3) au lieu de `valeur`.
Le mode `code` de la recherche n'a pas cours : on ne crée pas une unité à partir
d'un fragment de code d'unité existante.

Comme pour la recherche, les critères envoyés se **croisent**, et la forme à
plat (`mode` / `valeur` à la racine) reste acceptée. Le croisement est ici plus
qu'un confort : seule, une grande région dépasse `IFA_FORMULAIRE_UNITES_MAX` et
la demande est refusée ; croisée avec un bassin ou une emprise, la même région
redevient embarquable sur un appareil de terrain.

`une_code_ident` et `type_ue` sont **exigés**, et demandés hors de `variables`
bien qu'ils y figurent aussi : ce qui entre dans la base métier ne doit pas
dépendre d'un dictionnaire libre dont les clés inconnues sont ignorées. Le type
voyage par son **libellé** (`Inventaire sur plan d'eau`), que le serveur résout
en `tue_code_ident` dans `type_unite_echan` — la liste des types est encore
codée en dur dans le plugin, et ce sont les libellés qui y sont écrits.

`variables` porte le contexte de l'unité à créer :

| Variable | Contenu |
|---|---|
| `code_region` | Région administrative choisie. |
| `code_projet` | `pro_no` du projet de sondage. |
| `code_formulaire` | Code du type d'UE. |
| `type_formulaire` | Libellé du type d'UE. |
| `code_lce` | N° du plan d'eau. |
| `une_code_ident` | Identifiant composé de la nouvelle unité. |

Les noms inconnus de cette liste sont **ignorés** (`formulaire.VARIABLES_ATTENDUES`),
et une valeur vide n'est pas posée : la valeur par défaut du formulaire vaut
mieux qu'une chaîne vide, qui masquerait son expression de repli.

### Ce que fait le serveur

1. **Résolution du filtre.** Le prédicat de `filtres.py` — le même qu'en §3 —
   sert une seule fois, à ramener la liste des `une_code_ident` visés. Le
   glisser dans le `WHERE` de chacune des trente-sept tables copiées rejouerait
   sa jointure autant de fois : un quart de seconde par table pour une région.
   Le plafond (`IFA_FORMULAIRE_UNITES_MAX`) est demandé à PostgreSQL en
   `LIMIT max + 1`, pas compté après coup. Le filtre passe **avant** toute
   écriture : une demande trop large est refusée sans qu'une ligne n'ait été
   créée.
2. **Création de l'unité** (`unite.py`). `INSERT` dans `unite_echan` :
   l'identifiant, le type, les six colonnes de traçabilité, et le verrou posé
   d'emblée — `une_ind_verro = 'O'`, l'utilisateur pour propriétaire, et pour
   raison **« nouvelle Unité d'échantillonnage »**. `qgis_id` n'est pas fourni :
   c'est une colonne d'identité (voir `fix_qgis_id_insert.sql`).
3. **La nouvelle unité rejoint les unités à embarquer.** Sans cela elle
   manquerait au projet livré : `unite_echan` est l'une des trente-sept tables
   du GeoPackage, et une unité qui vient de naître n'a encore ni mesurage ni
   `infor_gener` — donc rien qui puisse répondre au filtre du technicien.
4. **Préparation du projet**, par `projets.preparer()` : copie du dernier paquet
   du modèle, remplissage du GeoPackage des inventaires de ces unités,
   renommage des tables et du fichier, packaging. C'est la mécanique
   décrite en §4, points 2 à 4, 6 et 7 — elle est commune aux deux points d'accès.
5. **Variables de projet.** `paquet.definir_variables()` écrit le bloc
   `properties/Variables` du `.qgs` livré. Tant que la saisie se faisait dans le
   projet déjà ouvert, le plugin posait ces variables lui-même ; le projet livré
   étant un *autre* projet, elles doivent voyager avec lui.

Le projet est modifiable : c'est celui où la saisie aura lieu.

### Pourquoi créer l'unité avant de préparer le projet

Pour la même raison que le verrou de §4 est posé avant la préparation : mieux
vaut échouer sans avoir rien packagé que de livrer un projet pour une unité dont
le code était déjà pris. Le code est ainsi **réservé** dès que le technicien
valide — l'identifiant étant composé de la région, du n° de plan d'eau et du
type, deux équipes qui visent le même plan d'eau composeraient le même.

La contrepartie : une préparation qui échoue laisse la ligne derrière elle.
Plutôt que de la supprimer — ce qui demanderait un droit `DELETE` sur la base du
ministère pour un cas de rattrapage —, une seconde tentative sur le même code
**reprend** la création : la ligne existe, elle est tenue par le même
utilisateur, avec la raison de création, donc c'est la sienne. Un code tenu par
quelqu'un d'autre, ou qui porte déjà des inventaires, ressort en revanche en
`ifa_unite_existante`.

> Le compte PostgreSQL du serveur a donc besoin du droit **`INSERT`** sur
> `unite_echan`, en plus de l'`UPDATE` qu'exigeait déjà le verrouillage. Toujours
> sur cette seule table.

### Réponse

```json
{
  "mode": "lce",
  "criteres": [{ "mode": "lce", "valeur": "12777" }],
  "filtre": "plan d'eau n° 12777 — 4 unité(s)",
  "unites": 5,
  "projet_id": "…", "projet_nom": "formulaire_UE_IFA", "projet_proprietaire": "…",
  "travail_id": "…",
  "lignes": 414,
  "tables": { "mesurage": 7, "denom_espec": 10 },
  "unite": { "une_code_ident": "02-12777-IPE", "une_ind_verro": "O",
             "une_nom_propr_verro": "ifauser", "une_date_verro": "…",
             "une_raiso_verro": "nouvelle Unité d'échantillonnage" }
}
```

`unites` compte les unités embarquées, la nouvelle comprise — d'où 5 pour un
filtre qui en désignait 4. `unite` rend l'unité telle que la base la porte après
sa création : elle existe dès le retour de l'appel, même si le packaging, lui,
tourne encore.

### Erreurs

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Mode inconnu, valeur absente, WKT illisible, identifiant absent ou trop long, ou **filtre trop large** — le message invite alors à resserrer la sélection. |
| 400 | `ifa_type_unite_introuvable` | Le libellé du type d'UE n'existe pas dans `type_unite_echan`. |
| 409 | `ifa_unite_existante` | Le code est déjà porté par une unité du fonds, ou tenu par quelqu'un d'autre. |
| 409 | `ifa_travaux_non_synchronises` | Le projet de saisie porte des modifications non appliquées. |
| 503 | `ifa_projet_modele_invalide` | Projet modèle absent, jamais packagé, ou paquet illisible. |

Une sélection **vide** n'est pas une erreur : créer une unité là où il n'y en a
jamais eu est le cas normal d'un nouveau plan d'eau. Le projet est alors livré
avec ses seuls référentiels — de quoi remplir les listes déroulantes du
formulaire, et c'est exactement ce qu'il faut.

### Pourquoi un plafond d'unités

Une région porte plus de douze mille unités et le fonds compte 700 000
mesurages : « toutes les unités de la région » ferait un GeoPackage qu'aucun
appareil de terrain ne téléchargerait. `IFA_FORMULAIRE_UNITES_MAX` (2 000)
arrête la demande avant toute lecture des inventaires, et
`IFA_FORMULAIRE_LIGNES_MAX` (300 000) l'arrête pendant le remplissage si les
unités retenues se révèlent plus lourdes que prévu. Les deux messages nomment
le remède : choisir un n° de plan d'eau, un nom de bassin, ou tracer une
emprise — seul ou croisé avec la région.

---

## 6. `POST /api/v1/ifa/unites/<une_code_ident>/deverrouiller/`

Relâche le verrou d'une unité. La demande n'a pas de corps : le code est porté
par l'URL, et le détenteur est celui qui appelle.

C'est le pendant du verrou posé à l'ouverture (§4) et à la création (§5).
Jusqu'ici aucune URL n'exposait `verrou.lever()`, et une unité restait tenue
jusqu'à ce qu'un administrateur intervienne dans la base.

Le plugin l'appelle **après une synchronisation**, quand le technicien confirme
qu'il rend son unité.

### Réponse

```json
{
  "deverrouille": true,
  "unite": { "une_code_ident": "02-12777-IPE", "une_ind_verro": "N",
             "une_nom_propr_verro": "", "une_date_verro": "",
             "une_raiso_verro": "" }
}
```

Trois cas, et un seul est une erreur :

| Cas | Réponse |
|---|---|
| L'unité est tenue par l'appelant | 200, `deverrouille: true` — le verrou tombe. |
| Elle n'était pas verrouillée | 200, `deverrouille: false`. Le résultat voulu est déjà là ; le dire par une erreur serait absurde. |
| Elle est tenue par quelqu'un d'autre | 409 `ifa_unite_verrouillee`, et le message le nomme. |

Un technicien ne déverrouille pas l'unité d'un collègue depuis le terrain :
celui-ci la croirait encore à lui. Le déverrouillage forcé, s'il devient
nécessaire, demandera un point d'accès distinct et un droit particulier.

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Code d'unité absent ou trop long. |
| 404 | `ifa_unite_introuvable` | Le code n'existe pas dans la base métier. |
| 409 | `ifa_unite_verrouillee` | L'unité est tenue par quelqu'un d'autre. |

---

## 7. Ce que les requêtes savent du schéma

Quatre pièges valent d'être connus avant de toucher à `filtres.py`.

**La région ne se lit pas dans le code d'UE.** Le préfixe (`02-…`) s'en approche
mais ment : plus de 5 000 unités portent un préfixe différent de la région de
leur projet, et le fonds contient des codes qui n'ont pas cette forme du tout
(identifiants hérités en hexadécimal). La source qui fait foi est
`proje_sonda.rad_no`, atteinte par les mesurages de l'unité — elle couvre
141 946 des 142 042 unités.

**Le n° de plan d'eau est stocké dézéroté d'un côté, pas de l'autre.** La base
porte `00256` là où le technicien saisit `256`, et le numéro officiel
(`ing_no_plan_eau_offic`) diffère du numéro saisi (`ing_no_plan_eau`) sur une
partie du fonds. Les deux sont interrogés, `ltrim(…, '0')` des deux côtés.

**Le code d'unité se cherche par fragment, et la casse n'y est pas uniforme.**
Un technicien connaît rarement le code entier : il tape le n° du plan d'eau, le
type, ou le début du code. D'où `ILIKE '%…%'`, qui règle du même coup le cas des
familles historiques en minuscules (réseau ANRO). Les jokers `%` et `_` d'une
saisie sont échappés — sans quoi un `%` tapé par mégarde ramènerait la table
entière.

**Le nom de bassin est un texte libre, sans référentiel fermé.**
`infor_gener.ing_nom_bassi` a été saisi au fil des années sans liste de valeurs :
on y trouve aussi bien « Saguenay » que « SAGUENAY (BASSIN) ». Le critère est
donc un `ILIKE '%…%'`, comme pour le code, et pour la même raison — exiger la
graphie exacte ne servirait qu'à ceux qui connaissent déjà ce que la base
contient. Il suit la même règle d'échappement et la même borne de deux
caractères.

**Les critères se croisent, et l'ordre des paramètres suit celui des
fragments.** `predicats()` parenthèse chaque fragment avant de les joindre par
`AND`, et concatène leurs paramètres dans le même ordre. Un fragment ajouté doit
donc rendre ses paramètres dans l'ordre où ses `%s` apparaissent : les
intervertir chercherait la région « Saguenay ».

## 8. Performances

Relevés sur le fonds de développement (142 000 unités, 700 000 mesurages) :

| Recherche | Sans index supplémentaire |
|---|---|
| par code (fragment) | 45–90 ms |
| par zone | ~240 ms (index GiST existant sur `infor_gener.shape`) |
| par région | ~250 ms |
| par n° de plan d'eau | ~950 ms |
| par nom de bassin (fragment) | ~430 ms |
| région **et** bassin, croisés | ~380 ms |

Croiser deux critères ne les additionne pas. PostgreSQL évalue les `EXISTS`
dans l'ordre qui l'arrange et s'arrête au premier qui échoue : le dénombrement
croisé mesuré ci-dessus (382 ms) reste en deçà de son critère le plus cher pris
seul (430 ms), et la page qui suit coûte moins puisqu'elle a moins de lignes à
enrichir. Croiser pour resserrer une recherche n'a donc pas de prix à payer.

`sql/index_recommandes.sql` ramène la recherche par n° de plan d'eau à quelques
millisecondes. Ce fichier n'est **pas** appliqué automatiquement : la base
appartient au ministère, à un administrateur de la passer. Il documente aussi
l'index trigramme qui accélérerait la recherche par fragment de code — plus
intrusif, puisqu'il demande l'extension `pg_trgm`.

La pagination s'applique sur `unite_echan` seule, avant les jointures
d'enrichissement : celles-ci ne portent ensuite que sur les lignes affichées, et
non sur les milliers de lignes que peut renvoyer un filtre par région.

## 9. Tests

```bash
docker compose exec app python manage.py test qfieldcloud.ifa
```

Les tests ne touchent pas à la base métier — ils portent sur la construction des
requêtes (`filtres.py`), la validation des filtres et des demandes d'ouverture
(`serializers.py`), la normalisation des lignes (`views.py`), l'écriture du
GeoPackage (`gpkg.py`), la lecture du projet packagé (`paquet.py`) et
l'appariement des tables (`inventaires.py`) : tout ce qui peut se casser sans
qu'un appel réseau ne le dise.

---

## 10. Distribution du plugin QField — `plugin.py`, `plugin_views.py`

Le serveur garde **la** version publiée du plugin « IFA 2.0 — Menu » et la sert
aux appareils, qui s'en servent pour se mettre à jour (voir le README du
plugin, §2).

| Adresse | Accès | Rôle |
|---|---|---|
| `GET /api/v1/ifa/plugin/metadata.txt` | **public** | la version publiée (`version=`) |
| `GET /api/v1/ifa/plugin/ifa_menu.zip` | **public** | l'archive, pour `pluginManager.installFromUrl()` |
| `<admin>/ifa/plugin/` | personnel | page de dépôt, lien « Plugin QField IFA » du menu du haut |

**Pourquoi publiques.** `installFromUrl()` télécharge sans le jeton du plugin,
et la vérification de version au démarrage ne doit pas réclamer de mot de
passe. Le plugin ne contient ni secret ni donnée, seulement son code QML.
Les réponses portent `Cache-Control: no-store` : l'adresse ne change pas quand
la version change.

**Pourquoi un nom d'archive fixe.** QField nomme le dossier du plugin installé
d'après le nom du fichier téléchargé (suffixe de version retiré), et ce nom est
l'identifiant du plugin. Servie sous un autre nom, la nouvelle version
s'installerait à côté de l'ancienne. Réglable par `IFA_PLUGIN_NOM` (défaut
`ifa_menu`), qui doit rester le nom du dossier qu'écrit `install.py`.

**Contrôles au dépôt** (`plugin.verifier()`) : archive `.zip` lisible, `main.qml`
à sa racine, `version=` numérique dans `metadata.txt`, et même version dans le
`metadata.txt` intérieur de l'archive s'il existe — sinon les appareils
compareraient une version et en installeraient une autre, puis la
reproposeraient sans fin. La page refuse aussi une version qui n'avance pas,
sauf case « Publier quand même ».

**Stockage.** `MEDIA_ROOT/ifa_plugin/`, sur le volume `media_volume` : les
fichiers survivent aux reconstructions d'image. Chaque fichier est écrit à
côté puis renommé (`os.replace`) — un appareil qui télécharge au même instant
reçoit l'ancien ou le nouveau, jamais un mélange —, l'archive **avant**
`metadata.txt`, pour qu'aucun appareil ne voie la nouvelle version annoncée
avec l'ancienne archive.

Tests : `tests/test_plugin.py`.

---

## 11. `POST /api/v1/ifa/projets-sondage/`

Crée un projet de sondage — une ligne dans `ifa_data.proje_sonda` — et les types
d'UE qu'il prévoit — une ligne par type dans `ifa_data.proje_type_unite_echan`.
C'est la commande « Créer un projet » du plugin (`FenetreCreerProjet.qml`). Rien
d'autre n'est préparé — pas de projet QFieldCloud, pas de packaging : la réponse
revient une fois les lignes écrites. Code : `projet_sonda.py`.

« Projet » désigne ici le **projet de sondage** de la base métier, auquel les
mesurages des unités sont rattachés — pas un projet QFieldCloud (`projets.py`).

### Requête

```json
{
  "pro_no": "09-OG",
  "pro_nom": "Observations générales",
  "pro_an": 2026,
  "rad_no": "09",
  "pro_code_statu": "El",
  "pro_ind_inven_norma": false,
  "pro_descr": "",
  "pro_com": "",
  "types_ue": [
    { "tue_code_ident": "f0758571-e68e-47f5-a3d5-9c865e3c61c9",
      "nb_impla_plani": 12, "nb_remes_plani": 2 },
    { "tue_code_ident": "8657841d-fb87-475a-a1ee-7ad6de8b9c09",
      "nb_impla_plani": 1, "nb_remes_plani": 0 }
  ]
}
```

| Champ | Obligatoire | Règle |
|---|---|---|
| `pro_no` | oui | 20 caractères. **Unique**, à la casse et aux espaces près. |
| `pro_nom` | oui | 100 caractères. |
| `pro_an` | oui | Entier entre 1950 et l'année courante + 5. |
| `rad_no` | oui | Une valeur du type énuméré `region` (`01`…`17`, `DDF`, `DFA`, `DPP`, `SP`). Nullable dans le schéma, mais exigée : c'est elle qui range le projet dans la recherche par région et dans la liste de « Créer une UE ». |
| `pro_code_statu` | non (`El`) | `El` (en élaboration) ou `Pr` (en production). Un projet ne naît pas `Te`. |
| `pro_ind_inven_norma` | non (`false`) | Écrit `O` / `N`. |
| `pro_descr`, `pro_com` | non | 1 000 et 4 000 caractères. Vides : écrits `NULL`. |
| `types_ue` | oui | Liste d'**au moins un** type, 50 au plus, sans doublon. Chaque type est désigné par son `tue_code_ident`, tel que le rend `GET types-ue/` (§12). « Type Projet » est refusé. |
| `types_ue[].nb_impla_plani` | oui | Nombre d'implantations planifiées : entier de 1 à 100 000. |
| `types_ue[].nb_remes_plani` | oui | Nombre de remesurages planifiés : entier de 0 à 100 000. |

### Ce que fixe le serveur

| Colonne | Valeur |
|---|---|
| `pro_code_ident` | Un UUID, comme les 166 projets hérités. |
| `pro_date_statu`, `pro_date_creat`, `pro_date_maj` | `LOCALTIMESTAMP`. |
| `pro_date_premi_mise_produ` | `LOCALTIMESTAMP` si le projet naît `Pr`, sinon `NULL`. |
| `pro_code_utili_creat`, `pro_code_utili_maj` | L'utilisateur QFieldCloud, tronqué à 20 caractères. |
| `vet_code_ident` | `IFA_PROJET_VERSION_TYPE` si renseignée ; sinon la version en production (`vet_code_statu = 'P'`) du type « Type Projet » — aujourd'hui « Modèle général », celle de tous les projets du fonds. S'il y en a plusieurs, celle que portent le plus de projets. |
| `qgis_id` | Identité, remplie par PostgreSQL. |

Et pour chaque type de `proje_type_unite_echan` : `pro_code_ident` (le projet
qui vient d'être écrit), `ptu_date_creat` / `ptu_date_maj` à
`LOCALTIMESTAMP`, `ptu_code_utili_creat` / `ptu_code_utili_maj` à
l'utilisateur.

### Les types d'UE du projet — `proje_type_unite_echan`

Un projet prévoit plusieurs types d'UE, et un type d'UE se retrouve dans
plusieurs projets : c'est une association plusieurs-à-plusieurs, qui n'existait
pas dans le schéma. La table est créée par **`sql/proje_type_unite_echan.sql`**
(idempotent, à appliquer une fois sur chaque base existante) ; sur une base
recréée de zéro, elle vient de `complement_sql_projet.sql`.

| Colonne | Type | Rôle |
|---|---|---|
| `pro_code_ident` | `varchar(40)` | Le projet — clé étrangère vers `proje_sonda`. |
| `tue_code_ident` | `varchar(40)` | Le type — clé étrangère vers `type_unite_echan`. |
| `ptu_nb_impla_plani` | `integer NOT NULL`, ≥ 1 | Nombre d'implantations planifiées. |
| `ptu_nb_remes_plani` | `integer NOT NULL`, ≥ 0 | Nombre de remesurages planifiés. |
| `ptu_date_creat`, `ptu_code_utili_creat`, `ptu_date_maj`, `ptu_code_utili_maj` | | Traçabilité, comme les autres tables. |
| `qgis_id` | `bigint` identité | Clé technique mono-colonne et déclencheur `trg_qgis_id`, comme les tables du projet QField. |

Clé primaire `(pro_code_ident, tue_code_ident)` — un type ne figure qu'une fois
par projet —, et un index sur `tue_code_ident` pour la question inverse
(« quels projets prévoient ce type ? »). Les noms suivent les conventions du
schéma : abréviations à cinq lettres, préfixe de colonne `ptu_`.

Les deux nombres sont **obligatoires** : ajouter un type à un projet, c'est dire
ce qu'on y planifie. Au moins une implantation — un type sans implantation
n'aurait rien à faire dans le projet —, et zéro remesurage ou plus — une
campagne unique n'en prévoit pas. Les contraintes `ck_ptu_nb_impla_plani` et
`ck_ptu_nb_remes_plani` le garantissent dans la base, le sérialiseur le dit en
français avant elle.

Le projet et ses types sont écrits dans **une même transaction**. Les types sont
vérifiés avant le premier `INSERT` : un type inconnu (ou « Type Projet ») annule
la demande entière, et aucun projet ne reste sans les types qu'on a voulu lui
donner.

### Pourquoi l'unicité du numéro est vérifiée ici

La clé primaire est l'UUID : la base n'empêche pas deux projets au même
`pro_no`. Le fonds n'en compte pourtant aucun, et le plugin transporte ce numéro
comme `code_projet` d'une unité créée — deux projets au même numéro rendraient
ce rattachement ambigu.

La vérification et l'`INSERT` se font dans la même transaction, sous
`pg_advisory_xact_lock(hashtext('ifa.proje_sonda.pro_no'))` : deux créations
simultanées du même numéro ne passent pas toutes les deux. Le verrou tombe avec
la transaction et ne demande aucun droit particulier.

Les noms, eux, ne sont pas uniques dans le fonds (« Aménagement et
compensation de l'habitat du poisson » y figure trois fois) : ils ne sont pas
contrôlés.

### Réponse — 201

La ligne écrite, sans aucun `null` :

```json
{
  "pro_code_ident": "015f3d0b-fdef-4f18-ac40-5d5e31ca3cd2",
  "pro_no": "09-OG", "pro_nom": "Observations générales", "pro_an": 2026,
  "rad_no": "09", "pro_descr": "", "pro_com": "",
  "pro_code_statu": "El", "pro_date_statu": "2026-10-05T09:30:00",
  "pro_date_premi_mise_produ": "", "pro_ind_inven_norma": "N",
  "pro_date_creat": "2026-10-05T09:30:00", "pro_code_utili_creat": "ifauser",
  "types_ue": [
    { "tue_code_ident": "f0758571-e68e-47f5-a3d5-9c865e3c61c9",
      "tue_nom": "Inventaire sur plan d'eau",
      "nb_impla_plani": 12, "nb_remes_plani": 2 },
    { "tue_code_ident": "8657841d-fb87-475a-a1ee-7ad6de8b9c09",
      "tue_nom": "ADNe", "nb_impla_plani": 1, "nb_remes_plani": 0 }
  ]
}
```

### Erreurs

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Champ absent, trop long, année hors bornes, région ou statut inconnu, aucun type d'UE, type en double, nombre planifié absent, sous son minimum ou au-delà de 100 000. Le message nomme le champ. |
| 400 | `ifa_type_unite_introuvable` | Un type d'UE n'existe pas dans `type_unite_echan`, ou c'est « Type Projet ». Rien n'est écrit. |
| 409 | `ifa_projet_existant` | Le n° est déjà pris ; le message nomme le projet qui le porte et son année. |
| 503 | `ifa_version_projet_introuvable` | Aucune version en production du type « Type Projet » : défaut du référentiel, à corriger par `IFA_PROJET_VERSION_TYPE`. |
| 503 | `ifa_base_indisponible` | Base injoignable, droit `INSERT` manquant sur `proje_sonda` ou `proje_type_unite_echan`, ou table `proje_type_unite_echan` absente (script non appliqué). |

---

## 12. `GET /api/v1/ifa/types-ue/`

Les types d'UE qu'un projet peut planifier : la liste du dialogue « Ajouter un
type d'UE » de « Créer un projet ». Lecture seule.

```json
{
  "types": [
    { "tue_code_ident": "8657841d-fb87-475a-a1ee-7ad6de8b9c09",
      "tue_nom": "ADNe", "tue_descr": "" },
    { "tue_code_ident": "f0758571-e68e-47f5-a3d5-9c865e3c61c9",
      "tue_nom": "Inventaire sur plan d'eau", "tue_descr": "" }
  ]
}
```

Lus dans `type_unite_echan`, triés par libellé, **sans « Type Projet »** (le
type qui qualifie les projets eux-mêmes, voir `vet_code_ident` au §11) et sans
les types au libellé vide. 19 types sur le fonds de développement.

Le plugin ne se sert pas ici de sa liste codée en dur (`Referentiels.typesUe`) :
elle compte 13 types et en omet 6 — ADNe, Enregistrement saumon atlantique,
Importation hors Québec de spécimens, Recrutement MOSA Gaspésie, Réseau
d'enregistrements des émetteurs, Réseau de suivi de la température.

---

## 13. `GET /api/v1/ifa/projets-sondage/types-ue/?pro_no=…`

Les types d'UE que prévoit un projet, lus dans `proje_type_unite_echan`. « Créer
une UE » y restreint sa liste de types quand un projet est choisi. Lecture
seule. Code : `projet_sonda.types_du_projet()`.

Le projet se désigne par son **n°** (`pro_no`), parce que c'est ce que porte la
liste de projets du plugin, lue dans la couche `proje_sonda`. Il voyage en
paramètre de requête et non dans le chemin : saisi librement, il peut contenir
des espaces, voire une barre oblique. La comparaison ignore la casse et les
espaces de bordure, comme l'unicité vérifiée à la création (§11).

```json
{
  "pro_code_ident": "ac9d1161-a64f-4582-93c1-60d7a605e147",
  "pro_no": "09-OG",
  "pro_nom": "Observations générales",
  "types": [
    { "tue_code_ident": "8657841d-fb87-475a-a1ee-7ad6de8b9c09",
      "tue_nom": "ADNe", "nb_impla_plani": 1, "nb_remes_plani": 0 },
    { "tue_code_ident": "a2c0ae50-ca5d-428f-b516-155a1b69a86a",
      "tue_nom": "Pêche sportive", "nb_impla_plani": 12, "nb_remes_plani": 3 }
  ]
}
```

`types` est triée par libellé, et **vide** quand le projet ne prévoit aucun
type — c'est le cas de tous les projets antérieurs à la table. Ce n'est pas une
erreur : le plugin propose alors tous les types.

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | `pro_no` absent, vide ou de plus de 20 caractères. |
| 404 | `ifa_projet_introuvable` | Aucun projet ne porte ce n°. |
| 503 | `ifa_base_indisponible` | Base injoignable, ou table `proje_type_unite_echan` absente. |

Le plugin traite ces trois erreurs de la même façon : il propose tous les types,
en disant pourquoi. La saisie d'une unité n'en est jamais bloquée.

---

## 14. Afficher, modifier, supprimer un projet de sondage

La fenêtre « Modifier / Afficher / Supprimer un projet » du plugin. Code :
`projet_gestion.py` ; la création reste dans `projet_sonda.py` (§11), dont les
contrôles sont repris (n° unique, types existants).

| Verbe | Chemin | Rôle |
|---|---|---|
| `GET` | `projets-sondage/` | Tous les projets, avec leur nombre d'UE et les droits de l'appelant sur chacun. |
| `GET` | `projets-sondage/<pro_code_ident>/` | Un projet, ses types d'UE, son nombre d'UE, les droits. |
| `POST` | `projets-sondage/<pro_code_ident>/modifier/` | Modifie les champs envoyés. |
| `POST` | `projets-sondage/<pro_code_ident>/supprimer/` | Supprime le projet et ses types — mot de passe exigé. |

Le projet se désigne par son identifiant (UUID), qui tient dans un segment
d'URL. `projets-sondage/types-ue/` (§13) est déclaré avant
`projets-sondage/<pro_code_ident>/`, qui l'avalerait sinon. Modifier et
supprimer passent par POST, comme les autres actions de l'application ; la
suppression porte un corps (le mot de passe), que certains intermédiaires
retirent d'un DELETE.

### Qui est administrateur

Un **superutilisateur** QFieldCloud, ou un **membre de rôle `admin`** de
l'organisation `IFA_ORGANISATION_ADMIN` (`ifa_team` par défaut) — y compris son
propriétaire. `is_staff` ne suffit pas : ce drapeau ouvre la page
d'administration Django (pour publier le plugin, par exemple), il ne dit rien du
métier. Sur l'instance de développement, `ifauser` est `is_staff` mais
seulement `member` d'`ifa_team` : il n'est **pas** administrateur des projets.

Pour nommer un administrateur : admin QFieldCloud → *Organization members* →
le membre d'`ifa_team` → rôle `admin`.

### Les droits — `droits()`

| | Utilisateur standard | Administrateur |
|---|---|---|
| **Modifier** un projet en production (`Pr`) | ✗ — affichage seul | ✓ |
| **Modifier** un projet hors production (`El`, `Te`) | ✓ | ✓ |
| … s'il est **utilisé par une UE** | nom, description et nombres planifiés | nom, description et nombres planifiés |
| **Supprimer** un projet qu'il a créé, hors production | ✓ | ✓ |
| **Supprimer** un projet en production, ou celui d'un autre | ✗ | ✓ |
| **Supprimer** un projet utilisé par une UE | ✗ | ✗ |

- **« Utilisé par une UE »** : au moins un mesurage le référence
  (`mesurage.pro_code_ident`). C'est le seul lien entre une unité et un projet.
  Sur le fonds de développement, 157 projets sur 166 le sont.
- **Le créateur** est `pro_code_utili_creat`, comparé au nom de l'utilisateur
  QFieldCloud tronqué à 20 caractères, sans tenir compte de la casse. Pour le
  fonds hérité, c'est le code de l'agent dans l'ancienne application
  (`kamdo1`, `robma8`…) : ces projets ne sont supprimables par un utilisateur
  standard que si son nom QFieldCloud est ce même code.
- **Projet utilisé : les types d'UE sont figés, pas leurs nombres.** On ne
  peut ni ajouter ni retirer un type — des mesurages en dépendent —, mais les
  nombres d'implantations et de remesurages planifiés restent modifiables.
  Les droits l'expriment par le pseudo-champ `types_ue_nombres`
  (`NOMBRES_PLANIFIES`) : la demande envoie toujours la liste complète dans
  `types_ue`, et `changements_effectifs()` la classe en `types_ue_nombres` si
  elle garde exactement les mêmes types, en `types_ue` sinon.
- **Aucun projet utilisé n'est supprimé, administrateur compris.**
  `mesurage.pro_code_ident` n'a pas de clé étrangère vers `proje_sonda` : la
  base laisserait faire, et les mesurages resteraient rattachés à un projet
  disparu, sans erreur ni trace. C'est une protection des données plutôt
  qu'une question de droits ; pour la lever, il faudrait d'abord décider du
  sort des mesurages.

Les droits sont rendus avec chaque projet, et la fenêtre s'en sert pour se
présenter. Ils sont **recalculés dans la transaction qui écrit** — après un
`SELECT … FOR UPDATE` sur le projet —, si bien qu'un projet passé en production
ou utilisé entre-temps est refusé au moment d'écrire.

```json
"droits": {
  "admin": false, "createur": true, "utilise": false, "nb_unites": 0,
  "modifiable": true,
  "champs_modifiables": ["pro_no", "pro_nom", "pro_an", "rad_no",
                         "pro_code_statu", "pro_ind_inven_norma",
                         "types_ue", "pro_descr", "pro_com",
                         "types_ue_nombres"],
  "raison_modification": "",
  "supprimable": true, "raison_suppression": ""
}
```

Les raisons sont rédigées pour être affichées telles quelles (« Ce projet est
en production : seul un administrateur peut le modifier. »).

### Modifier

```json
{ "pro_date_maj": "2026-10-07T10:12:03", "pro_nom": "Nouveau nom",
  "types_ue": [ { "tue_code_ident": "…", "nb_impla_plani": 5, "nb_remes_plani": 1 } ] }
```

- **Seuls les champs envoyés** sont considérés, avec les règles de la création
  (§11) — le statut accepte en plus `Te`. Un champ envoyé mais identique à la
  base n'est pas un changement et ne demande aucun droit.
- **`pro_date_maj` est exigé** : c'est la date lue à l'ouverture. Si elle a
  changé, quelqu'un a modifié le projet entre-temps : **409**
  `ifa_projet_modifie`, qui nomme l'auteur, plutôt que d'écraser son travail.
- **Le statut** : `pro_date_statu` passe à maintenant ; un passage en production
  date `pro_date_premi_mise_produ`, une fois pour toutes.
- **Les types d'UE** : la liste envoyée remplace l'ancienne. Les types retirés
  sont supprimés, les nouveaux ajoutés, ceux dont les nombres changent mis à
  jour ; les autres ne sont pas touchés.
- `pro_date_maj` et `pro_code_utili_maj` sont mis à jour. La réponse est le
  projet relu (comme `GET`), droits compris.

### Supprimer

```json
{ "mot_de_passe": "…" }
```

1. Le **mot de passe** est vérifié en premier (`check_password`), avant toute
   lecture de la base. Faux : **403** `ifa_mot_de_passe_invalide` — pas 401,
   sur lequel `SessionCloud` redemanderait un jeton et rejouerait la requête.
   L'échec est journalisé (`WARNING`), jamais le mot de passe.
2. Les droits sont recalculés sous `FOR UPDATE`.
3. Les types du projet (`proje_type_unite_echan`) puis le projet sont
   supprimés, dans la même transaction. La suppression est journalisée
   (`WARNING`) avec son auteur.

### Erreurs

| Statut | `code` | Cas |
|---|---|---|
| 400 | `ifa_filtre_invalide` | Identifiant absent ou trop long, champ invalide, `pro_date_maj` absente, mot de passe vide. |
| 400 | `ifa_type_unite_introuvable` | Un type d'UE inconnu. |
| 403 | `ifa_modification_refusee` | Projet en production (standard), ou champ hors de ceux permis pour un projet utilisé — le message nomme les champs refusés. |
| 403 | `ifa_suppression_refusee` | Pas le créateur, projet en production (standard), ou projet utilisé. |
| 403 | `ifa_mot_de_passe_invalide` | Mot de passe incorrect. |
| 404 | `ifa_projet_introuvable` | Le projet n'existe plus. |
| 409 | `ifa_projet_modifie` | Modifié par quelqu'un d'autre depuis l'ouverture. |
| 409 | `ifa_projet_existant` | Le nouveau n° est déjà porté par un autre projet. |
| 503 | `ifa_base_indisponible` | Base injoignable, ou droit `UPDATE`/`DELETE` manquant. |

### Performances

Le nombre d'UE d'un projet se compte dans `mesurage`, qui n'a pas d'index sur
`pro_code_ident` : ~350 ms par projet, et autant pour **toute la liste**, que
`lister()` compte en une seule requête (`SELECT DISTINCT pro_code_ident,
une_code_ident`). `sql/index_recommandes.sql` propose
`idx_mesurage_pro_code_ident`, qui répond depuis l'index seul.

### Ce qui n'est pas fait

- Pas de limite au nombre d'essais de mot de passe : la suppression exige déjà
  une session authentifiée. Si le risque le justifie, la limitation de débit de
  DRF (`throttle_classes`) se pose sur `SupprimerProjetView`.
- Pas d'historique des modifications au-delà de `pro_date_maj` /
  `pro_code_utili_maj` et du journal du serveur.

---

## 15. Supprimer une unité d'échantillonnage — `unite_gestion.py`

« Consulter une UE » propose de supprimer une unité. Deux points d'accès :

| | |
|---|---|
| `GET /api/v1/ifa/unites/<une_code_ident>/` | l'unité, ce que sa suppression emporterait, et les droits de l'appelant |
| `POST /api/v1/ifa/unites/<une_code_ident>/supprimer/` | `{"mot_de_passe": "…"}` — la suppression |

POST et non DELETE, comme pour un projet : la demande porte le mot de passe.

### Les droits — `droits()`

La même logique que les projets (§14) :

| | Utilisateur standard | Administrateur |
|---|---|---|
| Unité qu'il a créée, données **non diffusées** | ✓ | ✓ |
| Unité qu'il a créée, données **diffusées** | ✗ | ✓ |
| Unité créée par un autre | ✗ | ✓ |
| Unité **verrouillée par quelqu'un d'autre** | ✗ | ✗ |

- **Créateur** : `une_code_utili_creat`, comparé comme pour un projet
  (`projet_gestion.meme_auteur` : nom tronqué à 20 caractères, casse ignorée).
- **Diffusée** : au moins un mesurage porte `une_etat_diffu = 'D'` — le
  pendant d'un projet en production. C'est le cas de tout le fonds hérité
  (699 885 mesurages sur 700 369) : en pratique, un utilisateur standard ne
  supprime que les unités qu'il a créées dans « Créer une UE » et qui n'ont
  pas encore été diffusées.
- **Verrouillée par un autre** : refusé à tous, administrateur compris — une
  équipe travaille dessus, son projet QField ne pourrait plus être
  synchronisé. Le message nomme le détenteur. Une unité verrouillée **par
  l'utilisateur lui-même** reste supprimable : c'est le cas d'une unité créée
  par erreur, qui naît verrouillée à son nom (§5).
- **Administrateur** : le même que pour les projets (§14).

### Ce qui est supprimé

Une unité ne vit pas seule : ses mesurages et toutes les données qui en
dépendent (pêches, captures, anomalies, habitat, physico-chimie…) portent son
code dans **43 tables**, plus `unite_echan`. Toutes partent, dans **une seule
transaction** : rien ne reste orphelin, et rien ne part si une table refuse.

Les clés étrangères de `ifa_data` sont en `NO ACTION` : un parent ne part
qu'après ses enfants. `NIVEAUX` range les tables des feuilles vers la racine
(`anoma_speci` → `detail_speci` → `pose_levee_filet` → `peche_exper` →
`mesurage`, et ainsi de suite) ; un test confronte cet ordre au graphe des clés
relevé sur la base. Chaque table porte `une_code_ident` en tête de sa clé
primaire : chaque `DELETE` passe par l'index (la plus grosse unité compte 132
mesurages).

**Garde-fou** : une table de `ifa_data` qui porte `une_code_ident` sans figurer
dans `NIVEAUX` — ajoutée au schéma depuis — n'est jamais vidée à l'aveugle. Si
elle contient des lignes de l'unité, la suppression est refusée
(`TablesInconnuesError`, 503) et le journal la nomme : il faut alors l'ajouter
à `NIVEAUX`, au bon niveau.

La suppression est journalisée en `WARNING`, avec le nombre de lignes par
table.

### Réponses

```json
GET → {
  "une_code_ident": "02-12777-IPE", "tue_nom": "Inventaire sur plan d'eau",
  "une_ind_verro": "N", "une_nom_propr_verro": "",
  "une_date_creat": "…", "une_code_utili_creat": "kamdo1", "…": "…",
  "nb_mesurages": 3, "nb_enregistrements": 8402,
  "tables": { "mesurage": 3, "peche_exper": 3, "detail_speci": 3649, "…": 0 },
  "droits": { "admin": false, "createur": true, "diffusee": true,
              "verrouillee_par_un_autre": false, "supprimable": false,
              "raison_suppression": "Les données de cette unité sont diffusées : …" }
}

POST → { "supprime": true, "une_code_ident": "02-12777-IPE",
         "nb_mesurages": 3, "nb_enregistrements": 8402, "tables": { … } }
```

### Erreurs

| Statut | Code | Quand |
|---|---|---|
| 400 | `ifa_filtre_invalide` | code absent ou trop long, mot de passe manquant |
| 403 | `ifa_mot_de_passe_invalide` | mot de passe faux — vérifié **avant** toute lecture |
| 403 | `ifa_suppression_refusee` | droits insuffisants ; le message dit pourquoi |
| 404 | `ifa_unite_introuvable` | l'unité n'existe pas (ou plus) |
| 503 | `ifa_tables_inconnues` | données dans une table que la suppression ne connaît pas |

### Droits SQL

La suppression demande `DELETE` sur les 44 tables qui portent `une_code_ident`
— voir le bloc `GRANT` du §1, qui les énumère depuis le catalogue.
