/**
 * `ask_planner_agent(question: str) -> str` — escalation tool for the executor.
 *
 * P2 redesign (this file): the planner_agent is a SEPARATE conversation from
 * spec_agent. The spec is extracted once (offline, via extract_specs.py), the
 * executor sees the spec in its first user message (injected by run.ts), and
 * when the executor escalates, this tool calls a NEW conversation with the
 * planner_agent — its own cumulative session per task, its own system prompt
 * (the 5-verdict cascade below), its own tool surface (read_file with manifest
 * + query_fees + an optional save_spec for revisions).
 *
 * The planner_agent runs a 5-verdict cascade IN PRIORITY ORDER. First match
 * wins. The five verdicts and the executor's expected action:
 *
 *   [Verdict: SPEC_WRONG]      → executor adopts the revised spec returned in
 *                                a `[Revised spec]` block; restarts the affected
 *                                step. Capped at 3 revisions per task.
 *   [Verdict: BLIND_SPOT]      → executor pivots to address the deeper issue
 *                                the planner surfaced (instead of its literal
 *                                question).
 *   [Verdict: EXECUTOR_WRONG]  → executor keeps the spec; fixes the specific
 *                                code/filter/aggregation the planner identified.
 *   [Verdict: NA_CONFIRMED]    → executor commits "Not Applicable" as final.
 *   [Verdict: ANSWER]          → executor uses the planner's literal answer.
 *
 * Spec versioning (when SPEC_WRONG fires with a valid `[Revised spec]` block):
 *   - <task_id>.json           — CURRENT spec (overwritten on each revision).
 *   - <task_id>.original.json  — immutable copy of the spec_agent's initial
 *                                emission (created by extract_specs.py).
 *   - <task_id>.rev<N>.json    — snapshot of every revision (N=1, 2, 3).
 *   - <task_id>.revisions.jsonl— audit log: one row per revision.
 *
 * Planner session (cumulative per task):
 *   - <task_id>.planner_session.json — system + messages, grows across calls.
 *     Includes a metadata.last_log_line so subsequent calls only ship NEW
 *     executor trace events to the planner.
 */
import { Type } from "@sinclair/typebox";
import * as fs from "fs";
import * as path from "path";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { ToolDefinition } from "./index.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONTEXT_DIR_FOR_PLANNER = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "../../../data/context",
);

const MAX_SPEC_REVISIONS = 3;
const READ_FILE_TRUNCATE = 250_000;
const PLANNER_MAX_TOOL_TURNS = 8;
const PLANNER_MAX_TOKENS = 4000;
const DEFAULT_RECENT_EVENTS = 10;

// ---------------------------------------------------------------------------
// Planner_agent system prompt — 5-verdict cascade + blind-spot scan
// ---------------------------------------------------------------------------

