param(
    [string]$IsccPath = "",
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$toolsDir = (Resolve-Path (Join-Path $scriptDir "..")).Path
$gameRoot = (Resolve-Path (Join-Path $toolsDir "..")).Path

Set-Location $gameRoot

function Resolve-Iscc {
    param([string]$ManualPath)
    if ($ManualPath -and (Test-Path $ManualPath)) {
        return (Resolve-Path $ManualPath).Path
    }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) {
            return $p
        }
    }
    throw "ISCC.exe (Inno Setup Compiler) not found. Install Inno Setup 6 or pass -IsccPath."
}

$exePath = Join-Path $toolsDir "PokemonIndigoSaveEditor.exe"
if (-not $SkipExeBuild -or -not (Test-Path $exePath)) {
    Write-Host "[INFO] Building EXE first..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $toolsDir "build_save_editor_exe.ps1") | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "EXE build failed."
    }
}

if (-not (Test-Path $exePath)) {
    throw "EXE not found at: $exePath"
}

$iscc = Resolve-Iscc -ManualPath $IsccPath
$issFile = Join-Path $scriptDir "PokemonSaveEditor_Setup.iss"
if (-not (Test-Path $issFile)) {
    throw "Missing installer script: $issFile"
}

Write-Host "[INFO] Using ISCC: $iscc"
Write-Host "[INFO] Compiling installer..."
Push-Location $scriptDir
try {
    & $iscc $issFile | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "ISCC failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$outDir = Join-Path $scriptDir "dist"
$setup = Join-Path $outDir "PokemonSaveEditor_Setup.exe"
if (-not (Test-Path $setup)) {
    throw "Installer build finished but setup EXE not found: $setup"
}

Write-Host "[DONE] Installer built:"
Write-Host "       $setup"
