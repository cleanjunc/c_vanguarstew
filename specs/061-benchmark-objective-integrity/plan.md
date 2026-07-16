# Plan 061 — objective integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1739

Maps the [spec](./spec.md) onto `benchmark/objective_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_061_objective_integrity.py` |
| ------------ | ---------------------------------------------------- |
| Constants and signature | `test_default_tolerance_constant_and_echo` |
| Numeric helpers | `test_is_number_and_is_ratio_semantics`, `test_dict_round3_and_mean_helpers` |
| List coercion | `test_rows_list_coerces_none_non_list_and_skips_non_dict_entries` |
| Slice selection | `test_generalization_shape_requires_both_partitions_and_the_gap_key`, `test_unscored_generalization_partition_is_dropped`, `test_per_repo_slices_require_positive_tasks_and_rows`, `test_expand_slice_labels_use_the_coerced_index_not_the_raw_index`, `test_single_repo_falls_back_to_run_label_and_empty_result_selects_nothing` |
| Artifact shape | `test_non_dict_artifact_yields_single_artifact_shape_failure`, `test_no_scored_slice_fails_artifact_shape` |
| Per-slice checks | `test_clean_run_passes_all_five_checks_unprefixed`, `test_generalization_checks_are_prefixed_by_partition_label`, `test_missing_dict_objective_fails_objectives_present`, `test_objective_mean_mismatch_and_unusable_mean_both_fail`, `test_tolerance_boundary_is_inclusive` |
| Problem detail formatting / empty slice | `test_problem_details_are_row_indexed_and_truncated_asymmetrically`, `test_empty_slice_branch_including_the_two_as_built_quirks` |
| Recall field validation | `test_bool_recall_field_is_rejected_by_the_gate`, `test_non_ratio_recall_field_reports_problem`, `test_absent_recall_key_is_skipped_and_non_dict_objective_reported`, `test_kind_recall_only_checked_when_actual_kinds_truthy` |
| Malformed per_repo rows | `test_corrupt_string_per_repo_row_is_flagged_by_raw_index`, `test_non_string_and_blank_per_repo_rows_are_not_flagged`, `test_no_per_repo_container_adds_no_wellformed_check`, `test_generalization_corrupt_rows_are_labelled_by_partition` |
| Reporting | `test_check_rows_list_requires_str_name_and_strict_bool_passed`, `test_headline_branches_exact_text`, `test_failed_checks_names_only_failing_usable_rows` |
| Pure evaluation | `test_check_objective_integrity_does_not_mutate_its_input` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / missing-key branch called out
in the spec has an asserting test (lessons from the Spec 057 / Spec 059 incompleteness rejections).

**Expected anchor values are pinned as literals, not re-derived.** A fixture that computes its own
expected `objective_mean` by calling `score.objective_component` — the function under test — is
tautological and stays green against a broken anchor. `test_objective_component_literals_pinned`
asserts the anchor's exact outputs (`0.8`, `0.5`, `0.6`, and `0.0` for a bool recall) and the
fixtures use those literals.

Confirmed load-bearing by mutating the module and re-running (each mutant reverted afterwards);
every one below **failed** the suite: `score.objective_component` → always `0.0`; dropping the
`isinstance(value, bool)` guard in `_recall_field_problems`; `kind_recall_valid` additionally
requiring rows; `objectives_present` dropping its rows requirement; tolerance `<=` → `<`; removing
`recall_fields_valid`'s `" ..."` marker; relaxing `_check_rows_list`'s `type(row["passed"]) is not
bool` to accept `int`.

`_partition_scored` → `return True` is an **equivalent mutant**: defined as
`bool(_expand_slice("_probe", part))`, forcing it `True` only lets the following
`extend(_expand_slice(...))` add an empty list, so no observable behavior changes and no test can
distinguish it.

## Coverage

`benchmark/objective_integrity.py` sits at **89%** under `tests/test_objective_integrity.py` alone
(21 uncovered statements) and **98%** with this file added (3 uncovered): the contract tests reach
18 statements the existing suite never executes — chiefly the empty-slice branch, the truncation
markers and the `_check_rows_list` rejection paths. Integration and CLI coverage stays in
`tests/test_objective_integrity.py`.

## Out of scope

No change to `benchmark/objective_integrity.py` or any other product module: this is a Phase 1/2
transcription of as-built behavior. The stale "inflate … `float(True) == 1.0`" docstring claim is
recorded in the spec's *Known discrepancy* section and left to a follow-up.
