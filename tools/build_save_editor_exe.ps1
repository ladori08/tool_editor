param(
    [switch]$OneDir,
    [switch]$SkipDependencyInstall,
    [switch]$UseSystemPython,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$gameRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
Set-Location $gameRoot

Write-Host "[INFO] Game root: $gameRoot"

if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "Python executable '$PythonExe' not found in PATH."
}

$buildPython = $PythonExe
$venvDir = Join-Path $gameRoot "tools\.build_venv"

if (-not $UseSystemPython) {
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "[INFO] Creating local build venv: $venvDir"
        & $PythonExe -m venv $venvDir | Out-Host
    }
    if (-not (Test-Path $venvPython)) {
        throw "Could not create build venv at $venvDir."
    }
    $buildPython = $venvPython
}

if (-not $SkipDependencyInstall) {
    Write-Host "[INFO] Installing/upgrading build dependencies..."
    & $buildPython -m pip install --upgrade pip | Out-Host
    & $buildPython -m pip install --upgrade pyinstaller rubymarshal | Out-Host
}

$distDir = Join-Path $gameRoot "tools\dist"
$buildDir = Join-Path $gameRoot "tools\build"
$specPath = Join-Path $gameRoot "tools\PokemonIndigoSaveEditor.spec"
$iconPath = Join-Path $gameRoot "tools\assets\masterball.ico"

function Get-NormalizedFullPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($Path).TrimEnd([char[]]("\/")).ToLowerInvariant()
    } catch {
        return $Path.TrimEnd([char[]]("\/")).ToLowerInvariant()
    }
}

function Test-PathWithinRoot {
    param(
        [string]$Path,
        [string]$Root
    )
    $pathNorm = Get-NormalizedFullPath $Path
    $rootNorm = Get-NormalizedFullPath $Root
    return ($pathNorm -eq $rootNorm -or $pathNorm.StartsWith($rootNorm + "\"))
}

function Test-FileUnlocked {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $true
    }
    $stream = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        return $true
    } catch {
        return $false
    } finally {
        if ($stream) {
            $stream.Close()
        }
    }
}

