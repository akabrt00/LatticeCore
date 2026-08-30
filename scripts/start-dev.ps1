[CmdletBinding()]
param(
    [switch]$CreateVenv,
    [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js nebyl nalezen. Nainstalujte Node.js 20.19 nebo novější."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm nebyl nalezen."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if ($CreateVenv -and -not (Test-Path -LiteralPath $VenvPython)) {
    $Bootstrap = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Bootstrap) { $Bootstrap = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $Bootstrap) { throw "Python nebyl nalezen." }
    $answer = Read-Host "Vytvořit lokální .venv? [a/N]"
    if ($answer -match "^[aAyY]$") {
        if ($Bootstrap.Name -eq "py.exe") { & $Bootstrap.Source -3 -m venv .venv }
        else { & $Bootstrap.Source -m venv .venv }
    }
}

if (Test-Path -LiteralPath $VenvPython) {
    $env:LATTICECORE_PYTHON = $VenvPython
} elseif (-not $env:LATTICECORE_PYTHON) {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) { $PythonCommand = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $PythonCommand) { throw "Python nebyl nalezen." }
    $env:LATTICECORE_PYTHON = $PythonCommand.Source
}

if ($InstallDependencies) {
    $answer = Read-Host "Nainstalovat nebo aktualizovat závislosti? [a/N]"
    if ($answer -match "^[aAyY]$") {
        & $env:LATTICECORE_PYTHON -m pip install -r requirements.txt
        npm.cmd install
    }
}

& $env:LATTICECORE_PYTHON -c "import numpy, scipy, pyvista, vtk" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Python závislosti chybí. Spusťte skript s -InstallDependencies."
}
if (-not (Test-Path -LiteralPath (Join-Path $Root "node_modules"))) {
    throw "Node závislosti chybí. Spusťte npm install nebo skript s -InstallDependencies."
}

npm.cmd run dev
