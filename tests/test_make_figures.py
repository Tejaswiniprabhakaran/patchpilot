"""Smoke test: the figure script runs on the committed results and writes PNGs."""

import subprocess
import sys
from pathlib import Path


def test_make_figures_writes_figures_for_available_results(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/make_figures.py", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    written = {p.name for p in tmp_path.glob("*.png")}
    assert "llm_speed_cpu.png" in written  # results/llm_speed_cpu.jsonl is committed
    assert "localization_topk.png" in written  # results/localization/heldout_bm25_test.json
    # Figures without data are skipped with an explanation instead of failing.
    assert "skip" in result.stdout or len(written) >= 5
