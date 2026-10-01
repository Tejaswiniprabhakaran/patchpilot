"""Split a Python file into functions and methods (the units ranked at function level)."""

from __future__ import annotations

import ast
from dataclasses import dataclass

MODULE = "<module>"


@dataclass(frozen=True)
class CodeUnit:
    path: str
    name: str  # qualified, e.g. "Parser.parse" or "<module>" for top-level code
    start: int  # 1-based, inclusive
    end: int
    source: str

    @property
    def unit_id(self) -> str:
        return f"{self.path}::{self.name}"


def extract_units(path: str, source: str) -> list[CodeUnit]:
    """Every function and method in ``source``. Unparseable files yield no units."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    lines = source.splitlines()
    units: list[CodeUnit] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{child.name}"
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                end = child.end_lineno or child.lineno
                units.append(CodeUnit(path, name, start, end, "\n".join(lines[start - 1 : end])))
                visit(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")

    visit(tree, "")
    return units


def unit_for_line(units: list[CodeUnit], line: int) -> str:
    """Innermost function containing ``line``, or ``<module>`` if none does."""
    best: CodeUnit | None = None
    for unit in units:
        if unit.start <= line <= unit.end and (best is None or unit.start >= best.start):
            best = unit
    return best.name if best else MODULE


def edited_units(units: list[CodeUnit], lines: set[int]) -> list[str]:
    """Names of the functions containing any of ``lines`` (``<module>`` for top-level edits)."""
    return sorted({unit_for_line(units, line) for line in lines})
