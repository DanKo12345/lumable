param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$distExe = Join-Path $root "dist\LumaBLE\LumaBLE.exe"

if (-not $SkipBuild) {
    & (Join-Path $root "build_exe.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path -LiteralPath $distExe)) {
    throw "LumaBLE.exe was not found. Build the app first or run .\build_installer.ps1 without -SkipBuild."
}

$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if ($null -eq $iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $iscc = Get-Item -LiteralPath $candidate
            break
        }
    }
}

if ($null -eq $iscc) {
    throw "Inno Setup 6 was not found. Install it from https://jrsoftware.org/isinfo.php and run this script again."
}

$installerDir = Join-Path $root "dist\installer"
New-Item -ItemType Directory -Force -Path $installerDir | Out-Null

$isccPath = if ($iscc -is [System.Management.Automation.CommandInfo]) {
    $iscc.Source
} else {
    $iscc.FullName
}

& $isccPath (Join-Path $root "installer\LumaBLE.iss")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Built installer in: dist\installer"
