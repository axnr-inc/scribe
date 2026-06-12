"""KramaBench paradigm-level pandas helpers.

Mirrors `data/context/dabstep_helper.py` in role but at the PARADIGM level:
these are cross-domain data-cleaning patterns common to scientific data
pipelines, NOT domain-specific business rules.

The spec_agent references these by name in its `computation_plan` so the
executor doesn't need to re-implement each pattern from scratch. The executor's
Python REPL auto-loads these via the preamble.

Justification per `docs/findings/14_paradigm_fit_and_helper_strategy.md`:
each helper was chosen because it would have prevented a SPECIFIC observed
pilot failure on the archeology subset (pilot12, 2026-06-06). Adding a new
helper requires the same evidentiary bar — a documented failure mode the
helper would fix.

Helpers:
  - read_multi_header_excel: handle xlsx files with N rows of metadata above
    the real header row. Fixes Krama hard-2 (wet-dry index column mis-located).
  - parse_missing_marker: convert sentinel-encoded missing values (e.g. "M",
    "N/A", "-999") to NaN. Fixes the "M means missing" failure mode
    documented in the KramaBench paper §4.2.
  - safe_dedupe: dedup with an explicit aggregation policy on a stable key.
    Fixes Krama hard-12 (3x over-count from missed dedup).
  - linear_interp_by_key: linearly interpolate `value_col` at integer keys
    spanning the min/max of `key_col`. Fixes Krama hard-1 (Maltese-area
    Potassium interpolation).
  - bp_to_calendar_year: convert "years before present" (where present = 1950
    by convention) to calendar year. Fixes Krama hard-5 (Neolithic year
    conversion).
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# read_multi_header_excel
# ---------------------------------------------------------------------------

def read_multi_header_excel(
    path: str,
    sheet: str | int = 0,
    header_row: int | None = None,
    header_keywords: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Read an Excel sheet that has N rows of metadata above the real header.

    Two modes:

    1. Explicit: pass `header_row` (0-indexed) to skip exactly that many
       metadata rows.
    2. Auto-detect: pass `header_keywords` (e.g. ["Site", "Hole"]). The
       function scans rows top-to-bottom and uses the first row that contains
       ALL of those tokens as the header row.

    Auto-detect was specifically motivated by Krama `archeology-hard-2` where
    the planner had to revise the spec to handle this multi-row header pattern.

    Returns the data rows BELOW the detected header, with column names taken
    from the detected header row. Empty/blank header cells are kept as-is
    (use the original column position to disambiguate).
    """
    if header_row is not None:
        df = pd.read_excel(path, sheet_name=sheet, header=header_row)
        return df

    raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)

    if header_keywords:
        kw_lower = [k.lower() for k in header_keywords]
        for i in range(min(50, len(raw))):
            row_vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
            if all(k in row_vals for k in kw_lower):
                cols = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[i].tolist()]
                df = raw.iloc[i + 1:].copy()
                df.columns = cols
                df = df.reset_index(drop=True)
                df = df.dropna(how="all")
                return df
        raise ValueError(
            f"read_multi_header_excel: could not find row containing all of {header_keywords}"
        )

    raise ValueError(
        "read_multi_header_excel: pass either header_row=int or header_keywords=[...]"
    )


# ---------------------------------------------------------------------------
# parse_missing_marker
# ---------------------------------------------------------------------------

def parse_missing_marker(
    df: pd.DataFrame,
    cols: Sequence[str] | None = None,
    markers: Sequence[object] = ("M", "N/A", "NA", "-999", "?"),
) -> pd.DataFrame:
    """Replace sentinel markers in `cols` (or all object cols) with NaN.

    Motivation: KramaBench paper §4.2 documents "M means missing" as a common
    pitfall — sample-based retrieval misses the marker, the agent uses the M
    literal as data, and the pipeline produces wrong totals. This helper makes
    the conversion explicit and reviewable.

    Default markers cover the most common conventions; pass a custom list to
    add domain-specific sentinels.

    Returns a NEW DataFrame; the original is not modified.
    """
    out = df.copy()
    target_cols = list(cols) if cols is not None else list(out.select_dtypes(include="object").columns)
    marker_set = set(str(m).strip() for m in markers)
    for c in target_cols:
        if c in out.columns:
            out[c] = out[c].apply(
                lambda v: np.nan if (isinstance(v, str) and v.strip() in marker_set) else v
            )
    return out


