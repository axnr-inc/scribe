/**
 * Lean benchmark-agnostic harness (DABStep / LiveSQLBench / KramaBench).
 *
 * Single command:
 *   npx tsx src/run.ts \
 *     -d data/datasets/dabstep_grafted/tasks.jsonl \
 *     -c configs/kimi_grafted.yaml \
 *     -o results/kimi_grafted/
 *
 * What it does:
 *   - Loads tasks (JSONL, one task per line, schema below)
 *   - For each task: builds the agent with the configured model + prompt + run_python tool
 *   - Runs the agent loop (max_iterations cap)
 *   - Writes per-task session log + summary to results/<arm>/<task_id>/
 *
 * Task JSONL schema:
 *   {"task_id": "...", "question": "...", "guidelines": "...",
 *    "level": "easy|medium|hard", "answer": "..."}
 */

import "dotenv/config";
import * as fs from "fs";
import * as path from "path";
import { Command } from "commander";
import { Agent, type AgentMessage } from "@mariozechner/pi-agent-core";
import type { Message } from "@mariozechner/pi-ai";
import { loadHarnessConfig, type HarnessConfig } from "./config.js";
import { PythonREPL } from "./harness/services/python_repl.js";
import { SessionLogger } from "./harness/services/session_logger.js";
import { TokenTracker } from "./harness/services/token_tracker.js";
import { makeRunPythonTool } from "./harness/tools/run_python.js";
import { makeRunSqlTool } from "./harness/tools/run_sql.js";
import { makeVerifyStepTool } from "./harness/tools/verify_step.js";
import { makeAskPlannerAgentTool } from "./harness/tools/ask_planner.js";
import { makeReadCurrentSpecTool } from "./harness/tools/read_current_spec.js";
import { renderSpecFromPath } from "./harness/spec_renderer.js";
import { buildToolRegistry } from "./harness/tools/index.js";
import { makeAfterToolCallHook } from "./harness/hooks/after_tool.js";
import { makeOnPayload } from "./harness/hooks/prompt_cache.js";
import { resolveHarnessModel } from "./model_resolver.js";
import * as yaml from "js-yaml";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const PROMPTS_DIR = path.join(ROOT, "src/prompts");
const CONTEXT_DIR = path.join(ROOT, "data/context");

interface TaskRow {
  task_id: string;
  question: string;
  guidelines?: string;
  level?: string;
  answer?: string;
  db_path?: string;       // LiveSQLBench: absolute path to the task's .sqlite file
  db_name?: string;       // LiveSQLBench: database name (for logging)
  // KramaBench: per-task data lake directory; overrides global CONTEXT_DIR in the
  // Python REPL preamble so the executor's run_python sees the right files.
  context_dir?: string;
  data_sources?: string[]; // KramaBench: files the spec_agent flagged as relevant
  answer_type?: string;    // KramaBench: numeric_exact / string_exact / list_exact / ...
  domain?: string;         // KramaBench: archeology / astronomy / ... (for logging)
}

interface PromptConfig {
  name: string;
  description: string;
  tools_section: string;
  quick_rules: string;
  deep_rules: string;
  preamble_extras?: string;
}

function loadTasks(file: string): TaskRow[] {
  return fs.readFileSync(file, "utf-8")
    .split("\n")
    .filter(Boolean)
    .map(line => JSON.parse(line) as TaskRow);
}

function loadPromptConfig(version: string): PromptConfig {
  const fp = path.join(PROMPTS_DIR, `${version}.yaml`);
  if (!fs.existsSync(fp)) throw new Error(`Prompt yaml not found: ${fp}`);
  return yaml.load(fs.readFileSync(fp, "utf-8")) as PromptConfig;
}

function buildSystemPrompt(question: string, mode: string, prompt: PromptConfig, task?: TaskRow): string {
  const role = mode === "deep"
    ? "You are an expert data analyst. You explore tables and provide thorough analysis using Python."
    : "You are an expert data analyst. Answer the user's question quickly and directly.";
  // Per-task context_dir override for the CONTEXT_DIR template variable.
  const ctxDir = task?.context_dir && task.context_dir.trim().length > 0
    ? task.context_dir
    : CONTEXT_DIR;
  const tools = prompt.tools_section.replace(/\{\{CONTEXT_DIR\}\}/g, ctxDir);
  const rules = mode === "deep" ? prompt.deep_rules : prompt.quick_rules;
  return [`# Role\n${role}`, `# Task\n${question}`, tools.trim(), `# Rules\n${rules.trim()}`].join("\n\n");
}

