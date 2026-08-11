# Système de validation IFE — Documentation technique

> Projet IFA 2.0 · DGEA  
> Dernière mise à jour : 2026-07-27

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture](#2-architecture)
3. [Composants serveur](#3-composants-serveur)
   - 3.1 [validate_ifa.py — point d'entrée](#31-validate_ifapy--point-dentrée)
   - 3.2 [validation_ifa/ — moteur de validation](#32-validation_ifa--moteur-de-validation)
   - 3.3 [Fichiers produits](#33-fichiers-produits)
4. [Configuration](#4-configuration)
   - 4.1 [Variables d'environnement](#41-variables-denvironnement)
   - 4.2 [docker-compose](#42-docker-compose)
5. [Plugin QField](#5-plugin-qfield)
   - 5.1 [Installation](#51-installation)
   - 5.2 [Fonctionnement — détection par timestamp de mise à jour](#52-fonctionnement--détection-par-timestamp-de-mise-à-jour)
   - 5.3 [Authentification (URL + token codés en dur)](#53-authentification-url--token-codés-en-dur)
   - 5.4 [Génération du token](#54-génération-du-token)
   - 5.5 [Interface](#55-interface)
   - 5.6 [Limites connues](#56-limites-connues)
6. [Workflow complet](#6-workflow-complet)
7. [Déploiement](#7-déploiement)
8. [Dépannage](#8-dépannage)

---

## 1. Vue d'ensemble

Le système de validation IFE (Inventaire Forestier Étendu) s'intègre dans le workflow
QFieldCloud **apply_deltas**. Après qu'un technicien de terrain pousse ses données depuis
QField, le serveur :

1. Valide les données du GeoPackage IPE contre les règles métier et le schéma PostgreSQL
2. Insère les données en base si elles sont valides
3. Écrit un rapport lisible dans le GPKG et un JSON pour le plugin QField
4. Ajoute automatiquement la couche `rapport_validation` au projet QGS
5. Upload le projet mis à jour → le technicien voit son rapport après synchronisation

```
Technicien (QField)          QFieldCloud (Docker)           PostgreSQL (IFA)
      │                              │                              │
      │──── push deltas ────────────►│                              │
      │                              │  apply_deltas job            │
      │                              │  ├─ start_qgis               │
      │                              │  ├─ apply_deltas             │
      │                              │  ├─ validate_ife_data ───────►│ (validation + insertion)
      │                              │  │   ├─ écrire rapport_validation dans GPKG
      │                              │  │   ├─ injecter couche dans .qgs
      │                              │  │   └─ écrire rapport_ife.json
      │                              │  └─ upload_project           │
      │                              │                              │
      │◄─ plugin: GET packages/latest (polling data_last_updated_at) │
      │   puis GET .../files/rapport_ife.json                 │     │
      │   → bouton IFE vert/rouge    │                              │
```

> **Note (2026-07-27).** Le plugin ne déclenche plus de synchronisation QField : il lit
> `rapport_ife.json` **directement depuis l'API de packaging** (voir §5.2). La couche
> `rapport_validation`, elle, reste visible après une synchronisation descendante QField.

---

## 2. Architecture

```
F:\stages\
├── QfieldCloud\QFieldCloud\
│   ├── docker-qgis\qfc_worker\
│   │   ├── validate_ifa.py              ← point d'entrée de la validation
│   │   └── validation_ifa\              ← moteur de validation (package Python)
│   │       ├── config.py               ← lecture des variables VALIDATION_PG_*
│   │       └── core\
│   │           ├── engine.py           ← orchestration des règles
│   │           ├── models.py           ← ValidationReport, ValidationIssue, Severity
│   │           ├── gpkg_reader.py      ← lecture du GeoPackage
│   │           ├── db_schema.py        ← lecture des contraintes PostgreSQL
│   │           └── rules\              ← règles métier (.py par domaine)
│   ├── docker-app\worker_wrapper\
│   │   └── wrapper.py                  ← passe VALIDATION_PG_* au conteneur QGIS
│   ├── docker-compose.override.local.yml
│   ├── .env                            ← valeurs des variables VALIDATION_PG_*
│   ├── mint_token.sh                   ← génération de token QFieldCloud (Git Bash)
│   └── mint_token.ps1                  ← génération de token QFieldCloud (PowerShell)
│
└── formulaires\
    ├── rapport_ife_plugin\
    │   └── plugin.qml                  ← plugin QField (polling API data_last_updated_at + affichage)
    └── package_plugin.py               ← script de packaging du plugin
```

---

## 3. Composants serveur

### 3.1 `validate_ifa.py` — point d'entrée

**Emplacement :** `docker-qgis/qfc_worker/validate_ifa.py`

Appelé comme étape du workflow apply_deltas. Fonction principale : `validate_ife_data(project_dir)`.

#### Flux d'exécution

```
validate_ife_data(project_dir)
  │
  ├─ _find_ipe_gpkg(project_dir)
  │     Cherche le GPKG contenant les tables IPE signature
  │     (mesurage + infor_gener). Retourne None si absent → skip.
  │
  ├─ Connexion PostgreSQL via config.get_dsn()
  │
  ├─ engine.run(gpkg_path, conn, pg_schema, apply=True)
  │     → ValidationReport
  │
  ├─ _write_rapport_to_gpkg(gpkg_path, result)
  │     Crée/remplace la table rapport_validation dans le GPKG
  │
  ├─ _add_rapport_layer_to_qgs(project_dir, gpkg_path)
  │     Injecte la couche dans le .qgs (XML) si absente
  │
  └─ _write_rapport_json(project_dir, gpkg_path, result)
        Écrit rapport_ife.json pour le plugin QField
```

#### Détection du GPKG IPE (`_find_ipe_gpkg`)

QFieldCloud suffixe les noms de tables avec un UUID lors du packaging, ex. :
`mesurage_4f552916_c02c_43c8_bdac_48c7a363bb95`

Ces tables apparaissent dans `sqlite_master` mais **pas** dans `gpkg_contents`.  
La détection interroge donc `sqlite_master` et accepte les noms exacts ET préfixés :

```python
_IPE_SIGNATURE_TABLES = frozenset({"mesurage", "infor_gener"})

# Exemple de correspondance acceptée :
# "mesurage"                                  → exact
# "mesurage_4f552916_c02c_43c8_bdac_48c7a363bb95" → préfixé par "mesurage_"
matched = {
    sig
    for sig in _IPE_SIGNATURE_TABLES
    if any(t == sig or t.startswith(sig + "_") for t in all_tables)
}
```

> **Pourquoi ne pas utiliser `gpkg_contents` ?**  
> OGR/QGIS utilise `gpkg_contents` pour lister les couches, mais QFieldCloud peut
> enregistrer les tables avec leur nom UUID sans mettre à jour `gpkg_contents`.
> `sqlite_master` est la seule source fiable.

#### Injection de la couche dans le QGS (`_add_rapport_layer_to_qgs`)

Manipulation directe du XML (sans PyQGIS, qui n'est pas disponible à cette étape) :

- Ajoute un `<maplayer>` dans `<projectlayers>`
- Ajoute un `<layer-tree-layer>` après `</custom-order>` (QGIS ≥ 3.x)
- N'écrit rien si `layername=rapport_validation` est déjà présent

Le QGS modifié est uploadé par `upload_project` → la couche est visible lors de
la synchronisation suivante.

### 3.2 `validation_ifa/` — moteur de validation

Package Python ajouté à `sys.path` dynamiquement par `validate_ifa.py`.

| Module | Rôle |
|--------|------|
| `config.py` | Lit `VALIDATION_PG_*` depuis l'environnement |
| `core/engine.py` | Orchestre les règles : lit le GPKG, interroge le schéma PostgreSQL, applique les règles, construit le `ValidationReport` |
| `core/models.py` | `ValidationReport`, `ValidationIssue`, `Severity` (ERROR / WARNING) |
| `core/gpkg_reader.py` | Lecture des couches du GeoPackage |
| `core/db_schema.py` | Introspection PostgreSQL : PK, NOT NULL, plages numériques, ENUMs |
| `core/rules/` | Règles métier (.py par domaine) |

#### Modèles clés (`core/models.py`)

```python
class Severity(str, Enum):
    ERROR   = "error"    # bloque l'insertion
    WARNING = "warning"  # signalé mais n'empêche pas l'insertion

@dataclass
class ValidationIssue:
    layer:     str         # couche concernée
    severity:  Severity
    code:      str         # identifiant stable de la règle
    message:   str         # message utilisateur (français)
    fields:    list[str]   # champs concernés
    record:    dict        # clé métier de l'enregistrement
    rule_name: str

@dataclass
class ValidationReport:
    source:           str
    layers_processed: list[str]
    record_counts:    dict[str, int]
    issues:           list[ValidationIssue]
    inserted:         bool

    @property errors(self)   → list[ValidationIssue]   # issues ERROR
    @property warnings(self) → list[ValidationIssue]   # issues WARNING
    @property is_valid(self) → bool                    # len(errors) == 0

    def to_dict(self) → dict   # JSON-sérialisable
```

> **Important :** `ValidationReport` n'a **pas** d'attributs `error_count` ni `warning_count`.  
> Utiliser `len(result.errors)` et `len(result.warnings)`.

### 3.3 Fichiers produits

#### `rapport_validation` (table GPKG)

Créée/remplacée dans le GPKG IPE à chaque exécution :

| Colonne | Type | Contenu |
|---------|------|---------|
| `id` | INTEGER PK | auto |
| `statut` | TEXT | VALIDE / INVALIDE / ERREUR_SYSTEME |
| `couche` | TEXT | nom de la couche concernée |
| `code_regle` | TEXT | code de la règle (RESUME pour la ligne de synthèse) |
| `severite` | TEXT | error / warning / info |
| `message` | TEXT | message lisible |
| `champs` | TEXT | champs concernés (séparés par virgule) |
| `enregistrement` | TEXT | clé métier JSON de l'enregistrement |
| `genere_le` | TEXT | horodatage UTC ISO 8601 |

La table est enregistrée dans `gpkg_contents` (`data_type = 'attributes'`) pour
être reconnue par QGIS Desktop et QField.

#### `rapport_ife.json`

Écrit dans le sous-dossier `plugins/` du projet (inclus dans le package via `attachment_dirs`) :

```json
{
  "source": "/tmp/.../data.gpkg",
  "layers_processed": ["mesurage", "infor_gener"],
  "record_counts": { "mesurage": 42, "infor_gener": 42 },
  "is_valid": false,
  "inserted": false,
  "error_count": 2,
  "warning_count": 1,
  "issues": [
    {
      "layer": "mesurage",
      "severity": "error",
      "code": "required_field",
      "message": "Champ obligatoire manquant",
      "fields": ["mes_diam_ref"],
      "record": { "une_code_ident": "P001", "mes_no_seq": 5 },
      "rule_name": "check_required_fields"
    }
  ],
  "gpkg": "data.gpkg",
  "genere_le": "2026-07-21T09:15:33Z"
}
```

Ce fichier est lu par le plugin QField après synchronisation.

---

## 4. Configuration

### 4.1 Variables d'environnement

| Variable | Description | Valeur par défaut |
|----------|-------------|-------------------|
| `VALIDATION_PG_HOST` | Hôte PostgreSQL | `localhost` |
| `VALIDATION_PG_PORT` | Port PostgreSQL | `5432` |
| `VALIDATION_PG_DB` | Nom de la base | `ifa` |
| `VALIDATION_PG_USER` | Utilisateur | `postgres` |
| `VALIDATION_PG_PASS` | Mot de passe | *(vide)* |
| `VALIDATION_PG_SCHEMA` | Schéma cible | `ifa_data` |

> **Docker Desktop (Windows) :** Le conteneur QGIS ne peut pas atteindre `localhost`
> (qui désigne le conteneur lui-même). Utiliser `host.docker.internal` pour joindre
> PostgreSQL installé sur la machine Windows hôte.

### 4.2 docker-compose

Les variables sont déclarées dans `docker-compose.override.local.yml` :

```yaml
services:
  worker_wrapper:
    environment:
      VALIDATION_PG_HOST: ${VALIDATION_PG_HOST:-localhost}
      VALIDATION_PG_PORT: ${VALIDATION_PG_PORT:-5432}
      VALIDATION_PG_DB:   ${VALIDATION_PG_DB:-ifa}
      VALIDATION_PG_USER: ${VALIDATION_PG_USER:-postgres}
      VALIDATION_PG_PASS: ${VALIDATION_PG_PASS:-}
      VALIDATION_PG_SCHEMA: ${VALIDATION_PG_SCHEMA:-ifa_data}
```

Les valeurs sont renseignées dans `.env` à la racine du projet QFieldCloud :

```dotenv
VALIDATION_PG_HOST=host.docker.internal
VALIDATION_PG_PORT=5432
VALIDATION_PG_DB=ifa
VALIDATION_PG_USER=postgres
VALIDATION_PG_PASS=ndele
VALIDATION_PG_SCHEMA=ifa_data
```

> **Attention :** `docker compose restart` ne relit pas `.env`.  
> Après toute modification du `.env`, recréer le conteneur :
> ```bash
> docker compose up -d worker_wrapper
> ```

---

## 5. Plugin QField

### 5.1 Installation

QField distingue deux types de plugins :

- **Plugin projet** : fichier `.qml` placé à côté du fichier projet, portant le **même nom**
  (ex. `ipe_extrait_cloud.qml` à côté de `ipe_extrait_cloud.qgs`). Actif uniquement pour ce projet.
  QFieldCloud le découvre et l'inclut **automatiquement** lors du packaging.
- **Plugin d'application** : archive `.zip` installée via le gestionnaire de plugins QField.
  Active pour tous les projets.

Ce plugin utilise le **type projet**.

**Fichiers concernés :**

```
formulaires/
├── rapport_ife_plugin/
│   └── plugin.qml          ← source du plugin
└── package_plugin.py       ← script d'installation
```

**Étapes :**

```bash
# Copier plugin.qml comme {nom_projet}.qml à côté du .qgs
python package_plugin.py --project-dir "C:\MesProjets\ipe_extrait"

# → crée ipe_extrait.qml dans C:\MesProjets\ipe_extrait\
```

**Déploiement sur QFieldCloud :**

1. Lancer le script ci-dessus (crée `{projet}.qml` dans le dossier du projet)
2. Dans QGIS Desktop : synchroniser via QFieldSync → le `.qml` est uploadé
3. QFieldCloud l'inclut automatiquement dans le package → QField le charge à l'ouverture du projet

### 5.2 Fonctionnement — détection par timestamp de mise à jour

> **Changement majeur (2026-07-27).** L'ancienne approche (« Option 3 ») interrogeait
> l'API des *jobs* puis appelait `iface.cloudConnection.synchronize()`. Elle ne
> fonctionnait pas : **`iface.cloudConnection` n'est pas exposé aux plugins QField**, et
> `synchronize()` ne déclenchait pas `onSynchronized` quand le deltafile était vide. Le
> plugin interroge désormais directement l'**endpoint de packaging** et compare le
> timestamp **`data_last_updated_at`**.

> **⚠️ Pourquoi `data_last_updated_at` et non `packaged_at` ?**
> Un push (`delta_apply`) **régénère `rapport_ife.json` sans créer de job `package`**.
> Résultat : `packaged_at` (= `data_last_packaged_at`, ne bouge qu'au packaging) reste
> **figé** après un push, alors que le rapport a changé. Seul **`data_last_updated_at`**
> avance à chaque push — c'est donc le bon signal. (Bug constaté : `packaged_at=13:52`,
> mais `rapport.genere_le=13:58` après un push → le plugin ne retéléchargeait pas.)

```
[Plugin démarre]  Component.onCompleted
      ├─ checkDeltafile()
      ├─ checkPackage()        ← premier chargement immédiat
      └─ pollTimer.start()     ← polling toutes les 3s

[Toutes les 3 secondes]
  checkDeltafile()
      GET file://{homePath}/deltafile.json
      └─ deltas.length > 0  → reportStale = true   (bouton gris + spinner)

  checkPackage()
      GET {serverUrl}/api/v1/packages/{projectId}/latest/
          Authorization: Token {authToken}
      changeStamp = data_last_updated_at (repli sur packaged_at)
      ├─ changeStamp inchangé depuis le dernier chargement → rien à faire
      └─ changeStamp plus récent → fetchReport()   (via Qt.callLater)

  fetchReport(changeStamp)
      GET {serverUrl}/api/v1/packages/{projectId}/latest/files/rapport_ife.json/
          Authorization: Token {authToken}
      ├─ 200 → report chargé, loaded=true, reportStale=false → bouton vert/rouge
      ├─ 404 → paquet sans rapport (validation non exécutée) ; mémorise changeStamp
      └─ autre → erreur transitoire, réessai au prochain poll
```

Avantages de cette approche :

- **Indépendante de QField** : ne dépend ni de `iface.cloudConnection`, ni d'une
  synchronisation descendante. Le rapport est lu directement depuis le serveur.
- **Détecte les pushes** : `data_last_updated_at` avance à chaque `delta_apply`, même
  sans repackaging — le rapport régénéré au push est donc bien détecté.
- **Robuste au flux de push** : le timestamp est comparé à chaque poll ; peu importe que
  le plugin soit réinitialisé ou que la fenêtre de push ait été affichée entre-temps.
- **Ne martèle pas le serveur** : `changeStamp` est mémorisé (sur 200 comme sur 404) ; un
  rapport n'est retéléchargé que si les données ont réellement changé.

### 5.3 Authentification (URL + token codés en dur)

**`iface.cloudConnection` n'existe pas dans l'API des plugins QField** — impossible d'en
lire l'URL ou le token. Ces valeurs sont donc **codées en dur** en tête de `plugin.qml` :

| Propriété QML | Source | Contenu |
|---|---|---|
| `serverUrl` | codé en dur | URL du serveur QFieldCloud (ex. `https://localhost`) |
| `authToken` | codé en dur | token QFieldCloud (voir §5.4) |
| `projectId` | `qgisProject.homePath` | UUID extrait du chemin du dossier cloud |

```qml
readonly property string serverUrl: "https://localhost"
readonly property string authToken: "<token_cli>"

// Le projet courant est la propriété globale qgisProject ; homePath est une PROPRIÉTÉ.
readonly property string projectHome: (typeof qgisProject !== "undefined" && qgisProject)
                                       ? "" + qgisProject.homePath : ""
// projectId = dernier segment du chemin correspondant à un UUID
//   .../cloud_projects/{org}/{uuid}/
```

> **API projet — pièges corrigés :**
> - `iface.mapCanvas.project()` **n'existe pas**. Le projet courant est la propriété
>   globale **`qgisProject`**, et le chemin est la **propriété** `qgisProject.homePath`
>   (pas une méthode).
> - Le dossier d'un projet cloud est toujours nommé d'après l'UUID du projet
>   (`.../cloud_projects/{org}/{uuid}/`), sur **toutes** les plateformes (Windows,
>   Android, iOS). L'extraction parcourt le chemin **de la fin vers le début** pour
>   ignorer un éventuel UUID de conteneur (cas iOS).

### 5.4 Génération du token

Le token QFieldCloud est un `AuthToken` généré côté serveur. Deux scripts sont fournis à
la racine du projet QFieldCloud :

| Script | Shell |
|---|---|
| `mint_token.sh` | Git Bash |
| `mint_token.ps1` | PowerShell |

```bash
# Git Bash — user=admin, 365 jours (défaut)
bash mint_token.sh
bash mint_token.sh admin 30        # expiration forcée à 30 jours
```
```powershell
# PowerShell
.\mint_token.ps1
.\mint_token.ps1 -Username admin -Days 30
```

Copier la valeur `TOKEN = ...` dans `authToken` (plugin.qml), puis redéployer
(`package_plugin.py`) et re-synchroniser via QGIS Desktop → QField.

> **Type de client `cli` — crucial.** Les scripts créent des tokens de type **`cli`**.
> QFieldCloud définit `single_token_clients = [QFIELD, QFIELDSYNC, UNKNOWN]` : pour ces
> types, un seul token actif à la fois par utilisateur. Un token `cli` **n'en fait pas
> partie**, il n'est donc **jamais invalidé** — ni par les reconnexions QField/QGIS, ni
> par la génération d'autres tokens. **Ne pas utiliser un token `unknown` ni `worker`** :
> un `unknown` est tué dès qu'un nouveau `unknown` est créé (cause d'un 401 rencontré en
> test), et un `worker` est réservé à l'usage interne du worker.

> **Expiration.** Durée de vie par défaut côté serveur :
> `QFIELDCLOUD_AUTH_TOKEN_EXPIRATION_HOURS = 720 h` (30 jours). Les scripts forcent
> 365 jours. À l'expiration, le bouton redevient gris et le diagnostic affiche
> `HTTP paquet = 401` → reminter un token et redéployer.

### 5.5 Interface

**Bouton « IFE » (barre d'outils des plugins)**

Le bouton est un **`ToolButton`** ajouté via `iface.addItemToPluginsToolbar()`.

> ⚠️ Un `Rectangle` + `MouseArea` **s'affiche mais ne capte pas les clics** dans la barre
> d'outils des plugins. Il faut impérativement un contrôle bouton natif (`ToolButton`).

| État | Couleur | Signification |
|---|---|---|
| Non prêt | gris | rapport pas encore chargé, ou modifications locales en attente |
| Valide | vert | `is_valid = true` |
| Invalide | rouge | `is_valid = false` |
| En attente | spinner | `reportStale` (deltas poussés, re-validation en cours) |

**Clic** : ouvre le panneau de rapport si prêt, sinon le **panneau diagnostic**.

**Panneau de rapport** (`Drawer`, glisse depuis le bas)

- En-tête : titre, horodatage, badge VALIDE / INVALIDE
- Compteurs : Erreurs / Avertissements / Couches traitées
- Filtre de sévérité : Tout / Erreur / Avertissement
- Liste des anomalies : couche, code, message, champs concernés

> **Deux pièges corrigés :**
> - Les `Drawer` sont parentés à **`iface.mainWindow().contentItem`** (un Item avec
>   dimensions valides). Parenter à `iface.mainWindow()` empêche le panneau de s'afficher.
> - La propriété `severityFilter` doit être portée par le **Drawer** (`reportPanel`),
>   puisqu'elle est référencée comme `reportPanel.severityFilter`. Sinon le filtre par
>   défaut tombe à « warnings uniquement » et la liste des erreurs reste vide.

**Panneau diagnostic** (clic sur le bouton gris)

Affiche l'état réel pour lever tout doute : `projectId`, serveur, token présent/absent,
**HTTP paquet**, **HTTP rapport**, **Màj données** (`data_last_updated_at`), deltas en attente, chemin du projet,
plus un bouton **Rafraîchir**. C'est l'outil de dépannage n°1 (voir §8).

### 5.6 Limites connues

- **`localhost`** ne fonctionne que si QField tourne sur la **même machine** que le
  serveur (QField desktop). Sur mobile, `localhost` désigne le téléphone → remplacer
  `serverUrl` par l'**IP LAN** du serveur (ex. `https://192.168.x.x`).
- **Certificat SSL auto-signé** : le `XMLHttpRequest` de Qt peut le rejeter →
  `HTTP paquet = 0` dans le diagnostic.
- **Token codé en dur** : il est packagé et distribué à **tous** les appareils qui
  ouvrent le projet. Acceptable en usage interne uniquement.

---

## 6. Workflow complet

```
1. [QGIS Desktop] Préparer le projet
   ├─ Créer le projet QGS avec les couches IPE (mesurage, infor_gener, ...)
   ├─ Installer le plugin : python package_plugin.py --project-dir <dossier_projet>
   │     → crée {projet}.qml à côté du .qgs
   └─ Publier sur QFieldCloud (plugin QGIS QFieldCloud)
         → QFieldCloud inclut automatiquement {projet}.qml dans le package

2. [QField] Collecte terrain
   ├─ Synchroniser le projet (pull)
   ├─ Saisir les données IPE dans les formulaires
   └─ Pousser les modifications (push)

3. [QFieldCloud — automatique]
   ├─ Job apply_deltas créé
   ├─ Les deltas sont appliqués au GPKG
   ├─ validate_ife_data() est appelé :
   │   ├─ Détection du GPKG IPE (_find_ipe_gpkg)
   │   ├─ Connexion PostgreSQL
   │   ├─ Validation et insertion si valide
   │   ├─ Écriture rapport_validation dans le GPKG
   │   ├─ Injection couche dans le .qgs
   │   └─ Écriture rapport_ife.json
   └─ upload_project : GPKG + QGS + JSON uploadés

4. [QField — automatique, via plugin]
   ├─ Le plugin interroge l'endpoint de packaging (polling 3s) et compare data_last_updated_at
   ├─ Dès que le paquet est régénéré, il télécharge rapport_ife.json depuis l'API
   └─ Affiche le rapport (bouton IFE vert/rouge + panneau de détail)
```

---

## 7. Déploiement

### Rebuild après modification de `validate_ifa.py`

```bash
# Reconstruire l'image QGIS
docker compose build qgis

# Recréer le worker (pas restart, pour relire les variables)
docker compose up -d worker_wrapper
```

### Mise à jour du plugin QField

```bash
# Copie plugin.qml comme {stem}.qml à côté du .qgs/.qgz du projet
python formulaires/package_plugin.py --project-dir "chemin/vers/projet"
```

Puis dans QGIS Desktop : **synchroniser via QFieldSync** (upload du `.qml`), puis dans
QField **synchroniser** pour retélécharger le plugin. Les deux étapes sont nécessaires,
sinon QField garde l'ancienne version.

### Mise à jour du token (à l'expiration)

```bash
# Génère un nouveau token cli (365 jours) — voir §5.4
bash   QfieldCloud/QFieldCloud/mint_token.sh          # ou
powershell -File QfieldCloud/QFieldCloud/mint_token.ps1
```

Coller la valeur `TOKEN = ...` dans `authToken` (plugin.qml), puis redéployer le plugin
comme ci-dessus.

### Vérification des variables d'environnement dans le conteneur

```bash
docker compose exec worker_wrapper env | grep VALIDATION_PG
```

---

## 8. Dépannage

### « aucun GPKG IPE trouvé »

**Cause probable :** Le projet ne contient pas de GPKG avec les tables IPE, ou les tables
ont un nom non reconnu.

**Diagnostic :**

```bash
# Lister les tables SQLite du GPKG
sqlite3 chemin/vers/data.gpkg ".tables"

# Vérifier les entrées gpkg_contents
sqlite3 chemin/vers/data.gpkg "SELECT table_name FROM gpkg_contents;"
```

La détection cherche des tables dont le nom commence par `mesurage` ou `infor_gener`
(exact ou préfixé par un UUID QFieldCloud). Si les noms sont différents, mettre à jour
`_IPE_SIGNATURE_TABLES` dans `validate_ifa.py`.

---

### « Connexion PostgreSQL échouée : connection refused »

**Cause probable :** `VALIDATION_PG_HOST` vaut `localhost`, qui depuis le conteneur
désigne le conteneur lui-même, pas la machine hôte Windows.

**Solution :** Vérifier que `.env` contient `VALIDATION_PG_HOST=host.docker.internal`
et recréer le conteneur (`docker compose up -d worker_wrapper`).

---

### `'ValidationReport' object has no attribute 'error_count'`

**Cause :** Code utilisant `result.error_count` au lieu de `len(result.errors)`.

`ValidationReport` expose `errors` et `warnings` comme `@property` (listes),
pas comme attributs scalaires. Utiliser `len(result.errors)` et `len(result.warnings)`.

---

### La couche `rapport_validation` n'apparaît pas dans QField

**Étapes de vérification :**

1. Vérifier que `rapport_validation` existe dans le GPKG :
   ```bash
   sqlite3 data.gpkg "SELECT * FROM gpkg_contents;"
   ```

2. Vérifier que la couche est dans le `.qgs` :
   ```bash
   grep "rapport_validation" projet.qgs
   ```

3. Si absent du `.qgs`, vérifier les logs du job QFieldCloud dans l'interface web
   pour comprendre pourquoi `_add_rapport_layer_to_qgs` a échoué.

4. S'assurer que le technicien a bien re-synchronisé après le push
   (ou que le plugin a déclenché la sync automatique).

---

### Le plugin ne s'affiche pas dans QField

**Vérifications :**

- Le fichier `{projet}.qml` est présent à côté du `.qgs` dans le dossier QGIS Desktop
- Le projet a été synchronisé via QFieldSync après l'ajout du `.qml`
- Un job de packaging a été relancé sur QFieldCloud (le packaging inclut le `.qml` automatiquement)
- La version de QField supporte les plugins QML (≥ 2.5)
- Consulter les logs QField (Paramètres → À propos → Journaux)

---

### Le bouton IFE reste gris → utiliser le panneau diagnostic

Le bouton est **cliquable même en gris** : un clic ouvre le **panneau diagnostic**, qui
affiche l'état réel. Lire d'abord `projectId`, `HTTP paquet` et `HTTP rapport`, puis :

| Symptôme dans le diagnostic | Cause | Correctif |
|---|---|---|
| `projectId` **vide** / `Chemin projet` vide | `qgisProject.homePath` non résolu | vérifier que le plugin est bien à jour (API `qgisProject`, pas `iface.mapCanvas.project()`) |
| `Token` **absent** | `authToken` vide dans plugin.qml | renseigner le token (§5.4) |
| `HTTP paquet` = **401** | token invalide/expiré, ou de type `unknown`/`worker` invalidé | reminter un token **cli** (§5.4) |
| `HTTP paquet` = **0** | connexion impossible : SSL auto-signé ou URL injoignable | passer l'URL à l'IP LAN ; certificat |
| `HTTP paquet` = **400** | projet jamais packagé sur QFieldCloud | lancer un packaging (push ou re-publication) |
| `HTTP rapport` = **404** | paquet OK mais validation non exécutée | vérifier `validate_ife_data` côté serveur (§8 GPKG/PostgreSQL) |
| Tout **200** mais bouton gris | modifications locales en attente (`Deltas en attente > 0`) | pousser/synchroniser ; le bouton se met à jour après la re-validation serveur (avance de `Màj données`) |

**Test manuel de l'API (mêmes appels que le plugin) :**

```bash
# 1) métadonnées du paquet (data_last_updated_at, packaged_at)
curl -k -H "Authorization: Token <token>" \
  "https://<serveur>/api/v1/packages/<uuid>/latest/"

# 2) téléchargement du rapport
curl -k -H "Authorization: Token <token>" \
  "https://<serveur>/api/v1/packages/<uuid>/latest/files/rapport_ife.json/"
```

---

### Le clic sur le bouton n'ouvre aucun panneau

- **Bouton non cliquable** → le plugin utilise encore un `Rectangle`+`MouseArea` : il faut
  un `ToolButton` (§5.5).
- **Bouton cliquable mais aucun panneau** → le `Drawer` est parenté à `iface.mainWindow()`
  au lieu de `iface.mainWindow().contentItem` (§5.5).

---

### Le panneau s'affiche mais la liste des erreurs est vide

La propriété `severityFilter` est déclarée sur le `ColumnLayout` alors qu'elle est
référencée comme `reportPanel.severityFilter` : elle vaut `undefined`, le filtre par
défaut retombe sur « warnings uniquement » et masque les erreurs. La déclarer sur le
`Drawer` `reportPanel` (§5.5).
