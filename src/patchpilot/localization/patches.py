"""Which files and lines does a unified diff change? (labels for fault localization, A1)"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileEdit:
    path: str
    # 1-based line numbers in the ORIGINAL file that the patch removes or changes. A pure
    # insertion is attributed to the original line just before it (where the bug "is").
    lines: set[int] = field(default_factory=set)
    is_new_file: bool = False


def edited_lines(diff: str) -> dict[str, FileEdit]:
    """Map each file the diff modifies to the original-file lines it touches."""
    edits: dict[str, FileEdit] = {}
    current: FileEdit | None = None
    old_line = 0
    pending_new_file = False
    for line in diff.splitlines():
        if line.startswith("--- "):
            pending_new_file = line.strip() == "--- /dev/null"
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":  # deleted file: nothing to localize in its new form
                current = None
                continue
            path = target[2:] if target.startswith("b/") else target
            current = edits.setdefault(path, FileEdit(path=path, is_new_file=pending_new_file))
            continue
        match = _HUNK.match(line)
        if match:
            old_line = int(match.group(1))
            continue
        if current is None or not line:
            if current is not None and not line:
                old_line += 1  # an empty context line
            continue
        marker = line[0]
        if marker == " ":
            old_line += 1
        elif marker == "-":
            current.lines.add(old_line)
            old_line += 1
        elif marker == "+":
            current.lines.add(max(old_line - 1, 1))
    return edits