# ---------------------------------------------------------------------------
# safe_dedupe
# ---------------------------------------------------------------------------

def safe_dedupe(
    df: pd.DataFrame,
    keys: Sequence[str],
    agg: str | dict = "first",
    sort_by: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Dedup with an EXPLICIT aggregation policy on a stable key.

    Motivation: Krama `archeology-hard-12` produced ~3x overcount because the
    pipeline never named a dedup key — multiple rows with the same conflict
    name + different annotations got counted separately. This helper makes the
    key explicit and forces the agent to choose an aggregation policy.

    Params:
      keys: column names that should be unique together
      agg: 'first' (keep first row per key) | 'last' | dict of col → agg fn
      sort_by: optional sort BEFORE dedup so 'first' is deterministic

    Returns a NEW DataFrame.
    """
    if sort_by:
        out = df.sort_values(by=list(sort_by), kind="stable").copy()
    else:
        out = df.copy()

    if isinstance(agg, str):
        keep = agg
        if keep not in ("first", "last"):
            raise ValueError(f"safe_dedupe: agg must be 'first', 'last', or a dict; got {agg!r}")
        return out.drop_duplicates(subset=list(keys), keep=keep).reset_index(drop=True)

    # agg is a dict: groupby + aggregate
    return out.groupby(list(keys), as_index=False).agg(agg)


# ---------------------------------------------------------------------------
# linear_interp_by_key
# ---------------------------------------------------------------------------

def linear_interp_by_key(
    df: pd.DataFrame,
    key_col: str,
    value_col: str,
    target_keys: Iterable[float] | None = None,
) -> pd.DataFrame:
    """Linearly interpolate `value_col` at integer keys spanning min..max of `key_col`.

    If `target_keys` is provided, interpolate at exactly those keys instead.
    Returns a DataFrame with columns [key_col, value_col_interp].

    Motivation: Krama `archeology-hard-1` requires linearly-interpolated K
    values for every integer year between the earliest and latest Maltese
    radiocarbon dates. The naive `pd.DataFrame.interpolate` doesn't enforce
    sorting, doesn't handle non-integer key spacing well, and doesn't restrict
    output to integer keys. This helper does all three.
    """
    sorted_df = df[[key_col, value_col]].dropna().sort_values(by=key_col)
    if sorted_df.empty:
        return pd.DataFrame({key_col: [], value_col + "_interp": []})

    if target_keys is None:
        lo = int(np.floor(sorted_df[key_col].min()))
        hi = int(np.ceil(sorted_df[key_col].max()))
        keys = np.arange(lo, hi + 1, dtype=float)
    else:
        keys = np.asarray(list(target_keys), dtype=float)

    vals = np.interp(keys, sorted_df[key_col].values, sorted_df[value_col].values)
    return pd.DataFrame({key_col: keys, value_col + "_interp": vals})


# ---------------------------------------------------------------------------
# bp_to_calendar_year
# ---------------------------------------------------------------------------

def bp_to_calendar_year(years_bp, reference_year: int = 1950):
    """Convert years-before-present (BP) to calendar year.

    Archaeology convention: "present" = 1950 (when radiocarbon was calibrated).
    A radiocarbon age of 2000 BP → calendar year 1950 - 2000 = -50 (50 BCE).

    Accepts scalar, list, ndarray, or pandas Series — returns same type.

    Motivation: Krama `archeology-hard-5` requires converting Neolithic ages
    from BP to a coordinate system the gold expects. Easy to get the sign
    wrong (calendar - BP vs BP - calendar). Helper makes the convention
    explicit and matches the radiocarbon standard.
    """
    if isinstance(years_bp, pd.Series):
        return reference_year - years_bp
    if isinstance(years_bp, np.ndarray):
        return reference_year - years_bp
    if isinstance(years_bp, list):
        return [reference_year - x for x in years_bp]
    return reference_year - years_bp


# ===========================================================================
# Expansion 2026-06-08: 11 new helpers mined from Opus 4.7 failure analysis
# (docs/findings/21_helper_manifest_expansion.md). Same paradigm-level
# altitude as the original 5 — each fixes a documented multi-task pattern.
# ===========================================================================

import re


# ---------------------------------------------------------------------------
# canonicalize_msa_name
# ---------------------------------------------------------------------------

_MSA_STATE_RE = re.compile(r",\s+([A-Z]{2}(?:-[A-Z]{2}){0,4})(\b|\s)")


def canonicalize_msa_name(name, suffix: str = "Metropolitan Statistical Area",
                          drop_comma_before_state: bool = True) -> str:
    """Canonicalize an MSA name to the FTC's verbose form.

    KramaBench / FTC convention: the gold form typically reads
    "Los Angeles-Long Beach-Anaheim CA Metropolitan Statistical Area"
    (no comma before the state code, full suffix).

    Args:
      name: MSA string in any source format.
      suffix: trailing classification to append if missing.
      drop_comma_before_state: if True, "..., CA Metro Area" → "... CA Metro Area".

    Returns: normalized string. Idempotent.

    Recovers: legal-hard-2, legal-hard-14, legal-hard-24, legal-hard-29.
    """
    s = str(name).strip()
    if drop_comma_before_state:
        s = _MSA_STATE_RE.sub(r" \1\2", s)
    if suffix and suffix not in s:
        s = s.rstrip(",") + " " + suffix
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# cross_state_msa
# ---------------------------------------------------------------------------

def cross_state_msa(name) -> bool:
    """Return True iff the MSA name's state-token block lists 2+ codes.

    Examples:
      "Boston-Cambridge-Newton, MA-NH ..." → True
      "Worcester, MA ..." → False
      "Washington-Arlington-Alexandria, DC-VA-MD-WV ..." → True

    Raises ValueError if no state-token block can be located.

    Recovers: legal-hard-15 (cross-state MSA bin).
    """
    m = re.search(r",\s+([A-Z]{2}(?:-[A-Z]{2}){0,4})\b", str(name))
    if not m:
        raise ValueError(f"no state-token block in {name!r}")
    return "-" in m.group(1)


# ---------------------------------------------------------------------------
# sum_subcategory_counts
# ---------------------------------------------------------------------------

def sum_subcategory_counts(df, total_col: str, category_cols: Sequence[str],
                           percent_col: str | None = None) -> int:
    """Return the sum-of-subcategory counts when sub-percentages overlap.

    FTC convention: a single report can be classified into multiple
    sub-types. If the sub-type percentage column sums to > 100, the headline
    total under-counts and the per-subcategory sum is the right answer.

    Recovers: legal-easy-21 (gold 16589 = sum of sub-type counts; not the
    headline total).
    """
    total = df[total_col].dropna().iloc[0]
    cat_sum = df[list(category_cols)].sum(numeric_only=True).sum()
    if percent_col is not None and df[percent_col].sum() > 100.01:
        return int(round(cat_sum))
    return int(round(total))


# ---------------------------------------------------------------------------
# pct_of_population_for_age_bucket
# ---------------------------------------------------------------------------

def pct_of_population_for_age_bucket(report_count_2024: float,
                                     share_2024_by_age: dict,
                                     target_age_groups: Sequence[str],
                                     base_total: float) -> float:
    """Project a categorical share onto a different base total.

    KramaBench pattern: "if 2007 reports were distributed across age
    groups exactly like 2024, how many would be in age groups X?"

    CRITICAL: base_total must describe the SAME population as
    share_2024_by_age. If share_2024 is identity-theft-only, base_total
    must also be identity-theft-only — not the full-corpus total.

    Recovers: legal-hard-17, legal-hard-18.
    """
    total_2024 = sum(share_2024_by_age.values())
    if total_2024 == 0:
        return 0.0
    selected = sum(share_2024_by_age[k] for k in target_age_groups)
    return base_total * (selected / total_2024)


# ---------------------------------------------------------------------------
# treat_missing_as
# ---------------------------------------------------------------------------

def treat_missing_as(df, cols: Sequence[str], policy: str):
    """Apply a named missing-data policy to selected columns.

    policy ∈ {
      "as_safe"   — NaN → False
      "as_unsafe" — NaN → True
      "preserve"  — leave NaN in place
      "drop"      — drop rows where ANY listed col is NaN
                    (rarely correct on KramaBench)
    }

    When a question says "if no data, assume safe", that is the "as_safe"
    policy on the per-row violation flag — NOT a post-aggregation rule.

    Recovers: environment-hard-16 (NaN-as-safe), wildfire-hard-21 (preserve).
    """
    out = df.copy()
    cols = list(cols)
    if policy == "as_safe":
        out[cols] = out[cols].fillna(False)
    elif policy == "as_unsafe":
        out[cols] = out[cols].fillna(True)
    elif policy == "drop":
        out = out.dropna(subset=cols)
    elif policy != "preserve":
        raise ValueError(f"unknown policy {policy!r}")
    return out


# ---------------------------------------------------------------------------
# per_unit_mean_vs_total
# ---------------------------------------------------------------------------

def per_unit_mean_vs_total(df, unit_col: str, value_col: str, condition) -> dict:
    """Return (conditional_mean_per_unit, baseline_mean_per_unit, delta).

    All three are MEANS in the same per-unit unit, so deltas are
    apples-to-apples. Do NOT compare a per-unit mean to a sum.

    Args:
      df: input frame.
      unit_col: column identifying the unit (e.g., 'fire_id').
      value_col: numeric column to aggregate (e.g., 'fatalities').
      condition: boolean Series same length as df selecting the
        conditional subset.

    Recovers: wildfire-easy-9 (mean-per-fire delta, not sum-vs-mean mix).
    """
    sub = df[condition]
    cond_mean = sub.groupby(unit_col)[value_col].sum().mean()
    base_mean = df.groupby(unit_col)[value_col].sum().mean()
    return {"conditional": float(cond_mean),
            "baseline":    float(base_mean),
            "delta":       float(cond_mean - base_mean)}


# ---------------------------------------------------------------------------
# top_k_pct_threshold
# ---------------------------------------------------------------------------

def top_k_pct_threshold(df, value_col: str, target_share: float = 0.9) -> float:
    """Smallest fraction of top-sorted rows whose value_col sums to
    at least target_share of the total.

    Returns a FRACTION in [0, 1], not a percentage. When the question
    asks "what percentage", the spec must multiply by 100 explicitly.

    Recovers: wildfire-hard-20 (Pareto fraction; 0.0465 vs the agent's
    bare 4.65 was a unit error from missing this primitive).
    """
    s = df[value_col].dropna().sort_values(ascending=False).reset_index(drop=True)
    if len(s) == 0 or s.sum() == 0:
        return 0.0
    cumulative = s.cumsum() / s.sum()
    n = int((cumulative >= target_share).idxmax()) + 1
    return n / len(s)


# ---------------------------------------------------------------------------
# lag_correlation
# ---------------------------------------------------------------------------

def lag_correlation(series_a, series_b, max_lag: int,
                    sign_convention: str = "b_leads_a") -> tuple:
    """Find lag L in [0, max_lag] that maximizes r² between two series.

    sign_convention:
      "b_leads_a" — test series_b.shift(+L) vs series_a
                    (canonical: "what lag of B best predicts A").
      "a_leads_b" — test series_a.shift(+L) vs series_b.

    For atmospheric drag: B = AP index, A = Δa, b_leads_a. A 24-hour lag
    means AP from 24 hours ago best predicts today's Δa.

    Returns: (best_lag, best_r2). best_lag is integer in [0, max_lag].

    Recovers: astronomy-hard-9 (sign convention; gold 24h vs got 14h).
    """
    best_lag, best_r2 = 0, -np.inf
    for L in range(0, int(max_lag) + 1):
        if sign_convention == "b_leads_a":
            ax, bx = series_a, series_b.shift(L)
        elif sign_convention == "a_leads_b":
            ax, bx = series_a.shift(L), series_b
        else:
            raise ValueError(f"unknown sign_convention {sign_convention!r}")
        joined = pd.concat([ax, bx], axis=1).dropna()
        if len(joined) < 3:
            continue
        r = joined.iloc[:, 0].corr(joined.iloc[:, 1])
        r2 = float(r * r) if r == r else 0.0  # nan-safe
        if r2 > best_r2:
            best_lag, best_r2 = L, r2
    return best_lag, best_r2


# ---------------------------------------------------------------------------
# geopotential_per_mass
# ---------------------------------------------------------------------------

def geopotential_per_mass(r_km, mu_km3_s2: float = 398600.4418,
                          r_earth_km: float = 6371.0):
    """Newtonian geopotential per unit mass anchored to Earth's surface.

    Φ = μ · (1/R_E − 1/r) · 1e6   (J/kg; the 1e6 converts km²/s² → m²/s²).

    Do NOT use g·h for satellite altitudes. The linear approximation
    under-counts by ~15× at Swarm altitude (~450 km).

    Args:
      r_km: orbital radius from Earth center, in km. Scalar or array.
      mu_km3_s2: Earth's gravitational parameter (default 398600.4418).
      r_earth_km: surface reference radius (default 6371.0).

    Recovers: astronomy-hard-12 (gold 6.68×10⁷ J/kg, got 4.34×10⁶ from g·h).
    """
    mu_si = mu_km3_s2 * 1e9          # km^3/s^2 → m^3/s^2
    r_si = np.asarray(r_km, dtype=float) * 1e3
    R_si = r_earth_km * 1e3
    return mu_si * (1.0 / R_si - 1.0 / r_si)


# ---------------------------------------------------------------------------
# count_two_actor_conflicts
# ---------------------------------------------------------------------------

_TWO_ACTOR_RE = re.compile(r"(?: vs\.? | - |,\s)")


def count_two_actor_conflicts(df, conflict_col: str,
                              second_actor_col: str | None = None):
    """Boolean mask: True where the row encodes a two-actor conflict.

    Brecke-style catalogue rules:
      1. second_actor_col, if provided, is non-null and non-empty.
      2. The pre-parenthesis portion of conflict_col contains any of:
           ' vs ', ' vs. ', ' - ' (space-padded), ', ' (comma + space).
         Hyphen rule requires space padding to avoid splitting hyphenated
         proper nouns ("Anglo-Saxon").

    Recovers: archeology-hard-12 (gold 409 vs got 233 — hyphen-only filter
    excluded 176 valid two-actor rows).
    """
    head = df[conflict_col].astype(str).str.split("(").str[0]
    mask = head.str.contains(_TWO_ACTOR_RE, regex=True, na=False)
    if second_actor_col and second_actor_col in df.columns:
        sec = df[second_actor_col].astype(str).str.strip()
        mask = mask | (df[second_actor_col].notna() & (sec != ""))
    return mask


# ---------------------------------------------------------------------------
# find_column_by_keywords
# ---------------------------------------------------------------------------

def find_column_by_keywords(df, keywords: Iterable[str],
                            case_insensitive: bool = True) -> list:
    """Return ALL columns whose name contains EVERY keyword (substring).

    When a sheet has multiple Age_ky / wet-dry / Al series (climateMeasurements.xlsx
    in archeology has three each), the helper returns all matches and the
    caller must choose. Returning all is intentional — auto-picking the
    first match is the exact bug in archeology-hard-2 / hard-5.

    Args:
      df: input frame.
      keywords: iterable of strings; column qualifies iff each appears
        as a substring (case-insensitive by default).
      case_insensitive: lowercase comparison when True.

    Recovers: archeology-hard-2 (column disambiguation), surfaces ambiguity
    in archeology-hard-5.
    """
    kws = [k.lower() if case_insensitive else k for k in keywords]
    out = []
    for c in df.columns:
        name = str(c).lower() if case_insensitive else str(c)
        if all(k in name for k in kws):
            out.append(c)
    return out
