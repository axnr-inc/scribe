/**
 * Render a spec JSON as a markdown-structured block for executor consumption.
 *
 * This is a direct TypeScript port of `render_spec_for_prompt()` in
 * `scripts/build_dataset.py`, which was used in the pre-P2 pipeline and
 * shown empirically to keep the executor anchored on the spec (the literal
 * "trust these facts, do not re-derive" header).
 *
 * Used by:
 *   - run.ts: render the initial spec into the executor's user message.
 *   - read_current_spec.ts: render whatever's currently on disk so the
 *     executor sees the SAME shape both upfront and on refresh.
 *
 * Why not just send raw JSON: smoke testing showed the executor treated raw
 * JSON as background context and re-derived plan steps from scratch, which
 * cost ~3 passes vs ~4 passes on a 5-task pilot. The rendered version anchors
 * attention.
 */

interface SpecLike {
  question_summary?: string;
  answer_type?: string;
  // DABStep fields
  merchant?: {
    name?: string;
    account_type?: string | null;
    merchant_category_code?: number | null;
    capture_delay?: string | null;
    acquirers?: string[];
    notes?: string;
  } | null;
  date_filter?: {
    kind?: string;
    year?: number;
    month?: number | null;
    day_of_year?: number | null;
    iso_date?: string | null;
    month_name?: string | null;
  } | null;
  applicable_card_schemes?: string[];
  matching_logic?: {
    convention?: string;
    fields_to_match?: string[];
    derived_fields?: string[];
  } | null;
  // Krama-specific fields
  data_sources_to_use?: string[];
  key_functionalities?: string[];
  // LiveSQL-specific fields (see scripts/extract_specs_livesql.py:33-43 for the
  // canonical save_spec schema)
  tables_needed?: string[];
  join_path?: Array<{ from_col?: string; to_col?: string; join_type?: string }>;
  json_columns?: Array<{ table?: string; column?: string; path?: string; alias?: string; cast?: string }>;
  kb_formulas?: Array<{
    name?: string;
    kb_id?: number | string;
    sql_expression?: string;
    depends_on?: string[];
    threshold?: string;
    notes?: string;
  }>;
  cte_plan?: string[] | Array<{
    name?: string;
    computes?: string;
    sql_sketch?: string;
    group_by?: string;
    agg_note?: string;
  }>;
  output_columns?: string[];
  output_ordering?: string;
  edge_cases?: string[];
  // Shared
  computation_plan?: string[];
  expected_output_format?: string;
  notes_for_executor?: string;
  _error?: string;
  [k: string]: unknown;
}

function renderKramaSpec(s: SpecLike): string {
  const lines: string[] = [
    "## Pipeline plan (from a planning step — trust these facts, do not re-derive)",
    "",
    `**Question summary**: ${s.question_summary ?? ""}`,
    `**Answer type**: ${s.answer_type ?? ""}`,
    "",
    "**Data sources to use:**",
  ];
  for (const f of s.data_sources_to_use ?? []) lines.push(`- ${f}`);
  if ((s.data_sources_to_use ?? []).length === 0) lines.push("- (none flagged)");

  lines.push("", "**Key functionalities** (rubric — any correct pipeline must do these):");
  (s.key_functionalities ?? []).forEach((kf, i) => lines.push(`  ${i + 1}. ${kf}`));
  if ((s.key_functionalities ?? []).length === 0) lines.push("  (none specified)");

  lines.push("", "**Computation plan** (concrete pandas steps to implement):");
  (s.computation_plan ?? []).forEach((step, i) => lines.push(`  ${i + 1}. ${step}`));

  lines.push("", `**Expected output format**: ${s.expected_output_format ?? ""}`);
  if (s.notes_for_executor) lines.push("", `**Notes**: ${s.notes_for_executor}`);
  return lines.join("\n");
}

function renderDabstepSpec(s: SpecLike): string {
  const m = s.merchant || {};
  const d = s.date_filter || {};
  const ml = s.matching_logic || {};

  const lines: string[] = [
    "## Rule-extraction summary (from a planning step — trust these facts, do not re-derive)",
    "",
    `**Question summary**: ${s.question_summary ?? ""}`,
    `**Answer type**: ${s.answer_type ?? ""}`,
    "",
    "**Merchant facts:**",
    `- name: ${m.name ?? null}`,
    `- account_type: ${m.account_type ?? null}`,
    `- merchant_category_code: ${m.merchant_category_code ?? null}`,
    `- capture_delay: ${m.capture_delay ?? null}`,
    `- acquirers: ${JSON.stringify(m.acquirers ?? [])}`,
  ];
  if (m.notes) lines.push(`- notes: ${m.notes}`);

  lines.push(
    "",
    "**Date filter:**",
    `- kind: ${d.kind ?? null}`,
    `- year: ${d.year ?? null}`,
    `- month: ${d.month ?? null}`,
    `- day_of_year: ${d.day_of_year ?? null}`,
    `- iso_date: ${d.iso_date ?? null}`,
    "",
    `**Applicable card schemes**: ${(s.applicable_card_schemes ?? []).join(", ")}`,
    "",
    "**Matching logic:**",
    `- convention: ${ml.convention ?? ""}`,
    `- fields_to_match: ${(ml.fields_to_match ?? []).join(", ")}`,
    "- derived_fields:",
  );
  for (const df of ml.derived_fields ?? []) lines.push(`  - ${df}`);

  lines.push("", "**Computation plan:**");
  (s.computation_plan ?? []).forEach((step, i) => {
    lines.push(`  ${i + 1}. ${step}`);
  });

  lines.push("", `**Expected output format**: ${s.expected_output_format ?? ""}`);
  if (s.notes_for_executor) lines.push("", `**Notes**: ${s.notes_for_executor}`);

  return lines.join("\n");
}

