# Run every remaining experiment step one after another, unattended (resource rules, D14):
#   B0 QuixBugs -> B0 SWE-bench -> ranker training (D16) -> localization evaluation
#   -> E1 SWE-bench -> summaries, figures, failure taxonomy (shortened in D19).
# One heavy job at a time, at Below Normal priority. A step whose output already exists is
# skipped, and `patchpilot eval` resumes from saved rows, so the pipeline can be stopped with
# scripts/pause_patchpilot.ps1 and started again at any time. It first waits for an evaluation
# that is already running, so there are never two copies. It stops (and says why in the log)
# when C: falls below 20 GB free, when Docker is not running, or when a step fails twice.
#
# Usage (from the repo root):
#   powershell -File scripts/run_pipeline.ps1 -Detach     # start in the background
#   Get-Content logs/pipeline.log -Tail 20                # progress; each step's output is in
#                                                          # logs/pipeline/<nn>-<step>-try<n>.log
#   powershell -File scripts/run_pipeline.ps1 -DryRun     # list the steps it would run now
param([switch]$Detach, [switch]$DryRun)

$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "logs/pipeline.log"
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null

function Get-OtherPipelines {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -like "*run_pipeline.ps1*" -and
        $_.CommandLine -notlike "*-Detach*" -and $_.CommandLine -notlike "*-DryRun*"
    })
}

if ($Detach) {
    $others = Get-OtherPipelines
    if ($others.Count -gt 0) {
        "NOT started: the pipeline is already running as process(es) $($others.ProcessId -join ', ')"
        exit 1
    }
    $proc = Start-Process powershell -WindowStyle Hidden -PassThru -ArgumentList `
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
    # Children (patchpilot, python) inherit Below Normal from their parent on Windows.
    $proc.PriorityClass = "BelowNormal"
    $proc.Id | Out-File -Encoding ascii (Join-Path $root "logs/pipeline.pid")
    "started the pipeline as process $($proc.Id) (Below Normal); log: $log"
    exit 0
}

if ((Get-OtherPipelines).Count -gt 0) { "the pipeline is already running"; exit 1 }
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"  # step logs fill as the step runs
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"
$env:COLUMNS = "150"
$py = Join-Path $root ".venv\Scripts\python.exe"
$pp = Join-Path $root ".venv\Scripts\patchpilot.exe"
$ranker = "data/models/fl-cross-encoder"
$stepLogs = Join-Path $root "logs/pipeline"
New-Item -ItemType Directory -Force $stepLogs | Out-Null
$script:step = 0

function Write-Log([string]$message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    if ($DryRun) { $line } else { $line | Out-File -Append -Encoding utf8 $log }
}

function Stop-Pipeline([string]$reason) {
    Write-Log "STOPPED: $reason"
    Write-Log "Start again with: powershell -File scripts/run_pipeline.ps1 -Detach (finished steps are skipped)"
    exit 1
}

function Assert-Resources([bool]$needsDocker) {
    $free = (Get-PSDrive C).Free / 1GB
    if ($free -lt 20) { Stop-Pipeline ("C: has {0:N1} GB free; the limit is 20 GB" -f $free) }
    if ($needsDocker) {
        docker info --format "{{.ServerVersion}}" *> $null
        if ($LASTEXITCODE -ne 0) { Stop-Pipeline "Docker Desktop is not running" }
    }
}

function Invoke-Step([string]$label, [string]$exe, [string]$arguments, [bool]$needsDocker) {
    $script:step++
    if ($DryRun) { Write-Log "would run: $label  ->  $(Split-Path -Leaf $exe) $arguments"; return }
    $slug = ($label -replace "[^A-Za-z0-9]+", "-").Trim("-").ToLower()
    # One retry after 5 minutes covers transient failures (an image pull, a network hiccup).
    for ($try = 1; $try -le 2; $try++) {
        Assert-Resources $needsDocker
        $out = Join-Path $stepLogs ("{0:D2}-{1}-try{2}.log" -f $script:step, $slug, $try)
        Write-Log "START $label (output: logs/pipeline/$(Split-Path -Leaf $out))"
        $proc = Start-Process -FilePath $exe -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError "$out.err"
        if ($proc.ExitCode -eq 0) { Write-Log "DONE  $label"; return }
        Write-Log "FAILED $label (exit code $($proc.ExitCode))"
        if ($try -eq 1) { Start-Sleep -Seconds 300 }
    }
    Stop-Pipeline "$label failed twice"
}

function Invoke-Eval([string]$experiment, [string]$config, [string]$benchmark) {
    $needsDocker = $true
    Invoke-Step "$experiment $benchmark" $pp "eval --config $config --benchmark $benchmark" $needsDocker
    # D13/D17: rows hit by a model-server stall are re-run once, by a rule blind to the outcome.
    $results = "results/$experiment/$benchmark.jsonl"
    Invoke-Step "$experiment $benchmark re-queue check" $py "scripts/requeue_infra_failures.py $results" $false
    Invoke-Step "$experiment $benchmark re-runs" $pp "eval --config $config --benchmark $benchmark" $needsDocker
}

Write-Log "PIPELINE STARTED (process $PID)"
while (-not $DryRun -and @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*patchpilot.exe*eval*" -and $_.Name -ne "powershell.exe"
    }).Count -gt 0) {
    Write-Log "waiting for the evaluation that is already running to finish"
    Start-Sleep -Seconds 300
}

Invoke-Eval "B0" "configs/exp_baseline.yaml" "quixbugs"
Invoke-Eval "B0" "configs/exp_baseline.yaml" "swebench-lite"

if (-not (Test-Path "$ranker/patchpilot.json")) {
    Invoke-Step "train the ranker (A1, D16, D19)" $py "scripts/train_ranker_cpu.py --budget-hours 2" $false
    # The base model was a temporary download; the trained model folder is self-contained.
    $base = Join-Path $env:USERPROFILE ".cache\huggingface\hub\models--microsoft--unixcoder-base"
    if ((Test-Path $base) -and -not $DryRun) {
        Remove-Item -Recurse -Force $base
        Write-Log "deleted the temporary base-model download $base"
    }
}
if (-not (Test-Path "results/localization/heldout_cross_encoder_test_sample100.json")) {
    Invoke-Step "localization, held-out sample" $py ("scripts/eval_localization.py --setting heldout " +
        "--sample 100 --methods bm25 embedding cross_encoder --model $ranker") $false
}
if (-not (Test-Path "results/localization/swebench_cross_encoder.json")) {
    Invoke-Step "localization, SWE-bench subset" $py ("scripts/eval_localization.py --setting swebench " +
        "--methods bm25 embedding cross_encoder --model $ranker") $true
}

Invoke-Eval "E1" "configs/exp_e1_ranker.yaml" "swebench-lite"

Invoke-Step "result summaries" $py "scripts/summarize_results.py" $false
Invoke-Step "figures" $py "scripts/make_figures.py" $false
Invoke-Step "failure taxonomy (rules, D19)" $py "scripts/classify_failures.py" $false
if (Test-Path "scripts/build_report.py") {
    Invoke-Step "report (DOCX and PDF)" $py "scripts/build_report.py" $false
}
Write-Log "PIPELINE FINISHED"
