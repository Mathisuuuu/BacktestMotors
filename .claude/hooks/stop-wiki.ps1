# Hook Stop - regenere wiki/hot.md, puis commite et pousse si l'arbre a change.
#
# Regle absolue : ce script ne doit JAMAIS faire echouer une session. Chaque
# etape est isolee dans son propre try/catch, et le code de sortie est
# toujours 0. Un wiki non pousse est un desagrement ; une session cassee est
# un probleme.

$ErrorActionPreference = 'Continue'

# --- Perimetre du commit automatique ---------------------------------------
# $true  : ne commite que wiki/ (+ les fichiers de config du wiki).
# $false : commite tout l'arbre de travail (`git add -A`).
#
# Bascule a $true le 2026-09-15, sur incident. Le `git add -A` a commite
# tests/fixtures/empreintes_attendues.json EN COURS D'ECRITURE par un run de
# fond : l'entree Zarattini ne portait que son symbole, et test_composition
# echouait sur un clone frais. Le hook ne peut pas savoir qu'un fichier est a
# moitie ecrit, et une session qui lance des runs en arriere-plan en produit
# regulierement.
#
# Ce qui change : src/, tests/ et examples/ ne partent plus tout seuls. Ils se
# commitent a la main, avec un message qui dit ce qui a ete fait - ce que les
# douze `sync automatique` du 2026-09-15 ne faisaient pas.
#
# Remettre a $false pour retrouver la synchronisation complete entre machines,
# en sachant que l'incident ci-dessus redeviendra possible.
$WikiOnly = $true
# ---------------------------------------------------------------------------

function Get-PythonCommand {
    foreach ($candidate in @('python', 'python3', 'py')) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

$repo = $null
try {
    $repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    Set-Location -Path $repo -ErrorAction Stop
}
catch {
    exit 0
}

# --- 1. Regenerer hot.md ----------------------------------------------------
try {
    $script = Join-Path $repo 'wiki\update_hot.py'
    $python = Get-PythonCommand
    if ($python -and (Test-Path $script)) {
        & $python $script | Out-Null
    }
}
catch {
    Write-Host "[wiki] regeneration de hot.md ignoree : $($_.Exception.Message)"
}

# --- 2. Commiter et pousser -------------------------------------------------
try {
    if (-not (Test-Path (Join-Path $repo '.git'))) { exit 0 }

    if ($WikiOnly) {
        git add -- wiki .claude/settings.json .claude/hooks CLAUDE.md | Out-Null
    }
    else {
        git add -A | Out-Null
    }

    # Rien d'indexe : rien a commiter, et surtout pas de commit vide.
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { exit 0 }

    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'
    git commit --quiet -m "chore(wiki): sync automatique $stamp" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[wiki] commit refuse (hook pre-commit ?) - ignore."
        exit 0
    }

    $remotes = git remote
    if (-not $remotes) { exit 0 }

    git push --quiet | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[wiki] push echoue (hors ligne ou divergence) - le commit local est fait."
    }
}
catch {
    Write-Host "[wiki] Stop ignore : $($_.Exception.Message)"
}

exit 0
