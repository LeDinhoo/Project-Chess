$ChessComUsername = "Le_Dinho"
$StockfishInput = "C:\Users\Dinho\Downloads\stockfish-windows-x86-64-universal\stockfish"

Write-Host "`n=== Vérification environnement chess-trainer ===`n" -ForegroundColor Cyan

$AllOk = $true
$StockfishPath = $null

function Check-Command {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    try {
        $Result = & $Command 2>&1

        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw ($Result | Out-String)
        }

        Write-Host "[OK] $Name" -ForegroundColor Green
        Write-Host "     $($Result | Select-Object -First 1)"
    }
    catch {
        Write-Host "[ERREUR] $Name" -ForegroundColor Red
        Write-Host "         $_"
        $script:AllOk = $false
    }
}

# --------------------------------------------------
# Git
# --------------------------------------------------

Check-Command "Git" {
    git --version
}

# --------------------------------------------------
# Python 3.14
# --------------------------------------------------

Check-Command "Python 3.14" {
    py -3.14 --version
}

# Python venv
try {
    $Result = py -3.14 -c "import venv; print('venv disponible')" 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Module Python venv" -ForegroundColor Green
    }
    else {
        throw ($Result | Out-String)
    }
}
catch {
    Write-Host "[ERREUR] Module Python venv" -ForegroundColor Red
    Write-Host "         $_"
    $AllOk = $false
}

# SQLite intégré à Python
try {
    $SqliteVersion = py -3.14 -c "import sqlite3; print(sqlite3.sqlite_version)" 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] SQLite Python ($SqliteVersion)" -ForegroundColor Green
    }
    else {
        throw ($SqliteVersion | Out-String)
    }
}
catch {
    Write-Host "[ERREUR] SQLite Python" -ForegroundColor Red
    Write-Host "         $_"
    $AllOk = $false
}

# Support Zstandard Python 3.14
try {
    $Zstd = py -3.14 -c "import compression.zstd; print('compression.zstd disponible')" 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] compression.zstd Python 3.14" -ForegroundColor Green
    }
    else {
        Write-Host "[INFO] compression.zstd non disponible dans ce runtime" -ForegroundColor Yellow
        Write-Host "       Ce n'est pas bloquant pour commencer."
        Write-Host "       Ce sera vérifié au moment de l'import Lichess."
    }
}
catch {
    Write-Host "[INFO] compression.zstd non disponible" -ForegroundColor Yellow
}

# --------------------------------------------------
# Node.js + npm
# --------------------------------------------------

Check-Command "Node.js" {
    node --version
}

Check-Command "npm" {
    npm --version
}

# --------------------------------------------------
# Stockfish
# Accepte un dossier OU un chemin direct vers le .exe
# --------------------------------------------------

if (Test-Path -LiteralPath $StockfishInput -PathType Leaf) {

    $StockfishPath = (Resolve-Path -LiteralPath $StockfishInput).Path

}
elseif (Test-Path -LiteralPath $StockfishInput -PathType Container) {

    $Candidates = Get-ChildItem `
        -LiteralPath $StockfishInput `
        -Filter "stockfish*.exe" `
        -File `
        -Recurse `
        -ErrorAction SilentlyContinue

    if ($Candidates.Count -eq 1) {
        $StockfishPath = $Candidates[0].FullName
    }
    elseif ($Candidates.Count -gt 1) {
        Write-Host "[INFO] Plusieurs exécutables Stockfish trouvés :" -ForegroundColor Yellow

        foreach ($Candidate in $Candidates) {
            Write-Host "       $($Candidate.FullName)"
        }

        # Prend le premier pour le test
        $StockfishPath = $Candidates[0].FullName

        Write-Host "[INFO] Utilisation pour le test :" -ForegroundColor Yellow
        Write-Host "       $StockfishPath"
    }
}
else {
    # Cas où l'utilisateur donne le chemin sans extension .exe
    if (Test-Path -LiteralPath "$StockfishInput.exe" -PathType Leaf) {
        $StockfishPath = (Resolve-Path -LiteralPath "$StockfishInput.exe").Path
    }
}

if ($StockfishPath) {

    Write-Host "[OK] Stockfish trouvé" -ForegroundColor Green
    Write-Host "     $StockfishPath"

    try {
        $StockfishOutput = @(
            "uci"
            "quit"
        ) | & $StockfishPath 2>&1

        if ($StockfishOutput -match "uciok") {
            Write-Host "[OK] Stockfish répond au protocole UCI" -ForegroundColor Green

            $IdName = $StockfishOutput |
                Where-Object { $_ -match "^id name " } |
                Select-Object -First 1

            if ($IdName) {
                Write-Host "     $IdName"
            }
        }
        else {
            Write-Host "[ERREUR] Stockfish démarre mais ne renvoie pas 'uciok'" -ForegroundColor Red
            $AllOk = $false
        }
    }
    catch {
        Write-Host "[ERREUR] Impossible d'exécuter Stockfish" -ForegroundColor Red
        Write-Host "         $_"
        $AllOk = $false
    }

}
else {

    Write-Host "[ERREUR] Exécutable Stockfish introuvable" -ForegroundColor Red
    Write-Host "         Chemin testé : $StockfishInput"
    Write-Host ""
    Write-Host "Vérifie le contenu avec :" -ForegroundColor Yellow
    Write-Host "Get-ChildItem `"$StockfishInput`" -Recurse -Filter `"stockfish*.exe`""
    $AllOk = $false
}

# --------------------------------------------------
# Chess.com
# --------------------------------------------------

try {

    $EncodedUsername = [uri]::EscapeDataString($ChessComUsername)

    $Headers = @{
        "User-Agent" = "chess-trainer-local/1.0 ($ChessComUsername)"
    }

    $Player = Invoke-RestMethod `
        -Uri "https://api.chess.com/pub/player/$EncodedUsername" `
        -Headers $Headers `
        -TimeoutSec 15

    if ($Player.username) {
        Write-Host "[OK] Chess.com accessible" -ForegroundColor Green
        Write-Host "     Compte trouvé : $($Player.username)"
    }
    else {
        throw "Réponse Chess.com inattendue."
    }

}
catch {

    Write-Host "[ERREUR] Vérification Chess.com" -ForegroundColor Red
    Write-Host "         $_"
    $AllOk = $false
}

# --------------------------------------------------
# Résumé + configuration à conserver
# --------------------------------------------------

Write-Host "`n============================================" -ForegroundColor Cyan

if ($AllOk) {

    Write-Host "TOUT EST PRÊT ✅" -ForegroundColor Green
    Write-Host ""
    Write-Host "Valeurs à utiliser dans config.json :" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "chesscom_username : $ChessComUsername"
    Write-Host "stockfish_path     : $StockfishPath"
    Write-Host "initial_games      : 20"
    Write-Host ""
    Write-Host "Tu peux lancer ton prompt de création."

}
else {

    Write-Host "IL RESTE DES ÉLÉMENTS À CORRIGER ❌" -ForegroundColor Red
    Write-Host "Regarde les lignes [ERREUR] ci-dessus."

}

Write-Host "============================================`n" -ForegroundColor Cyan
