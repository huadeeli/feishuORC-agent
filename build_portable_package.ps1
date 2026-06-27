$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistRoot = Join-Path $ProjectRoot "dist"
$StageRoot = Join-Path $DistRoot "orc-feishu-portable"
$StageApp = Join-Path $StageRoot "app"
$ZipPath = Join-Path $DistRoot "orc-feishu-portable.zip"

function Invoke-Batch([string]$Path) {
    if (-not (Test-Path $Path)) {
        throw "Missing build script: $Path"
    }
    & cmd.exe /c "`"$Path`""
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Path"
    }
}

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$RobocopyArgs) {
    if (-not (Test-Path $Source)) {
        throw "Missing source path: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy $Source $Destination @RobocopyArgs
    $code = $LASTEXITCODE
    if ($code -gt 7) {
        throw "Robocopy failed from $Source to $Destination with exit code $code"
    }
    $global:LASTEXITCODE = 0
}

function Remove-Existing([string]$Path) {
    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Get-VenvHome([string]$VenvRoot) {
    $pyvenv = Join-Path $VenvRoot "pyvenv.cfg"
    if (-not (Test-Path $pyvenv)) {
        throw "Missing pyvenv.cfg: $pyvenv"
    }
    $homeLine = Get-Content -Encoding UTF8 -Path $pyvenv | Where-Object { $_ -match "^\s*home\s*=" } | Select-Object -First 1
    if (-not $homeLine) {
        throw "Cannot find base Python home in $pyvenv"
    }
    return ($homeLine -split "=", 2)[1].Trim()
}

function Get-OcrCacheSource {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:ORC_CALC_OCR_CACHE_DIR)) {
        $candidates += $env:ORC_CALC_OCR_CACHE_DIR
    }
    $candidates += Join-Path (Split-Path -Parent $ProjectRoot) "orc_calc_ocr_cache"
    $candidates += Join-Path $ProjectRoot ".ocr-cache"
    $candidates += Join-Path $ProjectRoot "ocr_cache"

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    throw "OCR model cache not found. Run check_ocr_modes.bat or recognize one image before packaging."
}

function Copy-PortableOcrRuntime([string]$Destination) {
    $venvRoot = Join-Path $ProjectRoot ".venv-ocr"
    if (-not (Test-Path (Join-Path $venvRoot "Lib\site-packages\paddleocr"))) {
        throw "Local OCR runtime is missing. Run install_ocr_cpu.bat before packaging."
    }

    $pythonHome = Get-VenvHome $venvRoot
    if (-not (Test-Path (Join-Path $pythonHome "python.exe"))) {
        throw "Base Python not found: $pythonHome"
    }

    Remove-Existing $Destination
    Copy-Tree $pythonHome $Destination @("/E", "/XD", "__pycache__", "site-packages", "/XF", "*.pyc", "*.pyo")
    Copy-Tree (Join-Path $venvRoot "Lib\site-packages") (Join-Path $Destination "Lib\site-packages") @("/MIR", "/XD", "__pycache__", "/XF", "*.pyc", "*.pyo")

    $marker = @(
        "Portable OCR runtime assembled by build_portable_package.ps1.",
        "Base Python: $pythonHome",
        "Site packages: $venvRoot\Lib\site-packages"
    )
    Set-Content -LiteralPath (Join-Path $Destination "PORTABLE-OCR-RUNTIME.txt") -Value $marker -Encoding UTF8
}

New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null

if ($env:ORC_PORTABLE_SKIP_BUILD -eq "1") {
    Write-Host "Skipping executable builds because ORC_PORTABLE_SKIP_BUILD=1."
} else {
    Write-Host "Building calculator executables..."
    Invoke-Batch (Join-Path $ProjectRoot "build_exe_ocr.bat")

    Write-Host "Building Feishu executables..."
    Invoke-Batch (Join-Path $ProjectRoot "build_feishu_exe.bat")
}

$calcDir = Join-Path $DistRoot "orc-calc"
$feishuDir = Join-Path $DistRoot "feishu-bot"
$trayDir = Join-Path $DistRoot "feishu-bot-tray"

if (-not (Test-Path (Join-Path $calcDir "orc-calc.exe"))) {
    throw "Calculator executable not found: $calcDir"
}
if (-not (Test-Path (Join-Path $calcDir "orc-calc-cli.exe"))) {
    throw "Calculator CLI executable not found: $calcDir"
}
if (-not (Test-Path (Join-Path $feishuDir "feishu-bot.exe"))) {
    throw "Feishu bot executable not found: $feishuDir"
}
if (-not (Test-Path (Join-Path $trayDir "feishu-bot-tray.exe"))) {
    throw "Feishu tray executable not found: $trayDir"
}

Write-Host "Staging portable package..."
Remove-Existing $StageRoot
New-Item -ItemType Directory -Path $StageApp -Force | Out-Null

Copy-Tree (Join-Path $ProjectRoot "packaging\portable") $StageRoot @("/MIR")
Copy-Tree $calcDir $StageApp @("/MIR")
Copy-Tree $feishuDir $StageApp @("/E")
Copy-Tree $trayDir $StageApp @("/E")

foreach ($name in @("runtime", "logs", "ocr_cache", "ocr-runtime", ".venv-ocr")) {
    Remove-Existing (Join-Path $StageApp $name)
}
Remove-Existing (Join-Path $StageApp ".env")
Remove-Existing (Join-Path $StageApp "server.json")

Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination (Join-Path $StageApp ".env.example") -Force

Write-Host "Copying portable OCR runtime..."
Copy-PortableOcrRuntime (Join-Path $StageApp "ocr-runtime")

Write-Host "Copying OCR model cache..."
$cacheSource = Get-OcrCacheSource
Copy-Tree $cacheSource (Join-Path $StageApp "ocr_cache") @("/MIR", "/XD", "__pycache__", "/XF", "*.pyc", "*.pyo")

foreach ($dir in @(
    (Join-Path $StageApp "runtime\feishu\downloads"),
    (Join-Path $StageApp "runtime\feishu\card_sessions"),
    (Join-Path $StageApp "runtime\feishu\logs")
)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Write-Host "Creating ZIP..."
Compress-Archive -Path (Join-Path $StageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal -Force

$zip = Get-Item -LiteralPath $ZipPath
$sizeMb = [Math]::Round($zip.Length / 1MB, 2)
Write-Host "Portable ZIP created: $ZipPath"
Write-Host "ZIP size: $sizeMb MB"
