from patchpilot.agent import parse_edits
from patchpilot.patchgen.data import (
    apply_hunks,
    build_example,
    hunks_to_blocks,
    parse_hunks,
    render_blocks,
)
from patchpilot.tools import apply_search_replace

SOURCE = """\
def add(a, b):
    return a - b


def sub(a, b):
    return a - b
"""

PATCH = """\
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
--- a/tests/test_mod.py
+++ b/tests/test_mod.py
@@ -1 +1,2 @@
 x
+y
"""


def test_parse_hunks_skips_tests_markers_and_new_files() -> None:
    patch = PATCH + "--- /dev/null\n+++ b/pkg/new.py\n@@ -0,0 +1 @@\n+print(1)\n"

    hunks = parse_hunks(patch)

    assert set(hunks) == {"pkg/mod.py", "tests/test_mod.py"}
    assert hunks["pkg/mod.py"][0].old == ["def add(a, b):", "    return a - b"]
    assert hunks["pkg/mod.py"][0].new == ["def add(a, b):", "    return a + b"]


def test_blocks_are_unique_and_reproduce_git_apply() -> None:
    # "    return a - b" alone appears twice; the hunk's context line makes it unique.
    hunks = parse_hunks(PATCH)["pkg/mod.py"]

    blocks = hunks_to_blocks("pkg/mod.py", SOURCE, hunks)

    assert blocks is not None
    assert SOURCE.count(blocks[0].search) == 1
    updated, _ = apply_search_replace(SOURCE, blocks[0].search, blocks[0].replace)
    assert updated == apply_hunks(SOURCE, hunks)


def test_ambiguous_block_is_grown_with_real_file_lines() -> None:
    patch = "--- a/m.py\n+++ b/m.py\n@@ -6,1 +6,1 @@\n-    return a - b\n+    return a // b\n"
    hunks = parse_hunks(patch)["m.py"]

    blocks = hunks_to_blocks("m.py", SOURCE, hunks)

    assert blocks is not None
    assert blocks[0].search.startswith("def sub(a, b):")  # grown upwards until unique
    assert "a // b" in blocks[0].replace


def test_rendered_blocks_parse_back_with_the_agent_parser() -> None:
    blocks = hunks_to_blocks("pkg/mod.py", SOURCE, parse_hunks(PATCH)["pkg/mod.py"])
    assert blocks is not None

    edits = parse_edits(render_blocks(blocks))

    assert [(e.path, e.search, e.replace) for e in edits] == [
        (b.path, b.search, b.replace) for b in blocks
    ]


def test_build_example_uses_agent_prompt_format() -> None:
    row = {
        "instance_id": "o__r-1",
        "repo": "o/r",
        "patch": PATCH,
        "test_patch": "--- a/tests/test_mod.py\n+++ b/tests/test_mod.py\n",
        "problem_statement": "add() subtracts.",
    }

    example, reason = build_example(row, {"pkg/mod.py": SOURCE}, "train")

    assert reason == ""
    assert example is not None
    system, user, assistant = (m["content"] for m in example["messages"])
    assert "SEARCH/REPLACE" in system or "<<<<<<< SEARCH" in system
    assert "add() subtracts." in user
    assert "     2      return a - b" in user  # numbered like the agent's context
    assert "Tests added by the fix" in user
    assert parse_edits(assistant)[0].replace == "def add(a, b):\n    return a + b\n"
    assert example["files"] == ["pkg/mod.py"]


def test_build_example_reports_why_it_skipped() -> None:
    row = {
        "instance_id": "x",
        "repo": "o/r",
        "patch": PATCH,
        "test_patch": "",
        "problem_statement": "",
    }

    assert build_example(row, {}, "train") == (None, "missing_source")
    only_tests = "--- a/tests/t.py\n+++ b/tests/t.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert build_example(row | {"patch": only_tests}, {}, "train") == (
        None,
        "no_python_source_edit",
    )


def test_multi_file_or_many_hunk_fixes_are_skipped_like_swe_bench_lite() -> None:
    two_files = PATCH.replace("tests/test_mod.py", "pkg/other.py")
    row = {
        "instance_id": "x",
        "repo": "o/r",
        "patch": two_files,
        "test_patch": "",
        "problem_statement": "",
    }

    assert build_example(row, {"pkg/mod.py": SOURCE, "pkg/other.py": "x\n"}, "train") == (
        None,
        "not_lite_like",
    )
