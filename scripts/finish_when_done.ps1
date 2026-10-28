# Wait for scripts/run_pipeline.ps1 to end, then commit results/ and the rebuilt report and push
# them to develop, so the project completes without anyone at the keyboard. If the pipeline stopped
# early, the partial results are pushed with a commit message that says why. Log: logs/finish.log.
#
# Usage (from the repo root):  powershell -File scripts/finish_when_done.ps1 -Detach
param([switch]$Detach)

$root = Split-Path -Parent $PSScriptRoot
$pipelineLog = Join-Path $root "logs/pipeline.log"
$log = Join-Path $root "logs/finish.log"

if ($Detach) {
    $proc = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList `
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
    $proc.PriorityClass = "BelowNormal"
    "waiting for the pipeline as process $($proc.Id); log: $log"
    exit 0
}

function Write-Log([string]$message) {
    "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message | Out-File -Append -Encoding utf8 $log
}

Set-Location $root
Write-Log "waiting for the pipeline to end"
while ($true) {
    $tail = (Get-Content $pipelineLog -Tail 3) -join "`n"
    if ($tail -match "PIPELINE FINISHED") {
        $subject = "results: B0 and E1 experiments complete; report rebuilt"
        break
    }
    if ($tail -match "STOPPED: ([^\r\n]*)") {
        $subject = "results: partial, the pipeline stopped ($($Matches[1]))"
        break
    }
    Start-Sleep -Seconds 600
}

Write-Log "committing: $subject"
git pull --ff-only -q origin develop 2>&1 | ForEach-Object { Write-Log "$_" }
git add results report
git commit -q -m $subject -m "Produced by scripts/run_pipeline.ps1 and committed by scripts/finish_when_done.ps1." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" 2>&1 | ForEach-Object { Write-Log "$_" }
git -c credential.helper= -c "credential.helper=!gh auth git-credential" push -q origin HEAD:develop 2>&1 | ForEach-Object { Write-Log "$_" }
if ($LASTEXITCODE -eq 0) { Write-Log "pushed to develop" } else { Write-Log "push failed (exit $LASTEXITCODE); push by hand" }
