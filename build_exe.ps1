$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python311 = Join-Path $root ".venv311\Scripts\python.exe"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $python311) {
    $python = $python311
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment was not found. Expected .venv311 or .venv in: $root"
}

$version = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$version -lt [version]"3.11") {
    throw "Release builds require Python 3.11+. Current build interpreter: Python $version ($python)"
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "LumaBLE" `
    --icon "app\assets\icon.ico" `
    --version-file "build\version_info.txt" `
    --add-data "app\assets;app\assets" `
    --add-data "app\i18n;app\i18n" `
    --add-data "THIRD_PARTY_NOTICES.txt;." `
    --exclude-module "PySide6.QtNetwork" `
    --exclude-module "PySide6.QtQml" `
    --exclude-module "PySide6.QtQmlMeta" `
    --exclude-module "PySide6.QtQmlModels" `
    --exclude-module "PySide6.QtQmlWorkerScript" `
    --exclude-module "PySide6.QtQuick" `
    --exclude-module "PySide6.QtQuickWidgets" `
    --exclude-module "PySide6.QtVirtualKeyboard" `
    --exclude-module "PySide6.QtPdf" `
    --exclude-module "PySide6.QtPdfWidgets" `
    main.py

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$unusedQtFiles = @(
    "dist\LumaBLE\_internal\PySide6\opengl32sw.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6Network.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6OpenGL.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6Pdf.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6PdfWidgets.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6Qml.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6QmlMeta.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6QmlModels.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6QmlWorkerScript.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6Quick.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6QuickWidgets.dll",
    "dist\LumaBLE\_internal\PySide6\Qt6VirtualKeyboard.dll",
    "dist\LumaBLE\_internal\PySide6\plugins\imageformats\qpdf.dll",
    "dist\LumaBLE\_internal\PySide6\plugins\platforminputcontexts\qtvirtualkeyboardplugin.dll"
)

foreach ($relativePath in $unusedQtFiles) {
    $path = Join-Path $root $relativePath
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

$translationsDir = Join-Path $root "dist\LumaBLE\_internal\PySide6\translations"
if (Test-Path -LiteralPath $translationsDir) {
    Get-ChildItem -LiteralPath $translationsDir -Filter "*.qm" | ForEach-Object {
        if ($_.Name -notmatch "(_ru|_zh|_en)\.qm$") {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    }
}

Write-Host "Built: dist\LumaBLE\LumaBLE.exe"
