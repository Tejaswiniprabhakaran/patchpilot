"""Parse the model's SEARCH/REPLACE edit blocks.

The model is asked to answer in this format (the same one Aider popularised, because small models
reproduce it reliably and it needs no line numbers):

    path/to/file.py
    <<<<<<< SEARCH
    exact lines to find
    =======
    lines to put instead
    >>>>>>> REPLACE
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BLOCK = re.compile(
    r"(?P<path>[^\n`<>=]+?)\s*\n"
    r"(?:```[a-zA-Z]*\s*\n)?"
    r"<{5,9} ?SEARCH\s*\n"
    r"(?P<search>.*?)"
    r"^={5,9}\s*\n"
    r"(?P<replace>.*?)"
    r"^>{5,9} ?REPLACE",
    re.DOTALL | re.MULTILINE,
)


@dataclass(frozen=True)
class Edit:
    path: str
    search: str
    replace: str


def parse_edits(text: str) -> list[Edit]:
    """Every well-formed SEARCH/REPLACE block in ``text``, in order."""
    edits = []
    for match in _BLOCK.finditer(text):
        path = match.group("path").strip().strip("`*").strip()
        path = path.split()[-1] if path else path  # "File: a/b.py" -> "a/b.py"
        edits.append(Edit(path=path, search=match.group("search"), replace=match.group("replace")))
    return edits