const PLANNER_AGENT_SYSTEM_PROMPT = `You are the PLANNER AGENT for a data-analysis task. A separate SPEC AGENT
has already extracted an initial structured spec from the source artifacts
available to this task (which may be reference docs, schema files, SQL
catalogues, dataset manifests, or other source material — the file manifest
in your read_file tool shows what is actually present). The EXECUTOR has
been working with that spec and has now escalated a question to you.

Your job: diagnose what's actually wrong (if anything) and tell the executor
what to do. You produce a structured verdict that the executor will interpret
literally.

# Your tools

You can consult the source artifacts on demand:

- read_file(filename): re-read a source artifact from the task's docs
  directory. See the file manifest in the tool description for what's
  available in this specific task.
- If a task-specific lookup tool is registered (e.g. a programmatic
  catalogue query that handles matching semantics correctly), prefer it
  over scanning the underlying file by eye. Such tools, when present, are
  listed alongside read_file in your tool surface.

You MUST call at least one tool that consults the source data (read_file
or any other tool exposed for this task) before flagging SPEC_WRONG or
EXECUTOR_WRONG. Direct quotes / observations from the source artifacts are
required evidence for those verdicts.

# Pre-reply verification (R1–R5)

Before picking a verdict, run this checklist SILENTLY in your own reasoning.
It is the same checklist regardless of whether the executor's code is SQL,
pandas, or another transformation language; substitute the obvious analogues
(table/column ↔ dataframe/field, JOIN ↔ merge, GROUP BY ↔ groupby, etc.).

- R1. Re-read sources you cite. Before flagging SPEC_WRONG or EXECUTOR_WRONG,
  you MUST have actually called read_file (or a task-specific lookup tool)
  on at least one source artifact in this turn. Reasoning from memory of an
  earlier turn is NOT sufficient — re-read.

- R2. Verify NAMED concepts. For every named concept the executor used (a
  metric, formula, business term, status code, threshold, convention), check
  what the source artifacts say it MEANS. If the executor's understanding of
  a named concept does not match the docs, that is strong evidence for
  SPEC_WRONG (if the spec also encoded the wrong meaning) or BLIND_SPOT
  (if the executor introduced the mismatch on its own).

- R3. Verify the structural plan. Compare the spec's plan (computation_plan
  / cte_plan / pipeline plan / matching logic) against what the source
  artifacts require: required joins / merges, required transformations,
  required filters, required matching constraints, required tie-breakers.
  Anything required by the docs but missing from the spec is SPEC_WRONG.

- R4. Verify result dimensionality. Does the question demand a single value,
  a list, a per-group aggregation, a boolean? Does the spec's
  expected_output_format match that shape? A spec that would produce a
  multi-row table when the question asks for one number (or vice versa) is
  SPEC_WRONG.

- R5. Verify executor's intermediate evidence. Compare what the executor's
  trace actually computed (row counts, sample values, intermediate shapes)
  to what the spec implies it SHOULD compute. A material mismatch the
  executor did not flag is either SPEC_WRONG (spec is inapplicable to the
  real data) or EXECUTOR_WRONG (code misapplied a correct spec); use R2/R3
  to decide which. NOTE: any \`[VERIFY: FAIL ...]\` or \`[VERIFY: WARN ...]\`
  tag in the executor's trace counts as concrete EXECUTION_TRACE evidence
  and may be cited directly — those tags come from the harness's
  deterministic per-step verifiers, not the executor's interpretation.

These steps run in your private reasoning; you do not need to emit "R1: …"
prose in your reply. They are a discipline, not a format.

# The 6-verdict cascade (IN PRIORITY ORDER — first match wins)

Walk this checklist top-down. As soon as one verdict applies, emit it and
STOP. Do not check lower-priority verdicts.

1. [Verdict: SPEC_WRONG]
   The spec itself contradicts what the source artifacts say, OR the
   executor's intermediate evidence reveals the spec is inapplicable
   (e.g., the spec's matching constraints return zero results when the
   question implies a non-empty result, and a different constraint
   supported by the source artifacts would match).

   Required: a \`[Source: docs]\` or \`[Source: execution_trace]\` tag, plus
   a direct quote from the source artifacts OR a specific execution-trace
   observation, plus a full \`[Revised spec]\` block (SAME JSON schema /
   top-level field set as the original spec — do not invent new fields or
   drop existing ones).

   Revision cap: at most 3 revisions per task. If you have already issued
   3 revisions for this task, you may NOT pick SPEC_WRONG; pick the
   highest-priority remaining verdict instead.

2. [Verdict: BLIND_SPOT]
   The executor's question is well-formed at the surface but the executor
   has a SILENT ASSUMPTION (something stated or implied in its
   # Assumptions section, or visible in its code, that it did NOT ask
   about) which is wrong against the source artifacts.

   Required rubric — BLIND_SPOT applies ONLY when BOTH:
   (a) executor's # Assumptions OR its code contains an assumption that is
       NOT in the current spec, AND
   (b) the source artifacts or data contradict that assumption.

   Use R2 (named-concept check) and R5 (intermediate-evidence check) to
   detect this: BLIND_SPOT is the right verdict when R2 surfaces an
   executor-introduced misreading of a named concept, OR when R5 surfaces
   an executor assumption that its own trace contradicts and that the spec
   never made.

   Reply must surface the silent assumption explicitly and answer the
   DEEPER question, not just the literal one.

3. [Verdict: EXECUTOR_WRONG]
   The spec is correct, the source artifacts support the spec, but the
   executor's code misapplied the spec (wrong filter, wrong aggregation,
   wrong join, wrong tie-break, stale variable, etc.). Quote the spec /
   source passage the executor missed and state the correct code pattern.

4. [Verdict: NA_CONFIRMED]
   You have independently verified (using read_file and any other tool
   exposed for this task) that "Not Applicable" is the correct answer.
   State: "Attempted lookup → found X matching entries. Therefore NA
   is correct." Do NOT confirm NA based on the executor's report alone.

5. [Verdict: SPEC_DOUBT]
   (I-3) The spec is NOT contradicted by docs (so SPEC_WRONG doesn't fire)
   AND the executor's code is correct (so EXECUTOR_WRONG doesn't fire),
   BUT the spec's question-interpretation is ARGUABLE and an alternative
   reading from the spec's \`interpretations[]\` array is more plausibly
   what the task author intended.

   Required rubric — SPEC_DOUBT applies ONLY when ALL:
   (a) the spec's \`chosen_interpretation\` is one of several plausible
       readings the spec_agent surfaced;
   (b) you can articulate a CONCRETE WAY in which a different listed
       interpretation better matches the question's wording, the docs,
       OR domain convention;
   (c) the answer the executor computed under the current interpretation
       is plausible-but-not-clearly-correct (e.g., right magnitude but
       wrong sign, off by a constant factor consistent with a
       convention swap, etc.).

   Reply must include: a \`[Source: spec]\` tag, a quote of the
   currently-chosen interpretation, a quote of the alternative
   interpretation you prefer, and a one-line explanation of which
   computational step would change under the alternative. Then emit a
   \`[Revised spec]\` block: same JSON schema as the original, BUT with
   \`chosen_interpretation.id\` switched to the alternative AND the
   \`computation_plan\` rewritten to implement the alternative.

   Revision-cap rules: counts against the same 3-revision budget as
   SPEC_WRONG. Do NOT use SPEC_DOUBT to spam alternatives; use it once
   per task at most, when you have specific evidence the alternative
   reading is better.

6. [Verdict: ANSWER]
   No spec error, no executor error, no blind spot, NA does not apply,
   AND the chosen interpretation is the best of the surfaced alternatives.
   Answer the executor's literal question with grounding from the source
   artifacts.

# Reply format (STRICT)

Your reply MUST start with exactly one of:
    [Verdict: SPEC_WRONG]
    [Verdict: BLIND_SPOT]
    [Verdict: EXECUTOR_WRONG]
    [Verdict: NA_CONFIRMED]
    [Verdict: SPEC_DOUBT]
    [Verdict: ANSWER]

Replies that don't start with one of these will default to ANSWER (and
indicate a malformed reply to the audit log).

After the verdict header:
- For SPEC_WRONG or SPEC_DOUBT: include \`[Source: docs]\` / \`[Source: spec]\`
  / \`[Source: execution_trace]\`, a direct quote / observation, then a fenced
  JSON block starting with \`[Revised spec]\` containing the full revised spec.
- For all other verdicts: include the source quote / observation, then the
  concrete advice/answer.

# What you must NOT do

- Do NOT skip read_file before flagging SPEC_WRONG or EXECUTOR_WRONG.
- Do NOT revise the spec on intuition. Quote a source passage OR cite
  specific execution-trace evidence.
- Do NOT change the spec's JSON shape (keep the same top-level fields).
- Do NOT confirm NA without doing the lookup yourself.
- Do NOT produce empty replies. If you cannot help, state why explicitly.
`;

// ---------------------------------------------------------------------------
// File manifest (used in read_file tool description for both spec_agent and
// planner_agent — the LLM picks the right file from this list)
// ---------------------------------------------------------------------------

/**
 * Generate a file manifest for the planner's read_file tool description.
 *
 * Two paths:
 *   - If the docsDir looks like DABStep (contains manual.md), use the
 *     hand-written DABSTEP_FILE_MANIFEST with rich per-file descriptions.
 *   - Otherwise (Krama / LiveSQL / etc.), auto-list every file in docsDir
 *     with name + size + extension hint. Generic but accurate.
 */
function makeFileManifest(docsDir: string): string {
  // DABStep layout? Use the rich manifest.
  try {
    if (fs.existsSync(path.join(docsDir, "manual.md"))) {
      return DABSTEP_FILE_MANIFEST;
    }
  } catch { /* fall through to auto */ }
  // Auto-list mode.
  return autoListManifest(docsDir);
}

// Extensions that read_file (utf-8) cannot meaningfully return. The executor
// can still read these via run_python (pd.read_excel, pyarrow, etc.).
const BINARY_EXTENSIONS = new Set([
  ".xlsx", ".xls", ".parquet", ".pq",
  ".sqlite", ".sqlite3", ".db",
  ".gpkg", ".shp", ".dbf",
  ".npy", ".npz", ".pkl", ".pickle",
  ".zip", ".gz", ".tar", ".bz2", ".7z",
  ".png", ".jpg", ".jpeg", ".pdf",
  ".dat", ".sp3",
]);

function isBinaryExt(name: string): boolean {
  const ext = path.extname(name).toLowerCase();
  return BINARY_EXTENSIONS.has(ext);
}