function buildPreamble(prompt: PromptConfig, task?: TaskRow): string {
  // Per-task context_dir override (KramaBench): if the task row carries its own
  // data-lake directory, the executor's Python REPL uses that instead of the
  // global DABStep CONTEXT_DIR. This is what makes the harness benchmark-agnostic.
  const ctxDir = task?.context_dir && task.context_dir.trim().length > 0
    ? task.context_dir
    : CONTEXT_DIR;
  const lines = [
    // -----------------------------------------------------------------------
    // Data-leakage sandbox: block HuggingFace datasets, Kaggle, and any other
    // path that would fetch labeled benchmark data from outside the DBs.
    // DAB maintainers reject submissions whose traces show `load_dataset(...)`,
    // `from datasets import`, kagglehub, etc. (see PRs #44, #47, #54, #56).
    // We block at the Python-module level: ANY import of these names raises.
    // -----------------------------------------------------------------------
    "import os, sys, json, csv, warnings, sqlite3",
    "os.environ['HF_HUB_OFFLINE'] = '1'",
    "os.environ['HF_DATASETS_OFFLINE'] = '1'",
    "os.environ['TRANSFORMERS_OFFLINE'] = '1'",
    "os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'",
    "_BLOCKED_MODULES = {'datasets', 'huggingface_hub', 'kagglehub', 'kaggle',",
    "                    'tensorflow_datasets', 'torchvision.datasets'}",
    "class _BlockedFinder:",
    "    def find_module(self, fullname, path=None):",
    "        root = fullname.split('.')[0]",
    "        if root in _BLOCKED_MODULES: return self",
    "        return None",
    "    def find_spec(self, fullname, path=None, target=None):",
    "        root = fullname.split('.')[0]",
    "        if root in _BLOCKED_MODULES:",
    "            raise ImportError('[SANDBOX] import of ' + fullname + ' blocked: external labeled-data libraries are disabled to prevent data leakage. Use the project DBs.')",
    "        return None",
    "    def load_module(self, fullname): raise ImportError('[SANDBOX] ' + fullname + ' blocked')",
    "sys.meta_path.insert(0, _BlockedFinder())",
    "# Belt-and-suspenders: also nullify the names so a cached import can't sneak by.",
    "for _m in _BLOCKED_MODULES: sys.modules[_m] = None",
    "# Network egress lockdown: block sockets to any host EXCEPT localhost (the",
    "# project DBs run on 127.0.0.1:5432 / :27017). This stops urllib/requests/",
    "# raw-socket downloads of labeled benchmark data (e.g. AG News CSV from",
    "# githubusercontent), which the import block alone does not catch.",
    "import socket as _socket",
    "_ALLOWED_HOSTS = {'127.0.0.1', 'localhost', '::1', '0.0.0.0'}",
    "_orig_connect = _socket.socket.connect",
    "def _guarded_connect(self, address):",
    "    try:",
    "        host = address[0] if isinstance(address, tuple) else str(address)",
    "    except Exception:",
    "        host = ''",
    "    if host not in _ALLOWED_HOSTS and not str(host).startswith('127.') and not str(host).startswith('/'):",
    "        raise OSError('[SANDBOX] network egress to ' + str(host) + ' blocked: only localhost DBs are reachable. External data downloads are disabled to prevent leakage.')",
    "    return _orig_connect(self, address)",
    "_socket.socket.connect = _guarded_connect",
    "# Local-cache lockdown: block reads of any pre-existing HuggingFace/Kaggle",
    "# dataset cache or arrow/parquet shards outside CONTEXT_DIR. The import +",
    "# network blocks don't stop an executor reading ~/.cache/huggingface/.../",
    "# ag_news-train.arrow directly off disk — this closes that path.",
    "import builtins as _bi",
    "_orig_open = _bi.open",
    "_BLOCKED_PATH_SUBSTR = ('huggingface', 'datasets--', '/.cache/huggingface',",
    "                        'kaggle', 'ag_news', 'tensorflow_datasets', 'torch/hub')",
    "def _path_blocked(path):",
    "    try:",
    "        s = os.path.realpath(str(path))",
    "    except Exception:",
    "        s = str(path)",
    "    low = s.lower()",
    "    if any(b in low for b in _BLOCKED_PATH_SUBSTR):",
    "        return True",
    "    # Block arrow/parquet shards that live OUTSIDE this task's CONTEXT_DIR",
    "    # (the project DBs are sqlite/duckdb/postgres/mongo, never arrow/parquet).",
    "    if (low.endswith('.arrow') or low.endswith('.parquet')) and CONTEXT_DIR not in s:",
    "        return True",
    "    return False",
    "def _guarded_open(file, *a, **k):",
    "    if isinstance(file, (str, bytes, os.PathLike)) and _path_blocked(file):",
    "        raise OSError('[SANDBOX] read of ' + str(file) + ' blocked: external labeled-dataset caches (HuggingFace/Kaggle/arrow/parquet) are disabled to prevent leakage. Use the project DBs.')",
    "    return _orig_open(file, *a, **k)",
    "_bi.open = _guarded_open",
    "import pandas as pd",
    "import numpy as np",
    "warnings.filterwarnings('ignore')",
    "# Also block pandas/pyarrow parquet+arrow readers that bypass builtins.open.",
    "_orig_read_parquet = pd.read_parquet",
    "def _guarded_read_parquet(path, *a, **k):",
    "    if isinstance(path, str) and _path_blocked(path):",
    "        raise OSError('[SANDBOX] pd.read_parquet of ' + str(path) + ' blocked (external dataset cache).')",
    "    return _orig_read_parquet(path, *a, **k)",
    "pd.read_parquet = _guarded_read_parquet",
    "",
    `CONTEXT_DIR = ${JSON.stringify(ctxDir)}`,
    "",
    "def context_path(*parts):",
    "    return os.path.join(CONTEXT_DIR, *parts)",
    "",
  ];
  if (task?.db_path) {
    lines.push(`DB_PATH = ${JSON.stringify(task.db_path)}`);
    lines.push("");
    lines.push("def run_sql(sql, params=None):");
    lines.push("    conn = sqlite3.connect(DB_PATH)");
    lines.push("    conn.row_factory = sqlite3.Row");
    lines.push("    cur = conn.execute(sql, params or [])");
    lines.push("    rows = [dict(r) for r in cur.fetchall()]");
    lines.push("    conn.close()");
    lines.push("    return rows");
    lines.push("");
  }
  // Per-task helper-manifest:
  // - DAB tasks (data_sources contains .db / .duckdb files) → dab_helper
  // - Krama tasks (any other per-task context_dir) → krama_helper
  // DABStep uses the global CONTEXT_DIR and gets no helper preamble.
  if (task?.context_dir && task.context_dir.trim().length > 0) {
    const helperPath = path.resolve("data/context");
    const isDab = (task.data_sources || []).some(s => {
      const lo = s.toLowerCase();
      return lo.endsWith(".db") || lo.endsWith(".duckdb")
        || lo.startsWith("postgres:") || lo.startsWith("mongo:");
    });
    lines.push(`import sys as _sys`);
    lines.push(`_sys.path.insert(0, ${JSON.stringify(helperPath)})`);
    lines.push(`try:`);
    if (isDab) {
      lines.push(`    from dab_helper import (`);
      lines.push(`        open_sqlite,`);
      lines.push(`        open_duckdb,`);
      lines.push(`        open_postgres,`);
      lines.push(`        open_mongo,`);
      lines.push(`        list_tables_sqlite,`);
      lines.push(`        list_tables_duckdb,`);
      lines.push(`        list_tables_postgres,`);
      lines.push(`        list_collections_mongo,`);
      lines.push(`        describe_sqlite,`);
      lines.push(`        describe_duckdb,`);
      lines.push(`        describe_postgres,`);
      lines.push(`        sqlite_sample,`);
      lines.push(`        duckdb_sample,`);
      lines.push(`        postgres_sample,`);
      lines.push(`        mongo_sample,`);
      lines.push(`    )`);
      // Patent-domain helpers: only for tasks with domain='patents'.
      // These cover the NL-text-parsing chain the executor was shortcutting:
      // - extract_assignee_from_patents_info() — gets owner from Patents_info string
      // - parse_cpc_field() / cpc_codes() / cpc_primary_code() / cpc_subclass() / cpc_main_group()
      // - parse_citation_field() / cited_publication_numbers()
      // - exponential_moving_average() + best_year_by_ema() with self-test
      if (task?.domain === "patents") {
        lines.push(`    from patent_helper import (`);
        lines.push(`        extract_assignee_from_patents_info,`);
        lines.push(`        extract_publication_number,`);
        lines.push(`        extract_application_number,`);
        lines.push(`        country_from_pubno,`);
        lines.push(`        is_country,`);
        lines.push(`        parse_cpc_field,`);
        lines.push(`        cpc_codes,`);
        lines.push(`        cpc_primary_code,`);
        lines.push(`        cpc_subclass,`);
        lines.push(`        cpc_main_group,`);
        lines.push(`        parse_citation_field,`);
        lines.push(`        cited_publication_numbers,`);
        lines.push(`        exponential_moving_average,`);
        lines.push(`        best_year_by_ema,`);
        lines.push(`        _ema_self_test,`);
        lines.push(`    )`);
        lines.push(`    assert _ema_self_test(), "EMA self-test failed; helper may be broken"`);
      }
      lines.push(`except Exception as _e:`);
      lines.push(`    print(f"[preamble] dab_helper import failed: {_e}")`);
    } else {
      lines.push(`    from krama_helper import (`);
      lines.push(`        read_multi_header_excel,`);
      lines.push(`        parse_missing_marker,`);
      lines.push(`        safe_dedupe,`);
      lines.push(`        linear_interp_by_key,`);
      lines.push(`        bp_to_calendar_year,`);
      lines.push(`        canonicalize_msa_name,`);
      lines.push(`        cross_state_msa,`);
      lines.push(`        sum_subcategory_counts,`);
      lines.push(`        pct_of_population_for_age_bucket,`);
      lines.push(`        treat_missing_as,`);
      lines.push(`        per_unit_mean_vs_total,`);
      lines.push(`        top_k_pct_threshold,`);
      lines.push(`        lag_correlation,`);
      lines.push(`        geopotential_per_mass,`);
      lines.push(`        count_two_actor_conflicts,`);
      lines.push(`        find_column_by_keywords,`);
      lines.push(`    )`);
      lines.push(`except Exception as _e:`);
      lines.push(`    print(f"[preamble] krama_helper import failed: {_e}")`);
    }
    lines.push("");
  }
  if (prompt.preamble_extras) lines.push(prompt.preamble_extras);
  return lines.join("\n");
}

