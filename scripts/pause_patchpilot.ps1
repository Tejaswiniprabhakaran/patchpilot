# "Pause PatchPilot": stop every PatchPilot job and sandbox container cleanly (decisions D14).
# Finished instances are already saved in results/; `patchpilot eval` skips them when resumed, and
# the instance that was interrupted is simply run again. Other projects are never touched.
#
# Usage:  powershell -File scripts/pause_patchpilot.ps1
$jobs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "patchpilot.exe") -or
    ($_.CommandLine -like "*build_localization_data.py*") -or
    ($_.CommandLine -like "*eval_localization.py*") -or
    ($_.CommandLine -like "*sanity_gold_patches.py*")
}
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
