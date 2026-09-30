"""PatchPilot command-line interface (S3).

Phase 0 only wires up the entry point; `fix`, `eval` and `show` arrive in Phase 2.
"""

import typer

from patchpilot import __version__

app = typer.Typer(
    name="patchpilot",
    help="An AI agent that fixes real bugs and verifies the fix in a Docker sandbox.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """PatchPilot command-line interface."""


@app.command()
def version() -> None:
    """Print the installed PatchPilot version."""
    typer.echo(f"patchpilot {__version__}")
