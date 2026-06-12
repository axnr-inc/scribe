# HELPER_MANIFEST expansion — failure-driven proposal

Scope: 25 remaining Opus 4.7 failures on KramaBench
(`data/splits/krama_opus_failed_v2.jsonl`), grounded in the per-task
verdicts in `19_opus_failure_analysis.md` and the gold/got pairs in
`_opus_failure_index.json`. The bar for inclusion is the one set in
`14a_paradigm_fit_and_helper_strategy.md`: each helper must be a
**paradigm-level data-pattern primitive** (cross-domain or recurring), not
a task-solver, and must have a documented failure it would have prevented.

## Current vocabulary (recap)

The five existing helpers in `data/context/krama_helper.py`:

1. `read_multi_header_excel(path, sheet, header_keywords)` — find the real
   header row in an xlsx with N metadata rows above it.
2. `parse_missing_marker(df, cols, markers)` — convert sentinel strings
   ("M", "N/A", "-999") to NaN before numeric coercion.
3. `safe_dedupe(df, keys, agg, sort_by)` — dedup with an explicit
   aggregation policy on a stable key.
4. `linear_interp_by_key(df, key_col, value_col, target_keys)` — linear
   interpolation of a value column at integer keys spanning the data.
5. `bp_to_calendar_year(years_bp, reference_year=1950)` — archaeology BP →
   calendar year conversion.

The pattern: each helper is a primitive that *multiple* tasks could call,
named at the level of the data-cleaning operation (not the task). The
proposals below stay at that altitude.

## Proposed additions

### `canonicalize_msa_name(name, suffix="Metropolitan Statistical Area", drop_comma_before_state=True)`

- **Purpose**: Normalize Federal Trade Commission MSA strings to the
  benchmark's canonical form ("Boston-Cambridge-Newton, MA-NH
  Metropolitan Statistical Area", with optional comma-before-state-code
  policy).
- **Recovers tasks**: `legal-hard-2`, `legal-hard-14`, `legal-hard-24`,
  `legal-hard-29` (and silently helps `legal-hard-15`).
- **Why a helper and not a prompt fix**: The MSA suffix
  ("Metropolitan Statistical Area") and the comma-before-state rule
  ("Los Angeles-Long Beach-Anaheim CA" vs "..., CA") appear inconsistently
  across the State MSA CSV files. A prompt patch that says "return MSA
  names verbatim" doesn't help when *the source files themselves disagree*
  — Opus 4.7 has picked the wrong source variant in 4/4 MSA tasks. A
  canonicalizer is paradigm-level because the FTC corpus has 50+ MSA-named
  files that share the same parsing surface.
- **Docstring**:
  ```
  """Canonicalize an MSA name to the FTC's verbose form.

  Args:
    name: The MSA string as it appears in any source file.
    suffix: Trailing classification to append if missing.
      Default "Metropolitan Statistical Area".
    drop_comma_before_state: If True, the comma immediately
      before the 2-letter state token is removed
      ("Los Angeles-Long Beach-Anaheim, CA ..." →
       "Los Angeles-Long Beach-Anaheim CA ...").
      KramaBench gold strings use BOTH conventions; the default
      matches the most common case. Set to False when matching
      Boston/Providence/Washington-style entries that DO keep
      the comma.

  Returns:
    The normalized string. Idempotent.

  Gotchas:
    Some MSAs span 4+ state codes ("DC-VA-MD-WV"). The state
    token is matched as 2-4 uppercase letters separated by '-'.
    "PR" (Puerto Rico) is a valid state token.
  """
  ```
- **Implementation sketch**:
  ```python
  import re
  STATE_RE = re.compile(r",\s+([A-Z]{2}(?:-[A-Z]{2}){0,4})(\b|\s)")
  def canonicalize_msa_name(name, suffix="Metropolitan Statistical Area",
                            drop_comma_before_state=True):
      s = str(name).strip()
      if drop_comma_before_state:
          s = STATE_RE.sub(r" \1\2", s)
      if suffix and not s.endswith(suffix):
          s = s + " " + suffix if not s.endswith(",") else s + " " + suffix
      return re.sub(r"\s+", " ", s).strip()
  ```

