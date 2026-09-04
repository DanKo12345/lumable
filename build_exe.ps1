$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = $null
foreach ($candidate in @(
    (Join-Path $root ".venv311\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)) {
    if (-not (Test-Path -LiteralPath $candidate)) {
        continue
    }
    # A copied venv still contains python.exe, but its launcher points at the
    # base interpreter on the old computer. Existence alone therefore selects
    # an environment that cannot run at all. Prove each candidate before using
    # it; stderr is intentionally hidden because the next candidate may work.
    & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $python = $candidate
        break
    }
}

if (-not $python) {
    throw "A working Python 3.11+ virtual environment was not found. Expected .venv311 or .venv in: $root"
}

$version = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$version -lt [version]"3.11") {
    throw "Release builds require Python 3.11+. Current build interpreter: Python $version ($python)"
}

# PyInstaller searches PATH while resolving DLL dependencies. A developer shell
# may contain unrelated OpenSSL or ICU builds, which then get copied beside Qt
# and override the versions Qt expects at runtime. Build against only Python,
# the selected venv and Windows, then restore the caller's environment.
$originalPath = $env:PATH
$basePrefix = & $python -c "import sys; print(sys.base_prefix)"
$safePath = @(
    (Split-Path -Parent $python),
    $basePrefix,
    (Join-Path $basePrefix "Scripts"),
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot "System32\Wbem")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique

$buildExitCode = 1
try {
    $env:PATH = $safePath -join [System.IO.Path]::PathSeparator
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
        --collect-all "soundcard" `
        --collect-all "sounddevice" `
        --collect-all "segno" `
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
    $buildExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $originalPath
}

if ($buildExitCode -ne 0) {
    exit $buildExitCode
}

$analysisPath = Join-Path $root "build\LumaBLE\Analysis-00.toc"
if (Test-Path -LiteralPath $analysisPath) {
    $foreignRuntimeDependency = Select-String -LiteralPath $analysisPath -Pattern "poppler" -SimpleMatch -Quiet
    if ($foreignRuntimeDependency) {
        throw "Build captured a DLL from an unrelated runtime. Use only dependencies from the release environment."
    }
}

$unusedQtFiles = @(
    "dist\LumaBLE\_internal\PySide6\opengl32sw.dll",
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
        if ($_.Name -notmatch "(_ru|_zh|_en|_es)\.qm$") {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    }
}

$exePath = Join-Path $root "dist\LumaBLE\LumaBLE.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Build finished but the exe is missing: $exePath"
}

# --- Startup smoke test ---------------------------------------------------
# A release that doesn't even start (e.g. a missing Qt submodule like the
# QtNetwork regression) must never ship. Launch the freshly built exe, give
# it a few seconds, and fail the build if it crashes on startup (a new
# *startup.log appears) or exits with an error code.
if ($env:LUMABLE_SKIP_SMOKE -eq "1") {
    Write-Host "Skipping startup smoke test (LUMABLE_SKIP_SMOKE=1)."
} else {
    $crashDir = Join-Path $env:APPDATA "LumaBLE\crash_logs"
    $beforeLog = $null
    if (Test-Path -LiteralPath $crashDir) {
        $beforeLog = Get-ChildItem -LiteralPath $crashDir -Filter "*startup.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }

    Write-Host "Running startup smoke test..."
    $proc = Start-Process -FilePath $exePath -WorkingDirectory (Split-Path -Parent $exePath) -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 6
    $proc.Refresh()

    $afterLog = $null
    if (Test-Path -LiteralPath $crashDir) {
        $afterLog = Get-ChildItem -LiteralPath $crashDir -Filter "*startup.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    $newCrash = $afterLog -and (-not $beforeLog -or $afterLog.FullName -ne $beforeLog.FullName)
    $exitedWithError = $proc.HasExited -and $proc.ExitCode -ne 0
    $windowTitle = if ($proc.HasExited) { "" } else { $proc.MainWindowTitle }
    $bootstrapDialog = $windowTitle -match "Unhandled exception|Failed to execute script"
    $appWindowMissing = -not $proc.HasExited -and $windowTitle -ne "LumaBLE"

    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }

    if ($newCrash) {
        Write-Host "SMOKE TEST FAILED - the app crashed on startup:" -ForegroundColor Red
        Get-Content -LiteralPath $afterLog.FullName -Raw | Write-Host
        throw "Startup smoke test failed: $($afterLog.FullName)"
    }
    if ($exitedWithError) {
        throw "Startup smoke test failed: the app exited with code $($proc.ExitCode)."
    }
    if ($bootstrapDialog) {
        throw "Startup smoke test failed before app startup: $windowTitle"
    }
    if ($appWindowMissing) {
        throw "Startup smoke test failed: expected the LumaBLE window, got '$windowTitle'."
    }
    Write-Host "Startup smoke test passed."
}

# --- Optional code signing ------------------------------------------------
# Set LUMABLE_SIGN_THUMBPRINT (certificate SHA-1 thumbprint) to sign releases
# for SmartScreen/antivirus trust. Until then this is a no-op with a reminder,
# so unsigned dev builds keep working.
if ($env:LUMABLE_SIGN_THUMBPRINT) {
    $signtool = if ($env:LUMABLE_SIGNTOOL) { $env:LUMABLE_SIGNTOOL } else { "signtool" }
    Write-Host "Signing the executable..."
    & $signtool sign /sha1 $env:LUMABLE_SIGN_THUMBPRINT /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Code signing failed."
    }
    Write-Host "Signed: $exePath"
} else {
    Write-Host "NOTE: build is unsigned. Set LUMABLE_SIGN_THUMBPRINT to sign releases (SmartScreen/AV trust)." -ForegroundColor Yellow
}

Write-Host "Built: dist\LumaBLE\LumaBLE.exe"