// Bug 9 fix: LiveSQL executor only has run_sql (no run_python), so the
// generic "load via run_python" hint is wrong for .sqlite/.db files.
const SQLITE_EXTENSIONS = new Set([".sqlite", ".sqlite3", ".db"]);
function isSqliteExt(name: string): boolean {
  return SQLITE_EXTENSIONS.has(path.extname(name).toLowerCase());
}

function autoListManifest(docsDir: string): string {
  const lines: string[] = [`Files available via read_file(filename) in ${docsDir}:`, ""];
  try {
    const entries = fs.readdirSync(docsDir).filter(n => !n.startsWith("."));
    if (entries.length === 0) return `(empty directory: ${docsDir})`;
    for (const name of entries.sort()) {
      const fp = path.join(docsDir, name);
      try {
        const stat = fs.statSync(fp);
        if (stat.isDirectory()) {
          lines.push(`- ${name}/  (directory)`);
        } else {
          const sizeKb = Math.round(stat.size / 1024);
          // Bug 9: sqlite-family files should suggest run_sql (LiveSQL executor
          // doesn't have run_python); other binary types still suggest run_python.
          let binTag = "";
          if (isSqliteExt(name)) {
            binTag = "  [BINARY — read_file will fail; ask executor to inspect via run_sql]";
          } else if (isBinaryExt(name)) {
            binTag = "  [BINARY — read_file will fail; ask executor to load via run_python]";
          }
          lines.push(`- ${name}  (~${sizeKb} KB)${binTag}`);
        }
      } catch {
        lines.push(`- ${name}  (unreadable)`);
      }
    }
    lines.push("");
    lines.push("read_file returns plain text and cannot decode binary formats (xlsx, parquet, sqlite, geopackage, etc.) — those are flagged [BINARY] above. For those files, ask the executor in your reply to load them via run_python (e.g. `pd.read_excel(...)`) and report shape/dtypes/head to you next time.");
    return lines.join("\n");
  } catch (e: any) {
    return `(unable to list ${docsDir}: ${e.message})`;
  }
}

const DABSTEP_FILE_MANIFEST = `Files available via read_file(filename):

- manual.md (~6K tokens): Authoritative business reference. Defines
  fee-rule matching semantics (wildcard, specificity tiebreaker), the
  per-txn fee formula (fixed_amount + rate*eur_amount/10000), and ALL
  named metrics the task may reference (fraud_rate, settlement_volume,
  etc.). Read FIRST when verifying what a NAMED metric, formula, or
  convention in the question MEANS.

- fees.json (~50K tokens, ~1000 rule entries): One JSON object per fee
  rule. Schema per rule: {rule_id, card_scheme, account_type[list],
  merchant_category_code[list], is_credit, monthly_volume, intracountry,
  capture_delay, monthly_fraud_level, fixed_amount, rate}. Wildcards:
  null OR empty-list = "matches any value". When you need to enumerate
  rules matching specific filter criteria, prefer query_fees(filters)
  over scanning the file.

- merchant_data.json (~3K tokens): Per-merchant attributes used as txn
  context during rule matching: {merchant_name, account_type,
  capture_delay, mcc}. Read to look up a merchant's attributes before
  applying rules.

- payments-readme.md (~2K tokens): Column meanings and dtypes for the
  payments.csv transaction table. Read when interpreting raw txn fields
  or resolving "which column holds X?".`;

// ---------------------------------------------------------------------------
// Planner tools — read_file and query_fees
// ---------------------------------------------------------------------------

function makePlannerReadFileTool(docsDir: string) {
  return {
    name: "read_file",
    description:
      `Re-read a source document from the task's docs directory (${docsDir}).\n\n` +
      makeFileManifest(docsDir) +
      `\n\nReturns plain text, truncated to ${READ_FILE_TRUNCATE} chars. ` +
      "Call multiple times to read different files.",
    input_schema: {
      type: "object",
      required: ["filename"],
      properties: {
        filename: {
          type: "string",
          description: "File name in the docs directory. See the manifest above for what's available in this task.",
        },
      },
    },
  };
}

function makePlannerQueryFeesTool(docsDir: string) {
  return {
    name: "query_fees",
    description:
      "Programmatic lookup over fees.json with correct wildcard semantics " +
      "(null OR empty-list = matches any value). Pass a subset of rule fields " +
      "as filters; returns the list of matching rules with their rule_id. " +
      "Use this instead of scanning fees.json by eye when you need to enumerate " +
      "applicable rules for a specific transaction context.",
    input_schema: {
      type: "object",
      required: ["filters"],
      properties: {
        filters: {
          type: "object",
          description:
            "Filter dict. Any subset of: card_scheme (str), account_type (str), " +
            "merchant_category_code (int), is_credit (bool), monthly_volume (str), " +
            "intracountry (bool), capture_delay (str), monthly_fraud_level (str).",
        },
        limit: {
          type: "integer",
          description: "Max rules to return (default 50; max 1000).",
        },
      },
    },
  };
}

// EC3 mitigation: query_fees is DABStep-specific (loads fees.json). For
// LiveSQL/Krama docsDirs that don't contain fees.json, skip exposing the tool
// rather than 500ing on first call.
function hasFeesJson(docsDir: string): boolean {
  try {
    return fs.existsSync(path.join(path.resolve(docsDir), "fees.json"));
  } catch { return false; }
}

function executePlannerReadFile(filename: string, docsDir: string = CONTEXT_DIR_FOR_PLANNER): string {
  const allowedDir = path.resolve(docsDir);
  const filePath = path.resolve(allowedDir, filename);
  if (!filePath.startsWith(allowedDir + path.sep) && filePath !== allowedDir) {
    return `Error: filename '${filename}' is outside the allowed context directory.`;
  }
  if (!fs.existsSync(filePath)) {
    return `Error: file not found: ${filename}`;
  }
  if (isBinaryExt(filename)) {
    return (
      `Error: '${filename}' is a binary format (${path.extname(filename).toLowerCase()}) ` +
      `that read_file cannot decode. Ask the executor (in your reply) to load it via ` +
      `run_python — e.g. \`df = pd.read_excel("${filename}"); print(df.shape, df.dtypes)\` ` +
      `— and report shape/dtypes/head to you next time.`
    );
  }
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    if (raw.length > READ_FILE_TRUNCATE) {
      return raw.slice(0, READ_FILE_TRUNCATE) + `\n\n[truncated at ${READ_FILE_TRUNCATE} chars]`;
    }
    return raw;
  } catch (e: any) {
    return `Error reading ${filename}: ${e.message}`;
  }
}

// query_fees: lazy-load fees.json once per process and cache.
let _feesCache: any[] | null = null;
function loadFees(docsDir: string): any[] {
  if (_feesCache) return _feesCache;
  const feesPath = path.join(path.resolve(docsDir), "fees.json");
  if (!fs.existsSync(feesPath)) {
    throw new Error(`fees.json not found at ${feesPath}`);
  }
  const raw = fs.readFileSync(feesPath, "utf-8");
  _feesCache = JSON.parse(raw);
  return _feesCache!;
}

