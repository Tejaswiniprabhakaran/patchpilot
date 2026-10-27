"""Experiment configuration (YAML + Pydantic). One file fully describes one experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from patchpilot.agent import AgentConfig
from patchpilot.llm import LLMConfig

BenchmarkName = Literal["quixbugs", "swebench-lite"]


class BenchmarkSelection(BaseModel):
    name: BenchmarkName
    # "all", "subset50" / "subset10" (seeded SWE-bench Lite subsets), or explicit instance ids.
    instances: Literal["all", "subset50", "subset10"] | list[str] = "all"


class ExperimentConfig(BaseModel):
    id: str
    description: str = ""
    localizer: Literal["llm_search", "ranker"] = "llm_search"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    benchmarks: list[BenchmarkSelection] = Field(default_factory=list)
    results_dir: Path = Path("results")
    seed: int = 42

    @classmethod
    def load(cls, path: Path) -> ExperimentConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def output_dir(self) -> Path:
        return self.results_dir / self.id
