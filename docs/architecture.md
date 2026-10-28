# Architecture

PatchPilot is a Python package (`src/patchpilot`) with one rule at its centre: **code from a
repository under repair only ever runs inside the Docker sandbox.** Everything else (the agent,
the models, the evaluation, the dashboard and the bot) talks to the sandbox through a small API.

## Components

```mermaid
flowchart TB
    subgraph Interfaces
        CLI[cli.py<br/>fix · eval · show · dashboard]
        DASH[dashboard/<br/>FastAPI + Jinja2]
        BOT[bot/ + github_action/<br/>PR comments]
    end
    subgraph Core
        AGENT[agent/<br/>loop · prompts · edits · trajectory]
        TOOLS[tools/<br/>list · read · search · edit · run_tests · submit]
        LLM[llm/<br/>OpenAI-compatible client]
        LOC[localization/<br/>BM25 · embeddings · cross-encoder]
    end
    subgraph Execution
        SANDBOX[sandbox/<br/>DockerSandbox]
        BENCH[benchmarks/<br/>QuixBugs · SWE-bench Lite]
    end
    subgraph Analysis
        EVAL[evaluation/<br/>runner · stats · summary]
        ANALYSIS[analysis/<br/>failure classifier · judge]
    end
    CLI --> AGENT
    CLI --> EVAL
    DASH --> AGENT
    BOT --> AGENT
    EVAL --> AGENT
    AGENT --> TOOLS
    AGENT --> LLM
    AGENT --> LOC
    TOOLS --> SANDBOX
    LOC --> SANDBOX
    BENCH --> SANDBOX
    EVAL --> BENCH
    ANALYSIS --> EVAL
    LLM -. HTTP .-> OLLAMA[(Ollama / vLLM /<br/>Gemini endpoint)]
    SANDBOX -. Docker API .-> DOCKER[(Docker, network off)]
```

| Package | Responsibility | Explainer |
|---|---|---|
| `sandbox` | Container per instance: no network, resource limits, no host mounts, timeouts, safe patching | [sandbox.md](explained/sandbox.md) |
| `benchmarks` | Instances, the resolution rule, QuixBugs and SWE-bench Lite loaders, sanity check | [benchmarks.md](explained/benchmarks.md) |
| `tools`, `agent`, `llm` | The six tools, the retry loop, prompts, SEARCH/REPLACE parsing, trajectories, model client | [agent.md](explained/agent.md) |
| `localization` | Labels from patches, BM25, embedding retrieval, cross-encoder, `RankerLocalizer` | [localization.md](explained/localization.md) |
| `patchgen` | Fine-tuning data in the agent's own prompt format | [patch_generator.md](explained/patch_generator.md) |
| `evaluation` | Experiment runner, scoring rules, statistics, results tables | (this page) |
| `analysis` | Failure classifier, LLM judge, manual-label agreement | [failure_analysis.md](explained/failure_analysis.md) |
| `dashboard` | Web UI over `results/` and `runs/`, live Try-it runs | (this page) |
| `bot` | Pull-request bot and GitHub Action | [github_bot.md](explained/github_bot.md) |

## One agent run

```mermaid
sequenceDiagram
    participant U as CLI / runner / bot
    participant A as Agent
    participant S as Sandbox (Docker)
    participant L as Localizer
    participant M as LLM
    U->>A: run(instance)
    A->>S: start container (network off)
    A->>S: apply failing test, run tests
    S-->>A: failing test output
    A->>L: localize(issue, test output)
    L->>S: read repository files
    L-->>A: top files and functions
    A->>S: read those files
    loop attempt 1..N (each from the original code)
        A->>M: issue + failing tests + code (+ last attempt's feedback)
        M-->>A: SEARCH/REPLACE edits
        A->>S: apply edits, run tests
        S-->>A: test summary (fed back if still failing)
    end
    A->>S: grade best patch on a fresh checkout
    A-->>U: trajectory (every step) + result
```

## Data flow of an experiment

```mermaid
flowchart LR
    CFG[configs/*.yaml] --> RUN[patchpilot eval]
    RUN --> ROWS[results/EXP/benchmark.jsonl]
    RUN --> TRAJ[results/EXP/trajectories/*.json.gz]
    ROWS --> SUM[summarize_results.py] --> TABLES[results/summary/]
    ROWS --> FIG[make_figures.py] --> FIGS[report/figures/]
    TRAJ --> CLS[classify_failures.py] --> TAX[results/analysis/]
    TABLES --> README[README · report · dashboard]
    FIGS --> README
    TAX --> README
```

Every number shown anywhere is computed from the files on the left, and every table names its
source file.

## Machine and resource rules

The development laptop has no NVIDIA GPU and hosts other projects, so: experiments run Gemma 4 E4B
on the CPU (D12), training runs on Kaggle, at most one SWE-bench image exists at a time, long jobs
run detached at Below Normal priority with a duplicate guard, and PatchPilot stays under 10 GB of
disk (D14).
