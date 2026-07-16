"""Contract tests for specs/061-benchmark-objective-integrity — assert objective_integrity.py
satisfies the spec's EARS criteria: constants, non-dict artifacts, empty slices, bool recall
fields, detail truncation, corrupt per_repo string rows, and every headline branch. Offline,
deterministic.

Expected anchor values are pinned as LITERALS, not re-derived by calling the function under test
(``score.objective_component``) — such a fixture stays green against a broken anchor.
``test_objective_component_literals_pinned`` ties those literals to the real anchor.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.objective_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _check_rows_list,
    _dict,
    _is_number,
    _is_ratio,
    _kind_recall_problems,
    _malformed_per_repo_rows,
    _mean,
    _recall_field_problems,
    _round3,
    _row_slices,
    _rows_list,
    check_objective_integrity,
    failed_checks,
    integrity_headline,
)
from benchmark.score import objective_component  # noqa: E402

# objective_component({"weighted_module_recall": 0.8, "module_recall": 0.2}) == 0.8 exactly:
# the weighted field wins and no actual_kinds means it is the only part. Pinned literally by
# test_objective_component_literals_pinned so these fixtures cannot drift silently.
_ANCHOR = 0.8


def _objective(**extra):
    return {"weighted_module_recall": 0.8, "module_recall": 0.2, **extra}


def _row(**extra):
    return {"objective": _objective(), **extra}


def _run(rows=None, objective_mean=_ANCHOR, **extra):
    """A single-repo artifact whose objective_mean is the pinned literal, not a re-derivation."""
    return {
        "rows": [_row()] if rows is None else rows,
        "composite_parts": {"objective_mean": objective_mean},
        **extra,
    }


def _named(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def test_objective_component_literals_pinned():
    """Tie the fixtures' literals to the real anchor (this is what catches a broken anchor)."""
    assert objective_component({"weighted_module_recall": 0.8, "module_recall": 0.2}) == _ANCHOR
    assert objective_component({"weighted_module_recall": 0.5, "module_recall": 0.5}) == 0.5
    # actual_kinds adds kind_recall as a second equally-weighted part: mean(0.8, 0.4) == 0.6.
    assert objective_component(
        {"weighted_module_recall": 0.8, "actual_kinds": ["feat"], "kind_recall": 0.4}
    ) == 0.6
    # A bool recall is floored to 0.0 by score._recall_for_component — deflation, never 1.0.
    assert objective_component({"weighted_module_recall": True}) == 0.0


# --- Recall field validation (load-bearing: this gate is what fails loudly on a bool) --------


def test_bool_recall_field_is_rejected_by_the_gate():
    assert _recall_field_problems(_objective(weighted_module_recall=True)) == [
        "weighted_module_recall is bool"
    ]
    out = check_objective_integrity(_run([_row(objective=_objective(weighted_module_recall=True))]))
    assert out["passed"] is False
    assert "recall_fields_valid" in failed_checks(out)


@pytest.mark.parametrize("bad", (1.5, -0.1, float("nan"), float("inf"), "0.5", None))
def test_non_ratio_recall_field_reports_problem(bad):
    assert _recall_field_problems(_objective(module_recall=bad)) == [
        f"module_recall={bad!r} is not a ratio in [0, 1]"
    ]


def test_absent_recall_key_is_skipped_and_non_dict_objective_reported():
    assert _recall_field_problems({}) == []
    assert _recall_field_problems("nope") == ["objective is not a dict"]
    assert _kind_recall_problems(None) == ["objective is not a dict"]


def test_kind_recall_only_checked_when_actual_kinds_truthy():
    assert _kind_recall_problems({"actual_kinds": []}) == []
    assert _kind_recall_problems({"kind_recall": 9.0}) == []       # no actual_kinds -> skipped
    # Missing kind_recall passes: the helper defaults it to an in-range value (0.0 as-built).
    assert _kind_recall_problems({"actual_kinds": ["feat"]}) == []
    assert _kind_recall_problems({"actual_kinds": ["feat"], "kind_recall": True}) == [
        "kind_recall is bool"
    ]
    assert _kind_recall_problems({"actual_kinds": ["feat"], "kind_recall": 2.0}) == [
        "kind_recall=2.0 is not a ratio in [0, 1]"
    ]


# --- Constants and numeric helpers ----------------------------------------------------------


def test_default_tolerance_constant_and_echo():
    assert DEFAULT_TOLERANCE == 0.002
    assert check_objective_integrity(_run())["tolerance"] == 0.002
    assert check_objective_integrity(_run(), tolerance=0.05)["tolerance"] == 0.05


