# Hook SessionStart - synchronise le depot avant de travailler.
#
# Regle absolue : ce script ne doit JAMAIS bloquer ni faire echouer une
# session. Toute erreur est avalee et le code de sortie reste 0.
#
# `--ff-only` est volontaire : en cas de divergence reelle entre machines, on
# preferer echouer silencieusement ici et laisser l'humain arbitrer, plutot
# que de fabriquer un merge automatique dans le dos de la session.

$ErrorActionPreference = 'Continue'

try {
    $repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    Set-Location -Path $repo -ErrorAction Stop

    # Pas de depot git, ou pas de remote : rien a faire, et ce n'est pas une erreur.
    if (-not (Test-Path (Join-Path $repo '.git'))) { exit 0 }
    $remotes = git remote
    if (-not $remotes) { exit 0 }

    git pull --ff-only --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[wiki] git pull --ff-only sans effet (divergence, hors ligne ou arbre modifie) - ignore."
    }
}
catch {
    Write-Host "[wiki] SessionStart ignore : $($_.Exception.Message)"
}

exit 0
