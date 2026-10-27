import json
from collections.abc import Sequence

from tests.fakes import FakeSandbox, make_instance

from patchpilot.agent.trajectory import Trajectory
from patchpilot.localization.bm25 import BM25Ranker
from patchpilot.localization.cross_encoder import CrossEncoderRanker
from patchpilot.localization.localizer import RankerLocalizer, repo_python_files
from patchpilot.sandbox import ExecResult
from patchpilot.tools import Toolbox

REPO = {
    "pkg/parser.py": "def parse_header(raw):\n    return raw.split(':')\n\ndef other():\n    pass",
    "pkg/render.py": "def render_page(t):\n    return t\n",
    "pkg/db.py": "def connect():\n    pass\n",
    "tests/test_parser.py": "def test_parse_header():\n    assert False\n",
}


class DumpingSandbox(FakeSandbox):
    """FakeSandbox that answers the in-container file dump with JSON."""

    def exec(self, command: str, timeout_s: int | None = None, truncate: bool = True) -> ExecResult:
        if command.startswith("python - <<'PYEOF'"):
            return ExecResult(0, "noise before json\n" + json.dumps(self.files), 0.1)
        return super().exec(command, timeout_s, truncate)


class KeywordRanker:
    """Stand-in for the cross-encoder: scores by how many query words a text contains."""

    name = "keyword"

    def rank(
        self, query: str, doc_ids: Sequence[str], texts: Sequence[str]
    ) -> list[tuple[str, float]]:
        words = set(query.lower().replace("_", " ").split())
        scores = [sum(w in t.lower() for w in words) for t in texts]
        return sorted(zip(doc_ids, map(float, scores), strict=True), key=lambda p: -p[1])


def test_repo_python_files_parses_the_dump() -> None:
    box = DumpingSandbox(REPO)

    assert repo_python_files(box) == REPO  # type: ignore[arg-type]


def test_ranker_localizer_returns_top_files_and_function_keywords() -> None:
    box = DumpingSandbox(REPO)
    instance = make_instance(problem_statement="parse header splits on every colon")
    trajectory = Trajectory("r", "demo", "demo-1", {})
    localizer = RankerLocalizer(KeywordRanker(), top_k=2, top_units=1)

    result = localizer.localize(instance, Toolbox(box, instance), "", trajectory)  # type: ignore[arg-type]

    assert result.files[0] == "pkg/parser.py"
    assert "tests/test_parser.py" not in result.files  # tests are never localization targets
    assert result.keywords == ["parse_header"]
    assert trajectory.steps[-1].name == "localization"
    assert trajectory.steps[-1].meta["candidate_files"] == 3


def test_cross_encoder_ranker_sorts_by_injected_scores() -> None:
    ranker = CrossEncoderRanker("unused", scorer=lambda q, texts: [len(t) for t in texts])

    assert ranker.rank("q", ["a", "b"], ["x", "xyz"]) == [("b", 3.0), ("a", 1.0)]


def test_bm25_satisfies_the_ranker_protocol() -> None:
    ranker = BM25Ranker(["a.py"], ["parse header"])

    assert ranker.rank("header")[0][0] == "a.py"
