# Start a long experiment as a detached process that keeps running if the terminal or the
# Claude session closes. Output goes to logs/<name>.log; the process id to logs/<name>.pid.
#
# Usage (from the repo root):
#   powershell -File scripts/run_detached.ps1 -Name B0_quixbugs eval --config configs/exp_baseline.yaml --benchmark quixbugs
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$PatchpilotArgs
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
$log = Join-Path $root "logs/$Name.log"
$exe = Join-Path $root ".venv/Scripts/patchpilot.exe"
$argLine = ($PatchpilotArgs | Where-Object { $_ -ne "--" }) -join " "
$cmd = "`$env:PYTHONIOENCODING='utf-8'; `$env:HF_HUB_DISABLE_SYMLINKS_WARNING='1'; `$env:COLUMNS='150'; " +
       "Set-Location '$root'; & '$exe' $argLine 2>&1 | Out-File -Append -Encoding utf8 '$log'"
$proc = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList "-NoProfile", "-Command", $cmd
$proc.Id | Out-File -Encoding ascii (Join-Path $root "logs/$Name.pid")
"started $Name as process $($proc.Id); log: $log"
