<#
.SYNOPSIS
    Génère un token QFieldCloud (type CLI, stable) et l'insère en base.

.DESCRIPTION
    Passe par le modèle AuthToken (shell Django dans le conteneur « app ») :
    génération de la clé + expiration + insertion en base en une opération.

    client_type = CLI → hors single_token_clients ([QFIELD, QFIELDSYNC, UNKNOWN]),
    donc le token n'est JAMAIS invalidé — ni par les reconnexions QField/QGIS,
    ni par la génération d'autres tokens. Idéal pour un token codé en dur.

.PARAMETER Username
    Nom d'utilisateur QFieldCloud (défaut : admin).

.PARAMETER Days
    Durée de validité en jours (défaut : 365).

.EXAMPLE
    .\mint_token.ps1
    .\mint_token.ps1 -Username alice
    .\mint_token.ps1 -Username admin -Days 30

.NOTES
    Si l'exécution est bloquée par la politique de scripts :
        powershell -ExecutionPolicy Bypass -File .\mint_token.ps1
#>
param(
    [string]$Username = "admin",
    [int]$Days = 365
)

$ErrorActionPreference = "Stop"

# Se place dans le dossier du script (= dossier du docker-compose.yml)
Set-Location -Path $PSScriptRoot

# Code Python passé à « manage.py shell -c ».
# N'utilise QUE des apostrophes simples (pas de guillemets doubles) pour
# éviter tout problème d'échappement lors du passage à docker.
$py = @"
from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import User
from django.utils import timezone
from datetime import timedelta
u = User.objects.get(username='$Username')
t = AuthToken.objects.create(user=u, client_type=AuthToken.ClientType.CLI)
t.expires_at = timezone.now() + timedelta(days=$Days)
t.save()
print('TOKEN   = ' + t.key)
print('USER    = ' + u.username)
print('CLIENT  = ' + t.client_type)
print('EXPIRES = ' + str(t.expires_at))
"@

docker compose exec -T app python manage.py shell -c $py
