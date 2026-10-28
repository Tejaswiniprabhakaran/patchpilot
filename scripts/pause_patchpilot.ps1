# "Pause PatchPilot": stop every PatchPilot job and sandbox container cleanly (decisions D14).
# Finished instances are already saved in results/; `patchpilot eval` skips them when resumed, and
# the instance that was interrupted is simply run again. Other projects are never touched.
#
# Usage:  powershell -File scripts/pause_patchpilot.ps1
#
# The pipeline goes first, so it cannot start its next step while the current one is stopped.
# `patchpilot eval` usually shows up as python.exe running Scripts\patchpilot.exe, so command
# lines are matched, not only process names.
$patterns = @(
    "*run_pipeline.ps1*",
    "*patchpilot.exe*eval*",
    "*train_ranker_cpu.py*",
    "*build_localization_data.py*",
    "*eval_localization.py*",
    "*sanity_gold_patches.py*"
)
$jobs = Get-CimInstance Win32_Process | Where-Object {
    $line = $_.CommandLine
    ($_.ProcessId -ne $PID) -and ($line -notlike "*pause_patchpilot.ps1*") -and
    (($_.Name -eq "patchpilot.exe") -or ($patterns | Where-Object { $line -like $_ }))
} | Sort-Object { if ($_.CommandLine -like "*run_pipeline.ps1*") { 0 } else { 1 } }
foreach ($job in $jobs) {
    # Stop the whole tree: the launcher shell, patchpilot.exe and its python children.
    & taskkill /PID $job.ProcessId /T /F 2>$null | Out-Null
    "stopped process $($job.ProcessId) ($($job.Name))"
}
$sandboxes = docker ps -aq --filter "label=patchpilot.sandbox"
foreach ($id in $sandboxes) {
    docker rm -f $id | Out-Null
    "removed PatchPilot sandbox container $id"
}
if (-not $jobs -and -not $sandboxes) { "nothing was running" }
"PatchPilot paused. See PROGRESS.md for the resume command."