def test_numeric_and_coercion_helper_semantics():
    assert _is_number(0) and _is_number(0.5)
    assert not _is_number(True) and not _is_number(float("nan")) and not _is_number(float("inf"))
    assert not _is_number("1") and not _is_number(None)
    assert not _is_number(10**400)          # OverflowError -> False, not a raise
    assert _is_ratio(0.0) and _is_ratio(1.0)
    assert not _is_ratio(1.0001) and not _is_ratio(-0.0001) and not _is_ratio(True)
    assert _dict({"a": 1}) == {"a": 1} and _dict(None) == {} and _dict("x") == {}
    assert _round3(0.12349) == 0.123
    assert _round3(float("nan")) is None and _round3("x") is None
    assert _mean([]) is None and _mean([0.1, 0.2]) == 0.15
    assert _rows_list(None) == [] and _rows_list("not a list") == []
    assert _rows_list([{"a": 1}, 7, None, {"b": 2}]) == [{"a": 1}, {"b": 2}]


# --- Slice selection ------------------------------------------------------------------------


def test_generalization_shape_requires_both_partitions_the_gap_key_and_a_scored_partition():
    gen = {"tuned": _run(), "held_out": _run(), "generalization_gap": 0.1}
    assert [label for label, _ in _row_slices(gen)] == ["tuned", "held_out"]
    assert _row_slices({"tuned": _run(), "held_out": _run()}) == []      # no gap key -> not gen
    unscored = {"tuned": _run(), "held_out": {"per_repo": [{"tasks": 0}]},
                "generalization_gap": 0.1}
    assert [label for label, _ in _row_slices(unscored)] == ["tuned"]


def test_per_repo_slices_require_positive_tasks_and_rows():
    result = {"per_repo": [
        dict(_run(), tasks=5),      # qualifies -> repo-0
        dict(_run(), tasks=0),      # zero tasks -> skipped
        {"tasks": 5},               # rows None -> skipped
    ]}
    assert [label for label, _ in _row_slices(result)] == ["repo-0"]


def test_expand_slice_labels_use_the_coerced_index_not_the_raw_index():
    """A non-dict row is dropped before indexing, so the surviving dict is repo-0, not repo-1."""
    result = {"tuned": {"per_repo": ["CORRUPT", dict(_run(), tasks=5)]},
              "held_out": _run(), "generalization_gap": 0.1}
    assert [label for label, _ in _row_slices(result)] == ["tuned:repo-0", "held_out"]


def test_single_repo_falls_back_to_run_label_and_empty_result_selects_nothing():
    assert [label for label, _ in _row_slices(_run())] == ["run"]
    assert _row_slices({}) == []


# --- Artifact shape -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "x", 42, [1]))
def test_non_dict_artifact_yields_single_artifact_shape_failure(bad):
    out = check_objective_integrity(bad)
    assert out["passed"] is False
    assert [c["name"] for c in out["checks"]] == ["artifact_shape"]
    assert out["checks"][0]["detail"] == (
        f"artifact must be a JSON object, got {type(bad).__name__}"
    )


def test_no_scored_slice_fails_artifact_shape():
    out = check_objective_integrity({}, tolerance=0.05)
    assert _named(out, "artifact_shape")["detail"] == (
        "no scored replay slice with per-task rows to verify"
    )
    assert out["passed"] is False


# --- Per-slice checks -----------------------------------------------------------------------


def test_clean_run_passes_all_five_checks_unprefixed():
    out = check_objective_integrity(_run())
    assert out["passed"] is True
    assert [c["name"] for c in out["checks"]] == [
        "rows_present", "objectives_present", "recall_fields_valid",
        "kind_recall_valid", "objective_mean_matches_rows",
    ]
    assert _named(out, "rows_present")["detail"] == "1 usable row(s)"


def test_generalization_checks_are_prefixed_by_partition_label():
    out = check_objective_integrity(
        {"tuned": _run(), "held_out": _run(), "generalization_gap": 0.1}
    )
    assert out["passed"] is True
    names = [c["name"] for c in out["checks"]]
    assert "tuned:rows_present" in names and "held_out:objective_mean_matches_rows" in names


def test_missing_dict_objective_fails_objectives_present():
    out = check_objective_integrity(_run([_row(), {"objective": "nope"}]))
    assert _named(out, "objectives_present")["passed"] is False
    assert _named(out, "objectives_present")["detail"] == "1 row(s) missing a dict objective"


def test_objective_mean_mismatch_and_unusable_mean_both_fail():
    assert _named(check_objective_integrity(_run(objective_mean=0.1)),
                  "objective_mean_matches_rows")["passed"] is False
    assert _named(check_objective_integrity(_run(objective_mean=None)),
                  "objective_mean_matches_rows")["detail"] == (
        "cannot compare objective_mean to row objective components"
    )


def test_tolerance_boundary_is_inclusive():
    """delta exactly == tolerance passes; just beyond it fails."""
    assert _named(check_objective_integrity(_run(objective_mean=_ANCHOR + 0.002)),
                  "objective_mean_matches_rows")["passed"] is True
    assert _named(check_objective_integrity(_run(objective_mean=_ANCHOR + 0.003)),
                  "objective_mean_matches_rows")["passed"] is False


