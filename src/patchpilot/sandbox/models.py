"""Plain data types returned by the sandbox."""

from dataclasses import dataclass, field
from enum import StrEnum


class TestStatus(StrEnum):
    __test__ = False  # not a pytest test class

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class SandboxLimits:
    """Resource limits applied to every sandbox container."""

    cpus: float = 2.0
    memory: str = "2g"
    pids: int = 512
    timeout_s: int = 300
    max_output_chars: int = 20_000


@dataclass(frozen=True)
class ExecResult:
    """Outcome of one command run inside the container."""

    exit_code: int
    output: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class TestRunResult:
    """Outcome of a test command, with one status per test id."""

    __test__ = False  # not a pytest test class

    statuses: dict[str, TestStatus] = field(default_factory=dict)
    exit_code: int = 0
    output: str = ""
    duration_s: float = 0.0
    timed_out: bool = False

    @property
    def passed(self) -> list[str]:
        return sorted(t for t, s in self.statuses.items() if s is TestStatus.PASSED)

    @property
    def failed(self) -> list[str]:
        bad = (TestStatus.FAILED, TestStatus.ERROR)
        return sorted(t for t, s in self.statuses.items() if s in bad)

    @property
    def all_passed(self) -> bool:
        """True only when tests actually ran, none failed and the run did not time out."""
        return bool(self.statuses) and not self.failed and not self.timed_out
