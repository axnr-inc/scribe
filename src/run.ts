/**
 * Lean DABStep harness for the grafting experiments.
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
import { makeAskPlannerTool } from "./harness/tools/ask_planner.js";
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

function buildSystemPrompt(question: string, mode: string, prompt: PromptConfig): string {
  const role = mode === "deep"
    ? "You are an expert data analyst. You explore tables and provide thorough analysis using Python."
    : "You are an expert data analyst. Answer the user's question quickly and directly.";
  const tools = prompt.tools_section.replace(/\{\{CONTEXT_DIR\}\}/g, CONTEXT_DIR);
  const rules = mode === "deep" ? prompt.deep_rules : prompt.quick_rules;
  return [`# Role\n${role}`, `# Task\n${question}`, tools.trim(), `# Rules\n${rules.trim()}`].join("\n\n");
}

function buildPreamble(prompt: PromptConfig): string {
  const lines = [
    "import os, json, csv, warnings",
    "import pandas as pd",
    "import numpy as np",
    "warnings.filterwarnings('ignore')",
    "",
    `CONTEXT_DIR = ${JSON.stringify(CONTEXT_DIR)}`,
    "",
    "def context_path(*parts):",
    "    return os.path.join(CONTEXT_DIR, *parts)",
    "",
  ];
  if (prompt.preamble_extras) lines.push(prompt.preamble_extras);
  return lines.join("\n");
}

function convertToLlm(messages: AgentMessage[]): Message[] {
  return messages.filter((m): m is Message =>
    m.role === "user" || m.role === "assistant" || m.role === "toolResult");
}

function extractFinalText(messages: AgentMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant" && Array.isArray(msg.content)) {
      return msg.content
        .filter((c): c is { type: "text"; text: string } => "type" in c && c.type === "text")
        .map(c => c.text).join("");
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
  fs.writeFileSync(preamblePath, buildPreamble(prompt));

  const pythonBin = config.connection.python_bin || "python3";
  const repl = new PythonREPL(pythonBin, preamblePath);

  // Build the FULL question text. If guidelines are present, append.
  const userText = task.guidelines && task.guidelines.trim()
    ? `${task.question}\n\nGuidelines:\n${task.guidelines}`
    : task.question;

  const systemPrompt = buildSystemPrompt(userText, config.execution.mode, prompt);

  const model = resolveHarnessModel(config);
  const tokenTracker = new TokenTracker(config.model.model);
  const sessionLogger = new SessionLogger(taskDir, "normal", "agent");

  const tools = [makeRunPythonTool(repl)];

  // If config has a planner AND --specs was provided, wire up ask_planner.
  if (config.planner && specsDir) {
    const specPath = path.join(specsDir, `${task.task_id}.json`);
    const sessionLogPath = path.join(taskDir, "sessions/normal_agent.jsonl");
    tools.push(makeAskPlannerTool({
      taskQuestion: task.question,
      specPath,
      sessionLogPath,
      planner: { provider: config.planner.provider, model: config.planner.model },
    }));
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
  const cost = tokenTracker.computeCost().total;
  const final = extractFinalText(agent.state.messages);

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
            if (evt.toolName === "ask_planner" || evt.toolName === "ask_spec_agent") askPlannerCalls++;
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
    .description("Run a dataset of DABStep tasks through a configured model")
    .requiredOption("-d, --dataset <path>", "Path to tasks JSONL")
    .requiredOption("-c, --config <path>", "Path to model+execution YAML config")
    .requiredOption("-o, --out-dir <path>", "Output directory for per-task results")
    .option("--specs <dir>", "Directory of per-task spec JSON files (required if config has a `planner` field — enables ask_planner tool)")
    .option("-n, --notes <text>", "Free-form notes for this run", "");

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

  const summary: Awaited<ReturnType<typeof runOneTask>>[] = [];
  for (const t of tasks) {
    console.log(`[task ${t.task_id}] starting...`);
    const r = await runOneTask(t, config, prompt, outDir, specsDir);
    console.log(`  done in ${r.wall_seconds.toFixed(1)}s, $${r.cost_usd.toFixed(4)}, tc=${r.tool_calls}, ask_planner=${r.ask_planner_calls}, tb=${r.thinking_blocks}, hit_cap=${r.hit_iter_cap}`);
    summary.push(r);
    // Save incrementally so partial runs are inspectable
    fs.writeFileSync(path.join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  }

  console.log(`\nAll ${tasks.length} tasks complete. Summary: ${path.join(outDir, "summary.json")}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