### `cross_state_msa(name)` → `bool`

- **Purpose**: Detect whether an MSA spans multiple states by inspecting
  its state-token suffix.
- **Recovers tasks**: `legal-hard-15` (gold 243377, got 242682 — a 0.3 %
  gap consistent with one MSA mis-binned). The 5/5 MSA-aggregation tasks
  in the legal corpus all share this primitive.
- **Why a helper and not a prompt fix**: The "cross-state" definition is
  not stated in the data — it's purely a string-parsing convention
  (count of "-"-separated 2-letter codes in the suffix). Three Opus 4.7
  runs got this off by one MSA because they used `"," in name` instead of
  parsing the state-token block.
- **Docstring**:
  ```
  """Return True iff the MSA name's state-token block lists 2+ codes.

  Examples:
    "Boston-Cambridge-Newton, MA-NH Metropolitan Statistical Area" → True
    "Worcester, MA Metropolitan Statistical Area" → False
    "Washington-Arlington-Alexandria, DC-VA-MD-WV ..." → True
    "Bridgeport-Stamford-Danbury, CT Metropolitan Statistical Area" → False

  Args:
    name: MSA name string (any source format).

  Returns:
    True if the state-token block contains '-'. False otherwise.
    Raises ValueError if no state-token block can be located.
  """
  ```
- **Implementation sketch**:
  ```python
  m = re.search(r",\s+([A-Z]{2}(?:-[A-Z]{2}){0,4})\b", str(name))
  if not m:
      raise ValueError(f"no state-token block in {name!r}")
  return "-" in m.group(1)
  ```

### `sum_subcategory_counts(df, total_col, category_cols, percent_col=None)`

- **Purpose**: For FTC-style tables where a single report can be filed
  under multiple sub-categories (sub-percentages summing >100 %), return
  the sum-of-sub-categories rather than the headline total.
- **Recovers tasks**: `legal-easy-21` (gold 16589 = sum of theft sub-type
  counts; got 13596 = headline total).
- **Why a helper and not a prompt fix**: The FTC convention "report
  classified into multiple sub-types" affects every identity-theft and
  fraud rollup. The executor in `legal-easy-21` actually *spotted* the
  >100 % sum and rationalized it away. A named helper that says "when
  percent_col sums >100 %, you sum the counts" makes the convention
  explicit and reviewable.
- **Docstring**:
  ```
  """Return the sum-of-subcategory counts when percentages overlap.

  KramaBench / FTC convention: a single report can be classified into
  multiple identity-theft sub-types. If the sub-type percentage column
  sums to > 100, the headline total under-counts the per-type sum.

  Args:
    df: Per-category table with one row per sub-type.
    total_col: Name of the headline-total column (single value
      repeated, or take the first non-null).
    category_cols: List of count columns to sum.
    percent_col: Optional name of the percentage column; if given
      and the sum is >100, the helper returns the sum-of-counts;
      otherwise returns the headline total.

  Returns: int.
  """
  ```
- **Implementation sketch**:
  ```python
  total = df[total_col].dropna().iloc[0]
  cat_sum = df[category_cols].sum(numeric_only=True).sum()
  if percent_col is not None and df[percent_col].sum() > 100.01:
      return int(round(cat_sum))
  return int(round(total))
  ```

### `pct_of_population_for_age_bucket(report_count_2024, share_2024_by_age, target_age_groups, base_total)`

- **Purpose**: Apply a 2024 percentage distribution to a 2007 base total
  (or any back-projection of a categorical share onto a different total).
- **Recovers tasks**: `legal-hard-17`, `legal-hard-18` (gold 91000 needs
  the 2007 *identity-theft-only* base, not the 2007 full-Sentinel base).
