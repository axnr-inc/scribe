# Lit review — data-analysis verifier vocabularies

Sources: Great Expectations, pandera, dbt-expectations, deequ, Soda Core, DataSciBench (arxiv 2502.13897), AlphaCodium (2401.08500), Self-Debug (2304.05128), KramaBench (2506.06541), DABStep (2506.23719), LiveSQLBench, Six Failures of Text-to-SQL (Weinmeister, Google Cloud), Reflexion, Voyager, Judge's Verdict (2510.09738), Snowflake Cortex Analyst, Hex Magic, Bigeye, smolagents.

## Six-family convergence

All production data-quality stacks (GE / pandera / dbt-expectations / deequ / Soda) ship roughly the same six families:
1. Schema / dtype
2. Row-count (table-shape)
3. Null
4. Uniqueness
5. Value-range / value-set
6. Aggregate-statistic (mean, sum, stdev)

Distribution-drift assertions appear in GE / dbt-expectations / Soda but rarely fire usefully without a per-task baseline (none of our 3 benchmarks provides one).

## Strongest empirical claims

- **AlphaCodium**: GPT-4 pass@5 19% → 44% with anchor-test iterative flow (test-anchored, generation-then-verify)
- **Self-Debug**: Spider +2-3%, Spider-hardest +9%, MBPP/TransCoder +12% — execution-as-feedback alone (no human signal)
- **KramaBench**: smolagents-DR 55.83%; gold-files lift only 0-7% → **most failures are reasoning/pipeline-design, not retrieval or data-quality**
- **Judge's Verdict**: LLM-judge for code correctness vs unit tests, κ = 0.10-0.21 (weak/fair) — **don't use LLM-judge in inner loop**

## Recommended v1 (9 assertions)

| # | Assertion | Rationale |
|---|---|---|
| 1 | `row_count(df, op, n)` | Universal. Catches empty-after-filter (DABStep) and join blow-up (Krama). |
| 2 | `shape(df, expected)` | Row+column count combined. Cheap. Catches missing-merge-column class. |
| 3 | `column_exists(df, name)` | Top-3 in every production stack. Only assertion that fires reliably on agent typos. |
| 4 | `dtype_matches(df, col, expected)` | Catches "joined-on string vs int" silently-empty merges (documented Krama failure mode). |
| 5 | `unique(df, cols)` + `composite_key_unique(df, cols)` | Same family, two arities. High lift on groupby/dedup steps. |
| 6 | `null_rate_below(df, col, threshold)` | **Strictly more useful than binary `not_null`**. GE uses proportion form; Soda has `missing_percent`. Lower FP when data is genuinely sparse. |
| 7 | `value_in_set(df, col, allowed_set)` | For categorical / fee-class / currency-code columns. DABStep fee-rule tasks have many. |
| 8 | `value_in_range(df, col, lo, hi)` | Numeric sibling of `value_in_set`. |
| 9 | `sqlglot_parses(sql, dialect)` | **SQL-only** (LiveSQL). Six Failures #5. Cheapest possible LiveSQL check; catches dialect-specific syntax before sqlite execute. |

Total: 9 assertions ship in v1.

## v2 wishlist (after pilot fires + measured FP rates)

- `row_count_change_pct(before, after, op, pct)` — for merges/groupbys. Strong for Krama multi-step. Needs "before" handle (harness state).
- `foreign_key_intact(df_left, fk_col, df_right, pk_col)` — Soda's `reference` check, dbt's `relationships`. High lift on multi-table DABStep `fees.json` joins.
- `column_sum_within_tolerance(df, col, expected_sum, tol)` — analogue of `expect_multicolumn_sum_to_equal`. Useful for fee-total reconciliation in DABStep.
- `query_returns_rows(sql)` — post-execute non-empty check for LiveSQL; the SQL analogue of `non_empty_after_filter`.
- `output_matches_format(answer, regex)` — DABStep often needs single number or currency string; catches "the answer is 42" wrapping.

## Don't ship in v1 (with rationale)

| Don't ship | Why |
|---|---|
| `no_unexpected_columns(df, allowed_set)` | High FP. Agents legitimately add helper columns mid-pipeline. Sensible only at final-answer boundary. |
| `non_empty_after_filter(df)` as hard FAIL | Empty result is sometimes the correct answer. Make it WARN-only. Weinmeister #5 + Krama analysis both note this. |
| `mean_within_tolerance` without spec-supplied target | Becomes drift detection without baseline — none provided per-task. |
| `column_values_to_be_within_n_stdevs` / cross-distribution checks | Need reference distribution. None of 3 benchmarks provides one per task. High FP, no real lift. |
| `intermediate_matches_subtask(value, sub_task_gold)` | Only Krama has sub-task golds. Even there, smolagents wins without this. Defer. |
| **LLM-judge verifiers in the inner loop** | κ ≈ 0.10-0.21 vs unit tests (arxiv 2510.09738). Reserve for cases where no programmatic check possible. |
| `no_inf_or_nan(df, col)` as separate top-level check | Subsume into `null_rate_below`. Standalone is redundant and noisy on legitimately sparse columns. |

## Expectation-setting

The empirical lift evidence comes mostly from **execution-as-verifier** (AlphaCodium 19→44%, Self-Debug +2-12%), not from assertion-vocabulary studies. None of the production stacks publishes a "which expectation catches the most production bugs" study; the only revealed preference is GE's curation from 300+ to 47 "most widely used".

**Expected P1 v1 lift bound: +5 to +12% (Self-Debug envelope), NOT +25%.** Most SCRIBE failures are reasoning/pipeline-design (per Krama's 0-7% gold-files-lift finding), not data-quality, so the assertion ceiling is modest.

Treat v1 as the hypothesis to test, not the answer. After the pilot, instrument every assertion's:
- **Fire rate** — how often does it trip on real runs?
- **True-positive / false-positive ratio** — does it catch real bugs?
- **Marginal accuracy lift** — does including it vs excluding it change pass rate?

Then make v2 decisions empirically.

## Open caveats

The biggest gap in this review is **negative results / FP rates**. No production stack and no academic paper reports per-assertion FP rates. The "don't ship in v1" list above is grounded in *structural* arguments (does it require a baseline? is empty-result sometimes valid?), not measured FP rates. Pilot data will be the first empirical signal.
