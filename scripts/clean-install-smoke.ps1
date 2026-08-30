[CmdletBinding()]
param([switch]$RunInstall)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not $RunInstall) {
    Write-Host "Dry-run: použijte -RunInstall pro vytvoření dočasného čistého prostředí."
    npm.cmd run test:all
    exit $LASTEXITCODE
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("latticecore-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $TempRoot | Out-Null
try {
    git archive HEAD -o (Join-Path $TempRoot "source.zip")
    Expand-Archive -LiteralPath (Join-Path $TempRoot "source.zip") -DestinationPath (Join-Path $TempRoot "source")
    Set-Location -LiteralPath (Join-Path $TempRoot "source")
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    npm.cmd ci
    $env:LATTICECORE_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe)
    npm.cmd run test:all
} finally {
    Set-Location -LiteralPath $Root
    Write-Host "Dočasné prostředí zůstává pro audit: $TempRoot"
}
