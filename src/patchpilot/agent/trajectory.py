"""Full record of one agent run: every tool call, every model call, and the outcome."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_STORED_TEXT = 20_000


@dataclass
class Step:
    index: int
    kind: str  # "tool" | "llm" | "note"
    name: str
    input: dict[str, Any]
    output: str
    ok: bool = True
    duration_s: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trajectory:
    run_id: str
    benchmark: str
    instance_id: str
    config: dict[str, Any]
    steps: list[Step] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def add(
        self,
        kind: str,
        name: str,
        input: dict[str, Any],
        output: str,
        ok: bool = True,
        duration_s: float = 0.0,
        **meta: Any,
    ) -> Step:
        step = Step(
            index=len(self.steps),
            kind=kind,
            name=name,
            input={k: _clip(v) for k, v in input.items()},
            output=_clip(output),
            ok=ok,
            duration_s=round(duration_s, 3),
            meta=meta,
        )
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.run_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8", newline="\n")
        return path

    @classmethod
    def load(cls, path: Path) -> Trajectory:
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = [Step(**s) for s in data.pop("steps")]
        return cls(steps=steps, **data)


class Timer:
    def __enter__(self) -> Timer:
        self.started = time.monotonic()
        self.elapsed = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed = time.monotonic() - self.started


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STORED_TEXT:
        return value[:MAX_STORED_TEXT] + f"\n... [{len(value) - MAX_STORED_TEXT} chars clipped]"
    return value
