# Start a long PatchPilot job as a detached, Below Normal priority process that keeps running if the
# terminal or the Claude session closes. Refuses to start if the same command is already running
# (resource rules, decisions D14). Output goes to logs/<name>.log; the process id to logs/<name>.pid.
#
# Usage (from the repo root):
#   powershell -File scripts/run_detached.ps1 -Name B0_quixbugs eval --config configs/exp_baseline.yaml --benchmark quixbugs
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$PatchpilotArgs
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$argLine = ($PatchpilotArgs | Where-Object { $_ -ne "--" }) -join " "

$running = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "patchpilot.exe" -and $_.CommandLine -like "*$argLine*" })
if ($running.Count -gt 0) {
    "NOT started: the same job is already running as process(es) $($running.ProcessId -join ', ')"
    exit 1
}

New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
$log = Join-Path $root "logs/$Name.log"
$exe = Join-Path $root ".venv/Scripts/patchpilot.exe"
$cmd = "`$env:PYTHONIOENCODING='utf-8'; `$env:HF_HUB_DISABLE_SYMLINKS_WARNING='1'; `$env:COLUMNS='150'; " +
       "Set-Location '$root'; & '$exe' $argLine 2>&1 | Out-File -Append -Encoding utf8 '$log'"
$proc = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList "-NoProfile", "-Command", $cmd
# Children (patchpilot, python) inherit Below Normal from their parent on Windows.
$proc.PriorityClass = "BelowNormal"
$proc.Id | Out-File -Encoding ascii (Join-Path $root "logs/$Name.pid")
"started $Name as process $($proc.Id) (Below Normal); log: $log"
