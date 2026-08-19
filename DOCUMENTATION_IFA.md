# Documentation IFA 2.0 — QFieldCloud, validation IFA et plugin QField

> Projet IFA 2.0
> Document unique — fusion de `README-IFA.md`, `VALIDATION_IFA.md` et `Mise en place du serveur.md`
> Dernière mise à jour : 2026-08-18

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
   - 1.1 [Périmètre](#11-périmètre)
   - 1.2 [Chaîne de traitement](#12-chaîne-de-traitement)
   - 1.3 [Arborescence du projet](#13-arborescence-du-projet)
2. [Installation locale (développement / test)](#2-installation-locale-développement--test)
3. [Déploiement sur serveur (VPS Ubuntu)](#3-déploiement-sur-serveur-vps-ubuntu)
   - 3.1 [Connexion au VPS](#31-connexion-au-vps)
   - 3.2 [Installation de Docker Engine](#32-installation-de-docker-engine)
   - 3.3 [Installation de PostgreSQL et PostGIS](#33-installation-de-postgresql-et-postgis)
   - 3.4 [Déploiement de QFieldCloud](#34-déploiement-de-qfieldcloud)
   - 3.5 [Rendre `host.docker.internal` résolvable sous Linux](#35-rendre-hostdockerinternal-résolvable-sous-linux)
   - 3.6 [Autoriser PostgreSQL depuis les conteneurs](#36-autoriser-postgresql-depuis-les-conteneurs)
   - 3.7 [Pare-feu](#37-pare-feu)
   - 3.8 [DNS et certificat Let's Encrypt](#38-dns-et-certificat-lets-encrypt)
4. [Composants serveur de validation](#4-composants-serveur-de-validation)
   - 4.1 [`validate_ifa.py` — point d'entrée](#41-validate_ifapy--point-dentrée)
   - 4.2 [`validation_ifa/` — moteur de validation](#42-validation_ifa--moteur-de-validation)
   - 4.3 [Fichiers produits](#43-fichiers-produits)
5. [Configuration de la validation](#5-configuration-de-la-validation)
   - 5.1 [Variables d'environnement](#51-variables-denvironnement)
   - 5.2 [docker-compose et `.env`](#52-docker-compose-et-env)
6. [Plugin QField `plugin_auth.qml`](#6-plugin-qfield-plugin_authqml)
   - 6.1 [Principe : aucune valeur codée en dur](#61-principe--aucune-valeur-codée-en-dur)
   - 6.2 [Installation et déploiement](#62-installation-et-déploiement)
   - 6.3 [Résolution de la connexion cloud](#63-résolution-de-la-connexion-cloud)
   - 6.4 [Authentification par session](#64-authentification-par-session)
   - 6.5 [Détection des changements (sondages)](#65-détection-des-changements-sondages)
   - 6.6 [Interface](#66-interface)
   - 6.7 [Limites connues](#67-limites-connues)
7. [Workflow complet](#7-workflow-complet)
8. [Interface utilisateur (hors admin)](#8-interface-utilisateur-hors-admin)
   - 8.1 [Le problème résolu](#81-le-problème-résolu)
   - 8.2 [Les écrans](#82-les-écrans)
   - 8.3 [Fichiers](#83-fichiers)
   - 8.4 [Principes de conception](#84-principes-de-conception)
   - 8.5 [Étendre le tableau de bord](#85-étendre-le-tableau-de-bord)
   - 8.6 [Notes](#86-notes)
9. [Exploitation et mises à jour](#9-exploitation-et-mises-à-jour)
10. [Dépannage](#10-dépannage)

---

## 1. Vue d'ensemble

### 1.1 Périmètre

QFieldCloud est un service basé sur Django qui synchronise projets et données entre
QGIS (+ plugin QFieldSync) et QField. Cette instance est **customisée pour le projet
IFA 2.0** : elle ajoute, au workflow `apply_deltas`, une étape de **validation IFE**
(Inventaire Forestier Étendu) et d'**insertion dans PostgreSQL**.

Après qu'un technicien de terrain pousse ses données depuis QField, le serveur :

1. valide les données du GeoPackage IPE contre les règles métier et le schéma PostgreSQL ;
2. insère les données en base si elles sont valides ;
3. écrit un rapport lisible dans le GPKG et un JSON pour le plugin QField ;
4. ajoute automatiquement la couche `rapport_validation` au projet QGS ;
5. upload le projet mis à jour → le technicien voit son rapport après synchronisation.

### 1.2 Chaîne de traitement

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
      │◄─ plugin : POST auth/login (session)                        │
      │   puis GET packages/latest (polling data_last_updated_at)   │
      │   puis GET .../files/rapport_ife.json                       │
      │   → bouton IFA vert / rouge / sablier                       │
```

Le plugin ne déclenche **pas** de synchronisation QField : il lit `rapport_ife.json`
**directement depuis l'API de packaging** (voir §6.5). La couche `rapport_validation`,
elle, devient visible après une synchronisation descendante QField.

### 1.3 Arborescence du projet

```
IFA 2.0\
├── QfieldCloud-ifa\                         ← instance QFieldCloud customisée
│   ├── docker-qgis\qfc_worker\
│   │   ├── validate_ifa.py                  ← point d'entrée de la validation
│   │   └── validation_ifa\                  ← moteur de validation (package Python)
│   │       ├── config.py                    ← lecture des variables VALIDATION_PG_*
│   │       └── core\
│   │           ├── engine.py                ← orchestration des règles
│   │           ├── models.py                ← ValidationReport, ValidationIssue, Severity
│   │           ├── gpkg_reader.py           ← lecture du GeoPackage
│   │           ├── db_schema.py             ← lecture des contraintes PostgreSQL
│   │           └── rules\                   ← règles métier (.py par domaine)
│   ├── docker-app\worker_wrapper\
│   │   └── wrapper.py                       ← lance le conteneur QGIS, passe VALIDATION_PG_*
│   ├── docker-compose.override.local.yml
│   ├── .env                                 ← valeurs des variables d'environnement
│   └── DOCUMENTATION_IFA.md                 ← le présent document
│
└── formulaires\
    ├── rapport_ife_plugin\
    │   ├── plugin_auth.qml                  ← ✅ plugin QField EN USAGE
    │   ├── plugin.qml                       ← variante : délégation à cloudProjectsModel
    │   ├── plugin_server.qml                ← variante historique (URL + token en dur)
    │   └── plugin_local.qml                 ← variante historique (lecture fichier local)
    └── package_plugin.py                    ← script de déploiement du plugin
```

---

## 2. Installation locale (développement / test)

### Prérequis

* **Docker + Docker Compose** (Docker Desktop sur Windows/macOS, ou Docker Engine +
  plugin Compose sur Linux)
* Environ 4–6 Go d'espace disque (les images QGIS sont volumineuses)

### Étape 1 — Configurer le fichier `.env`

```shell
nano .env   # ou code .env, vim .env
```

Vérifier / modifier :

| Variable | Valeur |
|---|---|
| `QFIELDCLOUD_HOST` | `localhost` ou le DNS du serveur hébergeant l'instance |
| `DEBUG` | `1` en développement ou test, `0` en production |

Voir aussi §5 pour les variables `VALIDATION_PG_*` propres à la validation IFE.

### Étape 2 — Créer le volume des certificats

```shell
docker volume create qfieldcloud_custom_ca_certificates
```

### Étape 3 — Construire et démarrer les conteneurs

```shell
docker compose up -d --build
```

> *NB : déconnecter le VPN pour éviter les restrictions de connexion pendant le build.*

Cette commande lit les fichiers `docker-compose*.yml` listés dans la variable
`COMPOSE_FILE` du `.env`, construit les images et démarre les conteneurs en
arrière-plan. La première exécution peut prendre **10 à 20 minutes** (téléchargement
des images QGIS notamment).

Suivre les logs en temps réel dans un autre terminal :

```shell
docker compose logs -f
```

### Étape 4 — Appliquer les migrations Django

```shell
docker compose exec app python manage.py migrate
```

### Étape 5 — Collecter les fichiers statiques

```shell
docker compose exec app python manage.py collectstatic --noinput
```

### Étape 6 — Créer le super-utilisateur

```shell
docker compose run app python manage.py createsuperuser --username admin --email admin@example.com
```

> Le mot de passe est demandé de façon interactive.

### Étape 7 — Traductions (optionnel)

```shell
docker compose run --user root app python manage.py compilemessages
```

### Étape 8 — Faire confiance au certificat auto-signé

QFieldCloud génère automatiquement un certificat et son certificat racine dans
`./conf/nginx/certs`. Il faut faire confiance à ce certificat racine pour que les
autres programmes (navigateur, curl, QGIS, QField) acceptent la connexion HTTPS locale.

**Linux (Debian/Ubuntu)**

```bash
sudo cp ./conf/nginx/certs/rootCA.pem /usr/local/share/ca-certificates/rootCA.crt
sudo update-ca-certificates
```

**macOS**

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ./conf/nginx/certs/rootCA.pem
```

**Windows**

```shell
cp ./conf/nginx/certs/rootCA.pem ./conf/nginx/certs/rootCA.crt
```

Ouvrir `rootCA.crt` puis :
***« Installer le certificat » → « Ordinateur local » → « Autorités de certification
racines de confiance »***.

### Étape 9 — Vérifier que tout fonctionne

```bash
curl https://localhost/api/v1/status/
```

Les clés `database` et `storage` doivent avoir le statut `ok`. Puis :

* Interface principale : <https://localhost>
* Admin Django : <https://localhost/admin>
* Serveur Django direct : <http://localhost:8011>

### Commandes utiles au quotidien

```bash
# Démarrer
docker compose up -d

# Arrêter
docker compose down

# Voir les logs
docker compose logs -f nginx app worker_wrapper qgis

# Accéder à la base de données QFieldCloud
docker compose exec -it db psql -U qfieldcloud_db_admin -d qfieldcloud_db
```

---

## 3. Déploiement sur serveur (VPS Ubuntu)

> **Identifiants.** Les mots de passe (VPS, base `ifa`, admin Django) ne sont
> volontairement pas écrits ici. Les conserver dans le gestionnaire de secrets de
> l'équipe ; les exemples ci-dessous utilisent des valeurs génériques.

### 3.1 Connexion au VPS

```bash
ssh ubuntu@<ip_du_vps>
```

### 3.2 Installation de Docker Engine

**a) Déclarer le dépôt apt de Docker**

```bash
# Clé GPG officielle
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Dépôt dans les sources apt
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
```

**b) Installer les paquets**

```bash
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**c) Vérifier que le service tourne**

```bash
sudo systemctl status docker
sudo systemctl start docker      # si nécessaire
```

**d) Test de bout en bout**

```bash
sudo docker run hello-world
```

### 3.3 Installation de PostgreSQL et PostGIS

```bash
sudo apt install postgresql postgis
```

Pour une version précise :

```bash
sudo apt install postgresql-17 postgis-3
```

**Créer l'utilisateur et la base**

```sql
CREATE USER ifauser WITH PASSWORD '<mot_de_passe>';
CREATE DATABASE ifa;
GRANT ALL PRIVILEGES ON DATABASE ifa TO ifauser;
```

Puis importer le dump de la base IFA (schéma `ifa_data` et référentiels).

### 3.4 Déploiement de QFieldCloud

**a)** Cloner le dépôt du code source sur le VPS.

**b)** Éditer le `.env` — en particulier l'endpoint du stockage objet. Chercher la
ligne (vers la ligne 133) :

```
"endpoint_url": "http://host.docker.internal:8009"
```

et la remplacer par :

```
"endpoint_url": "http://rustfs:9000"
```

> `rustfs` = nom du service dans `docker-compose.override.standalone.yml` ;
> `9000` = port **interne** du conteneur, pas le port publié `8009`.

**c)** Vérifier les paramètres de connexion PostgreSQL du script de validation
(`config.py` / variables `VALIDATION_PG_*`, voir §5).

**d)** Reprendre les étapes 3 à 7 du §2 (build, migrations, statiques, superutilisateur).

### 3.5 Rendre `host.docker.internal` résolvable sous Linux

Le conteneur `qgis` (qui exécute la validation IFE) est lancé dynamiquement par
`client.containers.run(...)` dans `docker-app/worker_wrapper/wrapper.py` (vers la
ligne 420), **sans** l'option `extra_hosts`. C'est pourquoi `host.docker.internal` ne
résout pas sous Linux, contrairement à Docker Desktop Windows/macOS où c'est automatique.

Ajouter la ligne `extra_hosts` juste après `network=…` :

```python
container: Container = client.containers.run(  # type:ignore
    settings.QFIELDCLOUD_QGIS_IMAGE_NAME,
    command,
    environment=environment,
    ports=ports,
    volumes=volumes,
    network=settings.QFIELDCLOUD_DEFAULT_NETWORK,
    extra_hosts={"host.docker.internal": "host-gateway"},   # ← ajout
    detach=True,
```

`host-gateway` est une valeur spéciale supportée par Docker Engine ≥ 20.10 sous Linux :
elle fait pointer `host.docker.internal` vers l'IP de la passerelle du réseau Docker,
exactement comme le fait Docker Desktop nativement. Le `.env`
(`VALIDATION_PG_HOST=host.docker.internal`) reste donc **identique entre dev local et VPS**.

### 3.6 Autoriser PostgreSQL depuis les conteneurs

La base `ifa` tourne nativement sur le VPS (hors Docker) : Postgres doit écouter
au-delà de `localhost` et autoriser explicitement le sous-réseau Docker.

**a) `postgresql.conf`** (typiquement `/etc/postgresql/<version>/main/postgresql.conf`)

Postgres n'accepte pas de plage CIDR dans `listen_addresses` — utiliser `*`, en
restreignant ensuite par `pg_hba.conf` **et** par le pare-feu (§3.7) :

```
listen_addresses = '*'
```

**b) `pg_hba.conf`** (même dossier) — les réseaux bridge Docker/Compose sont dans la
plage `172.16.0.0/12` :

```
host    ifa    postgres    172.16.0.0/12    scram-sha-256
host    ifa    ifauser     172.16.0.0/12    scram-sha-256
```

**c) Redémarrer**

```bash
sudo systemctl restart postgresql
```

### 3.7 Pare-feu

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Postgres : uniquement depuis les réseaux Docker
sudo ufw allow from 172.16.0.0/12 to any port 5432 proto tcp
```

> ⚠️ **Ne jamais faire `sudo ufw allow 5432`** tout court : cela exposerait PostgreSQL
> à tout Internet, `listen_addresses = '*'` étant actif.

### 3.8 DNS et certificat Let's Encrypt

Une fois l'enregistrement DNS pointé vers le VPS, remplacer le certificat mkcert
auto-signé par un certificat Let's Encrypt. La manœuvre se fait en **deux passes** sur
le `.env` : la première prépare l'émission, la seconde bascule nginx sur le certificat émis.

#### Passe 1 — `.env` avant l'émission

**Modification 1 — `QFIELDCLOUD_HOST`** (vers la ligne 14) :

```diff
-QFIELDCLOUD_HOST=localhost
+QFIELDCLOUD_HOST=ifa.example.org
```

Sans `https://` devant, sans barre oblique ni port à la fin : cette variable sert aussi
à construire les chemins des certificats plus bas.

**Modification 2 — `DJANGO_ALLOWED_HOSTS`** (vers la ligne 278) :

```diff
-DJANGO_ALLOWED_HOSTS="149.56.108.189 localhost 127.0.0.1 0.0.0.0 app nginx"
+DJANGO_ALLOWED_HOSTS="ifa.example.org localhost 127.0.0.1 0.0.0.0 app nginx"
```

Sans cela Django renvoie **400** sur toutes les requêtes portant le nouveau nom.

**Ce qu'il ne faut pas encore toucher :** les lignes 48 et 54
(`QFIELDCLOUD_TLS_CERT` / `QFIELDCLOUD_TLS_KEY`) restent sur mkcert. Elles se dérivent
automatiquement du nouveau `QFIELDCLOUD_HOST`, donc mkcert génère un certificat
auto-signé pour le domaine. C'est voulu : il permet à nginx de démarrer, et le
challenge ACME passe de toute façon par le port 80 en clair.

**En ligne de commande**

```bash
cd ~/QfieldCloud-ifa
cp .env .env.bak-$(date +%F)          # sauvegarde avant édition

docker compose up -d mkcert
ls -l conf/nginx/certs/               # attendre l'apparition de ifa.example.org.pem

docker compose up -d --force-recreate nginx app worker_wrapper
```

Vérifier que le chemin ACME répond **avant** d'appeler Let's Encrypt — un échec ici
consomme le quota :

```bash
docker compose exec -T nginx sh -c 'mkdir -p /var/www/certbot/.well-known/acme-challenge && echo ok-acme > /var/www/certbot/.well-known/acme-challenge/test'
curl -s http://ifa.example.org/.well-known/acme-challenge/test     # doit afficher : ok-acme
docker compose exec -T nginx rm -f /var/www/certbot/.well-known/acme-challenge/test
```

Émission, à blanc puis pour de vrai :

```bash
docker compose run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot -d ifa.example.org \
  --email toi@example.org --agree-tos --no-eff-email \
  --rsa-key-size 4096 --non-interactive --dry-run

# si l'essai passe, relancer la même commande sans --dry-run
ls -l conf/certbot/conf/live/ifa.example.org/
```

#### Passe 2 — `.env` après l'émission

Le fichier contient déjà les bonnes lignes en commentaire, juste au-dessus des lignes
actives : il suffit d'inverser lesquelles sont commentées.

**Modification 3 — `QFIELDCLOUD_TLS_CERT`** (lignes 45 à 48) :

```diff
 # For usage with Let's Encrypt certificate, use as:
-# QFIELDCLOUD_TLS_CERT="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/fullchain.pem"
+QFIELDCLOUD_TLS_CERT="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/fullchain.pem"
 # DEFAULT: "/etc/nginx/certs/${QFIELDCLOUD_HOST}.pem"
-QFIELDCLOUD_TLS_CERT="/etc/nginx/certs/${QFIELDCLOUD_HOST}.pem"
+# QFIELDCLOUD_TLS_CERT="/etc/nginx/certs/${QFIELDCLOUD_HOST}.pem"
```

**Modification 4 — `QFIELDCLOUD_TLS_KEY`** (lignes 51 à 54) :

```diff
 # For usage with Let's Encrypt certificate, use as:
-# QFIELDCLOUD_TLS_KEY="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/privkey.pem"
+QFIELDCLOUD_TLS_KEY="/etc/letsencrypt/live/${QFIELDCLOUD_HOST}/privkey.pem"
 # DEFAULT: "/etc/nginx/certs/${QFIELDCLOUD_HOST}-key.pem"
-QFIELDCLOUD_TLS_KEY="/etc/nginx/certs/${QFIELDCLOUD_HOST}-key.pem"
+# QFIELDCLOUD_TLS_KEY="/etc/nginx/certs/${QFIELDCLOUD_HOST}-key.pem"
```

Laisser `${QFIELDCLOUD_HOST}` **littéralement** : c'est Docker Compose qui l'expanse.
Ne pas le remplacer par le domaine en dur.

**Puis**

```bash
docker compose up -d --force-recreate nginx
docker compose logs --tail=30 nginx

# Test décisif : SANS -k, exactement ce que fait le XMLHttpRequest du plugin
curl -sS -o /dev/null -w "HTTP %{http_code}\n" https://ifa.example.org/api/v1/status/

echo | openssl s_client -connect ifa.example.org:443 -servername ifa.example.org 2>/dev/null \
  | openssl x509 -noout -issuer -dates
```

L'émetteur doit être `O=Let's Encrypt, CN=R10` (ou R11 / E5). S'il affiche encore
`mkcert development CA`, la passe 2 n'a pas été prise en compte.

**Renouvellement et nettoyage**

```bash
docker compose run --rm --entrypoint certbot certbot renew --dry-run
docker compose stop mkcert     # il ne sert plus
```

> Un certificat valide reconnu publiquement supprime du même coup la principale cause
> de `HTTP paquet = 0` côté plugin (voir §10).

---

## 4. Composants serveur de validation

### 4.1 `validate_ifa.py` — point d'entrée

**Emplacement :** `docker-qgis/qfc_worker/validate_ifa.py`

Appelé comme étape du workflow `apply_deltas`. Fonction principale :
`validate_ife_data(project_dir)`.

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
# "mesurage"                                      → exact
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

- ajoute un `<maplayer>` dans `<projectlayers>` ;
- ajoute un `<layer-tree-layer>` après `</custom-order>` (QGIS ≥ 3.x) ;
- n'écrit rien si `layername=rapport_validation` est déjà présent.

Le QGS modifié est uploadé par `upload_project` → la couche est visible lors de la
synchronisation suivante.

### 4.2 `validation_ifa/` — moteur de validation

Package Python ajouté dynamiquement à `sys.path` par `validate_ifa.py`.

| Module | Rôle |
|--------|------|
| `config.py` | Lit `VALIDATION_PG_*` depuis l'environnement |
| `core/engine.py` | Orchestre les règles : lit le GPKG, interroge le schéma PostgreSQL, applique les règles, construit le `ValidationReport` |
| `core/models.py` | `ValidationReport`, `ValidationIssue`, `Severity` (ERROR / WARNING) |
| `core/gpkg_reader.py` | Lecture des couches du GeoPackage |
| `core/db_schema.py` | Introspection PostgreSQL : PK, NOT NULL, plages numériques, ENUMs |
| `core/rules/` | Règles métier (un `.py` par domaine) |

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

> **Important :** `ValidationReport` n'a **pas** d'attributs `error_count` ni
> `warning_count`. Utiliser `len(result.errors)` et `len(result.warnings)`.
> (Le JSON produit, lui, expose bien `error_count` / `warning_count` — voir §4.3.)

### 4.3 Fichiers produits

#### `rapport_validation` (table GPKG)

Créée / remplacée dans le GPKG IPE à chaque exécution :

| Colonne | Type | Contenu |
|---------|------|---------|
| `id` | INTEGER PK | auto |
| `statut` | TEXT | VALIDE / INVALIDE / ERREUR_SYSTEME |
| `couche` | TEXT | nom de la couche concernée |
| `code_regle` | TEXT | code de la règle (`RESUME` pour la ligne de synthèse) |
| `severite` | TEXT | error / warning / info |
| `message` | TEXT | message lisible |
| `champs` | TEXT | champs concernés (séparés par virgule) |
| `enregistrement` | TEXT | clé métier JSON de l'enregistrement |
| `genere_le` | TEXT | horodatage UTC ISO 8601 |

La table est enregistrée dans `gpkg_contents` (`data_type = 'attributes'`) pour être
reconnue par QGIS Desktop et QField.

#### `rapport_ife.json`

Écrit dans le sous-dossier `plugins/` du projet (inclus dans le package via
`attachment_dirs`) :

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

Ce fichier est téléchargé par le plugin QField via l'API de packaging (§6.5).

---

## 5. Configuration de la validation

### 5.1 Variables d'environnement

| Variable | Description | Valeur par défaut |
|----------|-------------|-------------------|
| `VALIDATION_PG_HOST` | Hôte PostgreSQL | `localhost` |
| `VALIDATION_PG_PORT` | Port PostgreSQL | `5432` |
| `VALIDATION_PG_DB` | Nom de la base | `ifa` |
| `VALIDATION_PG_USER` | Utilisateur | `postgres` |
| `VALIDATION_PG_PASS` | Mot de passe | *(vide)* |
| `VALIDATION_PG_SCHEMA` | Schéma cible | `ifa_data` |

> **Docker Desktop (Windows) :** le conteneur QGIS ne peut pas atteindre `localhost`
> (qui désigne le conteneur lui-même). Utiliser `host.docker.internal` pour joindre le
> PostgreSQL installé sur la machine hôte. Sous Linux, voir §3.5.

### 5.2 docker-compose et `.env`

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

Les valeurs sont renseignées dans `.env` à la racine du projet :

```dotenv
VALIDATION_PG_HOST=host.docker.internal
VALIDATION_PG_PORT=5432
VALIDATION_PG_DB=ifa
VALIDATION_PG_USER=ifauser
VALIDATION_PG_PASS=<mot_de_passe>
VALIDATION_PG_SCHEMA=ifa_data
```

> **Attention :** `docker compose restart` ne relit pas `.env`.
> Après toute modification, **recréer** le conteneur :
> ```bash
> docker compose up -d worker_wrapper
> ```

---

## 6. Plugin QField `plugin_auth.qml`

**Source :** `formulaires/rapport_ife_plugin/plugin_auth.qml`

Le plugin affiche, dans QField, l'état de validation des données poussées : un bouton
**IFA** vert (valide) / rouge (invalide) / sablier (en attente), et deux panneaux
coulissants — rapport détaillé et diagnostic.

Trois autres variantes existent dans le même dossier et **ne sont pas utilisées** :
`plugin.qml` (délégation des requêtes à `cloudProjectsModel`), `plugin_server.qml`
(version historique à URL + token codés en dur) et `plugin_local.qml` (lecture du
rapport depuis un fichier local).

### 6.1 Principe : aucune valeur codée en dur

Ni l'URL du serveur ni un token ne figurent dans le fichier. Les deux sont obtenus à
l'exécution :

| Donnée | Origine |
|---|---|
| `serverUrl` | propriété `url` (repli `defaultUrl`) de l'objet **QFieldCloudConnection** de QField |
| `cloudUsername` | propriété `username` du même objet |
| `authToken` | **obtenu par `POST /api/v1/auth/login/`**, en mémoire uniquement |
| `projectId` | UUID extrait de `qgisProject.homePath` |

Conséquences pratiques : le même `.qml` fonctionne sur toutes les instances (locale,
VPS, IP LAN) sans être ré-édité, il n'y a plus de token à régénérer ni à faire expirer,
et chaque appareil interroge le serveur **avec les droits de l'utilisateur réellement
connecté** dans QField.

### 6.2 Installation et déploiement

QField distingue deux types de plugins :

- **Plugin projet** : fichier `.qml` placé à côté du fichier projet, portant le **même
  nom** (ex. `ipe_extrait_cloud.qml` à côté de `ipe_extrait_cloud.qgs`). Actif
  uniquement pour ce projet ; QFieldCloud le découvre et l'inclut **automatiquement**
  lors du packaging.
- **Plugin d'application** : archive `.zip` installée via le gestionnaire de plugins
  QField, active pour tous les projets.

Ce plugin utilise le **type projet**.

**Déploiement**

```bash
# Copie le plugin comme {nom_projet}.qml à côté du .qgs/.qgz
python formulaires/package_plugin.py --project-dir "C:\MesProjets\ipe_extrait"
# → crée ipe_extrait.qml dans C:\MesProjets\ipe_extrait\
```

> ⚠️ **À vérifier avant de lancer le script :** `package_plugin.py` définit la source
> du plugin en tête de fichier. Elle doit pointer sur la variante en usage :
> ```python
> PLUGIN_SRC = SCRIPT_DIR / "rapport_ife_plugin" / "plugin_auth.qml"
> ```

Puis :

1. dans **QGIS Desktop**, synchroniser via **QFieldSync** → le `.qml` est uploadé ;
2. QFieldCloud l'inclut automatiquement dans le package ;
3. dans **QField**, synchroniser → le plugin est retéléchargé et chargé à l'ouverture
   du projet.

Les deux synchronisations sont nécessaires : sans la seconde, QField conserve
l'ancienne version du plugin.

### 6.3 Résolution de la connexion cloud

`iface` (AppInterface) n'expose **aucun membre cloud** : `iface.cloudConnection`
n'existe pas. L'objet `QFieldCloudConnection` reste toutefois atteignable par son
`objectName`, plusieurs noms étant essayés successivement :

```qml
function resolveCloudConnection() {
    var names = ["cloudConnection", "qfieldCloudConnection", "QFieldCloudConnection"]
    for (var i = 0; i < names.length; i++) {
        try {
            var o = iface.findItemByObjectName(names[i])
            if (o) return o
        } catch (e) { /* nom inconnu : on essaie le suivant */ }
    }
    return null
}
```

La résolution a lieu dans `Component.onCompleted`, **après** construction de l'arbre
applicatif — plus tôt, `findItemByObjectName()` ne trouverait rien. Toute lecture de
propriété passe par `cloudProp(name)`, défensif : selon la version de QField une
propriété peut ne pas être exposée à QML et renvoyer `undefined`.

La barre oblique finale éventuelle de `url` est retirée, sinon les chemins d'API
seraient construits avec un double séparateur.

**`projectId`** est extrait du chemin du projet, parcouru **de la fin vers le début**
pour ignorer un éventuel UUID de conteneur (cas iOS) :

```qml
readonly property string projectHome: {
    if (typeof qgisProject !== "undefined" && qgisProject)
        return "" + qgisProject.homePath
    return ""
}
// .../cloud_projects/{org}/{uuid}/  →  projectId = {uuid}
```

> **Pièges API :** `iface.mapCanvas.project()` **n'existe pas**. Le projet courant est
> la propriété globale **`qgisProject`**, et `homePath` en est une **propriété**, pas
> une méthode. Le dossier d'un projet cloud est toujours nommé d'après l'UUID du
> projet, sur toutes les plateformes (Windows, Android, iOS).

### 6.4 Authentification par session

Le token détenu par QField **n'est pas lisible depuis QML** : `token()`, `get()` et
`post()` sont de simples fonctions C++, ni `Q_PROPERTY` ni `Q_INVOKABLE`. Le plugin
obtient donc **son propre token** en s'authentifiant sur l'API avec l'identifiant de
l'utilisateur déjà connecté.

```
ensureToken()
  ├─ token déjà présent, ou login en cours   → ne rien faire
  ├─ connexion cloud / URL / utilisateur absent → message de diagnostic
  ├─ mot de passe disponible via cloudProp("password") → doLogin() direct
  └─ sinon → ouvrir la boîte de dialogue « Connexion QFieldCloud »

doLogin(password)
  POST {serverUrl}/api/v1/auth/login/
       { "username": <user>, "password": <mdp> }        (+ "email" si l'identifiant
                                                          a la forme d'un e-mail)
  ├─ 200 + token → authToken, tokenExpiresAt, enchaîne sur checkPackage()
  ├─ 400 / 401   → « Identifiants refusés », boîte rouverte avec le message
  └─ autre / 0   → « Connexion impossible au serveur (URL/SSL ?) »
```

Points de conception :

- **Le champ `email` n'est rempli que si l'identifiant en a la forme.** L'API accepte
  `username` **ou** `email` et privilégie `email` quand il est renseigné — mais un
  `EmailField` non valide ferait échouer toute la requête.
- **Le mot de passe ne survit pas à l'appel** : il est effacé du champ dès sa
  transmission, n'est stocké dans aucune propriété du plugin et n'est pas journalisé.
- **`authFailed`** empêche la boîte de dialogue de se rouvrir toute seule à chaque
  sondage (toutes les 3 s) après un refus ou une annulation. Seul le bouton
  **« Se connecter »** du panneau diagnostic la rouvre.
- **`invalidateToken()`** : un 401/403 en cours de route (token expiré ou révoqué)
  jette le token et relance le cycle d'authentification, sans lever `authFailed` —
  ce n'est pas l'utilisateur qui a échoué.
- Le token vit **en mémoire uniquement** : il est reperdu à la fermeture de QField, et
  le mot de passe est redemandé à la session suivante.

### 6.5 Détection des changements (sondages)

```
[Démarrage]  Component.onCompleted
      ├─ addItemToPluginsToolbar(toolbarButton)
      ├─ cloudConnection = resolveCloudConnection()
      ├─ checkDeltafile()      ← état local immédiat
      ├─ checkPackage()        ← déclenche l'authentification si nécessaire
      ├─ pollTimer.start()     ← serveur, toutes les 3 s
      └─ deltaTimer.start()    ← deltafile local, toutes les 400 ms

[400 ms]  checkDeltafile()
      GET file://{homePath}/deltafile.json
      └─ deltas.length > 0  → reportStale = true   (sablier)

[3 s]     checkPackage()
      GET {serverUrl}/api/v1/packages/{projectId}/latest/
          Authorization: Token {authToken}
      changeStamp = data_last_updated_at (repli sur packaged_at)
      ├─ 401 / 403 → invalidateToken() → ré-authentification
      ├─ changeStamp inchangé → rien à faire
      └─ changeStamp plus récent → fetchReport()

          fetchReport(changeStamp)
              GET {serverUrl}/api/v1/packages/{projectId}/latest/files/rapport_ife.json/
              ├─ 200 → report chargé, loaded = true, reportStale = false → bouton vert/rouge
              ├─ 404 → paquet sans rapport (validation non exécutée) ; changeStamp mémorisé
              └─ autre → erreur transitoire, réessai au prochain sondage
```

#### Pourquoi `data_last_updated_at` et non `packaged_at` ?

Un push (`delta_apply`) **régénère `rapport_ife.json` sans créer de job `package`**.
`packaged_at` (= `data_last_packaged_at`, qui ne bouge qu'au packaging) reste donc
**figé** après un push alors que le rapport a changé. Seul `data_last_updated_at`
avance à chaque push — c'est le bon signal. *(Bug constaté : `packaged_at = 13:52`
mais `rapport.genere_le = 13:58` après un push → le plugin ne retéléchargeait pas.)*

#### Deux sondages de cadences différentes

Le **deltafile** est sondé bien plus vite (400 ms) que le serveur (3 s) : c'est lui qui
signale le geste du technicien (saisie puis push), et attendre le tour de 3 s ferait
apparaître le sablier longtemps après le clic. Il s'agit d'une lecture locale de
quelques centaines d'octets, asynchrone comme les requêtes réseau — une lecture
bloquante à cette cadence finirait par se voir à l'usage.

`reportStale` est levé dès la première saisie et abaissé **seulement** à l'arrivée d'un
rapport frais : le sablier couvre donc tout l'intervalle saisie → push → validation →
rapport, sans trou au moment où QField vide le deltafile après l'envoi.

> Sur une URL `file://`, Qt laisse `status` à 0 même en cas de succès : c'est le corps
> de la réponse qui fait foi, pas le code HTTP. Le chemin doit par ailleurs être
> **absolu et commencer par `/`** — sous Windows `homePath` commence par `C:/`, et sans
> la barre ajoutée on obtient `file://C:/…` où `C:` est lu comme nom d'hôte, ce qui
> fait échouer la lecture silencieusement.

#### Amortissement et garde-fous

| Minuteur | Durée | Rôle |
|---|---|---|
| `pollTimer` | 3 s | sondage du paquet serveur |
| `deltaTimer` | 400 ms | sondage du deltafile local |
| `syncDelay` | 300 ms | retarde l'affichage du sablier — un aller-retour nominal dure quelques dizaines de ms, l'afficher sans délai le ferait clignoter à chaque sondage |
| `syncWatchdog` | 20 s | si le serveur ne répond jamais, `waitingForSync` resterait levé et figerait le plugin ; au-delà du délai on repart de zéro |

`waitingForSync` protège le cycle paquet → rapport contre le chevauchement ;
`deltaCheckInFlight` fait de même pour le sondage deltafile. `changeStamp` est mémorisé
aussi bien sur 200 que sur 404, de sorte qu'un rapport n'est retéléchargé que si les
données ont réellement changé — le serveur n'est pas martelé.

### 6.6 Interface

#### Bouton « IFA » (barre d'outils des plugins)

Ajouté via `iface.addItemToPluginsToolbar()`, c'est un **`ToolButton`**.

> ⚠️ Un `Rectangle` + `MouseArea` **s'affiche mais ne capte pas les clics** dans la
> barre d'outils des plugins. Un contrôle bouton natif est indispensable.

| État | Aspect | Signification |
|---|---|---|
| Non prêt | gris | rapport pas encore chargé, ou non authentifié |
| Valide | vert `#2e7d32` | `is_valid = true` |
| Invalide | rouge `#c62828` | `is_valid = false` |
| En attente | **sablier animé** | requête en vol (`syncVisible`) ou deltas en attente de validation (`reportStale`) |

Le sablier est **dessiné dans un `Canvas`** plutôt que rendu par le glyphe ⏳ : la barre
d'outils tourne sur Android comme sur desktop, et la présence d'une police couvrant les
emoji n'y est pas garantie. Il se **retourne** périodiquement plutôt que de tourner en
continu — un sablier qui tourne sans fin cesse d'être lu comme un sablier.

**Clic** : ouvre le panneau de rapport si celui-ci est prêt, sinon le panneau diagnostic.
Le bouton reste **cliquable même en gris**.

#### Panneau de rapport (`Drawer`, glisse depuis le bas)

- En-tête : titre, horodatage, badge **VALIDE / INVALIDE**
- Compteurs : Erreurs / Avertissements / Couches traitées
- Filtre de sévérité : Tout / Erreur / Avertissement
- Liste des anomalies : couche, code, message, champs concernés

> **Deux pièges corrigés :**
> - les `Drawer` sont parentés à **`iface.mainWindow().contentItem`** (un `Item` aux
>   dimensions valides) ; parenter à `iface.mainWindow()` empêche le panneau de s'afficher ;
> - la propriété `severityFilter` doit être portée par le **`Drawer`** (`reportPanel`),
>   puisqu'elle est référencée comme `reportPanel.severityFilter`. Déclarée ailleurs,
>   elle vaut `undefined`, le filtre retombe sur « avertissements uniquement » et la
>   liste des erreurs reste vide.

#### Panneau diagnostic

Affiche l'état réel pour lever tout doute. C'est l'outil de dépannage n°1 (voir §10).

| Champ | Contenu |
|---|---|
| **Utilisateur** | `cloudUsername` — l'utilisateur QFieldCloud connecté dans QField |
| **Serveur** | `serverUrl` résolu depuis la connexion cloud |
| **Session** | `non authentifié` / `authentification…` / `authentifié` |
| **Expire le** | `expires_at` renvoyé par l'API de login |
| **projectId** | UUID extrait du chemin |
| **HTTP login** | code de la dernière réponse `POST /auth/login/` |
| **HTTP paquet** | code de la dernière réponse `packages/{id}/latest/` |
| **HTTP rapport** | code de la dernière réponse `…/files/rapport_ife.json/` |
| **Màj données** | `data_last_updated_at` du dernier paquet |
| **Deltas en attente** | nombre de deltas lus dans `deltafile.json` |
| **Chemin projet** | `qgisProject.homePath` |

Trois boutons : **Se connecter** (visible tant qu'aucun token n'est détenu — seule
porte de sortie après une annulation, `authFailed` bloquant la réouverture
automatique), **Rafraîchir** (réinitialise `lastSeenPackagedAt` et relance les deux
sondages ; désactivé pendant une attente, sans quoi il paraîtrait sans effet) et
**Fermer**.

### 6.7 Limites connues

- **Mot de passe demandé à chaque session.** Le token n'est pas persisté ; à chaque
  redémarrage de QField, le plugin redemande le mot de passe de l'utilisateur connecté
  (sauf si QField expose `password`, ce qui n'est en général pas le cas).
- **API non documentée.** `QFieldCloudConnection` est atteint par
  `iface.findItemByObjectName()`, qui fait un `root->findChild<QObject*>(name)`. Une
  mise à jour de QField peut le renommer sans préavis. Tous les accès sont gardés — en
  cas de perte, le diagnostic affiche « Connexion QFieldCloud introuvable dans QField ».
- **Certificat SSL auto-signé** : le `XMLHttpRequest` de Qt peut le rejeter →
  `HTTP login = 0` ou `HTTP paquet = 0` dans le diagnostic. Voir §3.8 (Let's Encrypt).
- **`localhost`** ne désigne le serveur que si QField tourne sur la **même machine**
  (QField desktop). Sur mobile, `localhost` désigne le téléphone : QField doit être
  connecté au serveur par son **IP LAN** ou son **nom DNS** — le plugin suit
  automatiquement l'URL configurée dans QField.

---

## 7. Workflow complet

```
1. [QGIS Desktop] Préparer le projet
   ├─ Créer le projet QGS avec les couches IPE (mesurage, infor_gener, ...)
   ├─ Installer le plugin : python package_plugin.py --project-dir <dossier_projet>
   │     → crée {projet}.qml (copie de plugin_auth.qml) à côté du .qgs
   └─ Publier sur QFieldCloud (plugin QGIS QFieldSync)
         → QFieldCloud inclut automatiquement {projet}.qml dans le package

2. [QField] Collecte terrain
   ├─ Se connecter à QFieldCloud, synchroniser le projet (pull)
   ├─ Au premier affichage du rapport : saisir le mot de passe demandé par le plugin
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
   │   ├─ Injection de la couche dans le .qgs
   │   └─ Écriture rapport_ife.json
   └─ upload_project : GPKG + QGS + JSON uploadés

4. [QField — automatique, via plugin]
   ├─ Sablier dès la saisie (deltafile local, 400 ms)
   ├─ Le plugin interroge l'endpoint de packaging (3 s) et compare data_last_updated_at
   ├─ Dès que les données ont changé, il télécharge rapport_ife.json depuis l'API
   └─ Affiche le rapport (bouton IFA vert/rouge + panneau de détail)
```

---

## 8. Interface utilisateur (hors admin)

### 8.1 Le problème résolu

L'accueil `/` de QFieldCloud redirige vers l'admin Django. Or l'admin n'affiche
que les modèles sur lesquels le compte détient une permission : un utilisateur
`is_staff = True` **sans permission de modèle** y voit une **page vide**.

Plutôt que de distribuer des permissions d'admin — qui donneraient accès à des
écrans d'administration complets — un espace autonome a été ajouté sur
`/dashboard/`, indépendant du système de permissions de l'admin.

> ⚠️ **Ne jamais renvoyer un compte non superutilisateur vers `/admin/`.**
> L'admin le redirige vers la page de connexion, laquelle — le voyant déjà
> authentifié — le renvoie vers `LOGIN_REDIRECT_URL`, qui vaut `index`,
> c'est-à-dire l'accueil : le navigateur tourne en rond jusqu'à abandonner.
> C'est le comportement que présentait l'installation d'origine pour tout
> utilisateur connecté dépourvu du statut `is_staff`.

### 8.2 Les écrans

| Écran | URL | Contenu |
|---|---|---|
| Projets | `/dashboard/` | Ses projets et ceux de ses équipes, en deux listes distinctes |
| Détail projet | `/dashboard/projets/<uuid>/` | Fichiers du projet + historique des synchronisations |
| Mon profil | `/dashboard/profil/` | Prénom, nom, e-mail, lettre d'information |
| Mot de passe | `/dashboard/mot-de-passe/` | Changement de mot de passe |

Aiguillage de l'accueil, assuré par `views.index_redirect()` :

| Visiteur | Destination |
|---|---|
| Non identifié | page de connexion |
| Superutilisateur | `/admin/` |
| Tout autre compte | `/dashboard/` |

### 8.3 Fichiers

**Paquet autonome** `docker-app/qfieldcloud/core/dashboard/` :

| Fichier | Rôle |
|---|---|
| `scope.py` | **Règle de visibilité** — qui voit quels projets |
| `forms.py` | Formulaire du profil (+ synchronisation allauth) |
| `views.py` | Les 4 vues + l'aiguillage de la page d'accueil |
| `urls.py` | Routes, montées sur `/dashboard/` |

**Gabarits** `docker-app/qfieldcloud/core/templates/dashboard/` :
`base.html` (mise en page + menu), `projects.html`, `project_detail.html`,
`profile.html`, `password.html`.

Ils réutilisent les feuilles de style existantes (`vendor.css` Bootstrap,
`qfieldcloud.css`) et le contexte `whitelabel`, déjà global au projet — aucun
actif nouveau.

**Seul fichier existant modifié** — `docker-app/qfieldcloud/urls.py` :

```python
from qfieldcloud.core.dashboard.views import index_redirect

path("", index_redirect, name="index"),
path("dashboard/", include("qfieldcloud.core.dashboard.urls")),
```

Le nom de route `index` est conservé : il est référencé ailleurs, notamment par
`LOGIN_REDIRECT_URL`. **Aucune migration** : la customisation n'ajoute aucun
modèle.

### 8.4 Principes de conception

#### a) Le rattachement se fait par l'activité, pas par la propriété

Un technicien qui synchronise un projet d'équipe n'en est pas propriétaire ; se
fonder sur `Project.owner` ne montrerait donc rien. La visibilité est déduite
des **synchronisations** (`Job.created_by`) :

- **« Mes projets »** — projets ayant au moins un `Job` créé par l'utilisateur ;
- **« Projets des équipes »** — projets ayant au moins un `Job` créé par un
  **coéquipier**, l'utilisateur étant exclu de cette liste ; sans cette
  exclusion, tout projet personnel réapparaîtrait dans la seconde liste.

Les équipes viennent de `TeamMember` :
`Team.objects.filter(members__member=user)`.

#### b) Tout passe par `scope.py`

Ce module est le **seul** endroit qui décide de la visibilité. La vue de détail
n'a pas sa propre règle : elle interroge `scope.visible_projects(user)` et
renvoie 404 si le projet n'y figure pas — ce qui ne révèle même pas son
existence. Modifier la règle se fait donc à un seul endroit.

#### c) « Mis à jour par » vient du dernier job

`Project.updated_at` dit *que* quelque chose a changé, jamais *par qui*.
`scope.with_last_sync()` annote donc chaque projet avec le dernier `Job`
(`last_sync_at`, `last_sync_by`, `last_sync_type`) au moyen d'un `Subquery`, en
une seule requête plutôt qu'une par ligne.

#### d) L'e-mail doit être synchronisé avec allauth

`ACCOUNT_LOGIN_METHODS` autorise la connexion par e-mail, et allauth n'interroge
pas `User.email` mais sa propre table `EmailAddress`. Modifier `User.email` seul
laisserait l'utilisateur se connecter avec son **ancienne** adresse.
`ProfileForm._sync_allauth_email()` répercute le changement et repasse l'adresse
en « non vérifiée » — sans conséquence sur la connexion tant que
`ACCOUNT_EMAIL_VERIFICATION=optional` (voir §5.1).

Le **nom d'utilisateur reste non modifiable** : il apparaît dans les chemins de
stockage des projets et dans les noms d'équipe (`@organisation/equipe`).

### 8.5 Étendre le tableau de bord

**Ajouter un écran** — trois gestes :

1. une vue dans `views.py`, héritant de `DashboardContextMixin` (elle fournit
   `menu` et `admin_uri` au gabarit) ;
2. une route dans `urls.py` ;
3. un gabarit qui fait `{% extends "dashboard/base.html" %}` ; ajouter l'entrée
   correspondante dans le menu de `base.html`.

**Changer la règle de visibilité** — modifier `scope.py` seul. Par exemple, pour
inclure aussi les projets dont l'utilisateur est propriétaire :

```python
def own_project_ids(user):
    from django.db.models import Q
    return Project.objects.filter(
        Q(jobs__created_by=user) | Q(owner=user)
    ).values_list("id", flat=True)
```

**Prise en compte des modifications** — le code Python est monté dans le
conteneur `app` : un redémarrage suffit, sans reconstruction d'image.

```bash
docker compose restart app
```

### 8.6 Notes

- Les libellés sont écrits **en français directement**, sans `{% translate %}` :
  c'est une customisation propre au déploiement IFA. Pour l'internationaliser,
  encadrer les chaînes de `{% translate %}` et alimenter les fichiers `.po`.
- L'historique des synchronisations est paginé (`JOBS_PER_PAGE = 25` dans
  `views.py`).
- Le tableau de bord reste vide tant que le compte n'a lancé aucune
  synchronisation : c'est le comportement voulu. Pour le voir peuplé, il faut un
  push depuis QField ou un rattachement à une équipe déjà active.

---

## 9. Exploitation et mises à jour

### Rebuild après modification de `validate_ifa.py` ou du moteur

```bash
# Reconstruire l'image QGIS
docker compose build qgis

# Recréer le worker (pas restart : il faut relire les variables)
docker compose up -d worker_wrapper
```

### Vérifier les variables d'environnement dans le conteneur

```bash
docker compose exec worker_wrapper env | grep VALIDATION_PG
```

### Mise à jour du plugin QField

```bash
python formulaires/package_plugin.py --project-dir "chemin/vers/projet"
```

Puis, **dans cet ordre** : synchroniser via **QFieldSync** dans QGIS Desktop (upload du
`.qml`), puis **synchroniser dans QField** pour retélécharger le plugin. Sans la
seconde étape, QField garde l'ancienne version.

> Il n'y a **plus de token à régénérer ni à renouveler** : le plugin s'authentifie
> lui-même (§6.4). Une mise à jour du plugin ne nécessite donc aucune manipulation
> côté serveur.

### Renouvellement du certificat TLS

```bash
docker compose run --rm --entrypoint certbot certbot renew --dry-run
```

---

## 10. Dépannage

### « aucun GPKG IPE trouvé »

**Cause probable :** le projet ne contient pas de GPKG avec les tables IPE, ou ces
tables portent un nom non reconnu.

```bash
# Lister les tables SQLite du GPKG
sqlite3 chemin/vers/data.gpkg ".tables"

# Vérifier les entrées gpkg_contents
sqlite3 chemin/vers/data.gpkg "SELECT table_name FROM gpkg_contents;"
```

La détection cherche des tables dont le nom commence par `mesurage` ou `infor_gener`
(exact ou préfixé par un UUID QFieldCloud). Si les noms diffèrent, mettre à jour
`_IPE_SIGNATURE_TABLES` dans `validate_ifa.py`.

---

### « Connexion PostgreSQL échouée : connection refused »

**Cause probable :** `VALIDATION_PG_HOST` vaut `localhost`, qui depuis le conteneur
désigne le conteneur lui-même, pas la machine hôte.

**Solution :** vérifier que `.env` contient `VALIDATION_PG_HOST=host.docker.internal`
et recréer le conteneur (`docker compose up -d worker_wrapper`). **Sous Linux**,
vérifier en plus que `extra_hosts={"host.docker.internal": "host-gateway"}` a bien été
ajouté dans `wrapper.py` (§3.5), et que `pg_hba.conf` autorise `172.16.0.0/12` (§3.6).

---

### `'ValidationReport' object has no attribute 'error_count'`

**Cause :** code utilisant `result.error_count` au lieu de `len(result.errors)`.

`ValidationReport` expose `errors` et `warnings` comme `@property` (listes), pas comme
attributs scalaires.

---

### La couche `rapport_validation` n'apparaît pas dans QField

1. Vérifier que la table existe dans le GPKG :
   ```bash
   sqlite3 data.gpkg "SELECT * FROM gpkg_contents;"
   ```
2. Vérifier que la couche est dans le `.qgs` :
   ```bash
   grep "rapport_validation" projet.qgs
   ```
3. Si absente du `.qgs`, consulter les logs du job QFieldCloud dans l'interface web
   pour comprendre pourquoi `_add_rapport_layer_to_qgs` a échoué.
4. S'assurer que le technicien a bien **re-synchronisé** après le push : la couche
   n'arrive que par une synchronisation descendante (contrairement au rapport JSON, lu
   directement depuis l'API).

---

### Le plugin ne s'affiche pas dans QField

- le fichier `{projet}.qml` est présent à côté du `.qgs` dans le dossier QGIS Desktop ;
- le projet a été synchronisé via QFieldSync après l'ajout du `.qml` ;
- un job de packaging a été relancé sur QFieldCloud ;
- la version de QField supporte les plugins QML (≥ 2.5) ;
- consulter les logs QField (Paramètres → À propos → Journaux).

---

### Le bouton IFA reste gris → ouvrir le panneau diagnostic

Le bouton est **cliquable même en gris** : un clic ouvre le panneau diagnostic. Lire
d'abord **Utilisateur**, **Serveur**, **Session** et **projectId**, puis les codes HTTP.

| Symptôme dans le diagnostic | Cause | Correctif |
|---|---|---|
| « Connexion QFieldCloud introuvable dans QField » | `findItemByObjectName()` n'a rien trouvé (version de QField ayant renommé l'objet) | vérifier la version de QField ; ajouter le nouveau nom dans `resolveCloudConnection()` |
| **Utilisateur** vide / « Aucun utilisateur QFieldCloud connecté » | QField n'est pas connecté au cloud | se connecter à QFieldCloud dans QField |
| **Serveur** = `(inconnu)` | la propriété `url` n'est pas exposée | vérifier la connexion cloud dans QField |
| **Session** = `non authentifié` | mot de passe non saisi, ou saisie annulée | bouton **Se connecter** dans le panneau |
| **HTTP login** = **400 / 401** | identifiants refusés | vérifier le mot de passe du compte QFieldCloud affiché dans **Utilisateur** |
| **HTTP login** = **0** | serveur injoignable : SSL auto-signé, URL erronée, réseau | installer un certificat reconnu (§3.8) ou faire confiance au rootCA (§2, étape 8) |
| **projectId** vide / **Chemin projet** vide | `qgisProject.homePath` non résolu, ou projet non cloud | ouvrir le projet depuis QFieldCloud (dossier `cloud_projects/{org}/{uuid}/`) |
| **HTTP paquet** = **401 / 403** | token expiré ou révoqué | le plugin se ré-authentifie seul ; si la boucle persiste, vérifier **HTTP login** |
| **HTTP paquet** = **400** | projet jamais packagé sur QFieldCloud | lancer un packaging (push ou re-publication) |
| **HTTP paquet** = **0** | connexion impossible | idem **HTTP login = 0** |
| **HTTP rapport** = **404** | paquet OK mais validation non exécutée | vérifier `validate_ife_data` côté serveur (GPKG / PostgreSQL ci-dessus) |
| Tout **200** mais bouton gris/sablier | modifications locales en attente (**Deltas en attente** > 0) | pousser / synchroniser ; le bouton se met à jour après la re-validation serveur (avance de **Màj données**) |
| « Délai dépassé — le serveur n'a pas répondu » | le watchdog de 20 s s'est déclenché | connexion instable ou serveur bloqué ; vérifier `docker compose logs -f app worker_wrapper` |

**Tests manuels de l'API (mêmes appels que le plugin)**

```bash
# 1) obtenir un token
curl -k -X POST -H "Content-Type: application/json" \
  -d '{"username":"<user>","password":"<mdp>"}' \
  "https://<serveur>/api/v1/auth/login/"

# 2) métadonnées du paquet (data_last_updated_at, packaged_at)
curl -k -H "Authorization: Token <token>" \
  "https://<serveur>/api/v1/packages/<uuid>/latest/"

# 3) téléchargement du rapport
curl -k -H "Authorization: Token <token>" \
  "https://<serveur>/api/v1/packages/<uuid>/latest/files/rapport_ife.json/"
```

> Le `-k` désactive la vérification TLS. Si les appels ne passent **qu'avec** `-k`, le
> plugin échouera lui aussi (`HTTP … = 0`) : c'est le certificat qu'il faut corriger.

---

### La boîte de mot de passe se rouvre en boucle

Elle ne devrait pas : `authFailed` est levé après un refus ou une annulation et bloque
la réouverture automatique. Si le comportement se reproduit, c'est que le login réussit
puis que le token est immédiatement rejeté — vérifier **HTTP login** (200 attendu) et
**HTTP paquet** (401 ⇒ le token émis n'est pas accepté, contrôler l'heure système du
serveur et la validité de la session côté Django).

---

### Le clic sur le bouton n'ouvre aucun panneau

- **Bouton non cliquable** → le plugin utilise un `Rectangle` + `MouseArea` au lieu
  d'un `ToolButton` (§6.6).
- **Bouton cliquable mais aucun panneau** → le `Drawer` est parenté à
  `iface.mainWindow()` au lieu de `iface.mainWindow().contentItem` (§6.6).

---

### Le panneau s'affiche mais la liste des erreurs est vide

`severityFilter` est déclarée sur le `ColumnLayout` alors qu'elle est référencée comme
`reportPanel.severityFilter` : elle vaut `undefined`, le filtre par défaut retombe sur
« avertissements uniquement » et masque les erreurs. La déclarer sur le `Drawer`
`reportPanel` (§6.6).