- **Why a helper and not a prompt fix**: The "use the matching subset
  total as the base" rule is a counterfactual-projection idiom that
  applies whenever the question phrases "if X were distributed exactly
  like Y, how many...". Without the helper, every such question requires
  re-deriving which total to use; *both* legal-hard-17 and legal-hard-18
  picked the wrong base.
- **Docstring**:
  ```
  """Project a categorical share onto a different base total.

  Common KramaBench pattern: "if 2007 were distributed like 2024,
  how many 2007 reports would be in category X?"

  Args:
    report_count_2024: total count in the source year (denominator
      for the share calculation).
    share_2024_by_age: dict[label -> count_in_2024] for the
      category breakdown.
    target_age_groups: list[label] — the buckets to project.
    base_total: the base total in the TARGET year (e.g., 2007)
      that the share is projected onto.

  CRITICAL GOTCHA: base_total must match the SAME population the
  share describes. If share_2024 is identity-theft-only, base_total
  must be identity-theft-only in the target year — NOT the
  full-corpus total. The most common bug here is mixing
  populations (all-fraud denominator with identity-theft-only
  share).

  Returns: float (the projected count).
  """
  ```
- **Implementation sketch**:
  ```python
  total_2024 = sum(share_2024_by_age.values())
  selected = sum(share_2024_by_age[k] for k in target_age_groups)
  return base_total * (selected / total_2024)
  ```

### `treat_missing_as(df, cols, policy)`

- **Purpose**: Centralize the "missing-means-safe vs missing-means-unsafe"
  decision that controls multi-year aggregation rollups.
- **Recovers tasks**: `environment-hard-16` (gold 60 vs got 75 — the
  question literally says "if no data, assume safe", but the executor
  conflated "no data for year" with "NaN violation rate within year").
- **Why a helper and not a prompt fix**: The same NaN-policy pivot point
  recurs in `wildfire-hard-21` (gold preserves rows with missing
  residential-loss values; the executor dropped them). Two failures, one
  pattern: which missing-treatment policy do we pin?
- **Docstring**:
  ```
  """Apply a named missing-data policy to selected columns.

  Args:
    df: input frame.
    cols: columns to apply policy to.
    policy: one of:
      "as_safe"   — NaN → False (treat as non-violation)
      "as_unsafe" — NaN → True
      "preserve"  — leave NaN in place (downstream aggregations
                    that use min/max/any/all preserve correctness)
      "drop"      — drop rows where ANY listed col is NaN
                    (RARELY correct on KramaBench — most questions
                    say "do not discard rows with missing values
                    unnecessarily")

  Returns a NEW DataFrame.

  Gotcha: when the question says "remained safe ... if no data,
  assume safe", that is the "as_safe" policy on the per-year
  violation column, NOT on the post-aggregation violation count.
  Distinct rows means distinct (beach, year) — missing year
  contributes 0, not NaN.
  """
  ```
- **Implementation sketch**:
  ```python
  out = df.copy()
  if policy == "as_safe":
      out[cols] = out[cols].fillna(False)
  elif policy == "as_unsafe":
      out[cols] = out[cols].fillna(True)
  elif policy == "drop":
      out = out.dropna(subset=cols)
  elif policy != "preserve":
      raise ValueError(f"unknown policy {policy!r}")
  return out
  ```

### `per_unit_mean_vs_total(df, unit_col, value_col, condition)`

- **Purpose**: Compute "mean per X" vs "total" disambiguator for
  conditional aggregation questions.
- **Recovers tasks**: `wildfire-easy-9` (gold -0.0059, got 25.9818 — the
  executor subtracted a *mean fatality per fire* from a *total fatality
  count*, off by a factor of 1500).
