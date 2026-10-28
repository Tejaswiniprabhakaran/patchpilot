"""PatchPilot web dashboard (S5): runs, trajectories, diffs, metrics and a live "Try it" page.

    patchpilot dashboard            # http://127.0.0.1:8765

Read-only over results/ and runs/, except that a Try-it run writes its trajectory to runs/.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from patchpilot.dashboard.data import diff_html, list_runs, load_run, read_csv
from patchpilot.dashboard.live import BusyError, LiveRunner, RunFunction

HERE = Path(__file__).parent
DEFAULT_PORT = 8765
# Ports used by the owner's other projects; the dashboard must never bind them (decisions D14).
RESERVED_PORTS = (
    set(range(7100, 7124))
    | set(range(7201, 7204))
    | {9094, 9100, 9101, 9201, 27117, 5435, 6380, 3307}
    | set(range(3001, 3004))
    | set(range(4001, 4024))
    | set(range(8081, 8084))
    | {5433}
    | {5000, 5001, 5434}
)


class TryRequest(BaseModel):
    instance_id: str


def check_port(port: int) -> None:
    if port in RESERVED_PORTS:
        raise ValueError(f"port {port} is reserved for another project; choose another")


def default_health(ollama_url: str = "http://localhost:11434/v1") -> dict[str, Any]:
    """Can a live run start? Docker must answer a ping and Ollama must list its models."""
    status: dict[str, Any] = {}
    try:
        import docker

        docker.from_env(timeout=3).ping()
        status["docker"] = True
    except Exception as exc:
        status["docker"] = False
        status["docker_error"] = type(exc).__name__
    try:
        import httpx

        models = httpx.get(f"{ollama_url}/models", timeout=3).json().get("data", [])
        status["ollama"] = True
        status["models"] = [m.get("id") for m in models]
    except Exception as exc:
        status["ollama"] = False
        status["ollama_error"] = type(exc).__name__
    return status


def default_run(config_path: Path = Path("configs/agent_dev.yaml")) -> RunFunction:
    """Live runs use the development config: base Gemma 4 E4B on QuixBugs."""

    def run(instance_id: str, on_step: Callable[[Any], None], run_id: str) -> Any:
        from patchpilot.benchmarks import quixbugs
        from patchpilot.config import ExperimentConfig
        from patchpilot.evaluation.runner import make_agent

        config = ExperimentConfig.load(config_path)
        instance = quixbugs.load_instance(instance_id)
        return make_agent(config).run(
            instance, {"experiment": "try"}, on_step=on_step, run_id=run_id
        )

    return run


def quixbugs_ids() -> list[str]:
    try:
        from patchpilot.benchmarks import quixbugs

        return quixbugs.program_names(quixbugs.DEFAULT_ROOT)
    except Exception:
        return []


def create_app(
    results_dir: Path = Path("results"),
    runs_dir: Path = Path("runs"),
    figures_dir: Path = Path("report/figures"),
    health: Callable[[], dict[str, Any]] = default_health,
    run: RunFunction | None = None,
    instance_ids: Callable[[], list[str]] = quixbugs_ids,
) -> FastAPI:
    app = FastAPI(title="PatchPilot dashboard")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    if figures_dir.exists():
        app.mount("/figures", StaticFiles(directory=str(figures_dir)), name="figures")
    runner = LiveRunner(run or default_run(), runs_dir)

    @app.get("/", response_class=HTMLResponse)
    def runs_page(
        request: Request, experiment: str = "", benchmark: str = "", status: str = ""
    ) -> HTMLResponse:
        runs = list_runs(results_dir, runs_dir)
        experiments = sorted({r["experiment"] for r in runs})
        shown = [
            r
            for r in runs
            if (not experiment or r["experiment"] == experiment)
            and (not benchmark or r["benchmark"] == benchmark)
            and (not status or (status == "resolved") == r["resolved"])
        ]
        return templates.TemplateResponse(
            request,
            "runs.html",
            {
                "runs": shown,
                "total": len(runs),
                "experiments": experiments,
                "f": {"experiment": experiment, "benchmark": benchmark, "status": status},
            },
        )

    @app.get("/runs/{experiment}/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, experiment: str, run_id: str) -> HTMLResponse:
        data = load_run(results_dir, runs_dir, experiment, run_id)
        if data is None:
            raise HTTPException(404, "run not found")
        attempts = [
            {"attempt": s["input"].get("attempt"), "html": diff_html(s["output"])}
            for s in data["steps"]
            if s["name"] == "submit" and s["ok"]
        ]
        return templates.TemplateResponse(
            request,
            "run.html",
            {
                "experiment": experiment,
                "t": data,
                "attempt_diffs": attempts,
                "final_diff": diff_html(data.get("result", {}).get("final_patch") or ""),
            },
        )

    @app.get("/metrics", response_class=HTMLResponse)
    def metrics_page(request: Request) -> HTMLResponse:
        figures = sorted(p.name for p in figures_dir.glob("*.png")) if figures_dir.exists() else []
        return templates.TemplateResponse(
            request,
            "metrics.html",
            {
                "rates": read_csv(results_dir / "summary" / "resolve_rates.csv"),
                "tests": read_csv(results_dir / "summary" / "paired_tests.csv"),
                "taxonomy": read_csv(results_dir / "analysis" / "taxonomy.csv"),
                "figures": figures,
            },
        )

    @app.get("/try", response_class=HTMLResponse)
    def try_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "try.html", {"instances": instance_ids(), "active": runner.active()}
        )

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        return health()

    @app.post("/api/try")
    def api_try(body: TryRequest) -> JSONResponse:
        if body.instance_id not in instance_ids():
            raise HTTPException(400, "unknown QuixBugs program")
        state = health()
        if not (state.get("docker") and state.get("ollama")):
            raise HTTPException(503, "Docker and Ollama must both be running for a live run")
        try:
            run_id = runner.start(body.instance_id)
        except BusyError as busy:
            raise HTTPException(409, f"another live run is in progress: {busy}") from busy
        return JSONResponse({"run_id": run_id})

    @app.get("/api/try/{run_id}")
    def api_try_status(run_id: str) -> dict[str, Any]:
        live = runner.status(run_id)
        if live is None:
            raise HTTPException(404, "unknown live run")
        payload: dict[str, Any] = {
            "run_id": live.run_id,
            "state": live.state,
            "error": live.error,
            "steps": [
                {
                    "index": s["index"],
                    "kind": s["kind"],
                    "name": s["name"],
                    "ok": s["ok"],
                    "duration_s": s["duration_s"],
                    "output": s["output"][:3000],
                }
                for s in live.steps
            ],
        }
        if live.state != "running":
            payload["result"] = {k: v for k, v in live.result.items() if k != "final_patch"}
            payload["patch_html"] = diff_html(live.result.get("final_patch") or "")
        return payload

    return app
