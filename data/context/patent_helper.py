"""DataAgentBench PATENTS domain helpers.

The publicationinfo table has a natural-language `Patents_info` field that
encodes assignee + country + publication number — there is no structured
assignee column. These helpers do the text parsing so the executor doesn't
have to re-invent it inline.

Sample Patents_info strings observed:
  "PANASONIC IP MAN CO LTD holds the US patent application (ID US-201916293577-A), with publication number US-11081687-B2."
  "Patent application (no. DE-102013211266-A) from DE, assigned to IBM, with publication number DE-102013211266-B4."
  "In US, the application (ID US-201916369247-A) is owned by COVESTRO LLC and has publication no. US-11124615-B2."
  "GLASSNER RUDOLF holds the US patent filing (application no. US-201916355911-A), with publication number US-10794458-B2."
  "VITTORI GIANFRANCO DE holds the FR patent filing (app. number FR-7811408-A)..."
  "MIELE & CIE holds the DE patent filing (app. number DE-102005018015-A)..."
  "UHLMANN PAC SYSTEME GMBH & CO KG holds the DE patent filing (app. number DE-102005045181-A)..."
  "In RU, the patent filing (app. number RU-2017142236-A) is held by Sletov Aleksandr Anatolevich..."

The grammar is varied but parsable. We use a small set of regex patterns that
together cover the observed phrasings.
"""
from __future__ import annotations

import json
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Assignee extraction from Patents_info
# ---------------------------------------------------------------------------

# Pattern 1: "<ASSIGNEE> holds the US patent ..."   (assignee at start)
_RE_HOLDS = re.compile(
    r"^(?P<assignee>[A-Z][^.]{2,200}?) holds the (?:[A-Z]{2}|FR|DE|US|RU|JP|CN|KR|GB) patent\s+(?:application|filing)",
    re.IGNORECASE,
)
# Pattern 2: "... assigned to <ASSIGNEE>, with ..."
_RE_ASSIGNED_TO = re.compile(
    r"assigned to\s+(?P<assignee>[^,.;]+?)(?=,|\.|;| with | and )",
    re.IGNORECASE,
)
# Pattern 3: "... is owned by <ASSIGNEE> and has publication ..."
_RE_OWNED_BY = re.compile(
    r"is\s+owned by\s+(?P<assignee>[^,.;]+?)(?=,|\.| and )",
    re.IGNORECASE,
)
# Pattern 4: "... is held by <ASSIGNEE> and ..."
_RE_HELD_BY = re.compile(
    r"is\s+held by\s+(?P<assignee>[^,.;]+?)(?=,|\.| and )",
    re.IGNORECASE,
)
# Pattern 5: "... belonging to <ASSIGNEE> ..."
_RE_BELONGING_TO = re.compile(
    r"belonging to\s+(?P<assignee>[^,.;]+?)(?=,|\.| and | with )",
    re.IGNORECASE,
)


def extract_assignee_from_patents_info(text: str) -> Optional[str]:
    """Best-effort extraction of the assignee/owner name from Patents_info.

    Returns None if no pattern matches. The returned string is the assignee
    name as written in the source (case-preserved, no normalization).
    """
    if not text:
        return None
    for rx in (_RE_HOLDS, _RE_ASSIGNED_TO, _RE_OWNED_BY, _RE_HELD_BY, _RE_BELONGING_TO):
        m = rx.search(text)
        if m:
            assignee = m.group("assignee").strip()
            # Strip trailing whitespace / punctuation noise
            assignee = re.sub(r"\s+", " ", assignee).strip(" ,.;")
            if assignee:
                return assignee
    return None


# ---------------------------------------------------------------------------
# Publication number + country code extraction
# ---------------------------------------------------------------------------

# Patent publication numbers in DAB are like "US-11081687-B2", "DE-102013211266-B4", etc.
_RE_PUB_NO = re.compile(
    r"\b(?P<country>[A-Z]{2})-(?P<id>[A-Z0-9]+)-(?P<kind>[A-Z]\d?)\b"
)


