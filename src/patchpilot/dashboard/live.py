"""The dashboard's "Try it" runner: one live agent run at a time, streamed step by step (S5).

Only one run may be active (PatchPilot's one-heavy-job rule, decisions D14). Steps are copied into
memory as the agent produces them; the page polls for them. A finished run is also saved to
runs/ like `patchpilot fix`, so it appears in the run list afterwards.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from patchpilot.agent import Step, Trajectory

# (instance_id, on_step, run_id) -> finished trajectory
RunFunction = Callable[[str, Callable[[Step], None], str], Trajectory]


@dataclass
class LiveRun:
    run_id: str
    instance_id: str
    state: str = "running"  # running | done | error
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class BusyError(RuntimeError):
    """Another live run is still going."""


class LiveRunner:
    def __init__(self, run: RunFunction, runs_dir: Path) -> None:
        self._run = run
        self._runs_dir = runs_dir
        self._lock = threading.Lock()
        self._runs: dict[str, LiveRun] = {}
        self._active: str | None = None

    def start(self, instance_id: str) -> str:
        with self._lock:
            if self._active is not None and self._runs[self._active].state == "running":
                raise BusyError(self._active)
            run_id = f"{instance_id}-live-{uuid.uuid4().hex[:6]}"
            self._runs[run_id] = LiveRun(run_id, instance_id)
            self._active = run_id
        thread = threading.Thread(target=self._work, args=(run_id,), daemon=True, name=run_id)
        thread.start()
        return run_id

    def status(self, run_id: str) -> LiveRun | None:
        return self._runs.get(run_id)

    def active(self) -> str | None:
        return self._active

    def _work(self, run_id: str) -> None:
        live = self._runs[run_id]

        def on_step(step: Step) -> None:
            live.steps.append(asdict(step))

        try:
            trajectory = self._run(live.instance_id, on_step, run_id)
            live.result = trajectory.result
            trajectory.save(self._runs_dir)
            live.state = "error" if trajectory.result.get("error") else "done"
            live.error = trajectory.result.get("error") or ""
        except Exception as exc:  # the page must always learn how the run ended
            live.state = "error"
            live.error = f"{type(exc).__name__}: {exc}"