/**
 * LiveSQL renderer — direct TypeScript port of `render_spec_markdown()` in
 * `scripts/livesqlbench_adapter.py:30-86`. LiveSQL specs have entirely
 * different fields than DABStep/Krama (cte_plan, tables_needed, kb_formulas,
 * etc.), so the DABStep renderer would emit a mostly-empty block.
 */
function renderLivesqlSpec(s: SpecLike): string {
  const lines: string[] = [
    "## Query Plan Spec (from a planning step — trust these facts, do not re-derive)",
    "",
    `**Question summary**: ${s.question_summary ?? ""}`,
    "",
  ];

  lines.push(`**Tables needed:** ${(s.tables_needed ?? []).join(", ")}`);

  const jp = s.join_path ?? [];
  if (jp.length > 0) {
    lines.push("", "**Join path:**");
    for (const j of jp) {
      lines.push(`- \`${j.from_col ?? ""}\` → \`${j.to_col ?? ""}\` (${j.join_type ?? "JOIN"})`);
    }
  }

  const jcols = s.json_columns ?? [];
  if (jcols.length > 0) {
    lines.push("", "**JSON extractions:**");
    for (const jc of jcols) {
      const cast = jc.cast ? ` AS ${jc.cast}` : "";
      lines.push(`- \`json_extract(${jc.table ?? ""}.${jc.column ?? ""}, '${jc.path ?? ""}')${cast}\` → \`${jc.alias ?? ""}\``);
    }
  }

  const formulas = s.kb_formulas ?? [];
  if (formulas.length > 0) {
    lines.push("", "**KB formulas (implement exactly):**");
    for (const f of formulas) {
      lines.push(`- **${f.name ?? ""}** (KB id=${f.kb_id ?? "?"}): \`${f.sql_expression ?? ""}\``);
      if (f.depends_on && f.depends_on.length > 0) {
        lines.push(`  - Depends on: ${f.depends_on.join(", ")}`);
      }
      if (f.threshold) lines.push(`  - Threshold: ${f.threshold}`);
      if (f.notes) lines.push(`  - Note: ${f.notes}`);
    }
  }

  const ctes = (s.cte_plan ?? []) as Array<any>;
  if (ctes.length > 0) {
    lines.push("", "**CTE plan (implement in this order):**");
    ctes.forEach((cte: any, i: number) => {
      // Handle string-shaped entries (defensive) vs object-shaped (canonical)
      if (typeof cte === "string") {
        lines.push("", `${i + 1}. ${cte}`);
        return;
      }
      lines.push("", `${i + 1}. \`${cte.name ?? ""}\` — ${cte.computes ?? ""}`);
      if (cte.sql_sketch) {
        lines.push("   ```sql");
        lines.push(`   ${cte.sql_sketch}`);
        lines.push("   ```");
      }
      if (cte.group_by) lines.push(`   GROUP BY: \`${cte.group_by}\``);
      if (cte.agg_note) lines.push(`   ⚠ Aggregation: ${cte.agg_note}`);
    });
  }

  lines.push("", `**Output columns:** ${(s.output_columns ?? []).join(", ")}`);
  lines.push("", `**Ordering:** ${s.output_ordering ?? "none"}`);
  lines.push("", `**Expected format:** ${s.expected_output_format ?? ""}`);

  const edge = s.edge_cases ?? [];
  if (edge.length > 0) {
    lines.push("", "**Edge cases:**");
    for (const e of edge) lines.push(`- ${e}`);
  }

  if (s.notes_for_executor) {
    lines.push("", `**SQLite notes:** ${s.notes_for_executor}`);
  }

  return lines.join("\n");
}

/**
 * Top-level dispatcher: pick LiveSQL / Krama / DABStep rendering based on
 * which schema fields are present.
 *   - LiveSQL: cte_plan / tables_needed / kb_formulas (none of DABStep's fields)
 *   - Krama:   key_functionalities
 *   - DABStep: fallback (merchant + date_filter + matching_logic)
 */
export function renderSpecForPrompt(spec: SpecLike | unknown): string {
  if (!spec || typeof spec !== "object") return "(no spec available)";
  const s = spec as SpecLike;
  if (s._error) return `(spec extraction failed: ${s._error})`;
  // LiveSQL branch: detect on any LiveSQL-specific field (none overlap with DABStep/Krama).
  if (s.cte_plan !== undefined || s.tables_needed !== undefined || s.kb_formulas !== undefined) {
    return renderLivesqlSpec(s);
  }
  if (s.key_functionalities !== undefined) return renderKramaSpec(s);
  // DABStep fallback. Warn if the spec has none of DABStep's required markers —
  // that means we're rendering an unknown spec shape as DABStep by default.
  if (s.merchant === undefined && s.date_filter === undefined && s.matching_logic === undefined) {
    console.warn("[spec_renderer] DABStep fallback fired on spec with no merchant/date_filter/matching_logic; rendering may be empty.");
  }
  return renderDabstepSpec(s);
}

/**
 * Convenience: read a spec JSON from disk and render it. Returns null on read
 * failure so the caller can decide on a fallback.
 */
export function renderSpecFromPath(specPath: string, fs: typeof import("fs")): string | null {
  if (!fs.existsSync(specPath)) return null;
  try {
    const raw = fs.readFileSync(specPath, "utf-8");
    const parsed = JSON.parse(raw);
    return renderSpecForPrompt(parsed);
  } catch {
    return null;
  }
}