def test_empty_slice_branch_including_the_two_as_built_quirks():
    out = check_objective_integrity(_run(rows=[]))
    assert _named(out, "rows_present")["passed"] is False
    # objectives_present fails on an empty slice: it requires rows, not merely "none missing".
    assert _named(out, "objectives_present")["passed"] is False
    assert _named(out, "objectives_present")["detail"] == "no rows to verify"
    # recall_fields_valid FAILS while carrying its success detail (passed and detail use
    # different conditions); kind_recall_valid is the only check that passes on an empty slice.
    assert _named(out, "recall_fields_valid")["passed"] is False
    assert _named(out, "recall_fields_valid")["detail"] == (
        "all recall fields are finite ratios in [0, 1]"
    )
    assert _named(out, "kind_recall_valid")["passed"] is True
    assert out["passed"] is False


def test_problem_details_are_row_indexed_and_truncated_asymmetrically():
    bad_recall = [{"objective": {"module_recall": 9.0}} for _ in range(4)]
    detail = _named(check_objective_integrity(_run(rows=bad_recall)), "recall_fields_valid")["detail"]
    assert detail.startswith("row[0]: module_recall=9.0 is not a ratio in [0, 1]; row[1]:")
    assert detail.count("row[") == 3 and detail.endswith(" ...")   # capped at 3, marker appended

    bad_kind = [{"objective": {"actual_kinds": ["f"], "kind_recall": 9.0}} for _ in range(4)]
    kind_detail = _named(check_objective_integrity(_run(rows=bad_kind)), "kind_recall_valid")["detail"]
    assert kind_detail.count("row[") == 3 and not kind_detail.endswith(" ...")  # no marker


# --- Malformed per_repo rows ----------------------------------------------------------------


def test_corrupt_string_per_repo_row_is_flagged_by_raw_index():
    out = check_objective_integrity({"per_repo": [dict(_run(), tasks=5), "CLONE FAILED: boom"]})
    check = _named(out, "per_repo_rows_wellformed")
    assert check["passed"] is False
    assert check["detail"] == "corrupt per_repo string row(s): repo-1"
    assert out["passed"] is False


@pytest.mark.parametrize("benign", (7, None, [], "", "   ", {"error": "unscored repo"}))
def test_non_string_and_blank_per_repo_rows_are_not_flagged(benign):
    result = {"per_repo": [dict(_run(), tasks=5), benign]}
    check = _named(check_objective_integrity(result), "per_repo_rows_wellformed")
    assert check["passed"] is True
    assert check["detail"] == "all per_repo rows are well-formed result objects"


def test_no_per_repo_container_adds_no_wellformed_check():
    assert _malformed_per_repo_rows(_run()) is None
    assert "per_repo_rows_wellformed" not in [
        c["name"] for c in check_objective_integrity(_run())["checks"]
    ]
    assert _malformed_per_repo_rows({"per_repo": "nope"}) is None   # present but not a list


def test_generalization_corrupt_rows_are_labelled_by_partition():
    result = {
        "tuned": {"per_repo": [dict(_run(), tasks=5)]},
        "held_out": {"per_repo": ["BOOM"]},
        "generalization_gap": 0.1,
    }
    assert _malformed_per_repo_rows(result) == ["held_out:repo-0"]


# --- Aggregation and reporting --------------------------------------------------------------


def test_check_rows_list_requires_str_name_and_strict_bool_passed(caplog):
    assert _check_rows_list(None) == [] and _check_rows_list("x") == []
    assert _check_rows_list([{"name": "a", "passed": 1}]) == []       # 1 is not exactly a bool
    assert _check_rows_list([{"name": 7, "passed": True}]) == []      # name must be str
    assert _check_rows_list([{"name": "a"}]) == []                    # missing 'passed'
    assert _check_rows_list([{"name": "a", "passed": True}]) == [{"name": "a", "passed": True}]
    with caplog.at_level(logging.WARNING):
        _check_rows_list([{"name": "a", "passed": 1}])
    assert "no usable rows" in caplog.text     # summarising warning when nothing survives


def test_headline_branches_exact_text():
    assert integrity_headline({}) == "objective integrity: no checks evaluated"
    assert integrity_headline(
        {"passed": True, "checks": [{"name": "a", "passed": True}]}
    ) == "objective integrity: VALID (1 checks passed)"
    assert integrity_headline({
        "passed": False,
        "checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}],
    }) == "objective integrity: INVALID (1/2 checks failed: b)"


def test_failed_checks_names_only_failing_usable_rows():
    result = {"checks": [
        {"name": "ok", "passed": True},
        {"name": "bad", "passed": False},
        {"name": "unusable", "passed": 0},
    ]}
    assert failed_checks(result) == ["bad"]


def test_check_objective_integrity_does_not_mutate_its_input():
    result = {"per_repo": [dict(_run(), tasks=5), "BOOM"]}
    before = copy.deepcopy(result)
    check_objective_integrity(result)
    assert result == before
