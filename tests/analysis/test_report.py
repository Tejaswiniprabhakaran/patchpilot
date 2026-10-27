from patchpilot.analysis.report import agreement, sample_for_labelling, taxonomy


def label(run: str, category: str, experiment: str = "B0", status: str = "complete") -> dict:  # type: ignore[type-arg]
    return {
        "experiment": experiment,
        "benchmark": "quixbugs",
        "instance_id": run,
        "run_id": run,
        "category": category,
        "experiment_status": status,
    }


def test_taxonomy_counts_and_shares_with_status() -> None:
    labels = [label("a", "wrong_file"), label("b", "wrong_file"), label("c", "patch_invalid")]

    rows = {r["category"]: r for r in taxonomy(labels)}

    assert rows["wrong_file"]["count"] == 2
    assert rows["wrong_file"]["share"] == round(2 / 3, 4)
    assert rows["patch_invalid"]["failed_runs"] == 3
    assert rows["wrong_file"]["experiment_status"] == "complete"


def test_agreement_reports_accuracy_kappa_and_confusion() -> None:
    auto = [label("a", "wrong_file"), label("b", "patch_invalid"), label("c", "wrong_file")]
    manual = [
        {"run_id": "a", "category": "wrong_file"},
        {"run_id": "b", "category": "patch_invalid"},
        {"run_id": "c", "category": "incomplete_fix"},
    ]

    result = agreement(auto, manual)

    assert result["n"] == 3
    assert result["accuracy"] == round(2 / 3, 4)
    assert result["confusion_manual_to_classifier"]["incomplete_fix"] == {"wrong_file": 1}
    assert agreement(auto, [])["status"].startswith("TODO")


def test_labelling_sample_is_seeded_and_capped() -> None:
    labels = [label(f"r{i}", "wrong_file") for i in range(50)]

    first = sample_for_labelling(labels, n=30)
    again = sample_for_labelling(list(reversed(labels)), n=30)

    assert first == again
    assert len(first) == 30
    assert len(sample_for_labelling(labels[:5], n=30)) == 5
