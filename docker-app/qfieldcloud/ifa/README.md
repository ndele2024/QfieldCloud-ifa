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
   `db.curseur_ecriture()`, sert aux deux écritures du programme, toutes deux
   sur `unite_echan` : le **verrouillage** d'une unité (`verrou.py`, quatre
   colonnes) et la **création** d'une nouvelle unité (`unite.py`). Le compte
   PostgreSQL du serveur a donc besoin des droits `UPDATE` et `INSERT` sur cette
   table, et d'eux seuls.
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
