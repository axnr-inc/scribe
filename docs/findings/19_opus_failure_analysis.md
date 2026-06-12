# 19 — Opus 4.7 Per-Task Failure Analysis on KramaBench (36 tasks)

Scope: every task in `docs/findings/_opus_failure_index.json` (36 KramaBench
items where Opus 4.7 was scored as failing under the strict driver). For each
task we ground the verdict in:

- the frozen spec at `results/krama_opus_104/specs/<task_id>.json`
  (`chosen_interpretation`, `computation_plan`, `expected_output_format`)
- the executor trace at
  `results/krama_opus_104/<task_id>/sessions/normal_agent.jsonl`
  (final assistant turn, the `[Verdict: …]` from `ask_planner_agent`, and any
  `[VERIFY]` lines from the run_python tool).

Failure classes used (single label per row): **FORMAT-LIST**, **FORMAT-STRING**,
**SCORER-GAP-RAE**, **UNITS**, **PREMATURE-NA**, **F-E-CEILING**,
**METHODOLOGY-BINNING**, **METHODOLOGY-WRONG**, **SPEC-WRONG**.

## Summary table

| Task | Class | Gold | Got | Recoverable by |
| --- | --- | --- | --- | --- |
| archeology-easy-8 | METHODOLOGY-BINNING | 52 | 50 | HELPER_MANIFEST (bibliography normalization) |
| archeology-hard-1 | METHODOLOGY-BINNING | 8577.5298 | 8347.1887 | HELPER_MANIFEST / sub-task labels |
| archeology-hard-2 | METHODOLOGY-WRONG | 38.42 | 50.25 | HELPER_MANIFEST (wet-dry index column id) |
| archeology-hard-5 | F-E-CEILING | 66158.3691 | 36815.2633 | sub-task labels |
| archeology-hard-9 | F-E-CEILING | 0.015648 | -0.210104 | sub-task labels |
| archeology-hard-12 | METHODOLOGY-WRONG | 409 | 233 | HELPER_MANIFEST (conflict actor parsing) |
| astronomy-easy-6 | FORMAT-LIST + UNITS | [0.0193, -0.002] | -0.0192778831, 0.0019657701 | prompt patch (list shape + ordering) |
| astronomy-hard-8 | FORMAT-LIST / SCORER-GAP-RAE | [6.1655e-07, 5.1206e-07] | [5.768…e-07, 4.531…e-07] | scorer driver fix (list rel-tol) |
| astronomy-hard-9 | METHODOLOGY-BINNING | 24 | 14 | HELPER_MANIFEST (lag-sign convention) |
| astronomy-hard-12 | SPEC-WRONG | 66822738.84 | 4344571.69 | spec extractor fix |
| biomedical-easy-2 | METHODOLOGY-BINNING | 68.5 | 68.08 | sub-task labels (Case_excluded filter) |
| biomedical-hard-4 | FORMAT-LIST + FORMAT-STRING | ['FIGO Grade 2'] | FIGO grade 2, FIGO grade 2, FIGO grade 2 | prompt patch (list+dedup+casing) |
| biomedical-hard-5 | METHODOLOGY-BINNING | 2.6563 | 2.4241 | sub-task labels (don't un-log) |
| environment-easy-2 | FORMAT-LIST | [2003, 2011, 2015, 2018, 2020, 2021, 2022, 2023] | 2003, 2011, 2018, 2020, 2021, 2022, 2023 | prompt patch (list shape) + binning |
| environment-hard-16 | METHODOLOGY-BINNING | 60 | 75 | HELPER_MANIFEST (NaN-violation rule) |
| environment-hard-20 | METHODOLOGY-WRONG | ['Bucks Creek', 'Pleasant Street', 'Forest Street'] | Bucks Creek, Pleasant Street, Schoolhouse Pond | prompt + HELPER_MANIFEST |
| legal-easy-3 | SCORER-GAP-RAE | 13.1628 | 13.1628 | scorer driver fix |
| legal-easy-4 | PREMATURE-NA | 2111635 | Not Applicable | prompt patch (anti-NA) |
| legal-easy-21 | METHODOLOGY-WRONG | 16589 | 13596 | HELPER_MANIFEST (sum-of-types vs ranking total) |
| legal-hard-2 | FORMAT-STRING | Miami…Metropolitan Statistical Area | Miami-Fort Lauderdale-West Palm Beach, FL | prompt patch (verbatim MSA suffix) |
| legal-hard-14 | FORMAT-LIST | ['Boston…', …5 items] | Boston…, Providence…, …, Worcester… | prompt patch (list shape) |
| legal-hard-15 | METHODOLOGY-BINNING | 243377 | 242682 | HELPER_MANIFEST (cross-state MSA defn) |
| legal-hard-17 | METHODOLOGY-BINNING / SCORER-GAP-RAE | 32542 | 32587 | scorer driver fix |
| legal-hard-18 | METHODOLOGY-WRONG | 91000 | 126000 | HELPER_MANIFEST (use published pct vs raw counts) |
| legal-hard-24 | FORMAT-STRING | Los Angeles-Long Beach-Anaheim CA Metropolitan Statistical Area | Los Angeles-Long Beach-Anaheim, CA Metropolitan Statistical Area | scorer driver fix (comma) |
| legal-hard-29 | FORMAT-STRING | Washington-Arlington-Alexandria, DC-VA-MD-WV Metropolitan Statistical Area | Washington-Arlington-Alexandria, DC-VA-MD-WV | prompt patch (suffix verbatim) |
| wildfire-easy-3 | F-E-CEILING | ['California', 'Nevada'] | Wyoming | sub-task labels (overlay threshold) |
| wildfire-easy-9 | METHODOLOGY-WRONG | -0.0059 | 25.9818 | HELPER_MANIFEST (per-fire fatality mean) |
| wildfire-hard-6 | SCORER-GAP-RAE | 0.519 | 0.519 | scorer driver fix |
| wildfire-hard-14 | METHODOLOGY-BINNING | 0.65 | 0.42 | HELPER_MANIFEST (unsafe-AQI category set) |
| wildfire-hard-16 | FORMAT-LIST / SCORER-GAP-RAE | [6.326, 0.787] | 6.3260058770…, 0.7871704568… | prompt + scorer fix |
| wildfire-hard-17 | SCORER-GAP-RAE | 4830.9 | 4826.89 | scorer driver fix |
| wildfire-hard-18 | METHODOLOGY-WRONG | "More aggressive suppression does not help fires end faster but helps fires affect less buildings." | "no" | prompt patch (full-sentence answer) |
| wildfire-hard-19 | METHODOLOGY-BINNING | 32.76 | 27.35 | HELPER_MANIFEST (1km rain-station rule) |
| wildfire-hard-20 | UNITS | 0.0465 | 4.65 | prompt patch (decimal-vs-percent) |
| wildfire-hard-21 | METHODOLOGY-WRONG | ['California', 'Washington', 'Idaho'] | California, Idaho, Montana | HELPER_MANIFEST (missing-value rule) |

Class roll-up (one label per task, using the more-specific class when multiple apply):
FORMAT-LIST 6 · FORMAT-STRING 4 · SCORER-GAP-RAE 6 · UNITS 2 · PREMATURE-NA 1 ·
F-E-CEILING 3 · METHODOLOGY-BINNING 9 · METHODOLOGY-WRONG 7 · SPEC-WRONG 1.

The single highest-leverage fix is the scorer driver: 6/36 failures are
numerically perfect or list-tied-to-string-shape and would flip with a list/rel-tol
rule. The next is HELPER_MANIFEST (~10 tasks) to lock down a handful of recurring
KramaBench conventions (FTC MSA suffix, NaN-as-safe, sum-of-types vs rank-total,
lag-sign convention, AQI unsafe category set, 1 km rain-station window).

---

## archeology

### archeology-easy-8 — METHODOLOGY-BINNING
Gold `52`, got `50`. The spec's `computation_plan` is literally "split `Select
Bibliography` on `;`, strip trailing `.`, `len(set(tokens))`" and the executor
ran exactly that. The planner returned `[Verdict: BLIND_SPOT]` after directly
inspecting `roman_cities.csv` and flagging at least three malformed rows
(`"1995"` as a truncated token, `"Sear 2006PECS"` as two citations concatenated,
etc.) that perturb the count by ±2. So the gold `52` reflects a particular
normalization choice (likely a regex for year tokens plus a fix for the missing
separator) that the spec did not encode. Recoverable by adding a
`roman_cities_bibliography_clean()` helper to HELPER_MANIFEST.

### archeology-hard-1 — METHODOLOGY-BINNING
Gold `8577.5298`, got `8347.1887`. Planner verdict ANSWER with detailed
arithmetic: `first_bp=6412, last_bp=6005 → K = (8466.247 + 8228.130)/2 =
8347.189`. The chosen interpretation read `first/last` as `max BP / min BP` of
Maltese rows (oldest/most recent), but gold corresponds to a different window
selection — almost certainly first/last by calendar order in the table or by
Maltese-cultural era. The spec's `chosen_interpretation` baked in the wrong
window. Fixable by adding a sub-task label that pins down "first/last study
record" semantics for this dataset.

### archeology-hard-2 — METHODOLOGY-WRONG
Gold `38.42`, got `50.25`. Planner verdict ANSWER. Executor located column 29
(`'ODP 967 wet-dry index'`) and paired it with `Age_ky.3` from column 28. Of
5992 transitions, 3011 were strictly positive → 50.25%. Gold (≈38%) implies a
different column or a different "increasing" definition (e.g., year-binned
rather than sample-to-sample, or a different wet-dry series with a stronger
drying trend). The spec's column-pairing rule from
`expected_output_format` was confidently wrong. Fixable by a HELPER_MANIFEST
entry for `climateMeasurements.xlsx` that names the canonical wet-dry column.

### archeology-hard-5 — F-E-CEILING
Gold `66158.3691`, got `36815.2633`. Spec correctly noted the lat/long
column-swap in `radiocarbon_database_regional.xlsx`. Planner verdict ANSWER
with reasonable physics: 14 Maltese-Neolithic rows share the same coordinates,
tie-break to `6005 BP` (Skorba), interpolate Al at 6.005 ka in ODP 967 → 36815.
Gold value is ~1.8× larger, suggesting the wrong Al series (there are multiple
Age_ky/Al column pairs in the multi-header sheet) or a different tie-break
(latest year by calendar epoch, not min BP). Multiple model families have
historically converged on a similar number here — a canonical F-E-CEILING.
Fixable only by sub-task labels that pin (a) which Al column to use, (b) the
tie-break definition.

### archeology-hard-9 — F-E-CEILING
Gold `0.015648`, got `-0.210104`. Planner verdict ANSWER. The spec pairs Roman
cities to modern cities by `abs(Δlat)<0.1 ∧ abs(Δlng)<0.1`, deduplicates by
keeping the largest `rome_idx`, computes Pearson. The executor followed this
faithfully. Gold's near-zero positive correlation implies either a different
matching radius, a different dedup rule (keep first / mean), or a different
rank-parsing convention for "or". This is the canonical archeology-hard-9
F-E-ceiling pattern documented in `06_krama_failure_analysis.md`. Sub-task
labels are the only realistic fix.

### archeology-hard-12 — METHODOLOGY-WRONG
Gold `409`, got `233`. Planner verdict ANSWER. The two-actor filter in the
spec is `name_head.str.contains('-')` applied to the substring of `Conflict`
before any `(`. This drops legitimate hyphen-free two-actor names (e.g.,
"Spanish vs. French" or comma-separated actors) and over-drops parenthetical
sub-events that are valid two-actor conflicts. The gold count of 409 implies a
looser two-actor definition (likely "any row with a non-blank `SecondActor`
column or a `vs`/comma/`-` between names"). Recoverable by a HELPER_MANIFEST
entry: `parse_brecke_two_actor(row) -> bool`.

---

## astronomy

### astronomy-easy-6 — FORMAT-LIST + UNITS
Gold `[0.0193, -0.002]` (list literal, quiet first, storm second; quiet
positive, storm negative). Got `-0.0192778831, 0.0019657701` — order reversed,
signs flipped, comma-separated string. Planner verdict ANSWER, explicitly
endorsing both the sign convention (Δa positive because `endpoint_slope` was
defined that way in the spec) and the ordering chosen. So two problems
stack: (a) wrong output shape (no brackets), (b) wrong sign/order convention
relative to gold. Fixable by a prompt patch that forces Python-list literals
when `answer_type=list_*` and by a HELPER_MANIFEST entry that pins the storm/quiet
order for Gannon-storm questions.

### astronomy-hard-8 — SCORER-GAP-RAE / FORMAT-LIST
Gold `[6.1655e-07, 5.1206e-07]`, got `[5.768e-07, 4.531e-07]`. The model
*did* emit a Python list literal (good). The numbers are within ~7% — RMSE on
calibrated `a_cal[:, 0]` data is sensitive to fill-value handling and 3-hour
windowing. Planner verdict ANSWER. Whether this is a true methodology miss or
a scorer rel-tol issue depends on the driver: with a list rel-tol of 0.1 (the
KramaBench convention for `list_approximate`) this should pass. Likely classed
under SCORER-GAP-RAE for list types or a 10%-tolerance fix in the driver.

### astronomy-hard-9 — METHODOLOGY-BINNING
Gold `24`, got `14`. Planner verdict ANSWER, with an explicit defence of the
`ap.shift(+L)` convention: "AP leads Δa by ~14 hours, consistent with known
thermospheric response timescales." Gold (24 h) corresponds to the *opposite*
shift sign or to a different alignment (rounding TLE epochs up vs nearest).
Fixable with a HELPER_MANIFEST `tle_ap_lag(period)` that defines the
lead/lag convention canonically.

### astronomy-hard-12 — SPEC-WRONG
Gold `66822738.84`, got `4344571.69`. Planner verdict `[Verdict: SPEC_WRONG]`
verbatim — the `.npz` only contains `lat_grid`, `lon_grid`, `alt_grid`, no
potential values. The spec's `chosen_interpretation` is
`mock_field_is_g_times_altitude`, which has the executor compute `g·h` over the
satellite's altitude track — yielding ~4.3 M J/kg (geometric-altitude
geopotential). Gold (~6.7 × 10⁷ J/kg) corresponds to the full
`Φ = -μ/r + μ/R_E`-style reference, not `g·h`. The spec extractor picked the
wrong mock-field definition. Only fixable by re-extraction of this spec (or
adding a stronger prior to the spec extractor for geopotential definitions).

---

## biomedical

### biomedical-easy-2 — METHODOLOGY-BINNING
Gold `68.5`, got `68.08`. Spec's chosen interpretation is `all_serous_rows`
(no `Case_excluded` filter). Planner verdict ANSWER with the arithmetic
worked through: 14 serous rows → 13 with non-null Age → mean 68.077. Gold
68.5 matches the `Case_excluded==No` filter (drops C3L-01247 age=63, leaving
12 rows with mean 68.5). The spec deliberately *chose the wrong
interpretation*. Fixable only with a sub-task label that pins
"analyzed in the study" = `Case_excluded != 'Yes'`.

### biomedical-hard-4 — FORMAT-LIST + FORMAT-STRING
Gold `['FIGO Grade 2']` (single-item list, "Grade" capitalised). Got
`FIGO grade 2, FIGO grade 2, FIGO grade 2` (no list, no dedup, lower-case
"grade"). Three format failures stacked. Prompt patch: list literal +
deduplicate + preserve source casing.

### biomedical-hard-5 — METHODOLOGY-BINNING
Gold `2.6563`, got `2.4241`. Spec's `unlog_all_serous` interpretation
explicitly inverts the log2 transform via `2**x`. Planner verdict ANSWER
endorses this. Gold `2.6563` is what you get *without* the `2**x` inversion —
i.e., the raw column `Log2_variant_per_Mbp` is already in
"variants per Mbp" units in the source's convention, despite its name. The
spec was wrong but in a defensible way. Sub-task label fix.

---

## environment

### environment-easy-2 — FORMAT-LIST + binning
Gold `[2003, 2011, 2015, 2018, 2020, 2021, 2022, 2023]`. Got
`2003, 2011, 2018, 2020, 2021, 2022, 2023` (missing 2015 + no list literal).
The format slip is clear-cut. The missing 2015 indicates a borderline year
right at the threshold — likely a rounding/tolerance issue against the
"2 decimal places" cutoff. List-format prompt patch fixes the shape;
HELPER_MANIFEST entry on threshold rounding fixes the missing year.

### environment-hard-16 — METHODOLOGY-BINNING
Gold `60`, got `75`. Planner verdict ANSWER. Spec's interpretation
`marine_filter_any` + `name_plus_community` keys; 39 NaN-violation rows
treated as non-violations ("absence/unknown = safe" per the prompt). Gold 60
implies a stricter rule (NaN = unsafe, OR a stricter beach-name normalization
that merges variants Opus kept separate). HELPER_MANIFEST entry for
"beach safe-for-all-seasons" defining the canonical missing-value rule.

### environment-hard-20 — METHODOLOGY-WRONG
Gold `['Bucks Creek', 'Pleasant Street', 'Forest Street']`. Got
`Bucks Creek, Pleasant Street, Schoolhouse Pond`. Planner verdict ANSWER —
Chatham confirmed as least-summer-rainfall city (8.71 in), and the top-3 most
polluted beaches under the spec's pollution metric are
Bucks Creek > Pleasant Street > Schoolhouse Pond. Gold swaps Schoolhouse Pond
for Forest Street → 3rd-place tie-break or a different "most polluted" metric
(e.g., violation rate vs total violation count vs exceedance rate). Plus the
list shape. Two-shot fix: prompt patch (list) + HELPER_MANIFEST on the
pollution metric.

---

## legal

### legal-easy-3 — SCORER-GAP-RAE
Gold `13.1628`, got `13.1628` — **bit-identical**. Planner verdict ANSWER;
final line is literally "13.1628". This is a strict-driver false negative.
Fix: scorer driver should treat exact-match strings as pass regardless of
type (the `numeric_approximate` driver is presumably comparing as float and
the trailing-zero / trailing-newline / dollar-sign normalization is failing).
Pure scorer fix.

### legal-easy-4 — PREMATURE-NA
Gold `2111635`, got `"Not Applicable"`. Planner verdict `NA_CONFIRMED` —
the planner explicitly endorsed the NA after inspecting three 2024 CSN files
and concluding "no 'Web' contact-method breakdown for 2022/2023 exists in
this corpus". The gold answer obviously exists in the data (2,111,635 web
fraud reports 2022–2024 is summable from per-year files). Both the executor
and the planner gave up too quickly — this is the canonical anti-NA case.
Fixable with a prompt patch that bans NA unless the executor has
*demonstrated* via tool call that the requested column/file does not exist,
*and* a HELPER_MANIFEST entry pointing to the per-year contact-method
breakdown files.

### legal-easy-21 — METHODOLOGY-WRONG
Gold `16589`, got `13596`. The session log shows the executor found two
candidate values: (a) Alabama State Rankings file: 13,596 reports, and
(b) per-theft-type breakdown summing to 16,589 with percentages summing to
122%. The planner call **failed mid-run** (`Planner error: fetch failed`,
log line 33). The executor then reasoned independently: "percentages add
to 122%, so summing categories double-counts → 13,596 is the unique total."
This is plausible but gold says sum-of-types is the intended answer (the
FTC convention allows a single report to be classified into multiple
identity-theft sub-types). HELPER_MANIFEST entry: for identity-theft
counts, prefer the per-type sum when both are available.

### legal-hard-2 — FORMAT-STRING
Gold `Miami-Fort Lauderdale-West Palm Beach FL Metropolitan Statistical Area`.
Got `Miami-Fort Lauderdale-West Palm Beach, FL`. Two format issues: missing
the suffix " Metropolitan Statistical Area", and the gold drops the comma
before "FL". Planner verdict ANSWER endorsing the executor's MSA pick (the
underlying answer is right). Prompt patch: "return MSA names verbatim from
the source file" + scorer fix on the comma.

### legal-hard-14 — FORMAT-LIST
Gold is a 5-element Python list of full MSA names; got is the same 5
strings, in the same order, joined by ", ". The planner returned
`[Verdict: SPEC_WRONG]` flagging that the per-state CSVs duplicate the
MSA-wide totals (Boston = 19,929 in both MA and NH), but the underlying
ranking is correct — the failure is purely list shape. Prompt patch.

### legal-hard-15 — METHODOLOGY-BINNING
Gold `243377`, got `242682` — 695 reports apart (~0.3%). Planner ANSWER.
Spec uses `cross_state_msa_literal`: an MSA is cross-state iff its suffix
lists multiple state codes (e.g., "MA-NH"). The gap is consistent with a
single MSA being included/excluded under a slightly different rule (e.g.,
including Puerto Rico-suffixed combinations, or de-duplicating
double-listed MSAs differently). HELPER_MANIFEST entry on the cross-state
MSA definition would close this; with `numeric_approximate` rel-tol = 1e-3
the scorer would already pass. Likely best classified as
SCORER-GAP-RAE-adjacent.

### legal-hard-17 — METHODOLOGY-BINNING / SCORER-GAP-RAE
Gold `32542`, got `32587` — 45 apart, ~0.14%. Planner ANSWER, with a
careful defence of using 6,471,708 (full Sentinel total) as the 2024
denominator. Either the gold uses a slightly different 2024 denominator
(e.g., sum-of-29-rows = 5,761,106) or a different 2007 base. Within
rel-tol of any reasonable scorer this should pass. Scorer driver fix.

### legal-hard-18 — METHODOLOGY-WRONG
Gold `91000`, got `126000`. Planner ANSWER citing the published 2007 total
identity-theft figure 258,427 × 0.4861 ≈ 125,614 → 126,000. Gold 91,000
corresponds to a *different* base population — most likely 187,000 (the
2007 identity-theft count from a different table) × the 40+ share, or
using 2007's own age distribution as the base. HELPER_MANIFEST entry on
"counterfactual report-count base" needed.

### legal-hard-24 — FORMAT-STRING
Gold `Los Angeles-Long Beach-Anaheim CA Metropolitan Statistical Area`.
Got `Los Angeles-Long Beach-Anaheim, CA Metropolitan Statistical Area`.
Identical string apart from the comma before CA. Planner verdict ANSWER.
Pure scorer fix (strip commas inside MSA names) or trivial prompt patch.

### legal-hard-29 — FORMAT-STRING
Gold `Washington-Arlington-Alexandria, DC-VA-MD-WV Metropolitan Statistical Area`.
Got `Washington-Arlington-Alexandria, DC-VA-MD-WV` (missing the
"Metropolitan Statistical Area" suffix). Planner verdict ANSWER endorsing
the executor's MSA pick. Prompt patch: "return MSA names verbatim
including the trailing classification suffix".

---

## wildfire

### wildfire-easy-3 — F-E-CEILING
Gold `['California', 'Nevada']`, got `Wyoming`. Planner verdict ANSWER,
backing Wyoming as the unique state with 3 distinct GACCs (Rocky Mountain
89.6%, Great Basin 7.1%, Northern Rockies 3.2%) at the spec's 1%
area-fraction threshold. Gold (CA + NV both with the most GACCs and tied)
implies a different overlap criterion (any non-zero overlap, or
state-boundary intersection rather than area fraction). The executor
faithfully implemented a different (defensible) definition.
F-E-CEILING — sub-task labels only.

### wildfire-easy-9 — METHODOLOGY-WRONG
Gold `-0.0059`, got `25.9818`. Planner verdict ANSWER with the literal
reading "total fatalities on humidity<30% days (26) − mean fatalities per
fire (0.0182)" = 25.9818. Gold is in the (-0.01, 0) range, implying the
intended computation is "mean fatalities per fire on humidity<30% days
minus mean fatalities per fire overall". The executor mixed a sum and a
mean. HELPER_MANIFEST entry: "per-fire fatality" disambiguation.

### wildfire-hard-6 — SCORER-GAP-RAE
Gold `0.519`, got `0.519` — exact. Planner verdict ANSWER. Pure scorer
fix (same class as legal-easy-3).

### wildfire-hard-14 — METHODOLOGY-BINNING
Gold `0.65`, got `0.42`. Planner verdict ANSWER. Spec defines
`Unsafe Days = USG + Unhealthy + Very Unhealthy + Hazardous`. The gap
between 0.42 and 0.65 is too large for rounding — likely the gold uses a
narrower or broader AQI-unsafe category set, or a different acres-burned
column. HELPER_MANIFEST: canonical "unsafe AQI" category list.

### wildfire-hard-16 — FORMAT-LIST / SCORER-GAP-RAE
Gold `[6.326, 0.787]`, got `6.3260058770343575, 0.7871704568385589`. The
numbers are bit-identical to gold at 4 decimals — pure list shape + decimal
rounding miss. Scorer with rel-tol 1e-3 over list elements would pass.
Prompt patch for the list shape; scorer fix for rounding.

### wildfire-hard-17 — SCORER-GAP-RAE
Gold `4830.9`, got `4826.89` — 0.08% apart. Planner ANSWER, with a 97.3%
RAWS station match rate noted in the trace. This is `numeric_approximate`
and within any reasonable rel-tol. Scorer fix.

### wildfire-hard-18 — METHODOLOGY-WRONG
Gold is a full sentence: "More aggressive suppression does not help fires
end faster but helps fires affect less buildings." Got `"no"`. Planner
verdict ANSWER. The model gave a single-word answer to a two-clause
question. The spec's `expected_output_format` did not require a sentence,
hence the executor reduced it to a yes/no. Prompt patch: when
`answer_type=string_*` and the question has multiple sub-clauses, emit a
sentence-level answer.

### wildfire-hard-19 — METHODOLOGY-BINNING
Gold `32.76`, got `27.35`. Planner ANSWER. The spec's
`linked_station_daily_rain` strategy uses each fire's `station_verified_in_psa`
RAWS ID. Gold (~5 pp higher) implies a broader rain-station window — likely
"any station within 1 km of the fire centroid" rather than the single linked
station. The 1-km diameter assumption in the question is the contested point.
HELPER_MANIFEST entry on the canonical station-selection rule for this
benchmark family.

### wildfire-hard-20 — UNITS
Gold `0.0465`, got `4.65` — exactly 100× off. Planner verdict ANSWER.
The model emitted a percentage in [0,100] when gold expected a fraction.
The question says "what percentage" so the model's reading is defensible,
but the gold convention is the fractional form. Prompt patch: when
`expected_output_format` does not specify the multiplier, emit both
fraction and percentage and let the scorer pick the closer.

### wildfire-hard-21 — METHODOLOGY-WRONG
Gold `['California', 'Washington', 'Idaho']`, got
`California, Idaho, Montana`. Planner verdict ANSWER. The executor
correctly preserved missing-value rows (the question explicitly says
"do not discard rows with missing values unnecessarily") but still gets a
different #2 (Washington vs Idaho/Montana). Gold's ordering suggests
Washington has a large value that the executor dropped or aggregated to a
different state. HELPER_MANIFEST entry on residential-property-loss
aggregation by state.

---

## What this means for the next experiment

Of the 36 failures, **6 are pure scorer-driver issues** (numerically perfect
or within reasonable rel-tol): `legal-easy-3`, `wildfire-hard-6`,
`wildfire-hard-17`, `wildfire-hard-16`, `astronomy-hard-8`, `legal-hard-17`.
A single driver patch (accept rae_score=1.0; rel-tol over list elements; strip
commas inside string MSAs) flips all six.

**4 are FORMAT-LIST** and **4 are FORMAT-STRING** — a handful of prompt
hardenings (Python list literal for `list_*`, verbatim MSA suffix for the
legal corpus, anti-NA rule for the legal corpus) flips most of these.

**1 is PREMATURE-NA** (`legal-easy-4`) — same prompt patch family.

**1 is UNITS** (`wildfire-hard-20`) — prompt patch on fraction/percent.

**1 is SPEC-WRONG** (`astronomy-hard-12`) — a spec-extractor fix is the only
recourse, since the executor was given a definitionally wrong mock-field
formula.

**3 are F-E-CEILING** (`archeology-hard-5`, `archeology-hard-9`,
`wildfire-easy-3`) — these are the canonical "defensible-but-wrong" tasks
where the model and the planner agree, the spec is plausible, and only a
sub-task label can recover them.

**The remaining ~16 are methodology** (binning or wrong column/rule). About
ten of these are recoverable with HELPER_MANIFEST entries that pin down
recurring KramaBench conventions (FTC MSA conventions, NaN-as-safe rule,
wet-dry index column id, AQI unsafe category set, conflict-actor parsing,
1 km rain-station rule, per-fire fatality mean, residential-property
aggregation). The rest need sub-task labels.

The cheapest interventions in expected-flip-per-effort order:

1. Scorer driver fix → +6 flips, ≤1 day work.
2. Format-list / format-string / anti-NA / units prompt patch bundle →
   +6–8 flips, ≤2 days work.
3. HELPER_MANIFEST additions for the ten domain conventions → +8–10 flips
   over a week.
4. Sub-task labels (canonical answers per interpretation) → the remaining
   F-E-CEILING and a few binning tasks; weeks of curation.

Re-running Opus 4.7 after items 1–3 should plausibly recover ~20 of the 36
failures without retraining.
