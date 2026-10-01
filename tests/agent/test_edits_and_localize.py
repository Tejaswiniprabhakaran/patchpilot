from pathlib import Path

import pytest

from patchpilot.agent import parse_edits
from patchpilot.agent.localize import extract_json, is_test_path, keywords_from_text
from patchpilot.agent.trajectory import Trajectory

REPLY = """The bug is a wrong operator.

pkg/mod.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE

```python
File: pkg/other.py
<<<<<<< SEARCH
x = 1
=======
x = 2
>>>>>>> REPLACE
```
"""


def test_parse_edits_handles_plain_and_fenced_blocks() -> None:
    edits = parse_edits(REPLY)

    assert [e.path for e in edits] == ["pkg/mod.py", "pkg/other.py"]
    assert edits[0].search == "    return a - b\n"
    assert edits[0].replace == "    return a + b\n"
    assert edits[1].replace == "x = 2\n"


def test_parse_edits_ignores_malformed_blocks() -> None:
    assert parse_edits("pkg/mod.py\n<<<<<<< SEARCH\nx\n>>>>>>> REPLACE\n") == []
    assert parse_edits("no edits here") == []


def test_extract_json_finds_object_inside_prose_and_fences() -> None:
    text = 'Sure!\n```json\n{"files": ["a.py"], "keywords": ["f"]}\n```\nDone {not json}'

    assert extract_json(text) == {"files": ["a.py"], "keywords": ["f"]}
    assert extract_json("nothing") == {}
    assert extract_json('{broken} then {"ok": 1}') == {"ok": 1}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("pkg/tests/helpers.py", True),
        ("pkg/test_a.py", True),
        ("pkg/a_test.py", True),
        ("conftest.py", True),
        ("python_testcases/test_gcd.py", True),
        ("pkg/testing_utils.py", False),
        ("django/db/models/query.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected


def test_keywords_from_text_skips_stopwords_and_duplicates() -> None:
    text = 'File "/testbed/pkg/mod.py", line 3, in compute_total\n    return self.compute_total()'

    words = keywords_from_text(text)

    assert words.count("compute_total") == 1
    assert "self" not in words
    assert "File" not in words


def test_trajectory_round_trips_and_clips_long_text(tmp_path: Path) -> None:
    trajectory = Trajectory("run-1", "demo", "demo-1", {"k": 1})
    trajectory.add("tool", "read_file", {"path": "a.py"}, "x" * 30_000, prompt_tokens=3)
    trajectory.result["resolved"] = True

    loaded = Trajectory.load(trajectory.save(tmp_path))

    assert loaded.result == {"resolved": True}
    assert loaded.steps[0].meta == {"prompt_tokens": 3}
    assert len(loaded.steps[0].output) < 30_000
    assert "clipped" in loaded.steps[0].output
