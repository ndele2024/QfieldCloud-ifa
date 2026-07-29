#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# Génère un token QFieldCloud et l'insère en base via le modèle AuthToken.
#
# Le modèle gère la génération de la clé + l'expiration + l'insertion en base.
#
# client_type = "cli" → type IDÉAL pour un token codé en dur :
#   il n'est PAS dans single_token_clients ([QFIELD, QFIELDSYNC, UNKNOWN]),
#   donc il n'est JAMAIS invalidé — ni par les reconnexions QField/QGIS,
#   ni par la génération d'autres tokens. (Un token "unknown" au contraire
#   est tué dès qu'un nouveau token "unknown" est créé.)
#
# Usage :
#   ./mint_token.sh                 # user=admin, expiration 365 jours
#   ./mint_token.sh alice           # user=alice, expiration 365 jours
#   ./mint_token.sh admin 30        # user=admin, expiration forcée à 30 jours
#
# À lancer depuis Git Bash (le script utilise « docker compose »).
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Se place dans le dossier du script (= dossier du docker-compose.yml)
cd "$(dirname "$0")"

USERNAME="${1:-admin}"
DAYS="${2:-365}"

docker compose exec -T app python manage.py shell -c "
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import User
from django.utils import timezone
from datetime import timedelta

u = User.objects.get(username='${USERNAME}')
# client_type=CLI → hors single_token_clients → token stable, jamais invalidé
t = AuthToken.objects.create(user=u, client_type=AuthToken.ClientType.CLI)
t.expires_at = timezone.now() + timedelta(days=int('${DAYS}'))
t.save()

print('TOKEN   = ' + t.key)
print('USER    = ' + u.username)
print('CLIENT  = ' + t.client_type)
print('EXPIRES = ' + str(t.expires_at))
"