function Wait-PathUnlocked {
    param(
        [string]$Path,
        [int]$TimeoutSeconds = 10
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $true
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $lockedFiles = @()
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            if (-not (Test-FileUnlocked -Path $Path)) {
                $lockedFiles += $Path
            }
        } else {
            $files = Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue
            foreach ($file in $files) {
                if (-not (Test-FileUnlocked -Path $file.FullName)) {
                    $lockedFiles += $file.FullName
                    break
                }
            }
        }
        if ($lockedFiles.Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-LocalBuildBlockers {
    param([string]$WorkspaceRoot)
    $workspaceTools = Join-Path $WorkspaceRoot "tools"
    $toolsNorm = Get-NormalizedFullPath $workspaceTools
    $targetNames = @("PokemonIndigoSaveEditor", "python", "pythonw", "pyinstaller", "iscc")
    $stopped = 0
    $stoppedIds = @()

    $currentPid = $PID
    $processes = @()
    foreach ($targetName in $targetNames) {
        $processes += @(Get-Process -Name $targetName -ErrorAction SilentlyContinue)
    }

    foreach ($procInfo in ($processes | Sort-Object -Property Id -Unique)) {
        if ($procInfo.Id -eq $currentPid) {
            continue
        }

        $procName = [string]$procInfo.ProcessName
        $procPath = ""
        try {
            $procPath = [string]$procInfo.Path
        } catch {
            $procPath = ""
        }

        if ([string]::IsNullOrWhiteSpace($procPath)) {
            try {
                $procPath = [string]$procInfo.MainModule.FileName
            } catch {
                $procPath = ""
            }
        }

        $procPathNorm = Get-NormalizedFullPath $procPath
        $shouldStop = $false

        if ($procName -eq "PokemonIndigoSaveEditor") {
            $shouldStop = $procPathNorm.StartsWith($toolsNorm + "\")
        } elseif ($procName -in @("python", "pythonw", "pyinstaller", "iscc")) {
            $shouldStop = $procPathNorm.StartsWith($toolsNorm + "\")
        }

        if (-not $shouldStop) {
            continue
        }

        try {
            Stop-Process -Id $procInfo.Id -Force -ErrorAction Stop
            $stopped++
            $stoppedIds += $procInfo.Id
            Write-Host ("[INFO] Stopped build blocker: {0} (PID {1})" -f $procName, $procInfo.Id)
        } catch {
            Write-Warning ("Could not stop build-blocking process ID {0} ({1}). Build may fail if a file is locked." -f $procInfo.Id, $procPath)
        }
    }

    foreach ($stoppedId in $stoppedIds) {
        try {
            Wait-Process -Id $stoppedId -Timeout 8 -ErrorAction SilentlyContinue
        } catch {
        }
    }

    if ($stopped -gt 0) {
        Write-Host ("[INFO] Stopped {0} local editor/build process(es) that could block release build." -f $stopped)
    }
}

function Remove-PathWithRetry {
    param(
        [string]$Path,
        [switch]$Recurse,
        [int]$Attempts = 8
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $toolsRoot = Join-Path $gameRoot "tools"
    if (-not (Test-PathWithinRoot -Path $resolvedPath -Root $toolsRoot)) {
        throw "Refusing to delete path outside tools workspace: $resolvedPath"
    }

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        Stop-LocalBuildBlockers -WorkspaceRoot $gameRoot
        [void](Wait-PathUnlocked -Path $Path -TimeoutSeconds 5)
        try {
            if ($Recurse) {
                Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
            }
            return
        } catch {
            if ($attempt -ge $Attempts) {
                throw
            }
            Write-Warning ("Could not remove {0} on attempt {1}/{2}: {3}" -f $Path, $attempt, $Attempts, $_.Exception.Message)
            Start-Sleep -Milliseconds 750
        }
    }
}

Stop-LocalBuildBlockers -WorkspaceRoot $gameRoot

Remove-PathWithRetry -Path $distDir -Recurse
Remove-PathWithRetry -Path $buildDir -Recurse
Remove-PathWithRetry -Path $specPath

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--name", "PokemonIndigoSaveEditor",
    "--distpath", "tools\dist",
    "--workpath", "tools\build",
    "--specpath", "tools",
    "--paths", "tools",
    "--hidden-import", "pokemon_indigo_probe_mapper",
    "--hidden-import", "pokemon_indigo_game_data",
    "--hidden-import", "pokemon_indigo_ev_patcher",
    "--hidden-import", "pokemon_indigo_patch_capability",
    "--hidden-import", "pokemon_indigo_custom_item_patcher",
    "--windowed",
    "tools\pokemon_indigo_save_editor_gui.py"
)

if (Test-Path $iconPath) {
    $pyiArgs = $pyiArgs[0..($pyiArgs.Count - 2)] + @("--icon", $iconPath, $pyiArgs[-1])
}

if (-not $OneDir) {
    $pyiArgs = @("-m", "PyInstaller", "--onefile") + $pyiArgs[2..($pyiArgs.Count - 1)]
}

Write-Host "[INFO] Building EXE with PyInstaller..."
& $buildPython @pyiArgs | Out-Host

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE."
}

$oneFileExe = Join-Path $distDir "PokemonIndigoSaveEditor.exe"
$oneDirExe = Join-Path $distDir "PokemonIndigoSaveEditor\PokemonIndigoSaveEditor.exe"
$targetExe = Join-Path $gameRoot "tools\PokemonIndigoSaveEditor.exe"

if (Test-Path $oneFileExe) {
    Copy-Item $oneFileExe $targetExe -Force
    Write-Host "[OK] One-file EXE built: $oneFileExe"
    Write-Host "[OK] Copied launcher EXE: $targetExe"
} elseif (Test-Path $oneDirExe) {
    Copy-Item $oneDirExe $targetExe -Force
    Write-Host "[OK] One-dir EXE built: $oneDirExe"
    Write-Host "[OK] Copied launcher EXE: $targetExe"
} else {
    throw "Build completed but EXE was not found in tools\\dist."
}

Write-Host "[DONE] Build finished."
