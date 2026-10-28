import json
from pathlib import Path

import pytest

from patchpilot.evaluation.results import load_experiment
from patchpilot.evaluation.stats import (
    Rate,
    mcnemar_exact,
    paired_compare,
    resolved_within,
    wilson_interval,
)
from patchpilot.evaluation.summary import build_tables, markdown, write_tables


def test_wilson_interval_known_values() -> None:
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4)
    assert high == pytest.approx(0.7634, abs=1e-4)
    assert wilson_interval(0, 0) == (0.0, 0.0)
    assert wilson_interval(0, 10)[0] == 0.0


def test_exact_mcnemar() -> None:
    assert mcnemar_exact(0, 6) == pytest.approx(2 * 0.5**6)  # 0.03125: significant
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 5) == pytest.approx(2 * (1 + 6) / 64)  # 0.21875


def test_paired_compare_uses_only_common_instances() -> None:
    a = {"x": True, "y": True, "z": False, "only_a": True}
    b = {"x": True, "y": False, "z": True, "only_b": False}

    result = paired_compare("A", a, "B", b)

    assert (result.n, result.both, result.a_only, result.b_only, result.neither) == (3, 1, 1, 1, 0)
    assert result.p_value == 1.0
    assert not result.significant()


def test_resolved_within_k_attempts() -> None:
    rows = [
        {"resolved": True, "best_attempt": 1},
        {"resolved": True, "best_attempt": 3},
        {"resolved": False, "best_attempt": 2},
    ]

    assert resolved_within(rows, 1) == Rate(1, 3)
    assert resolved_within(rows, 3) == Rate(2, 3)
    assert Rate(2, 3).describe().startswith("2/3 (66.7%")


def write_rows(results: Path, experiment: str, benchmark: str, rows: list[dict]) -> None:  # type: ignore[type-arg]
    folder = results / experiment
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{benchmark}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_load_experiment_excludes_invalid_instances(tmp_path: Path) -> None:
    sanity = tmp_path / "sanity.jsonl"
    sanity.write_text(json.dumps({"instance_id": "bad", "valid": False}) + "\n")
    write_rows(
        tmp_path,
        "B0",
        "swebench-lite",
        [{"instance_id": "bad", "resolved": True}, {"instance_id": "ok", "resolved": False}],
    )

    res = load_experiment("B0", "swebench-lite", tmp_path, sanity)

    assert list(res.rows) == ["ok"]
    assert res.excluded == ["bad"]
    assert not res.complete  # 1 of 10 - 1 excluded


def test_build_tables_reports_todo_and_tests_only_complete_pairs(tmp_path: Path) -> None:
    sanity = tmp_path / "sanity.jsonl"
    sanity.write_text("")
    full_b0 = [
        {
            "instance_id": f"q{i}",
            "resolved": i < 10,
            "best_attempt": 1,
            "attempts_used": 1,
            "wall_s": 10.0,
            "llm_calls": 2,
            "prompt_tokens": 100,
            "completion_tokens": 20,
        }
        for i in range(40)
    ]
    full_e1 = [dict(r, resolved=r["instance_id"] in {f"q{i}" for i in range(16)}) for r in full_b0]
    write_rows(tmp_path, "B0", "quixbugs", full_b0)
    write_rows(tmp_path, "E1", "quixbugs", full_e1)

    tables = build_tables(tmp_path, sanity)

    rates = {(r["config"], r["benchmark"]): r for r in tables["resolve_rates"]}
    assert rates[("B0", "quixbugs")]["resolved"] == 10
    assert rates[("E1", "quixbugs")]["resolved"] == 16
    assert ("E2", "quixbugs") not in rates  # fine-tuning was dropped (D18)
    rq2 = next(
        t
        for t in tables["paired_tests"]
        if t["benchmark"] == "quixbugs" and (t["a"], t["b"]) == ("B0", "E1")
    )
    assert rq2["status"] == "done"
    assert (rq2["a_only"], rq2["b_only"]) == (0, 6)
    assert rq2["mcnemar_exact_p"] == pytest.approx(0.0312, abs=1e-4)
    swe = next(t for t in tables["paired_tests"] if t["benchmark"] == "swebench-lite")
    assert swe["status"].startswith("TODO")
    text = markdown(tables)
    assert "TODO: not yet run" in text
    assert "`" + str(tmp_path / "B0" / "quixbugs.jsonl").replace("\\", "/") + "`" in text
    written = write_tables(tables, tmp_path / "summary")
    assert {p.name for p in written} == {
        "resolve_rates.csv",
        "paired_tests.csv",
        "retries_curve.csv",
        "cost.csv",
    }


def test_derived_configs_cap_attempts(tmp_path: Path) -> None:
    sanity = tmp_path / "sanity.jsonl"
    sanity.write_text("")
    rows = [
        {
            "instance_id": f"q{i}",
            "resolved": i < 4,
            "best_attempt": 1 if i < 2 else 3,
            "attempts_used": 3,
        }
        for i in range(40)
    ]
    write_rows(tmp_path, "E1", "quixbugs", rows)

    tables = build_tables(tmp_path, sanity)

    rates = {(r["config"], r["benchmark"]): r for r in tables["resolve_rates"]}
    assert rates[("E1", "quixbugs")]["resolved"] == 4
    assert rates[("E1@1", "quixbugs")]["resolved"] == 2
    curve = {
        c["attempts"]: c["resolved"]
        for c in tables["retries_curve"]
        if c["benchmark"] == "quixbugs" and c["config"] == "E1"
    }
    assert curve == {1: 2, 2: 2, 3: 4}


def test_retries_are_measured_on_the_base_model_runs(tmp_path: Path) -> None:
    sanity = tmp_path / "sanity.jsonl"
    sanity.write_text("")
    # 40 instances: 6 fixed at the first attempt, 4 more only after a retry.
    rows = [
        {
            "instance_id": f"q{i}",
            "resolved": i < 10,
            "best_attempt": 1 if i < 6 else 2,
            "attempts_used": 1 if i < 6 else 2,
        }
        for i in range(40)
    ]
    write_rows(tmp_path, "B0", "quixbugs", rows)

    tables = build_tables(tmp_path, sanity)

    rates = {(r["config"], r["benchmark"]): r for r in tables["resolve_rates"]}
    assert (rates[("B0@1", "quixbugs")]["resolved"], rates[("B0", "quixbugs")]["resolved"]) == (
        6,
        10,
    )
    rq4 = next(t for t in tables["paired_tests"] if (t["a"], t["b"]) == ("B0@1", "B0"))
    assert rq4["status"] == "done" and (rq4["a_only"], rq4["b_only"]) == (0, 4)
    curve = [(c["attempts"], c["resolved"]) for c in tables["retries_curve"] if c["config"] == "B0"]
    assert curve == [(1, 6), (2, 10), (3, 10)]
    assert "| B0 | quixbugs | 2 | 10/40 | 25.0% |" in markdown(tables)


def test_runs_left_out_by_design_are_not_todo(tmp_path: Path) -> None:
    sanity = tmp_path / "sanity.jsonl"
    sanity.write_text("")

    tables = build_tables(tmp_path, sanity)

    rates = {(r["config"], r["benchmark"]): r for r in tables["resolve_rates"]}
    assert rates[("E1", "quixbugs")]["status"] == "not run (D19)"
    assert rates[("E1", "swebench-lite")]["status"] == "TODO: not yet run"
    rq2 = next(
        t
        for t in tables["paired_tests"]
        if (t["a"], t["b"], t["benchmark"]) == ("B0", "E1", "quixbugs")
    )
    assert rq2["status"] == "not run (D19)"
