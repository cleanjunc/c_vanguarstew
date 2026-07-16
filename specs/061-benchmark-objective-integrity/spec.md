# Spec 061 — objective integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1739
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (row composite vs headline),
  [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py) (composite blend),
  [`benchmark/score.py`](../../benchmark/score.py) (`objective_component`, the anchor under test)

This spec makes the **existing, implicit** objective-integrity contract explicit. It describes the
as-built behavior of `benchmark/objective_integrity.py`; it introduces **no behavior change**.

## Why

`row_integrity` verifies that row composites and headline means agree; `score_integrity` verifies
the composite blend. Both trust the component means they are handed, and neither checks that a
row's `objective` dict carries valid numeric recall fields — so a malformed artifact reaches the
anchor unchallenged.

What such an artifact does is worth stating precisely, because the module's own docstring gets it
backwards. `score._recall_for_component` (`benchmark/score.py:664-676`) rejects a boolean recall
and falls back to `module_recall`, else `0.0`, so `objective_component({"weighted_module_recall":
True})` returns **`0.0`**: a bool recall is silently **floored** (deflation), never inflated to
`1.0`. Nothing raises, and the run reports a plausible-but-wrong *low* anchor that `row_integrity`
and `score_integrity` both certify as internally consistent — the corrupted value is consistent
with itself. This gate exists to fail **loudly** on that artifact instead.

Specs 027–030, 057 and 059 already document the sibling integrity gates (`gap`, `aggregate`,
`row`, `tally`, `task`, `score`). Of the nine `benchmark/*integrity*.py` modules only
`objective_integrity`, `weight_integrity` and `judge_report_integrity` have no spec.

