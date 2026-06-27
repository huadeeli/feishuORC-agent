$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $ProjectRoot "dist"
$SourceDir = Join-Path $DistRoot "orc-calc"
$StageRoot = Join-Path $DistRoot "orc-calc-portable"
$StageApp = Join-Path $StageRoot "orc-calc"
$ZipPath = Join-Path $DistRoot "orc-calc-portable.zip"
$CacheSource = $env:ORC_CALC_OCR_CACHE_DIR

if ([string]::IsNullOrWhiteSpace($CacheSource)) {
    $CacheSource = Join-Path (Split-Path -Parent $ProjectRoot) "orc_calc_ocr_cache"
}

if (-not (Test-Path (Join-Path $SourceDir "orc-calc.exe"))) {
    throw "Portable app not found: $SourceDir. Run build_exe_ocr.bat and copy_ocr_runtime.bat first."
}

if (-not (Test-Path $CacheSource)) {
    throw "OCR model cache not found: $CacheSource. Run ocr-check or recognize once before packaging."
}

if (Test-Path $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $StageRoot | Out-Null

& robocopy $SourceDir $StageApp /MIR
if ($LASTEXITCODE -gt 7) {
    throw "Failed to copy portable app. Robocopy exit code: $LASTEXITCODE"
}

foreach ($name in @("runtime", "logs", "ocr_cache")) {
    $path = Join-Path $StageApp $name
    if (Test-Path $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

$serverState = Join-Path $StageApp "server.json"
if (Test-Path $serverState) {
    Remove-Item -LiteralPath $serverState -Force
}

& robocopy $CacheSource (Join-Path $StageApp "ocr_cache") /MIR /XD __pycache__ /XF *.pyc *.pyo
if ($LASTEXITCODE -gt 7) {
    throw "Failed to copy OCR model cache. Robocopy exit code: $LASTEXITCODE"
}

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive -Path $StageApp -DestinationPath $ZipPath -CompressionLevel Optimal -Force

$zip = Get-Item -LiteralPath $ZipPath
$sizeMb = [Math]::Round($zip.Length / 1MB, 2)
Write-Host "Portable ZIP created: $ZipPath"
Write-Host "ZIP size: $sizeMb MB"
