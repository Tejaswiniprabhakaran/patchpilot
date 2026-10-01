"""Agent loop, localization strategies, prompts and trajectory logging (S2)."""

from patchpilot.agent.edits import Edit, parse_edits
from patchpilot.agent.localize import LLMSearchLocalizer, Localization, Localizer
from patchpilot.agent.loop import Agent, AgentConfig, Candidate
from patchpilot.agent.trajectory import Step, Trajectory

__all__ = [
    "Agent",
    "AgentConfig",
    "Candidate",
    "Edit",
    "LLMSearchLocalizer",
    "Localization",
    "Localizer",
    "Step",
    "Trajectory",
    "parse_edits",
]