**Known discrepancy (documented, not fixed here).** `benchmark/objective_integrity.py:5-8` claims
a malformed artifact can "**inflate** the objective anchor via `float(True) == 1.0` (#1233)". That
is false against the shipped code, per the snippet above: the bool-rejecting
`_recall_for_component` landed in **the same commit that added this gate** (`4f43859`,
*feat(benchmark): add objective-anchor integrity gate for replay rows (#1239)*), so the inflation
hazard never existed in any code state where this module exists, and #1233 is closed. Correcting
that docstring is left to a follow-up so this change stays a pure transcription with no
product-code diff.

## User stories

1. **As a benchmark operator**, I can tell whether an artifact's per-task objective inputs are
   sound before trusting its `composite_mean`.
2. **As a CI maintainer**, I can gate on `scripts/objective_integrity.py` and log a stable
   `integrity_headline()` string.
3. **As a reviewer**, every malformed-input, empty-slice and headline branch is written down
   (addressing the incompleteness class of rejection seen on Specs 057/059).

## Acceptance criteria (EARS)

### Constants and signature

- `DEFAULT_TOLERANCE` SHALL be `0.002`.
- `check_objective_integrity(result, tolerance=DEFAULT_TOLERANCE)` SHALL accept an overriding
  `tolerance` and echo the effective value back as the result's `tolerance` field.

### Numeric helpers

- `_is_number(value)` SHALL be true only for finite, non-boolean `int`/`float` values (`bool`,
  `NaN`, `inf` and non-numerics are false; an oversized `int` yields `False` via `OverflowError`
  rather than raising).
- `_is_ratio(value)` SHALL be true only when `_is_number(value)` and `0.0 <= value <= 1.0`.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_round3(value)` SHALL return `round(float(value), 3)` when `_is_number(value)`, else `None`.
- `_mean(values)` SHALL return `None` for an empty list, else the `_round3` of the arithmetic mean.

### List coercion (`_rows_list`, `_per_repo_list`)

- WHEN the input is `None` or not a `list` THEN the helper SHALL return `[]` (logging a warning
  for the non-list case) rather than raising.
- WHEN it is a `list` THEN non-`dict` entries SHALL be skipped (`_rows_list` logs each;
  `_per_repo_list` does not) and dict entries kept in order.

### Slice selection (`_expand_slice`, `_row_slices`)

- WHEN a part carries a non-`None` `rows` THEN `_expand_slice` SHALL yield exactly that part under
  its own label.
- OTHERWISE it SHALL yield one slice per `per_repo` entry whose `tasks` is a `_is_number` with
  `int(tasks) > 0` **and** whose `rows` is not `None`, labelled `{label}:repo-{index}` by the
  entry's index in the **coerced** dict-only list.
- `_row_slices` SHALL select the **generalization** shape only when `tuned` and `held_out` are both
  dicts **and** the key `generalization_gap` is present; each partition is included only when
  `_partition_scored` (i.e. it expands to at least one slice).
- OTHERWISE WHEN the key `per_repo` is present THEN slices SHALL be the qualifying entries
  labelled `repo-{index}`.
- OTHERWISE WHEN `rows` is not `None` THEN the single slice SHALL be `("run", result)`.
- OTHERWISE `_row_slices` SHALL return `[]`.

### Artifact shape (`check_objective_integrity`)

- WHEN `result` is not a `dict` THEN the outcome SHALL be exactly one `artifact_shape` check with
  `passed: False` and detail `artifact must be a JSON object, got {type}`.
- WHEN `result` is a dict with no qualifying slice THEN an `artifact_shape` check SHALL fail with
  detail `no scored replay slice with per-task rows to verify`.
- Every returned mapping SHALL carry `passed`, `checks` and `tolerance`, with `passed` equal to
  `all(c["passed"] for c in checks)`.

### Per-slice checks (`_check_slice`)

Each slice contributes five checks, named bare for the `run` label and prefixed `{label}:`
otherwise:

- `rows_present` SHALL pass when at least one usable row dict is present; detail
  `{n} usable row(s)`.
- `objectives_present` SHALL pass only when rows exist **and** every row's `objective` is a dict;
  detail `{n} row(s) missing a dict objective`, or `no rows to verify` when there are no rows.
- `recall_fields_valid` SHALL pass only when rows exist **and** no row reports a recall problem.
- `kind_recall_valid` SHALL pass when no row reports a kind problem — unlike the two checks above
  it does **not** additionally require rows.
- `objective_mean_matches_rows` SHALL compare `composite_parts.objective_mean` against `_mean` of
  `score.objective_component` over every dict `objective`, passing when `abs(delta) <= tolerance`
  (**inclusive**); WHEN either side is unusable it SHALL fail with detail `cannot compare
  objective_mean to row objective components`.

**Problem detail formatting.** A per-row problem SHALL render as `row[{index}]: {problems joined
by ", "}` (indexed within the coerced row list), joined across rows with `"; "`. Both
`recall_fields_valid` and `kind_recall_valid` SHALL list at most **3** offending rows;
`recall_fields_valid` SHALL append `" ..."` when more than 3 exist and `kind_recall_valid` SHALL
append **no** marker (an as-built asymmetry).

**Empty-slice branch.** WHEN a selected slice has no usable rows (e.g. `rows: []`) THEN
`rows_present`, `objectives_present`, `recall_fields_valid` and `objective_mean_matches_rows` SHALL
all fail while `kind_recall_valid` SHALL pass. Two as-built oddities are recorded rather than
silently transcribed: `recall_fields_valid` **fails while carrying its success detail** (`all
recall fields are finite ratios in [0, 1]` — the detail is chosen by `not recall_bad`, the `passed`
flag by `not recall_bad and bool(rows)`), and `kind_recall_valid` is the only one of the five that
passes on an empty slice. Neither is changed by this spec.

### Recall field validation (`_recall_field_problems`, `_kind_recall_problems`)

- WHEN `objective` is not a dict THEN both helpers SHALL return `["objective is not a dict"]`.
- For each of `weighted_module_recall`, `module_recall`: an **absent** key SHALL be skipped; a
  `bool` SHALL report `{key} is bool`; a non-`_is_ratio` SHALL report
  `{key}={value!r} is not a ratio in [0, 1]`.
- `_kind_recall_problems` SHALL return `[]` when `actual_kinds` is falsy (absent, `[]`, `None`).
- OTHERWISE it SHALL read `kind_recall` defaulting to `0.0`, reporting `kind_recall is bool` for a
  bool and `kind_recall={value!r} is not a ratio in [0, 1]` for a non-ratio (so a truthy
  `actual_kinds` with no `kind_recall` passes, the default being in range).

### Malformed per_repo rows (`_malformed_per_repo_rows`)

- WHEN the result carries no `per_repo` container (neither the generalization pair nor a top-level
  `per_repo` key), or the key is present but not a list, THEN it SHALL return `None` and **no**
  `per_repo_rows_wellformed` check SHALL be added.
- WHEN a container is a list THEN each entry that is a **non-empty stripped string** SHALL be
  flagged `repo-{index}` (or `{partition}:repo-{index}`) by its index in the **raw** list; dicts,
  ints, `None`, lists and blank strings SHALL NOT be flagged.
- WHEN a flag list is non-empty THEN `per_repo_rows_wellformed` SHALL fail with detail `corrupt
  per_repo string row(s): {labels}`, else pass with `all per_repo rows are well-formed result
  objects`.

**Label-index caveat (as-built).** Slice labels use the **coerced** dict-only index while
corrupt-row labels use the **raw** index, so the two collide: for `per_repo: [<corrupt string>,
<good dict>]` the check `repo-0:rows_present` describes the **dict** while the detail `corrupt
per_repo string row(s): repo-0` describes the **string** — one artifact where `repo-0` denotes two
different repos. Recorded as current behavior.

### Reporting (`_check_rows_list`, `failed_checks`, `integrity_headline`)

- `_check_rows_list` SHALL keep only check rows that are dicts carrying both `name` and `passed`,
  with `name` a `str` and `passed` **exactly** a `bool` (`type(...) is bool`, so `0`/`1` are
  rejected); everything else SHALL be skipped with a warning, and a `None`/non-list `checks` SHALL
  yield `[]`. WHEN `checks` is non-empty but no row is usable THEN a summarising warning SHALL also
  be logged.
- `failed_checks(result)` SHALL return the `name`s of usable check rows whose `passed` is falsy.
- WHEN no usable check row exists THEN `integrity_headline` SHALL be exactly `objective integrity:
  no checks evaluated`; WHEN `result["passed"]` is truthy it SHALL be `objective integrity: VALID
  ({n} checks passed)`; OTHERWISE `objective integrity: INVALID ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O, and `check_objective_integrity()` SHALL NOT mutate its input.

## Out of scope

- Whether the composite **blend** is correct (`benchmark/score_integrity.py`).
- Whether row composites match the headline mean (`benchmark/row_integrity.py`).
- Changing `objective_component` weighting (`benchmark/score.py`).

## Verification

- `tests/test_spec_061_objective_integrity.py` exercises each EARS block above, pinning the
  anchor's expected values as literals rather than re-deriving them from `objective_component`.
- Broader coverage (including the CLI) remains in `tests/test_objective_integrity.py`.
