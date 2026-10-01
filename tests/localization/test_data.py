from pathlib import Path

from patchpilot.localization import data as locdata

SRC = '''\
class Parser:
    """Parse HTTP headers."""

    def parse(self, raw):
        return raw.split(":")


def helper(x):
    return x
'''

PATCH = """\
--- a/pkg/parser.py
+++ b/pkg/parser.py
@@ -4,2 +4,2 @@ class Parser:
     def parse(self, raw):
-        return raw.split(":")
+        return raw.split(":", 1)
--- a/tests/test_parser.py
+++ b/tests/test_parser.py
@@ -1 +1 @@
-x
+y
"""

PROMPT = """<issue>boom</issue>
<code>
[start of README.md]
1 hello
[end of README.md]
[start of pkg/other.py]
1 def unrelated():
2     pass
[end of pkg/other.py]
</code>"""


def row(**overrides: str) -> dict[str, str]:
    base = {
        "instance_id": "o__r-1",
        "repo": "o/r",
        "patch": PATCH,
        "problem_statement": "Header parsing splits on every colon.",
    }
    base.update(overrides)
    return base


def test_parse_code_blocks_strips_line_numbers() -> None:
    files = locdata.parse_code_blocks(PROMPT)

    assert files == {"README.md": "hello", "pkg/other.py": "def unrelated():\n    pass"}


def test_file_skeleton_lists_signatures_with_docstring_summary() -> None:
    skeleton = locdata.file_skeleton("pkg/parser.py", SRC)

    assert skeleton.splitlines() == [
        "pkg/parser.py",
        "class Parser  # Parse HTTP headers.",
        "    def parse(self, raw)",
        "def helper(x)",
    ]


def test_build_example_labels_files_and_functions() -> None:
    example = locdata.build_example(
        row(), {"pkg/parser.py": SRC}, locdata.parse_code_blocks(PROMPT), "train"
    )

    assert example is not None
    assert example.gold_files == ["pkg/parser.py"]  # the test file is not a localization target
    assert example.gold_units == ["pkg/parser.py::Parser.parse"]
    labels = {c.cid: c.label for c in example.files}
    assert labels == {"pkg/other.py": 0, "pkg/parser.py": 1}  # README is not Python
    unit_labels = {c.cid: c.label for c in example.units}
    assert unit_labels["pkg/parser.py::Parser.parse"] == 1
    assert unit_labels["pkg/parser.py::helper"] == 0
    assert unit_labels["pkg/other.py::unrelated"] == 0


def test_build_example_skips_patches_without_source_edits() -> None:
    only_tests = "--- a/tests/t.py\n+++ b/tests/t.py\n@@ -1 +1 @@\n-x\n+y\n"

    assert locdata.build_example(row(patch=only_tests), {}, {}, "train") is None


def test_selection_is_seeded_and_capped_per_repo() -> None:
    rows = [{"repo": "big", "instance_id": f"b{i}"} for i in range(50)]
    rows += [{"repo": "small", "instance_id": "s1"}]

    first = locdata.select_instances(rows, per_repo_cap=10)
    again = locdata.select_instances(list(reversed(rows)), per_repo_cap=10)

    assert first == again
    assert sum(r == "big" for r in first.values()) == 10
    assert first["s1"] == "small"


def test_repo_split_keeps_each_repo_in_one_split() -> None:
    sizes = {f"repo{i}": 10 for i in range(20)}

    assignment = locdata.split_repos(sizes, val_share=0.1, test_share=0.1)

    assert set(assignment) == set(sizes)
    assert sum(s == "test" for s in assignment.values()) == 2
    assert sum(s == "val" for s in assignment.values()) == 2


def test_examples_round_trip(tmp_path: Path) -> None:
    example = locdata.build_example(row(), {"pkg/parser.py": SRC}, {}, "val")
    assert example is not None

    counts = locdata.write_examples([example], tmp_path)
    loaded = list(locdata.read_examples(tmp_path / "val.jsonl.gz"))

    assert counts == {"train": 0, "val": 1, "test": 0}
    assert loaded[0].gold_units == example.gold_units
    assert loaded[0].files[0].label == 1
