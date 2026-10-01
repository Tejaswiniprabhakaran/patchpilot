from patchpilot.localization.code_units import MODULE, edited_units, extract_units, unit_for_line
from patchpilot.localization.patches import edited_lines

DIFF = """\
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -3,4 +3,4 @@ class Calc:
     def add(self, a, b):
-        return a - b
+        return a + b

@@ -10,2 +10,3 @@ def helper():
     x = 1
+    y = 2
     return x
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1 @@
+print('hi')
"""

SOURCE = """\
import os

class Calc:
    def add(self, a, b):
        return a - b

    @staticmethod
    def sub(a, b):
        return a - b
def helper():
    x = 1
    return x
"""


def test_edited_lines_maps_removals_and_insertions_to_original_lines() -> None:
    edits = edited_lines(DIFF)

    assert set(edits) == {"pkg/mod.py", "pkg/new.py"}
    assert edits["pkg/mod.py"].lines == {4, 10}
    assert not edits["pkg/mod.py"].is_new_file
    assert edits["pkg/new.py"].is_new_file


def test_extract_units_qualifies_methods_and_includes_decorators() -> None:
    units = {u.name: u for u in extract_units("pkg/mod.py", SOURCE)}

    assert set(units) == {"Calc.add", "Calc.sub", "helper"}
    assert units["Calc.sub"].start == 7  # the decorator line
    assert units["helper"].source.startswith("def helper():")
    assert units["Calc.add"].unit_id == "pkg/mod.py::Calc.add"


def test_lines_map_to_innermost_function_or_module() -> None:
    units = extract_units("pkg/mod.py", SOURCE)

    assert unit_for_line(units, 5) == "Calc.add"
    assert unit_for_line(units, 1) == MODULE
    assert edited_units(units, {5, 11, 1}) == [MODULE, "Calc.add", "helper"]


def test_unparseable_source_yields_no_units() -> None:
    assert extract_units("bad.py", "def broken(:\n") == []