/**
 * Apply wildcard-aware matching for a single rule field.
 * - null / undefined → wildcard (always matches)
 * - empty list → wildcard (always matches)
 * - list → query value must be in the list
 * - scalar → query value must equal it
 */
function ruleFieldMatches(ruleVal: any, queryVal: any): boolean {
  if (ruleVal === null || ruleVal === undefined) return true;
  if (Array.isArray(ruleVal)) {
    if (ruleVal.length === 0) return true;
    return ruleVal.includes(queryVal);
  }
  return ruleVal === queryVal;
}

function executePlannerQueryFees(filters: any, limit: number = 50, docsDir: string = CONTEXT_DIR_FOR_PLANNER): string {
  let fees: any[];
  try {
    fees = loadFees(docsDir);
  } catch (e: any) {
    return `Error loading fees.json: ${e.message}`;
  }
  const safeLimit = Math.max(1, Math.min(1000, limit ?? 50));
  const filterEntries = Object.entries(filters || {});
  const matches: any[] = [];
  for (const rule of fees) {
    let ok = true;
    for (const [key, queryVal] of filterEntries) {
      if (!ruleFieldMatches(rule[key], queryVal)) {
        ok = false;
        break;
      }
    }
    if (ok) {
      matches.push(rule);
      if (matches.length >= safeLimit) break;
    }
  }
  return JSON.stringify({
    matched_count: matches.length,
    total_rules_searched: fees.length,
    limit_applied: safeLimit,
    rules: matches,
  }, null, 2);
}

// ---------------------------------------------------------------------------
// Spec versioning helpers
// ---------------------------------------------------------------------------

function readCurrentSpec(specPath: string): string {
  if (!fs.existsSync(specPath)) return `(no spec file found at ${specPath})`;
  try {
    return fs.readFileSync(specPath, "utf-8");
  } catch (e: any) {
    return `(spec read error: ${e.message})`;
  }
}

