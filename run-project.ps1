$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating the Python 3.12 environment..."
    py -3.12 -m venv .venv
}

& $python -m pip check
$dependencyCheckExitCode = $LASTEXITCODE
$dotenvAvailable = $false
& $python -c "import dotenv" 2>$null
$dotenvImportExitCode = $LASTEXITCODE
if ($dotenvImportExitCode -eq 0) {
    $dotenvAvailable = $true
}
if ($dependencyCheckExitCode -ne 0 -or -not $dotenvAvailable) {
    Write-Host "Installing project dependencies..."
    & $python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
}

$secretFile = Join-Path $PSScriptRoot ".flask_secret"
if (-not (Test-Path $secretFile)) {
    $secret = & $python -c "import secrets; print(secrets.token_hex(32))"
    Set-Content -Path $secretFile -Value $secret -NoNewline
}
if (-not $env:FLASK_SECRET_KEY) {
    $dotenvSecret = & $python -c "from dotenv import dotenv_values; print(dotenv_values(r'backend\.env').get('FLASK_SECRET_KEY') or '')"
    if ($dotenvSecret) {
        $env:FLASK_SECRET_KEY = $dotenvSecret
    }
    else {
        $env:FLASK_SECRET_KEY = (Get-Content -Path $secretFile -Raw).Trim()
    }
}

Write-Host "Starting CircuitCycle at http://localhost:5000"
& $python -m backend.app
