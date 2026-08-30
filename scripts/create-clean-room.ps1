[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DestinationPath = [System.IO.Path]::GetFullPath($Destination)
$RootPath = [System.IO.Path]::GetFullPath($Root)

if ($DestinationPath -eq $RootPath -or $DestinationPath.StartsWith($RootPath + [System.IO.Path]::DirectorySeparatorChar)) {
    throw "Clean-room destination must be outside the source repository."
}
if (Test-Path -LiteralPath $DestinationPath) {
    $existing = Get-ChildItem -LiteralPath $DestinationPath -Force
    if ($existing.Count -gt 0) {
        throw "Clean-room destination must be new or empty."
    }
} else {
    New-Item -ItemType Directory -Path $DestinationPath | Out-Null
}

$ExcludedCategories = @(
    ".git metadata",
    "node_modules",
    "Python virtual environments",
    "Python bytecode and test caches",
    "dist and build output",
    "calculation cache",
    "job and result storage",
    "exports and local STL/OBJ models",
    "logs and temporary files"
)
$ExcludedTopLevels = @(
    ".git", "node_modules", ".venv", "__pycache__", ".pytest_cache",
    "dist", "build", "cache", "job-storage", "result-storage", "exports"
)

$relativeFiles = @(
    git -C $RootPath -c core.quotepath=false ls-files --cached --others --exclude-standard
) | Where-Object { $_ -and $_.Trim() }

$manifestFiles = [System.Collections.Generic.List[object]]::new()
foreach ($relative in ($relativeFiles | Sort-Object -Unique)) {
    if ([System.IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Unsafe relative path returned by git."
    }
    $normalized = $relative.Replace("\", "/")
    $topLevel = $normalized.Split("/")[0]
    if ($ExcludedTopLevels -contains $topLevel) {
        continue
    }
    if ($normalized -match '(^|/)(__pycache__|\.pytest_cache)(/|$)' -or $normalized -match '\.py[co]$') {
        continue
    }
    if ($normalized -match '\.(stl|obj|log|tmp)$') {
        continue
    }

    $source = Join-Path $RootPath $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        continue
    }
    $target = Join-Path $DestinationPath $relative
    $targetDirectory = Split-Path -Parent $target
    New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $target
    $item = Get-Item -LiteralPath $target
    $manifestFiles.Add([ordered]@{
        path = $normalized
        sizeBytes = $item.Length
        sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    })
}

$manifest = [ordered]@{
    schemaVersion = 1
    createdAt = (Get-Date).ToUniversalTime().ToString("o")
    source = "current git working tree (tracked and untracked, non-ignored files)"
    excludedCategories = $ExcludedCategories
    fileCount = $manifestFiles.Count
    files = $manifestFiles
}
$manifestPath = Join-Path $DestinationPath "clean-room-manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

[pscustomobject]@{
    destinationName = Split-Path -Leaf $DestinationPath
    fileCount = $manifestFiles.Count
    manifest = "clean-room-manifest.json"
}