function getRevisionCount(specPath: string): number {
  // Count <task_id>.rev<N>.json files alongside <task_id>.json
  const dir = path.dirname(specPath);
  const base = path.basename(specPath, ".json");
  if (!fs.existsSync(dir)) return 0;
  const files = fs.readdirSync(dir);
  const re = new RegExp(`^${base.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.rev(\\d+)\\.json$`);
  let max = 0;
  for (const f of files) {
    const m = f.match(re);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return max;
}

function persistRevision(
  specPath: string,
  revisedSpecJson: string,
  verdict: string,
  evidenceSource: string,
): { revNum: number; revPath: string } {
  const dir = path.dirname(specPath);
  const base = path.basename(specPath, ".json");
  const revNum = getRevisionCount(specPath) + 1;
  const revPath = path.join(dir, `${base}.rev${revNum}.json`);
  fs.writeFileSync(revPath, revisedSpecJson);
  fs.writeFileSync(specPath, revisedSpecJson);
  const logPath = path.join(dir, `${base}.revisions.jsonl`);
  const logRow = JSON.stringify({
    rev: revNum,
    verdict,
    evidence_source: evidenceSource,
    timestamp: new Date().toISOString(),
    rev_path: path.basename(revPath),
  }) + "\n";
  fs.appendFileSync(logPath, logRow);
  return { revNum, revPath };
}

// ---------------------------------------------------------------------------
// Planner session helpers — cumulative per task, separate from spec_agent's
// extraction session.
// ---------------------------------------------------------------------------

interface AnthropicPlannerSession {
  provider: "anthropic";
  model: string;
  system: string;
  messages: any[];
  metadata: { last_log_line: number; revisions_emitted: number };
}
interface OpenRouterPlannerSession {
  provider: "openrouter";
  model: string;
  system: string;
  messages: any[];
  metadata: { last_log_line: number; revisions_emitted: number };
}
type PlannerSession = AnthropicPlannerSession | OpenRouterPlannerSession;

function loadOrCreatePlannerSession(
  sessionPath: string,
  provider: "anthropic" | "openrouter",
  model: string,
  system: string,
  specPath: string,
): PlannerSession {
  if (fs.existsSync(sessionPath)) {
    try {
      const obj = JSON.parse(fs.readFileSync(sessionPath, "utf-8"));
      if (obj && obj.provider === provider && obj.model === model) {
        // Defensive: ensure metadata field exists for older session files.
        if (!obj.metadata) obj.metadata = { last_log_line: 0, revisions_emitted: 0 };
        // EC2 mitigation: keep counter in sync with disk if rev{N}.json files
        // outnumber what the session thinks (can happen on resume / out-of-band edits).
        const onDisk = getRevisionCount(specPath);
        if (onDisk > obj.metadata.revisions_emitted) obj.metadata.revisions_emitted = onDisk;
        return obj as PlannerSession;
      }
    } catch { /* fall through to fresh */ }
  }
  // EC2 mitigation: when no session exists but rev{N}.json files DO (resume
  // scenario), initialise the counter from disk so the cap is respected.
  const initialRevs = getRevisionCount(specPath);
  return {
    provider,
    model,
    system,
    messages: [],
    metadata: { last_log_line: 0, revisions_emitted: initialRevs },
  } as PlannerSession;
}

function saveSession(sessionPath: string, session: PlannerSession): void {
  try {
    fs.writeFileSync(sessionPath, JSON.stringify(session, null, 2));
  } catch { /* best-effort */ }
}

// ---------------------------------------------------------------------------
// Trace delta — ship only NEW executor events to the planner. Tracked via
// `metadata.last_log_line` in the planner session.
// ---------------------------------------------------------------------------

function summariseEventsFrom(logPath: string, fromLine: number, max: number): { text: string; newLastLine: number } {
  if (!fs.existsSync(logPath)) return { text: "(no session log available yet)", newLastLine: fromLine };
  const lines = fs.readFileSync(logPath, "utf-8").split("\n").filter(Boolean);
  const newLastLine = lines.length;
  const slice = lines.slice(fromLine);
  // If too many new events, take only the most recent `max`.
  const recent = slice.length > max ? slice.slice(-max) : slice;
  const parts: string[] = [];
  if (slice.length > max) {
    parts.push(`[omitted ${slice.length - max} earlier events; showing last ${max}]`);
  }
  for (const line of recent) {
    try {
      const evt = JSON.parse(line);
      const t = evt.type;
      if (t === "user_message") continue;
      if (t === "assistant_thinking") {
        parts.push(`[thinking]\n${String(evt.content || "").slice(0, 1500)}`);
      } else if (t === "assistant_response") {
        parts.push(`[response]\n${String(evt.content || "").slice(0, 1000)}`);
      } else if (t === "tool_call") {
        const code = (evt.toolArgs && (evt.toolArgs.code || evt.toolArgs.sql))
          ? String(evt.toolArgs.code || evt.toolArgs.sql).slice(0, 1200)
          : "";
        parts.push(`[tool_call ${evt.toolName}]\n${code}`);
      } else if (t === "tool_call_result") {
        parts.push(`[tool_result]\n${String(evt.content || "").slice(0, 1500)}`);
      }
    } catch { /* skip malformed */ }
  }
  return { text: parts.join("\n\n") || "(no parseable new events)", newLastLine };
}

// ---------------------------------------------------------------------------
// User message + prior-action summary
// ---------------------------------------------------------------------------

function buildPlannerUserMessage(args: {
  taskQuestion: string;
  currentSpec: string;
  newEvents: string;
  question: string;
  revisionsSoFar: number;
  isFirstCall: boolean;
  priorActionSummary?: string;
}): string {
  const revisionBanner = args.revisionsSoFar >= MAX_SPEC_REVISIONS
    ? `# REVISION CAP REACHED\nYou have already issued ${args.revisionsSoFar} spec revisions for this task. You may NOT pick [Verdict: SPEC_WRONG] or [Verdict: SPEC_DOUBT]. Pick the highest-priority remaining verdict (BLIND_SPOT > EXECUTOR_WRONG > NA_CONFIRMED > ANSWER).\n`
    : `# Revisions used so far for this task: ${args.revisionsSoFar} of ${MAX_SPEC_REVISIONS} (SPEC_WRONG and SPEC_DOUBT both count against this cap)\n`;

  const priorSummary = args.isFirstCall
    ? "(this is the first escalation for this task)"
    : (args.priorActionSummary || "(executor returned without further info on your last reply)");

  return [
    "# Task question",
    args.taskQuestion,
    "",
    "# Current spec (latest version — overwritten on each SPEC_WRONG revision)",
    "```json",
    args.currentSpec,
    "```",
    "",
    revisionBanner,
    "# Since your last reply",
    priorSummary,
    "",
    "# Executor trace events (NEW since your last reply)",
    args.newEvents,
    "",
    "# Executor's structured summary and question (verbatim)",
    args.question,
    "",
    "Run the 5-verdict cascade in order. First match wins. Your reply MUST",
    "start with exactly one [Verdict: X] header. For SPEC_WRONG or",
    "EXECUTOR_WRONG you MUST first call read_file at least once.",
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Verdict parser
// ---------------------------------------------------------------------------

const VERDICT_NAMES = ["SPEC_WRONG", "BLIND_SPOT", "EXECUTOR_WRONG", "NA_CONFIRMED", "SPEC_DOUBT", "ANSWER"] as const;
type VerdictName = typeof VERDICT_NAMES[number];

interface ParsedReply {
  verdict: VerdictName;
  verdictWasMalformed: boolean;
  revisedSpec?: string;
  evidenceSource?: string;
}

function parseVerdict(reply: string): ParsedReply {
  const trimmed = reply.trim();
  let verdict: VerdictName = "ANSWER";
  let malformed = true;
  for (const name of VERDICT_NAMES) {
    const tag = `[Verdict: ${name}]`;
    if (trimmed.startsWith(tag) || trimmed.includes(tag)) {
      verdict = name;
      malformed = !trimmed.startsWith(tag);
      break;
    }
  }
  let revisedSpec: string | undefined;
  let evidenceSource: string | undefined;
  // SPEC_WRONG and SPEC_DOUBT both emit a [Revised spec] block + [Source: ...]
  if (verdict === "SPEC_WRONG" || verdict === "SPEC_DOUBT") {
    // Extract [Source: docs] / [Source: execution_trace] / [Source: spec]
    const srcMatch = reply.match(/\[Source:\s*(docs|execution_trace|spec)\]/i);
    if (srcMatch) evidenceSource = srcMatch[1].toLowerCase();

    // Extract the `[Revised spec]` block. Accept either:
    //   [Revised spec]\n```json\n{...}\n```
    //   [Revised spec]\n{...}
    const revIdx = reply.indexOf("[Revised spec]");
    if (revIdx !== -1) {
      const afterTag = reply.slice(revIdx + "[Revised spec]".length);
      const fenceMatch = afterTag.match(/```(?:json)?\s*\n([\s\S]*?)```/);
      if (fenceMatch) {
        revisedSpec = fenceMatch[1].trim();
      } else {
        // Greedy: take everything starting from first { up to last }
        const firstBrace = afterTag.indexOf("{");
        const lastBrace = afterTag.lastIndexOf("}");
        if (firstBrace !== -1 && lastBrace > firstBrace) {
          revisedSpec = afterTag.slice(firstBrace, lastBrace + 1).trim();
        }
      }
    }
  }
  return { verdict, verdictWasMalformed: malformed, revisedSpec, evidenceSource };
}

// Required-field lists keyed by spec flavour. Sources of truth:
//   DABStep — scripts/extract_specs.py save_spec input_schema.required
//   Krama   — scripts/extract_specs_krama.py:59-63
//   LiveSQL — scripts/extract_specs_livesql.py:33-43
const REQUIRED_DABSTEP = [
  "question_summary", "answer_type", "merchant", "date_filter",
  "applicable_card_schemes", "matching_logic", "computation_plan", "expected_output_format",
];
const REQUIRED_KRAMA = [
  "question_summary", "answer_type",
  // I-1 question-restating gate fields (Krama spec_agent must surface 2-4 readings)
  "interpretations", "chosen_interpretation",
  "data_sources_to_use", "key_functionalities",
  "computation_plan", "expected_output_format",
];
const REQUIRED_LIVESQL = [
  "question_summary", "tables_needed", "join_path", "json_columns",
  "kb_formulas", "cte_plan", "output_columns", "output_ordering",
  "expected_output_format",
];

/**
 * Inspect the CURRENT spec text to determine which schema family it belongs to,
 * and return the matching required-field list. Bug 3 fix: prior implementation
 * hardcoded DABStep, so Krama/LiveSQL revisions were always rejected.
 */
function requiredFieldsForSpec(currentSpecText: string): string[] {
  try {
    const obj = JSON.parse(currentSpecText);
    if (obj && typeof obj === "object") {
      if ("cte_plan" in obj || "tables_needed" in obj || "kb_formulas" in obj) {
        return REQUIRED_LIVESQL;
      }
      if ("key_functionalities" in obj) {
        return REQUIRED_KRAMA;
      }
      // No recognised markers — fall through to DABStep but warn if the spec
      // also lacks DABStep's own markers (truly unknown shape).
      if (!("merchant" in obj) && !("date_filter" in obj) && !("matching_logic" in obj)) {
        console.warn("[ask_planner] requiredFieldsForSpec default-DABStep fired on spec with no recognised markers; revision validation may reject valid specs.");
      }
    }
  } catch { /* fall through to DABStep default */ }
  return REQUIRED_DABSTEP;
}

function validateRevisedSpec(revisedJson: string, required: string[]): { ok: boolean; reason?: string; pretty?: string } {
  try {
    const obj = JSON.parse(revisedJson);
    for (const k of required) {
      if (!(k in obj)) return { ok: false, reason: `missing required field '${k}'` };
    }
    return { ok: true, pretty: JSON.stringify(obj, null, 2) };
  } catch (e: any) {
    return { ok: false, reason: `JSON parse error: ${e.message}` };
  }
}

function summarisePriorAssistant(lastAssistantContent: any): string {
  if (!lastAssistantContent) return "(no prior reply)";
  let text = "";
  if (typeof lastAssistantContent === "string") {
    text = lastAssistantContent;
  } else if (Array.isArray(lastAssistantContent)) {
    text = lastAssistantContent.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n");
  }
  // Pull the [Verdict: X] header + first line after it.
  const m = text.match(/\[Verdict:\s*(\w+)\]/);
  const head = m ? `Last verdict: ${m[1]}` : "Last verdict: (unrecognised)";
  const firstLine = text.split("\n").slice(0, 3).join(" ").slice(0, 240);
  return `${head}. Excerpt: ${firstLine}...`;
}

// ---------------------------------------------------------------------------
// API call wrappers — Anthropic and OpenRouter, both now exposing read_file
// AND query_fees to the planner.
// ---------------------------------------------------------------------------

async function callPlannerAnthropic(args: {
  model: string;
  system: string;
  messages: any[];
  max_tokens: number;
  maxToolTurns?: number;
  docsDir?: string;
}): Promise<{ text: string; finalMessages: any[]; usage: { input: number; output: number } }> {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("ANTHROPIC_API_KEY not set");
  const maxToolTurns = args.maxToolTurns ?? PLANNER_MAX_TOOL_TURNS;
  let messages = [...args.messages];
  const usage = { input: 0, output: 0 };

  const docsDir = args.docsDir ?? CONTEXT_DIR_FOR_PLANNER;
  // EC3: only expose query_fees when the docs dir actually has fees.json.
  const plannerTools: any[] = [makePlannerReadFileTool(docsDir)];
  if (hasFeesJson(docsDir)) plannerTools.push(makePlannerQueryFeesTool(docsDir));

  for (let turn = 0; turn <= maxToolTurns; turn++) {
    const body: any = {
      model: args.model,
      max_tokens: args.max_tokens,
      system: args.system,
      tools: plannerTools,
      messages,
    };
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Anthropic ${res.status}: ${errText.slice(0, 500)}`);
    }
    const data = await res.json() as any;
    if (data?.usage) {
      usage.input += (data.usage.input_tokens ?? 0)
        + (data.usage.cache_read_input_tokens ?? 0)
        + (data.usage.cache_creation_input_tokens ?? 0);
      usage.output += data.usage.output_tokens ?? 0;
    }
    const blocks: any[] = data.content || [];
    const toolUses = blocks.filter((b: any) => b.type === "tool_use");
    messages.push({ role: "assistant", content: blocks });

    if (toolUses.length === 0) {
      const text = blocks.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n");
      return { text, finalMessages: messages, usage };
    }

    const toolResultBlocks: any[] = [];
    for (const tu of toolUses) {
      let result: string;
      if (tu.name === "read_file") {
        result = executePlannerReadFile(String((tu.input && tu.input.filename) || ""), docsDir);
      } else if (tu.name === "query_fees") {
        result = executePlannerQueryFees(
          (tu.input && tu.input.filters) || {},
          (tu.input && tu.input.limit) ?? 50,
          docsDir,
        );
      } else {
        result = `Error: unsupported tool '${tu.name}'. Available: read_file, query_fees.`;
      }
      toolResultBlocks.push({ type: "tool_result", tool_use_id: tu.id, content: result });
    }
    messages.push({ role: "user", content: toolResultBlocks });
  }

  const lastAssistant = messages.slice().reverse().find(m => m.role === "assistant");
  const lastText = lastAssistant && Array.isArray(lastAssistant.content)
    ? lastAssistant.content.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n")
    : "";
  return {
    text: (lastText ? lastText + "\n\n" : "")
      + `[planner hit tool-turn cap of ${maxToolTurns}; returning partial reply]`,
    finalMessages: messages,
    usage,
  };
}

async function callPlannerOpenRouter(args: {
  model: string;
  system: string;
  messages: any[];
  max_tokens: number;
  maxToolTurns?: number;
  docsDir?: string;
}): Promise<{ text: string; finalMessages: any[]; usage: { input: number; output: number } }> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) throw new Error("OPENROUTER_API_KEY not set");
  const maxToolTurns = args.maxToolTurns ?? PLANNER_MAX_TOOL_TURNS;
  const docsDir = args.docsDir ?? CONTEXT_DIR_FOR_PLANNER;
  const usage = { input: 0, output: 0 };

  // OpenRouter uses OpenAI-style tool schema. Convert our planner tools.
  // EC3: gate query_fees on the docs dir containing fees.json.
  const orTools: any[] = [
    {
      type: "function",
      function: {
        name: "read_file",
        description: makePlannerReadFileTool(docsDir).description,
        parameters: makePlannerReadFileTool(docsDir).input_schema,
      },
    },
  ];
  if (hasFeesJson(docsDir)) {
    orTools.push({
      type: "function",
      function: {
        name: "query_fees",
        description: makePlannerQueryFeesTool(docsDir).description,
        parameters: makePlannerQueryFeesTool(docsDir).input_schema,
      },
    });
  }

  // OpenRouter expects {role: "system", content} first.
  let openaiMessages: any[] = [
    { role: "system", content: args.system },
    ...args.messages,
  ];

  for (let turn = 0; turn <= maxToolTurns; turn++) {
    const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "authorization": `Bearer ${key}`,
      },
      body: JSON.stringify({
        model: args.model,
        max_tokens: args.max_tokens,
        messages: openaiMessages,
        tools: orTools,
      }),
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`OpenRouter ${res.status}: ${errText.slice(0, 500)}`);
    }
    const data = await res.json() as any;
    if (data?.usage) {
      usage.input += data.usage.prompt_tokens ?? 0;
      usage.output += data.usage.completion_tokens ?? 0;
    }
    const msg = data.choices?.[0]?.message;
    if (!msg) throw new Error("OpenRouter: no message in response");

    openaiMessages.push(msg);

    const toolCalls: any[] = msg.tool_calls || [];
    if (toolCalls.length === 0) {
      const text = msg.content ?? "(no content)";
      // Strip the leading system message back out before returning to caller.
      const finalMessages = openaiMessages.slice(1);
      return { text, finalMessages, usage };
    }
    for (const tc of toolCalls) {
      const fname = tc.function?.name;
      let fargs: any = {};
      try { fargs = JSON.parse(tc.function?.arguments || "{}"); } catch { /* leave empty */ }
      let result: string;
      if (fname === "read_file") {
        result = executePlannerReadFile(String(fargs.filename || ""), docsDir);
      } else if (fname === "query_fees") {
        result = executePlannerQueryFees(fargs.filters || {}, fargs.limit ?? 50, docsDir);
      } else {
        result = `Error: unsupported tool '${fname}'.`;
      }
      openaiMessages.push({
        role: "tool",
        tool_call_id: tc.id,
        content: result,
      });
    }
  }

  // Hit the cap.
  const lastMsg = openaiMessages.slice().reverse().find((m: any) => m.role === "assistant");
  const lastText = lastMsg?.content ?? "";
  const finalMessages = openaiMessages.slice(1);
  return {
    text: (lastText ? lastText + "\n\n" : "")
      + `[planner hit tool-turn cap of ${maxToolTurns}; returning partial reply]`,
    finalMessages,
    usage,
  };
}

// ---------------------------------------------------------------------------
// Public config + factory
// ---------------------------------------------------------------------------

export interface AskPlannerConfig {
  /** Original task question (just the question, no spec). */
  taskQuestion: string;
  /** Absolute path to the task's CURRENT spec JSON (results/<arm>/specs/<task_id>.json).
   *  This file may be overwritten by planner revisions. */
  specPath: string;
  /** Absolute path to the executor's session JSONL log. Used to gather NEW trace events for the planner. */
  sessionLogPath: string;
  /** Planner provider + model. */
  planner: { provider: "anthropic" | "openrouter"; model: string };
  /** How many of the executor's most recent NEW events to send per call. Default 10. */
  recentEventCount?: number;
  /** Directory the planner's read_file tool is restricted to. Defaults to data/context/ (DABStep). */
  docsDir?: string;
  /** Optional Langfuse tracer for planner LLM calls (same trace as executor). */
  langfuseTracer?: import("../services/langfuse_tracer.js").LangfuseTaskTracer;
}

function makeTool(toolName: string, cfg: AskPlannerConfig): ToolDefinition {
  const recentN = cfg.recentEventCount ?? DEFAULT_RECENT_EVENTS;
  // Planner session lives next to the spec file.
  const dir = path.dirname(cfg.specPath);
  const base = path.basename(cfg.specPath, ".json");
  const plannerSessionPath = path.join(dir, `${base}.planner_session.json`);

  return {
    name: toolName,
    label: "Ask Planner Agent",
    description: (
      "Escalate to the PLANNER AGENT for a structured diagnosis. The planner " +
      "has read access to source documents (read_file) and any task-specific " +
      "lookup tools when registered. It will reply with one of five verdicts: " +
      "SPEC_WRONG (revised spec attached) / BLIND_SPOT (you asked the wrong " +
      "question; here's the real one) / EXECUTOR_WRONG (your code misapplied " +
      "the spec) / NA_CONFIRMED (Not Applicable is correct) / ANSWER " +
      "(no error; here's the doc-grounded answer). " +
      "Send a STRUCTURED SUMMARY using these headers verbatim: " +
      "`# Step` / `# Computed so far` / `# Pseudo-code` / `# Assumptions` / `# Question`."
    ),
    parameters: Type.Object({
      question: Type.String({
        description: "Your structured summary (5 headers) + the question.",
      }),
    }),
    execute: async (_toolCallId: string, params: any): Promise<AgentToolResult<unknown>> => {
      const question = String(params.question ?? "").trim();
      if (!question) {
        return { content: [{ type: "text", text: "Error: empty question to planner." }], details: {} };
      }

      // Per-task planner cost sidecar: written next to the executor session log
      // (unique per task+trial out dir) so run.ts can attribute planner-role
      // (Opus) tokens separately from executor (e.g. Kimi) tokens.
      const plannerCostPath = path.join(path.dirname(cfg.sessionLogPath), "planner_cost.json");
      const accumPlannerCost = (u: { input: number; output: number }) => {
        let acc = { model: cfg.planner.model, input_tokens: 0, output_tokens: 0, calls: 0 };
        try { if (fs.existsSync(plannerCostPath)) acc = JSON.parse(fs.readFileSync(plannerCostPath, "utf-8")); } catch {}
        acc.model = cfg.planner.model;
        acc.input_tokens += u.input;
        acc.output_tokens += u.output;
        acc.calls += 1;
        try { fs.writeFileSync(plannerCostPath, JSON.stringify(acc)); } catch {}
      };

      const currentSpec = readCurrentSpec(cfg.specPath);
      const session = loadOrCreatePlannerSession(
        plannerSessionPath,
        cfg.planner.provider,
        cfg.planner.model,
        PLANNER_AGENT_SYSTEM_PROMPT,
        cfg.specPath,
      );
      const isFirstCall = session.messages.length === 0;
      const { text: newEvents, newLastLine } = summariseEventsFrom(
        cfg.sessionLogPath,
        session.metadata.last_log_line,
        recentN,
      );

      // Summarise the planner's last assistant reply (for "since your last reply").
      let priorActionSummary: string | undefined;
      if (!isFirstCall) {
        const lastAssistantMsg = session.messages.slice().reverse().find((m: any) => m.role === "assistant");
        if (lastAssistantMsg) priorActionSummary = summarisePriorAssistant(lastAssistantMsg.content);
      }

      const userMessage = buildPlannerUserMessage({
        taskQuestion: cfg.taskQuestion,
        currentSpec,
        newEvents,
        question,
        revisionsSoFar: session.metadata.revisions_emitted,
        isFirstCall,
        priorActionSummary,
      });

      const messagesForCall = [...session.messages, { role: "user", content: userMessage }];

      try {
        const start = Date.now();
        let reply: string;
        let finalMessages: any[];

        if (cfg.planner.provider === "anthropic") {
          const r = await callPlannerAnthropic({
            model: cfg.planner.model,
            system: session.system,
            messages: messagesForCall,
            max_tokens: PLANNER_MAX_TOKENS,
            docsDir: cfg.docsDir,
          });
          reply = r.text;
          finalMessages = r.finalMessages;
          accumPlannerCost(r.usage);
          cfg.langfuseTracer?.logPlannerGeneration({
            model: cfg.planner.model,
            provider: cfg.planner.provider,
            inputTokens: r.usage.input,
            outputTokens: r.usage.output,
            latencyMs: Date.now() - start,
            inputPreview: userMessage,
            outputPreview: reply,
          });
        } else {
          const r = await callPlannerOpenRouter({
            model: cfg.planner.model,
            system: session.system,
            messages: messagesForCall,
            max_tokens: PLANNER_MAX_TOKENS,
            docsDir: cfg.docsDir,
          });
          reply = r.text;
          finalMessages = r.finalMessages;
          accumPlannerCost(r.usage);
          cfg.langfuseTracer?.logPlannerGeneration({
            model: cfg.planner.model,
            provider: cfg.planner.provider,
            inputTokens: r.usage.input,
            outputTokens: r.usage.output,
            latencyMs: Date.now() - start,
            inputPreview: userMessage,
            outputPreview: reply,
          });
        }

        // EC4 mitigation: if the verdict header is malformed, retry exactly ONCE
        // with an explicit instruction. Caps cost; still surfaces the failure to
        // the audit footer.
        let parsed = parseVerdict(reply);
        let retryFiredAndFixed = false;
        let retryFiredAndStillMalformed = false;
        if (parsed.verdictWasMalformed) {
          const retryNudge =
            "Your previous reply did not start with the required [Verdict: X] header. " +
            "Re-send your reply NOW, beginning with EXACTLY one of: " +
            "[Verdict: SPEC_WRONG], [Verdict: BLIND_SPOT], [Verdict: EXECUTOR_WRONG], " +
            "[Verdict: NA_CONFIRMED], [Verdict: ANSWER]. " +
            "Keep all the substantive content from your previous reply.";
          const retryMessages = [...finalMessages, { role: "user", content: retryNudge }];
          try {
            if (cfg.planner.provider === "anthropic") {
              const r2 = await callPlannerAnthropic({
                model: cfg.planner.model,
                system: session.system,
                messages: retryMessages,
                max_tokens: PLANNER_MAX_TOKENS,
                docsDir: cfg.docsDir,
              });
              reply = r2.text;
              finalMessages = r2.finalMessages;
              accumPlannerCost(r2.usage);
            } else {
              const r2 = await callPlannerOpenRouter({
                model: cfg.planner.model,
                system: session.system,
                messages: retryMessages,
                max_tokens: PLANNER_MAX_TOKENS,
                docsDir: cfg.docsDir,
              });
              reply = r2.text;
              finalMessages = r2.finalMessages;
              accumPlannerCost(r2.usage);
            }
            const parsed2 = parseVerdict(reply);
            if (parsed2.verdictWasMalformed) {
              retryFiredAndStillMalformed = true;
            } else {
              retryFiredAndFixed = true;
            }
            parsed = parsed2;
          } catch (retryErr: any) {
            // If the retry call itself fails, keep the original parsed and surface error in footer.
            retryFiredAndStillMalformed = true;
          }
        }

        const elapsedMs = Date.now() - start;

        // Enforce revision cap: SPEC_WRONG and SPEC_DOUBT (I-3) both consume the
        // same 3-revision budget — both emit a [Revised spec] block that we
        // persist as a new revision file and adopt as the current spec.
        let revisionInfo: { revNum: number; revPath: string } | undefined;
        let revisionRejected = false;
        let revisionRejectionReason = "";
        if (parsed.verdict === "SPEC_WRONG" || parsed.verdict === "SPEC_DOUBT") {
          if (session.metadata.revisions_emitted >= MAX_SPEC_REVISIONS) {
            revisionRejected = true;
            revisionRejectionReason = `revision cap (${MAX_SPEC_REVISIONS}) reached`;
          } else if (!parsed.revisedSpec) {
            revisionRejected = true;
            revisionRejectionReason = "no [Revised spec] block found in reply";
          } else {
            // Bug 3 fix: pick required-field list based on the CURRENT spec's flavour.
            const requiredFields = requiredFieldsForSpec(currentSpec);
            const valid = validateRevisedSpec(parsed.revisedSpec, requiredFields);
            if (!valid.ok) {
              revisionRejected = true;
              revisionRejectionReason = `revised spec failed validation: ${valid.reason}`;
            } else {
              revisionInfo = persistRevision(
                cfg.specPath,
                valid.pretty!,
                parsed.verdict,
                parsed.evidenceSource ?? "unspecified",
              );
              session.metadata.revisions_emitted = revisionInfo.revNum;
            }
          }
        }

        // Persist the updated planner session.
        session.messages = finalMessages;
        session.metadata.last_log_line = newLastLine;
        saveSession(plannerSessionPath, session);

        // Build the reply returned to the executor.
        const footerParts: string[] = [];
        footerParts.push(`[planner: ${cfg.planner.provider}:${cfg.planner.model}, ${elapsedMs}ms, verdict=${parsed.verdict}]`);
        if (retryFiredAndFixed) footerParts.push("[verdict retry: original reply was malformed; corrected on retry]");
        if (retryFiredAndStillMalformed) footerParts.push("[verdict retry: still malformed after 1 retry; defaulted to ANSWER]");
        if (parsed.verdictWasMalformed && !retryFiredAndFixed && !retryFiredAndStillMalformed) {
          footerParts.push("[note: verdict header was malformed; defaulted to ANSWER]");
        }
        if (revisionInfo) footerParts.push(`[spec revision rev${revisionInfo.revNum} persisted; ${cfg.specPath} updated]`);
        if (revisionRejected) footerParts.push(`[SPEC_WRONG verdict but revision rejected: ${revisionRejectionReason}]`);

        return {
          content: [{ type: "text", text: reply.trim() + "\n\n" + footerParts.join("\n") }],
          details: {
            planner: cfg.planner,
            elapsedMs,
            verdict: parsed.verdict,
            verdictMalformed: parsed.verdictWasMalformed,
            verdictRetryFired: retryFiredAndFixed || retryFiredAndStillMalformed,
            verdictRetryFixed: retryFiredAndFixed,
            revisionPersisted: !!revisionInfo,
            revisionRejected,
            revisionRejectionReason: revisionRejected ? revisionRejectionReason : undefined,
            revisionsSoFar: session.metadata.revisions_emitted,
          },
        };
      } catch (e: any) {
        const msg = e?.message || String(e);
        return {
          content: [{ type: "text", text: `Planner error: ${msg}\nProceed with your best judgment.` }],
          details: { error: msg },
        };
      }
    },
  };
}

/**
 * Canonical name for the tool. Use this in new code.
 */
export function makeAskPlannerAgentTool(cfg: AskPlannerConfig): ToolDefinition {
  return makeTool("ask_planner_agent", cfg);
}

/**
 * Backward-compat alias. Old configs/prompts that still say `ask_spec_agent`
 * keep working — same implementation, same semantics. Will be removed once
 * all configs are migrated.
 */
export function makeAskPlannerTool(cfg: AskPlannerConfig): ToolDefinition {
  return makeTool("ask_spec_agent", cfg);
}
