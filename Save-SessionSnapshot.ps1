param(
    [Parameter(Mandatory = $true)]
    [string]$Objective,
    [string]$Checks = "",
    [string]$Findings = "",
    [string]$ReasoningSummary = "",
    [string]$Decision = "",
    [string]$NextStep = ""
)

function Split-Entry([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return @() }
    return ($text -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
}

function Push-Bullets([System.Collections.Generic.List[string]]$buffer, [string]$title, [string]$text) {
    $buffer.Add("- $title")
    $items = Split-Entry $text
    if ($items.Count -eq 0) {
        $buffer.Add("- (none)")
        return
    }
    foreach ($item in $items) {
        $buffer.Add("- $item")
    }
}

$root = (Resolve-Path -LiteralPath ".").Path
$notePath = Join-Path $root "SESSION_NOTES.md"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"

$lines = New-Object 'System.Collections.Generic.List[string]'
$lines.Add("")
$lines.Add("### $stamp")
$lines.Add("- Objective: $Objective")
Push-Bullets $lines "Code checks run:" $Checks
$lines.Add("- Findings: " + ($(if ([string]::IsNullOrWhiteSpace($Findings)) { "(none)" } else { $Findings })))
$lines.Add("- Reasoning summary (high-level): " + ($(if ([string]::IsNullOrWhiteSpace($ReasoningSummary)) { "(none)" } else { $ReasoningSummary })))
$lines.Add("- Decision / change applied: " + ($(if ([string]::IsNullOrWhiteSpace($Decision)) { "(none)" } else { $Decision })))
$lines.Add("- Next step: " + ($(if ([string]::IsNullOrWhiteSpace($NextStep)) { "(none)" } else { $NextStep })))

Add-Content -Path $notePath -Value $lines
Write-Host ("Session snapshot appended to: {0}" -f $notePath)