def extract_publication_number(text: str) -> Optional[str]:
    """Pull the publication number (e.g., 'US-11081687-B2') from Patents_info."""
    if not text:
        return None
    # Prefer "publication number X" / "publication no. X" / "pub. no. X"
    m = re.search(
        r"(?:publication\s+(?:number|no\.?)|pub\.?\s+no\.?)\s+([A-Z]{2}-[A-Z0-9]+-[A-Z]\d?)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = _RE_PUB_NO.search(text)
    return m.group(0) if m else None


def extract_application_number(text: str) -> Optional[str]:
    """Pull the application/filing number from Patents_info."""
    if not text:
        return None
    m = re.search(
        r"(?:application(?:\s+number|\s+no\.?)?|app\.?\s+number|filing\s+(?:number|no\.?)?|"
        r"ID|app\s+no\.?)\s*\(?\s*(?:no\.?\s*)?([A-Z]{2}-[A-Z0-9]+-[A-Z]\d?)",
        text,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


def country_from_pubno(pubno: Optional[str]) -> Optional[str]:
    """ISO 2-letter country code (DE, US, FR, ...) from a publication number."""
    if not pubno:
        return None
    m = _RE_PUB_NO.match(pubno.upper())
    return m.group("country") if m else None


def is_country(text: str, country_code: str) -> bool:
    """True if Patents_info indicates a patent from the given country.

    Heuristic: matches if the publication-number country == country_code OR
    the text contains 'In <CC>,' or '<CC> patent' or 'from <CC>'.
    """
    if not text:
        return False
    cc = country_code.upper()
    pn = extract_publication_number(text)
    if pn and country_from_pubno(pn) == cc:
        return True
    if re.search(rf"\b(?:in|from)\s+{cc}\b", text, re.IGNORECASE):
        return True
    if re.search(rf"\b{cc}\s+patent\b", text, re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# Structured-field JSON parsing
# ---------------------------------------------------------------------------

def parse_cpc_field(cpc_str: str) -> list[dict]:
    """Parse the publicationinfo.cpc field (JSON list of {code, first, inventive, tree})."""
    if not cpc_str or not cpc_str.strip():
        return []
    try:
        return json.loads(cpc_str)
    except json.JSONDecodeError:
        return []


def parse_citation_field(citation_str: str) -> list[dict]:
    """Parse the publicationinfo.citation field (JSON list of cited refs)."""
    if not citation_str or not citation_str.strip():
        return []
    try:
        return json.loads(citation_str)
    except json.JSONDecodeError:
        return []


def cited_publication_numbers(citation_str: str) -> list[str]:
    """Just the publication_number strings from the citation JSON list."""
    refs = parse_citation_field(citation_str)
    return [c.get("publication_number") for c in refs
            if isinstance(c, dict) and c.get("publication_number")]


def cpc_codes(cpc_str: str) -> list[str]:
    """Just the codes (e.g., 'C01B33/00') from the cpc JSON list."""
    refs = parse_cpc_field(cpc_str)
    return [c.get("code") for c in refs if isinstance(c, dict) and c.get("code")]


def cpc_primary_code(cpc_str: str) -> Optional[str]:
    """The 'primary' CPC code = first entry with first==True, else first entry."""
    refs = parse_cpc_field(cpc_str)
    for c in refs:
        if isinstance(c, dict) and c.get("first") is True:
            return c.get("code")
    if refs and isinstance(refs[0], dict):
        return refs[0].get("code")
    return None


def cpc_subclass(code: str) -> Optional[str]:
    """Strip a CPC code to its subclass (e.g., 'C01B33/00' -> 'C01B')."""
    if not code:
        return None
    m = re.match(r"^([A-Z]\d{2}[A-Z])", code)
    return m.group(1) if m else None


def cpc_main_group(code: str) -> Optional[str]:
    """Strip to main group (level 4): 'C01B33/00' or 'C01B33/20' -> 'C01B33'."""
    if not code:
        return None
    m = re.match(r"^([A-Z]\d{2}[A-Z]\d+)", code)
    return m.group(1) if m else None


def cpc_subclass_title(code: str, conn_pg) -> Optional[str]:
    """Title of the code's SUBCLASS (4-char level), by EXACT symbol lookup.

    'H01M10/0525' -> looks up symbol == 'H01M' in cpc_definition and returns
    its titleFull. Never traverses the `parents` chain — ascending parents
    returns section/class titles (e.g. 'GEOPHYSICS; ...'), which are the
    wrong granularity for "primary CPC subclass" questions.

    conn_pg: psycopg connection to the CPC-definition Postgres DB
    (e.g. dab_helper.open_postgres('patent_CPCDefinition')).
    """
    sub = cpc_subclass(code)
    if not sub:
        return None
    cur = conn_pg.execute(
        'SELECT "titleFull" FROM cpc_definition WHERE symbol = %s', (sub,)
    )
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# EMA helper with self-test
# ---------------------------------------------------------------------------

def exponential_moving_average(values, alpha: float, seed: str = "x0") -> list[float]:
    """Recursive EMA: y_t = a*x_t + (1-a)*y_{t-1}.

    Args:
        values: numeric series.
        alpha: smoothing factor in (0, 1].
        seed: 'x0' → y_0 = values[0] (pandas ewm adjust=False default).
              'zero' → y_0 = a*x_0 (the warm-up form; matches argmax behavior
              that lets later peaks dominate).

    Use seed='x0' to match pandas ewm(alpha=..., adjust=False).mean().
    Use seed='zero' for the "warm-up from zero" form where best_year reflects
    the latest large value.
    """
    out = []
    prev = None
    for v in values:
        v = float(v)
        if prev is None:
            if seed == "x0":
                prev = v
            elif seed == "zero":
                prev = alpha * v
            else:
                raise ValueError(f"seed must be 'x0' or 'zero'; got {seed!r}")
        else:
            prev = alpha * v + (1.0 - alpha) * prev
        out.append(prev)
    return out


def best_year_by_ema(year_to_count: dict, alpha: float,
                     fill_missing_with_zero: bool = True,
                     seed: str = "zero",
                     tie_break: str = "latest") -> Optional[int]:
    """Compute argmax-EMA-year for a {year: count} dict.

    Args:
        year_to_count: e.g. {2014: 3, 2015: 1, 2018: 2}.
        alpha: EMA smoothing factor.
        fill_missing_with_zero: if True, the time series spans min..max
            inclusive, with 0 for missing years. Otherwise only the observed
            years are used. Default True (zero-fill matches "filings each year").
        seed: 'x0' or 'zero' — see exponential_moving_average. Default 'zero'
            (the convention that lets later peaks win, which matches DAB gold
            patterns where best_year is often the latest peak year).
        tie_break: 'latest' or 'earliest' — when multiple years share the
            max EMA value. Default 'latest'.

    Returns the year with the maximum EMA value, or None if input is empty.
    """
    if not year_to_count:
        return None
    years = sorted(year_to_count.keys())
    if fill_missing_with_zero:
        years_full = list(range(min(years), max(years) + 1))
        counts = [year_to_count.get(y, 0) for y in years_full]
    else:
        years_full = years
        counts = [year_to_count[y] for y in years]
    ema = exponential_moving_average(counts, alpha, seed=seed)
    max_val = max(ema)
    candidates = [years_full[i] for i, v in enumerate(ema) if v == max_val]
    if tie_break == "latest":
        return candidates[-1]
    return candidates[0]


def _ema_self_test() -> bool:
    """Quick sanity check on EMA — call this once before relying on results."""
    # Known: EMA(adjust=False) of [1,2,3,5,4] with alpha=0.2:
    # y0=1, y1=.2*2+.8*1=1.2, y2=.2*3+.8*1.2=1.56, y3=.2*5+.8*1.56=2.248,
    # y4=.2*4+.8*2.248=2.5984
    got = exponential_moving_average([1, 2, 3, 5, 4], 0.2)
    expected = [1.0, 1.2, 1.56, 2.248, 2.5984]
    return all(abs(g - e) < 1e-9 for g, e in zip(got, expected))