function convertToLlm(messages: AgentMessage[]): Message[] {
  return messages.filter((m): m is Message =>
    m.role === "user" || m.role === "assistant" || m.role === "toolResult");
}

// Count "rows" in a final answer using format-specific heuristics. Returns
// at least 1 for any non-empty answer. The aim: detect when the executor
// collapsed multi-row data to a single tuple/row.
function countRowsInAnswer(answer: string): number {
  if (!answer || !answer.trim()) return 0;
  // Heuristic A: tuples in a python list literal — `[(...), (...), ...]`.
  // Each pair of `(...)` is one tuple = one row.
  const tupleMatches = answer.match(/\([^()]*\)/g) || [];
  const tupleCount = tupleMatches.length;
  // Heuristic B: pipe-separated rows on separate lines.
  const pipeLines = answer.split(/\r?\n/).filter(l => l.trim() && l.includes("|")).length;
  // Heuristic C: comma-separated list items in `['a', 'b', 'c']` or
  // `["a", "b", "c"]` (used by q1-style answers — list of bare codes).
  // We count top-level commas inside the outermost `[...]`.
  let listItemCount = 0;
  const listMatch = answer.match(/\[\s*(['"])(.*)\1\s*(?:,|\])/s);
  if (listMatch) {
    // Count commas at depth 1 of the bracket structure.
    const inner = answer.slice(answer.indexOf("[") + 1, answer.lastIndexOf("]"));
    let depth = 0; let commas = 0;
    for (const ch of inner) {
      if (ch === "[" || ch === "(") depth++;
      else if (ch === "]" || ch === ")") depth--;
      else if (ch === "," && depth === 0) commas++;
    }
    listItemCount = commas + 1;
  }
  return Math.max(tupleCount, pipeLines, listItemCount, 1);
}

// Best-effort extraction of an explicit row-count floor from the spec's
// expected_output_format text. Looks for `min_rows: 23`, `at least 23 rows`,
// `23 entries`, etc.
function extractMinRowsFromOutputFormat(fmt: string | undefined): number | null {
  if (!fmt) return null;
  let m = fmt.match(/min_rows\s*[:=]\s*(\d+)/i);
  if (m) return parseInt(m[1], 10);
  m = fmt.match(/at\s+least\s+(\d+)\s+(?:rows?|entries|items|tuples)/i);
  if (m) return parseInt(m[1], 10);
  m = fmt.match(/(\d+)\s+rows?/i);
  if (m) return parseInt(m[1], 10);
  // Multi-row keyword without explicit count → default floor of 5
  // (lower would let single-row collapses sneak through with 2-element pipe lines).
  if (/multi[-\s]?row|one\s+row\s+per|for\s+each\s+\w+|all\s+(\w+\s+)?(groups?|rows?|entries)/i.test(fmt)) {
    return 5;
  }
  return null;
}

function extractFinalText(messages: AgentMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant" && Array.isArray(msg.content)) {
      const full = msg.content
        .filter((c): c is { type: "text"; text: string } => "type" in c && c.type === "text")
        .map(c => c.text).join("");
      // Prompt contract: "Final answer on its OWN LINE, as the LAST line. No
      // trailing prose." Honor it by returning only the last non-empty line.
      // Falls back to full text if no non-empty line found (defensive).
      const lines = full.split(/\r?\n/);
      for (let j = lines.length - 1; j >= 0; j--) {
        const line = lines[j].trim();
        if (line.length > 0) return line;
      }
      return full;
    }
  }
  return "";
}

async function runOneTask(
  task: TaskRow,
  config: HarnessConfig,
  prompt: PromptConfig,
  outDir: string,
  specsDir: string | null,
): Promise<{
  task_id: string;
  wall_seconds: number;
  cost_usd: number;
  final_answer: string;
  tool_calls: number;
  ask_planner_calls: number;
  thinking_blocks: number;
  iter_count: number;
  hit_iter_cap: boolean;
  error: string | null;
}> {
  const taskDir = path.join(outDir, task.task_id);
  fs.mkdirSync(path.join(taskDir, "sessions"), { recursive: true });

  const preamblePath = path.join(taskDir, "preamble.py");
  fs.writeFileSync(preamblePath, buildPreamble(prompt, task));

  const pythonBin = config.connection.python_bin || "python3";
  const repl = new PythonREPL(pythonBin, preamblePath);

  // Build the FULL question text. If guidelines are present, append.
  let userText = task.guidelines && task.guidelines.trim()
    ? `${task.question}\n\nGuidelines:\n${task.guidelines}`
    : task.question;

  // P2: inject the spec into the executor's user message so the executor sees
  // it upfront (not just at escalation time). The spec path is the CURRENT spec
  // — overwritten in place by the planner on SPEC_WRONG revisions.
  //
  // We use the markdown-rendered form (renderSpecFromPath) instead of raw JSON.
  // Empirical reason: pilot smoke testing showed the executor re-derived plan
  // steps when shown raw JSON; the rendered "trust these facts, do not
  // re-derive" header keeps it anchored on the spec.
  let specPathForTask: string | null = null;
  if (specsDir) {
    const candidatePath = path.join(specsDir, `${task.task_id}.json`);
    // Bug 6 fix: detect spec extraction failures up-front. If the spec JSON
    // has an `_error` key, don't inject a "(spec extraction failed: ...)"
    // placeholder + planner-agent prompt — the planner has nothing real to
    // revise from, so it's pure noise for the executor.
    let specHasError = false;
    if (fs.existsSync(candidatePath)) {
      try {
        const rawObj = JSON.parse(fs.readFileSync(candidatePath, "utf-8"));
        if (rawObj && typeof rawObj === "object" && "_error" in rawObj) {
          specHasError = true;
          console.warn(`  ${task.task_id}: spec has _error (${(rawObj as any)._error}); skipping injection`);
        }
      } catch { /* let renderer handle parse failure below */ }
    }
    if (specHasError) {
      // Don't set specPathForTask → ask_planner + read_current_spec won't be wired below.
    } else {
      specPathForTask = candidatePath;
      const rendered = renderSpecFromPath(specPathForTask, fs);
      if (rendered) {
        userText += "\n\n" + rendered + "\n\nIf uncertain about any step, escalate via ask_planner_agent.";
      } else {
        console.warn(`  ${task.task_id}: spec file not found / unreadable at ${specPathForTask}; executor will see task only.`);
      }
    }
  }

  const systemPrompt = buildSystemPrompt(userText, config.execution.mode, prompt, task);

  const model = resolveHarnessModel(config);
  const tokenTracker = new TokenTracker(config.model.model);
  const sessionLogger = new SessionLogger(taskDir, "normal", "agent");

  // LiveSQL tasks (task.db_path set) use run_sql (SQL-only interface);
  // DABStep and KramaBench tasks both use run_python (pandas).
  // P1 Tier-C: verify_step is wired for run_python paths (DABStep + Krama) where
  // the executor builds DataFrames in the persistent REPL. LiveSQL's executor
  // only sees run_sql and has no DataFrames in its REPL view, so verify_step
  // would be inert there — we skip it.
  const tools = task.db_path
    ? [makeRunSqlTool(repl)]
    : [makeRunPythonTool(repl), makeVerifyStepTool(repl)];

  // If config has a planner AND --specs was provided, wire up ask_planner_agent
  // + read_current_spec (EC1 mitigation — lets executor refresh after a SPEC_WRONG
  // revision overwrites the spec file).
  if (config.planner && specPathForTask) {
    const sessionLogPath = path.join(taskDir, "sessions/normal_agent.jsonl");
    // Planner reads source docs from this directory. Priority order:
    //   1. task.context_dir (KramaBench: per-task data lake)
    //   2. dirname(task.db_path) (LiveSQLBench: per-task DB dir)
    //   3. undefined → ask_planner.ts falls back to DABStep's data/context
    const docsDir = (task.context_dir && task.context_dir.trim()) ||
                    (task.db_path ? path.dirname(task.db_path) : undefined);
    if (!docsDir) {
      // Loud one-shot warning: silently inheriting the DABStep docs dir is a
      // foot-gun for any future benchmark that forgets to set context_dir/db_path.
      console.warn(
        `${task.task_id}: no per-task docs dir; using DABStep default (data/context). ` +
        `If this isn't a DABStep task, set task.context_dir or task.db_path.`
      );
    }
    tools.push(makeAskPlannerAgentTool({
      taskQuestion: task.question,
      specPath: specPathForTask,
      sessionLogPath,
      planner: { provider: config.planner.provider, model: config.planner.model },
      docsDir,
    }));
    tools.push(makeReadCurrentSpecTool(specPathForTask));
  }

  const agent = new Agent({
    initialState: {
      systemPrompt,
      model,
      thinkingLevel: config.model.thinking,
      tools: buildToolRegistry(tools),
      messages: [],
    },
    convertToLlm,
    afterToolCall: makeAfterToolCallHook(sessionLogger, tokenTracker, config),
    onPayload: config.model.prompt_caching ? makeOnPayload() : undefined,
    toolExecution: config.execution.tool_execution as "sequential" | "parallel",
  });

  const maxIter = config.execution.max_iterations;
  let iterCount = 0;
  let abortedForIter = false;
  let thinkingCount = 0;
  let toolCallCount = 0;

  agent.subscribe((event) => {
    try {
      if (event.type === "message_end") {
        const msg = (event as any).message;
        if (msg?.role === "assistant" && Array.isArray(msg.content)) {
          for (const part of msg.content) {
            if (part?.type === "thinking") {
              thinkingCount++;
              sessionLogger.logAssistantThinking(String(part.thinking || ""));
            }
            if (part?.type === "text") {
              sessionLogger.logAssistantResponse(String(part.text || ""));
            }
            // Tool-call counting happens post-hoc by reading the session log (see
            // count_session_events below). pi-ai's content blocks use a non-obvious
            // type name for tool_use that varies by provider, so we count from the
            // single source of truth — the SessionLogger's JSONL events.
          }
        }
        if (msg?.usage) {
          const u = msg.usage;
          tokenTracker.update({
            input_tokens: (u.input ?? 0) + (u.cacheRead ?? 0) + (u.cacheWrite ?? 0),
            output_tokens: u.output ?? 0,
            cache_read_input_tokens: u.cacheRead ?? 0,
            cache_creation_input_tokens: u.cacheWrite ?? 0,
          });
        }
      }
      if (event.type === "turn_end") {
        iterCount++;
        if (maxIter !== null && iterCount >= maxIter && !abortedForIter) {
          abortedForIter = true;
          console.warn(`  ${task.task_id}: max_iterations=${maxIter} hit; aborting.`);
          try { agent.abort(); } catch {}
        }
      }
    } catch {}
  });

  const startTime = Date.now();
  sessionLogger.logUserMessage(userText);
  let error: string | null = null;
  try {
    await agent.prompt(userText);
    await agent.waitForIdle();
  } catch (e: any) {
    error = String(e?.message || e);
  }
  const wallSeconds = (Date.now() - startTime) / 1000;
  const cost0 = tokenTracker.computeCost().total;
  let final = extractFinalText(agent.state.messages);

  // ---------------------------------------------------------------------------
  // Multi-row gate: if the spec declares `min_rows: N` and the executor's
  // final answer has fewer than N rows, force a single retry.
  // Row count heuristic: count tuples in `[(...), (...), ...]`; or count
  // newlines / pipe-separated lines; or count comma-separated items in a list.
  // Conservative: pick the MAX of these so we don't over-trigger.
  // ---------------------------------------------------------------------------
  let multiRowRetry = false;
  if (specPathForTask) {
    try {
      const specObj = JSON.parse(fs.readFileSync(specPathForTask, "utf-8"));
      const minRows = specObj.min_rows ?? extractMinRowsFromOutputFormat(specObj.expected_output_format);
      if (typeof minRows === "number" && minRows >= 2) {
        const actualRows = countRowsInAnswer(final);
        if (actualRows < minRows) {
          multiRowRetry = true;
          const retryMsg = (
            `# Multi-row gate triggered\n\n` +
            `Your final answer has ${actualRows} row(s) but the spec's expected_output_format requires at least ${minRows} rows.\n\n` +
            `The validator will FAIL because it fuzzy-matches each gold row independently — missing rows are penalized; extra rows are NOT. ` +
            `You almost certainly computed the full multi-row data earlier in the conversation but collapsed it to top-N at the end. ` +
            `Re-emit ALL rows from the multi-row DataFrame, NOT just the top one.\n\n` +
            `Print the final answer as a single Python list literal on the LAST line, containing every row.`
          );
          console.warn(`  ${task.task_id}: multi-row gate (${actualRows} < ${minRows}); forcing one retry.`);
          try {
            await agent.prompt(retryMsg);
            await agent.waitForIdle();
            final = extractFinalText(agent.state.messages);
          } catch (e: any) {
            error = (error ? error + "; " : "") + `multi-row retry failed: ${e?.message || e}`;
          }
        }
      }
    } catch {}
  }
  const cost = tokenTracker.computeCost().total;

  repl.kill();

  // Count tool_calls post-hoc by re-reading the JSONL session log — single
  // source of truth, regardless of how pi-ai labels its content-block types.
  let actualToolCalls = toolCallCount;
  let askPlannerCalls = 0;
  try {
    const logPath = path.join(taskDir, "sessions/normal_agent.jsonl");
    if (fs.existsSync(logPath)) {
      const lines = fs.readFileSync(logPath, "utf-8").split("\n").filter(Boolean);
      for (const line of lines) {
        try {
          const evt = JSON.parse(line);
          if (evt.type === "tool_call") {
            actualToolCalls++;
            if (evt.toolName === "ask_planner" || evt.toolName === "ask_spec_agent" || evt.toolName === "ask_planner_agent") askPlannerCalls++;
          }
        } catch {}
      }
    }
  } catch {}

  return {
    task_id: task.task_id,
    wall_seconds: wallSeconds,
    cost_usd: cost,
    final_answer: final,
    tool_calls: actualToolCalls,
    ask_planner_calls: askPlannerCalls,
    thinking_blocks: thinkingCount,
    iter_count: iterCount,
    hit_iter_cap: abortedForIter,
    error,
  };
}

async function main() {
  const program = new Command()
    .name("run")
    .description("Run a dataset of tasks (DABStep / LiveSQLBench / KramaBench) through a configured model")
    .requiredOption("-d, --dataset <path>", "Path to tasks JSONL")
    .requiredOption("-c, --config <path>", "Path to model+execution YAML config")
    .requiredOption("-o, --out-dir <path>", "Output directory for per-task results")
    .option("--specs <dir>", "Directory of per-task spec JSON files (required if config has a `planner` field — enables ask_planner tool)")
    .option("-n, --notes <text>", "Free-form notes for this run", "")
    .option("-w, --workers <n>", "parallel task workers", "1");

  program.parse();
  const opts = program.opts();

  const config = loadHarnessConfig(opts.config);
  const prompt = loadPromptConfig(config.prompt_version);
  const tasks = loadTasks(opts.dataset);

  const outDir = path.resolve(opts.outDir);
  fs.mkdirSync(outDir, { recursive: true });

  const specsDir = opts.specs ? path.resolve(opts.specs) : null;
  if (config.planner && !specsDir) {
    console.warn(`  WARN: config has a planner field but --specs was not provided. ask_planner tool will be DISABLED.`);
  }
  if (specsDir && !config.planner) {
    console.warn(`  WARN: --specs provided but config has no planner field. ask_planner tool will be DISABLED.`);
  }

  // Save a small run-manifest for reproducibility
  fs.writeFileSync(path.join(outDir, "run_manifest.json"), JSON.stringify({
    started_at: new Date().toISOString(),
    dataset: path.resolve(opts.dataset),
    config: path.resolve(opts.config),
    model: config.model,
    planner: config.planner,
    specs_dir: specsDir,
    prompt_version: config.prompt_version,
    max_iterations: config.execution.max_iterations,
    notes: opts.notes,
    task_count: tasks.length,
  }, null, 2));

  console.log(`\nRunning ${tasks.length} tasks with model ${config.model.model} (${config.model.provider})`);
  console.log(`Prompt: ${config.prompt_version}, max_iter=${config.execution.max_iterations}`);
  console.log(`Output: ${outDir}\n`);

  const summaryPath = path.join(outDir, "summary.json");

  // Simple async mutex to serialise concurrent writes to summary.json
  let summaryLock = Promise.resolve();
  async function updateSummary(result: Awaited<ReturnType<typeof runOneTask>>) {
    summaryLock = summaryLock.then(async () => {
      let existing: Awaited<ReturnType<typeof runOneTask>>[] = [];
      if (fs.existsSync(summaryPath)) {
        try { existing = JSON.parse(fs.readFileSync(summaryPath, "utf-8")); } catch {}
      }
      // Replace entry if task_id already present (retry scenarios), otherwise append
      const idx = existing.findIndex(e => e.task_id === result.task_id);
      if (idx >= 0) existing[idx] = result; else existing.push(result);
      fs.writeFileSync(summaryPath, JSON.stringify(existing, null, 2));
    });
    return summaryLock;
  }

  const workers = parseInt(opts.workers ?? "1", 10);

  async function runPool(poolTasks: TaskRow[], maxWorkers: number) {
    const queue = [...poolTasks];

    async function runNext(): Promise<void> {
      if (queue.length === 0) return;
      const task = queue.shift()!;
      console.log(`[task ${task.task_id}] starting...`);
      const result = await runOneTask(task, config, prompt, outDir, specsDir);
      console.log(`  done in ${result.wall_seconds.toFixed(1)}s, $${result.cost_usd.toFixed(4)}, tc=${result.tool_calls}, ask_planner=${result.ask_planner_calls}, tb=${result.thinking_blocks}, hit_cap=${result.hit_iter_cap}`);
      await updateSummary(result);
      await runNext();
    }

    const active: Promise<void>[] = [];
    for (let i = 0; i < Math.min(maxWorkers, poolTasks.length); i++) {
      active.push(runNext());
    }
    await Promise.all(active);
  }

  await runPool(tasks, workers);

  console.log(`\nAll ${tasks.length} tasks complete. Summary: ${summaryPath}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