- **Why a helper and not a prompt fix**: The "per-X mean" vs "summed
  total" distinction is the single most common arithmetic-mix-up in
  conditional questions ("on humidity<30 % days, how many MORE
  fatalities..."). Two units, one operator. Naming the per-unit version
  forces the executor to apply mean-to-mean comparison.
- **Docstring**:
  ```
  """Return (conditional_mean_per_unit, baseline_mean_per_unit, delta).

  Args:
    df: input frame.
    unit_col: column identifying the unit (e.g., 'fire_id').
    value_col: the metric to average (e.g., 'fatalities').
    condition: boolean Series same length as df selecting the
      conditional subset.

  Returns:
    dict with keys 'conditional', 'baseline', 'delta'. All three
    are MEANS in the same unit (per-unit value), so deltas are
    apples-to-apples.

  Gotcha: do NOT compare a per-unit mean to a sum. If the
  question asks "how many more fatalities", it almost always
  means "how many more PER FIRE on average".
  """
  ```
- **Implementation sketch**:
  ```python
  sub = df[condition]
  cond_mean = sub.groupby(unit_col)[value_col].sum().mean()
  base_mean = df.groupby(unit_col)[value_col].sum().mean()
  return {"conditional": cond_mean, "baseline": base_mean,
          "delta": cond_mean - base_mean}
  ```

### `top_k_pct_threshold(df, value_col, target_share=0.9)`

- **Purpose**: Find the smallest fraction of records whose `value_col`
  cumulatively accounts for `target_share` of the total.
- **Recovers tasks**: `wildfire-hard-20` (gold 0.0465 — the fraction of
  fires accounting for 90 % of residential damage). Pareto-style.
- **Why a helper and not a prompt fix**: The "what fraction accounts for
  X %" pattern is a textbook power-law summary that appears in 3+
  KramaBench tasks (wildfire, environment) and is easy to compute wrong
  (sort direction, ≥ vs >, percentage vs fraction). The helper also pins
  the return units (decimal fraction in [0,1], not percent).
- **Docstring**:
  ```
  """Return the fraction of rows whose top-sorted value_col sums
  to at least target_share of the total.

  Args:
    df: input frame.
    value_col: numeric column to rank/sum on.
    target_share: cumulative share in [0,1]. Default 0.9.

  Returns:
    float in [0,1]: smallest n/N such that sum(top_n) >= target_share * sum_total.

  Gotcha: returns a FRACTION (e.g., 0.0465), not a percentage.
  When the question says "what percentage", the spec must
  multiply by 100 explicitly.
  """
  ```
- **Implementation sketch**:
  ```python
  s = df[value_col].dropna().sort_values(ascending=False).reset_index(drop=True)
  if len(s) == 0 or s.sum() == 0:
      return 0.0
  cumulative = s.cumsum() / s.sum()
  n = int((cumulative >= target_share).idxmax()) + 1
  return n / len(s)
  ```

### `lag_correlation(series_a, series_b, max_lag, sign_convention="b_leads_a")`

- **Purpose**: Return the lag in [0, max_lag] that maximizes r² between
  two time-aligned series, with an explicit lead/lag sign convention.
- **Recovers tasks**: `astronomy-hard-9` (gold 24 h, got 14 h — sign
  flipped on the AP-vs-Δa shift).
- **Why a helper and not a prompt fix**: Lag-sign mistakes are the
  classic time-series bug, and KramaBench has 3+ tasks of this form
  (atmospheric drag vs solar drivers, fire vs weather, water-body
  testing vs rainfall). Naming the convention in code makes it
  inspectable.
- **Docstring**:
  ```
  """Find the lag in [0, max_lag] that maximizes r² between two series.

  Args:
    series_a, series_b: pandas Series indexed by a common time index.
    max_lag: int, in the unit of the series' index step.
    sign_convention:
      "b_leads_a"  — test series_b.shift(+L) against series_a
                     (canonical: "what lag of B best predicts A").
      "a_leads_b"  — test series_a.shift(+L) against series_b.

  Returns:
    (best_lag, best_r2). best_lag is integer.

  Gotcha: the KramaBench atmospheric-drag tasks use
  sign_convention="b_leads_a" with B = AP index, A = Δa.
  A 24-hour lag means AP from 24 hours ago best predicts today's Δa.
  """
  ```
- **Implementation sketch**:
  ```python
  best = (0, -np.inf)
  for L in range(0, max_lag + 1):
      if sign_convention == "b_leads_a":
          ax, bx = series_a, series_b.shift(L)
      else:
          ax, bx = series_a.shift(L), series_b
      df = pd.concat([ax, bx], axis=1).dropna()
      if len(df) < 3:
          continue
      r = df.iloc[:, 0].corr(df.iloc[:, 1])
      if r * r > best[1]:
          best = (L, r * r)
  return best
  ```

### `geopotential_per_mass(r_km, mu_km3_s2=398600.4418, r_earth_km=6371.0)`

- **Purpose**: Compute Newtonian geopotential per unit mass at radius
  `r_km`, anchored to Earth's surface (`Φ = μ·(1/R_E − 1/r)`).
- **Recovers tasks**: `astronomy-hard-12` (gold 6.68 × 10⁷ J/kg vs got
  4.34 × 10⁶ J/kg — the executor used `g·h` instead of the proper
  Newtonian form).
- **Why a helper and not a prompt fix**: The `g·h` vs Newtonian
  geopotential confusion is a *physics primitive* mistake — there's no
  way to get it right from a prompt. A pure-Python helper that names the
  formula and the reference altitude eliminates the choice. KramaBench
  has at least 2 satellite-altitude tasks that touch this.
- **Docstring**:
  ```
  """Newtonian geopotential per unit mass relative to Earth's surface.

  Args:
    r_km: orbital radius from Earth center, in km. Scalar or array.
    mu_km3_s2: Earth's gravitational parameter (default 398600.4418).
    r_earth_km: surface reference radius (default 6371.0).

  Returns:
    Geopotential per unit mass in J/kg:
        Φ = mu * (1/R_E - 1/r) * 1e6
    where the 1e6 converts km^2/s^2 → m^2/s^2 = J/kg.

  Gotcha: Do NOT use g·h (linear approximation valid only near
  surface). For Swarm at ~450 km altitude, the linear form
  under-counts by ~15x. This helper uses the closed-form
  Newtonian potential anchored to the surface so Φ(R_E) = 0.
  """
  ```
- **Implementation sketch**:
  ```python
  mu_si = mu_km3_s2 * 1e9          # km^3/s^2 → m^3/s^2
  r_si = np.asarray(r_km) * 1e3    # km → m
  R_si = r_earth_km * 1e3
  return mu_si * (1.0 / R_si - 1.0 / r_si)
  ```

### `count_two_actor_conflicts(df, conflict_col, second_actor_col=None)`

- **Purpose**: Identify two-actor conflict rows in the Brecke-style
  conflict catalogue, handling the four separator conventions
  (`'-'`, `' vs '`, `','`, explicit SecondActor column).
- **Recovers tasks**: `archeology-hard-12` (gold 409 vs got 233 — the
  hyphen-only rule excluded 176 valid two-actor rows).
- **Why a helper and not a prompt fix**: Brecke's conflict catalogue is
  used in 4+ KramaBench archeology tasks. The two-actor rule is a
  parsing convention, not domain knowledge. Pinning it once stops every
  future task from re-deriving "what counts as two actors".
- **Docstring**:
  ```
  """Return a boolean mask: True where the row encodes a two-actor conflict.

  Rules (any one suffices):
    1. second_actor_col, if provided, is non-null and non-empty.
    2. The pre-paren portion of conflict_col contains any of:
         ' vs ', ' vs. ', ' - ', ', ' (comma-and-space).
       The hyphen rule fires ONLY on a space-padded hyphen, to avoid
       splitting hyphenated proper nouns ("Anglo-Saxon").

  Args:
    df: input frame.
    conflict_col: name of the conflict-string column.
    second_actor_col: optional column with the second-party name.

  Returns: pd.Series[bool] aligned with df.index.
  """
  ```
- **Implementation sketch**:
  ```python
  head = df[conflict_col].astype(str).str.split("(").str[0]
  mask = head.str.contains(r"(?: vs\.? | - |,\s)", regex=True, na=False)
  if second_actor_col and second_actor_col in df.columns:
      mask = mask | df[second_actor_col].notna() & (df[second_actor_col].astype(str).str.strip() != "")
  return mask
  ```

### `find_column_by_keywords(df, keywords, case_insensitive=True)`

- **Purpose**: Locate the right column when sheets contain multiple
  `Age_ky.N` / `wet-dry` / `Al` series and the planner has to disambiguate
  among them.
- **Recovers tasks**: `archeology-hard-2` (gold uses a different wet-dry
  column than the one the executor picked); also reduces the ambiguity
  surface in `archeology-hard-5`.
- **Why a helper and not a prompt fix**: `climateMeasurements.xlsx` has
  3 separate wet-dry indices and 3 separate Al time-series, each on its
  own Age_ky column. The naming pattern is recurring (ODP 967 vs other
  cores). A helper that returns *all* matching columns (so the spec can
  reason about which one) plus a "preferred" key for canonical picks
  short-circuits the column-pairing guesswork.
- **Docstring**:
  ```
  """Return columns whose names contain ALL of `keywords` (substring match).

  Args:
    df: input frame.
    keywords: iterable of strings; column qualifies iff each appears
      as a substring (case-insensitive by default).
    case_insensitive: if True (default), match in lowercase.

  Returns:
    list[str] of matching column names in the order they appear
    in df.columns.

  Gotcha: when multiple columns match (e.g., 'Al ppm' in 3 cores),
  the helper returns all of them; the caller must choose. This is
  intentional — sweeping the wrong column under the rug is the
  exact bug in archeology-hard-2 and archeology-hard-5.
  """
  ```
- **Implementation sketch**:
  ```python
  def find_column_by_keywords(df, keywords, case_insensitive=True):
      kws = [k.lower() if case_insensitive else k for k in keywords]
      out = []
      for c in df.columns:
          name = c.lower() if case_insensitive else c
          if all(k in name for k in kws):
              out.append(c)
      return out
  ```

## Tasks NOT recoverable by helpers

The following 8 of the 25 failures are *not* addressable by adding a
helper, for the reasons given:

- **`archeology-hard-1`** — METHODOLOGY-BINNING on which two Maltese rows
  count as "first/last sample" by the gold's definition. The arithmetic
  is fine; the window-selection convention is sub-task-label territory.
- **`archeology-hard-5`** — F-E-CEILING. Even with
  `find_column_by_keywords`, the canonical Al series can't be inferred
  without a gold-labelled disambiguation. `find_column_by_keywords` makes
  this *reviewable* but doesn't auto-pick.
- **`archeology-hard-9`** — F-E-CEILING on matching radius and rank-or
  convention. Multiple defensible readings; the helper "or-rank averages
  the two numbers" is too narrow to merit a primitive.
- **`astronomy-easy-6`** — FORMAT-LIST + sign-convention disagreement.
  Prompt patch (list literal + storm/quiet order).
- **`astronomy-hard-8`** — SCORER-GAP-RAE on a `list_approximate` answer
  within ~7 %. Scorer rel-tol fix, not a helper.
- **`biomedical-hard-5`** — METHODOLOGY-BINNING: gold says don't invert
  the log2 transform; spec says invert. Sub-task label only.
- **`wildfire-easy-3`** — F-E-CEILING on the GACC-overlap definition
  (area-fraction threshold vs any-intersection).
- **`wildfire-hard-18`** — METHODOLOGY-WRONG: gold is a free-text
  sentence; got is "no". Prompt patch (answer-shape), not a helper.

## Spec_agent prompt updates

Append the following 11 lines to the helper-description block at
`scripts/extract_specs_krama.py:212` (after `bp_to_calendar_year`):

```
- canonicalize_msa_name(name, suffix="Metropolitan Statistical Area",
                        drop_comma_before_state=True)
    Normalize an FTC MSA string to the canonical "<core>, <STATE>
    Metropolitan Statistical Area" form. Use whenever joining
    State MSA *.csv files or emitting an MSA-typed answer.
- cross_state_msa(name) -> bool
    True iff the MSA's state-token block lists 2+ codes (e.g., "MA-NH").
    Use for any "cross-state MSA" filter.
- sum_subcategory_counts(df, total_col, category_cols, percent_col=None)
    Use for FTC totals where sub-percentages sum > 100 % (a single
    report can be classified into multiple sub-types).
- pct_of_population_for_age_bucket(report_count_2024, share_2024_by_age,
                                   target_age_groups, base_total)
    Back-project a 2024 share onto a 2007 base. CRITICAL: base_total
    must match the SAME population as share_2024 (don't mix
    all-fraud denominator with identity-theft-only share).
- treat_missing_as(df, cols, policy)
    Centralize the missing-as-safe vs missing-as-unsafe vs preserve
    vs drop decision. policy in {"as_safe","as_unsafe","preserve","drop"}.
- per_unit_mean_vs_total(df, unit_col, value_col, condition)
    Returns (conditional_mean_per_unit, baseline_mean_per_unit, delta).
    Use whenever the question asks "how many more X on days when Y" —
    do NOT mix a per-unit mean with a sum.
- top_k_pct_threshold(df, value_col, target_share=0.9)
    Returns the smallest fraction (∈[0,1], NOT percent) of rows whose
    top-sorted value_col covers target_share of the total.
- lag_correlation(series_a, series_b, max_lag,
                  sign_convention="b_leads_a")
    Returns (best_lag, best_r2). Convention: "b_leads_a" tests
    series_b.shift(+L) against series_a.
- geopotential_per_mass(r_km, mu_km3_s2=398600.4418, r_earth_km=6371.0)
    Newtonian geopotential per unit mass anchored to Earth's surface.
    Do NOT use g·h for satellite altitudes (linear approximation is off
    by 15x at 450 km).
- count_two_actor_conflicts(df, conflict_col, second_actor_col=None)
    Brecke-style two-actor mask: hyphen-only is too narrow; accepts
    " vs ", " - ", ", ", or a non-null second_actor_col.
- find_column_by_keywords(df, keywords, case_insensitive=True)
    Returns ALL columns whose name contains every keyword. Use when
    a sheet has multiple Age_ky / wet-dry / Al series and the spec
    must pick deliberately (do not auto-select).
```

## Estimated impact

- **11 new helpers proposed** (vs 5 existing).
- **Tasks directly recoverable by a single helper**: 11
  (`legal-hard-2`, `legal-hard-14`, `legal-hard-24`, `legal-hard-29`,
  `legal-hard-15`, `legal-easy-21`, `legal-hard-17`, `legal-hard-18`,
  `environment-hard-16`, `wildfire-easy-9`, `wildfire-hard-20`,
  `astronomy-hard-9`, `astronomy-hard-12`, `archeology-hard-12`,
  `archeology-hard-2`).
- **Tasks where a helper reduces ambiguity but doesn't fully resolve**:
  `archeology-hard-5` (column disambiguation surfaces options to the
  planner).
- **Residual unrecoverable by helpers**: 8 tasks (the F-E-ceiling triad,
  prompt-shape failures, format-list, scorer-tolerance, and the
  free-text-sentence wildfire case).
- **Expected pass-rate uplift**: 11–14 of 25 (44–56 %) on top of the
  scorer/prompt fixes already proposed in `19_opus_failure_analysis.md`.

All 11 helpers stay at the same altitude as the existing 5: each names a
data-pattern primitive (string canonicalization, missingness policy,
per-unit aggregation, lag-with-sign-convention, Newtonian potential,
multi-actor conflict parsing, percentile-threshold sweep, column lookup).
None encodes a task-specific answer or solves a single task with a
hard-coded rule.
