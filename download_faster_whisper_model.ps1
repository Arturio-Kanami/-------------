param(
    [string]$Model = "medium",
    [string]$Mirror = "https://hf-mirror.com"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = "Systran/faster-whisper-$Model"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$modelDir = Join-Path $root "models\faster-whisper-$Model"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

$apiUrl = "$Mirror/api/models/$repo"
Write-Host "Fetching model file list: $repo"
$metaText = & curl.exe -L --fail --silent --show-error --max-time 60 $apiUrl
if ($LASTEXITCODE -ne 0 -or -not $metaText) {
    throw "Failed to query model metadata from $apiUrl"
}

$meta = $metaText | ConvertFrom-Json
$files = @()
foreach ($sibling in $meta.siblings) {
    $name = [string]$sibling.rfilename
    if (-not $name) { continue }
    if ($name -eq ".gitattributes" -or $name -eq "README.md") { continue }
    $files += $name
}

if ($files.Count -eq 0) {
    throw "No downloadable model files found for $repo"
}

foreach ($file in $files) {
    $target = Join-Path $modelDir $file
    $targetParent = Split-Path -Parent $target
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null

    if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target).Length -gt 0)) {
        Write-Host "Exists: $file"
        continue
    }

    $urlFile = $file -replace "\\", "/"
    $url = "$Mirror/$repo/resolve/main/$urlFile"
    Write-Host "Downloading: $file"
    & curl.exe -L --fail --silent --show-error --retry 3 --retry-delay 2 --connect-timeout 30 --output $target $url
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
        throw "Failed to download $file"
    }
}

$modelBin = Join-Path $modelDir "model.bin"
if (-not (Test-Path -LiteralPath $modelBin)) {
    throw "Downloaded model is incomplete: model.bin is missing."
}

Write-Host "Model ready: $modelDir"
Write-Output $modelDir
