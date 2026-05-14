param(
    [string]$LogDirectory = ".\\logs",
    [string]$Prefix = "session"
)

$root = (Resolve-Path -LiteralPath ".").Path
$targetDir = Join-Path $root $LogDirectory
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
$targetDir = (Resolve-Path -LiteralPath $targetDir).Path

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $targetDir ("{0}-{1}.log" -f $Prefix, $stamp)

Start-Transcript -Path $logPath -IncludeInvocationHeader | Out-Null
Write-Host ("Transcript started: {0}" -f $logPath)
Write-Host "Run Stop-Transcript when you finish the session."
