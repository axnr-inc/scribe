/**
 * `ask_planner(question: str) -> str` — escalation tool for the executor.
 *
 * v2.1: SESSION CONTINUITY + BLIND-SPOT DETECTION.
 *
 * The planner is the same conversation thread that extracted the spec. When
 * extract_specs.py runs, it persists the extraction call's full conversation
 * (system + user with manual.md/fees.json/etc. + assistant's tool_use spec) to
 * `<spec_dir>/<task_id>.session.json`. This tool LOADS that session, APPENDS
 * a new user message (executor recent events + the executor's question), POSTS
 * the full history to the planner API, and APPENDS the assistant reply to the
 * session file so subsequent ask_planner calls within the same task have full
 * cumulative continuity.
 *
 * The planner's system prompt also has a BLIND-SPOT DETECTION clause: it must
 * silently verify the executor's question is well-formed given the spec, and
 * if CERTAIN of a deeper misconception, surface the right question + answer in
 * addition to answering the literal question.
 *
 * Effect: the planner already has the source docs in its conversation history
 * (no separate read_file tool needed) and is explicitly prompted to catch
 * misconceptions like "executor asked about tie-breaking but the real issue is
 * whether to sum or pick at all".
 */
import { Type } from "@sinclair/typebox";
import * as fs from "fs";
import * as path from "path";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { ToolDefinition } from "./index.js";

/**
 * Tool the PLANNER has available (in v2.2). The planner is given a sandboxed
 * read_file tool so it can re-read source docs (manual.md, fees.json, etc.) on
 * demand rather than relying solely on its conversation history. The planner
 * does NOT get run_python — it should not execute code; only diagnose +
 * recommend.
 *
 * read_file is restricted to files under <CONTEXT_DIR> (data/context/) for
 * security. The CONTEXT_DIR path is resolved at runtime relative to this file.
 */
const CONTEXT_DIR_FOR_PLANNER = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "../../../data/context",
);

const PLANNER_READ_FILE_TOOL = {
  name: "read_file",
  description:
    "Read a file from the DABStep data/context directory (e.g. manual.md, fees.json, " +
    "merchant_data.json, payments-readme.md, acquirer_countries.csv, merchant_category_codes.csv). " +
    "Use this to RE-EXAMINE source documents when verifying your answer. The file content is returned " +
    "as plain text (truncated to ~50K chars). You may call this multiple times.",
  input_schema: {
    type: "object",
    required: ["filename"],
    properties: {
      filename: {
        type: "string",
        description: "File name relative to data/context, e.g. 'manual.md' or 'fees.json'.",
      },
    },
  },
};

function executePlannerReadFile(filename: string): string {
  // Resolve filename safely under CONTEXT_DIR_FOR_PLANNER
  const filePath = path.resolve(CONTEXT_DIR_FOR_PLANNER, filename);
  if (!filePath.startsWith(CONTEXT_DIR_FOR_PLANNER + path.sep) && filePath !== CONTEXT_DIR_FOR_PLANNER) {
    return `Error: filename '${filename}' is outside the allowed context directory.`;
  }
  if (!fs.existsSync(filePath)) {
    return `Error: file not found: ${filename}`;
  }
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    if (raw.length > 50_000) return raw.slice(0, 50_000) + "\n\n[truncated at 50000 chars]";
    return raw;
  } catch (e: any) {
    return `Error reading ${filename}: ${e.message}`;
  }
}

export interface AskPlannerConfig {
  /** Original task question (just the question, no spec). */
  taskQuestion: string;
  /** Absolute path to the task's spec JSON (results/<arm>/specs/<task_id>.json). May not exist; we handle it. */
  specPath: string;
  /** Absolute path to the session seed JSON (results/<arm>/specs/<task_id>.session.json). If missing, falls back to v2.0 single-shot behaviour. */
  sessionPath?: string;
  /** Absolute path to the executor's session JSONL log. Used to gather context for the planner. */
  sessionLogPath: string;
  /** Planner provider + model — e.g. {provider: "anthropic", model: "claude-sonnet-4-6"}. */
  planner: { provider: "anthropic" | "openrouter"; model: string };
  /** How many of the executor's most recent events to send to the planner. Default 10. */
  recentEventCount?: number;
}

// v2.3: The session seed (system prompt) from extract_specs.py already contains the
// review protocol with the read_file mandate. No separate fallback/blind-spot prompt.
// If a session seed is missing (e.g. older spec without session.json), we use a minimal
// fallback that mirrors the spec-agent meta-rules.
const SPEC_AGENT_FALLBACK_SYSTEM = (
  "You are a spec agent that previously produced a structured spec for this task. " +
  "The executor is calling back with a STRUCTURED SUMMARY of its work (# Step / # Computed so far / " +
  "# Pseudo-code / # Assumptions / # Question). Use read_file to verify the executor's assumptions " +
  "against the source documents (you MUST call read_file at least once before replying). " +
  "If you find an assumption inconsistent with what the docs state, reply with `[Flag: mistake detected]`, " +
  "quote the relevant doc passage, and emit a FULL REVISED SPEC. " +
  "If no mistake, reply with `[No flag]` and answer the executor's question grounded in doc quotes. " +
  "Do not flag based on intuition — only flag when you can quote the doc passage that contradicts " +
  "the executor's assumption."
);

function summariseRecentEvents(logPath: string, max: number): string {
  if (!fs.existsSync(logPath)) return "(no session log available yet)";
  const lines = fs.readFileSync(logPath, "utf-8").split("\n").filter(Boolean);
  const recent = lines.slice(-max);
  const parts: string[] = [];
  for (const line of recent) {
    try {
      const evt = JSON.parse(line);
      const t = evt.type;
      if (t === "user_message") {
        // skip — we send the task question separately
      } else if (t === "assistant_thinking") {
        parts.push(`[thinking]\n${String(evt.content || "").slice(0, 1500)}`);
      } else if (t === "assistant_response") {
        parts.push(`[response]\n${String(evt.content || "").slice(0, 1000)}`);
      } else if (t === "tool_call") {
        const code = (evt.toolArgs && evt.toolArgs.code) ? String(evt.toolArgs.code).slice(0, 1200) : "";
        parts.push(`[tool_call ${evt.toolName}]\n${code}`);
      } else if (t === "tool_call_result") {
        parts.push(`[tool_result]\n${String(evt.content || "").slice(0, 1500)}`);
      }
    } catch { /* skip malformed */ }
  }
  return parts.join("\n\n");
}

function readSpec(specPath: string): string {
  if (!fs.existsSync(specPath)) return "(no spec file found at " + specPath + ")";
  try {
    return fs.readFileSync(specPath, "utf-8");
  } catch (e: any) {
    return `(spec read error: ${e.message})`;
  }
}

interface AnthropicSession {
  provider: "anthropic";
  model: string;
  system: string;
  tools?: any[];
  messages: any[];
}
interface OpenRouterSession {
  provider: "openrouter";
  model: string;
  system: string;
  messages: any[];
}
type LoadedSession = AnthropicSession | OpenRouterSession;

function loadSession(sessionPath: string): LoadedSession | null {
  if (!fs.existsSync(sessionPath)) return null;
  try {
    const obj = JSON.parse(fs.readFileSync(sessionPath, "utf-8"));
    if (obj && obj.provider && obj.system && Array.isArray(obj.messages)) {
      return obj as LoadedSession;
    }
  } catch {}
  return null;
}

function saveSession(sessionPath: string, session: LoadedSession): void {
  try {
    fs.writeFileSync(sessionPath, JSON.stringify(session, null, 2));
  } catch {}
}

/** Build the user message for an ask_spec_agent turn. The executor is expected to send
 * a structured summary in `question`; we pass it through verbatim along with original
 * task + spec context. */
function buildAskUserMessage(cfg: AskPlannerConfig, question: string, spec: string, recent: string, recentN: number): string {
  return [
    "# Executor calling for review",
    "Original task:",
    cfg.taskQuestion,
    "",
    "Spec you produced (for reference — already in your conversation history):",
    spec,
    "",
    `Executor's recent trace events (last ${recentN}, for cross-reference):`,
    recent,
    "",
    "Executor's structured summary and question:",
    question,
    "",
    "Follow the review protocol from your system prompt: call read_file at least once to verify, "
      + "then either flag a mistake (with a revised spec) or answer the question grounded in doc quotes.",
  ].join("\n\n");
}

/**
 * Multi-turn Anthropic call for the planner. Exposes `read_file` to the planner
 * so it can re-examine docs. Loops until the planner stops calling tools (i.e.
 * emits a pure-text response). Returns the final text + the final `messages`
 * array (so the caller can persist the full extended history).
 *
 * Iteration cap of 5 tool-call turns to prevent runaway. If hit, returns the
 * partial text along with the messages so far.
 */
async function callPlannerAnthropic(args: {
  model: string;
  system: string;
  messages: any[];
  max_tokens: number;
  maxToolTurns?: number;
}): Promise<{ text: string; finalMessages: any[] }> {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("ANTHROPIC_API_KEY not set");
  const maxToolTurns = args.maxToolTurns ?? 5;
  // Working copy of the message list; we APPEND assistant + user (tool_result) pairs as we go.
  let messages = [...args.messages];

  for (let turn = 0; turn <= maxToolTurns; turn++) {
    const body: any = {
      model: args.model,
      max_tokens: args.max_tokens,
      system: args.system,
      tools: [PLANNER_READ_FILE_TOOL],
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
    const blocks: any[] = data.content || [];

    // Find any tool_use blocks the planner wants to execute.
    const toolUses = blocks.filter((b: any) => b.type === "tool_use");
    // Append the assistant message to the conversation regardless of whether it has tool_uses.
    messages.push({ role: "assistant", content: blocks });

    if (toolUses.length === 0) {
      // Pure text response — we're done.
      const text = blocks.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n");
      return { text, finalMessages: messages };
    }

    // Execute each tool_use (only read_file is supported on the planner side).
    const toolResultBlocks: any[] = [];
    for (const tu of toolUses) {
      if (tu.name === "read_file") {
        const filename = String((tu.input && tu.input.filename) || "");
        const content = executePlannerReadFile(filename);
        toolResultBlocks.push({
          type: "tool_result",
          tool_use_id: tu.id,
          content,
        });
      } else {
        toolResultBlocks.push({
          type: "tool_result",
          tool_use_id: tu.id,
          content: `Error: unsupported tool '${tu.name}'. Only read_file is available to the planner.`,
        });
      }
    }
    messages.push({ role: "user", content: toolResultBlocks });
    // Loop and let the planner observe + continue.
  }

  // Hit the cap. Return whatever text was last emitted, plus the messages so far.
  const lastAssistant = messages.slice().reverse().find(m => m.role === "assistant");
  const lastText = lastAssistant && Array.isArray(lastAssistant.content)
    ? lastAssistant.content.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n")
    : "";
  return {
    text: (lastText ? lastText + "\n\n" : "")
      + `[planner hit tool-turn cap of ${maxToolTurns}; returning partial reply]`,
    finalMessages: messages,
  };
}

async function callPlannerOpenRouter(args: {
  model: string;
  system: string;
  messages: any[];
  max_tokens: number;
}): Promise<string> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) throw new Error("OPENROUTER_API_KEY not set");
  // OpenRouter expects system as the first message.
  const fullMessages = [
    { role: "system", content: args.system },
    ...args.messages,
  ];
  const res = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "authorization": `Bearer ${key}`,
    },
    body: JSON.stringify({
      model: args.model,
      max_tokens: args.max_tokens,
      messages: fullMessages,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`OpenRouter ${res.status}: ${errText.slice(0, 500)}`);
  }
  const data = await res.json() as any;
  return data.choices?.[0]?.message?.content ?? "(no content)";
}

export function makeAskPlannerTool(cfg: AskPlannerConfig): ToolDefinition {
  const recentN = cfg.recentEventCount ?? 10;
  // Derive session path from spec path if not provided.
  const sessionPath = cfg.sessionPath
    ?? cfg.specPath.replace(/\.json$/, ".session.json");

  return {
    name: "ask_spec_agent",
    label: "Ask Spec Agent",
    description: (
      "Ask the spec agent that wrote your initial spec for clarification or review. " +
      "Call this when you are uncertain about any aspect of your work — DO NOT overcommit when you " +
      "have unresolved ambiguity. The spec agent has read all source documents and will re-read them " +
      "to verify your assumptions. " +
      "Send a STRUCTURED SUMMARY of your work so far, using these headers verbatim: " +
      "`# Step` / `# Computed so far` / `# Pseudo-code` / `# Assumptions` / `# Question`. " +
      "The spec agent will either flag a mistake (and emit a revised spec) or answer your question " +
      "with doc quotes. Each call costs money — don't ask routine pandas questions; do ask substantive " +
      "task-relevant questions."
    ),
    parameters: Type.Object({
      question: Type.String({
        description: "Your STRUCTURED SUMMARY using the five headers (# Step / # Computed so far / # Pseudo-code / # Assumptions / # Question).",
      }),
    }),
    execute: async (_toolCallId: string, params: any): Promise<AgentToolResult<unknown>> => {
      const question = String(params.question ?? "").trim();
      if (!question) {
        return { content: [{ type: "text", text: "Error: empty question to planner." }], details: {} };
      }
      const spec = readSpec(cfg.specPath);
      const recent = summariseRecentEvents(cfg.sessionLogPath, recentN);
      const askUserMessage = buildAskUserMessage(cfg, question, spec, recent, recentN);

      // Try to load the session seed produced by extract_specs.py. If present we use
      // session continuity. If absent (older spec, or session.json missing), we fall
      // back to v2.0 single-shot behaviour with a self-contained system prompt.
      const session = loadSession(sessionPath);

      try {
        const start = Date.now();
        let reply: string;

        let finalMessages: any[] | null = null;
        if (session && session.provider === cfg.planner.provider && session.model === cfg.planner.model) {
          // CONTINUITY PATH — extension of the same conversation seeded by extract_specs.py.
          // The seed system prompt already contains the v2.3 review protocol; no extra clauses
          // are appended (we removed the blind-spot clause in v2.3).
          const sysPrompt = session.system;
          const newMessages = [...session.messages, { role: "user", content: askUserMessage }];

          if (cfg.planner.provider === "anthropic") {
            const r = await callPlannerAnthropic({
              model: cfg.planner.model,
              system: sysPrompt,
              messages: newMessages,
              max_tokens: 2000,
            });
            reply = r.text;
            finalMessages = r.finalMessages;
          } else {
            reply = await callPlannerOpenRouter({
              model: cfg.planner.model,
              system: sysPrompt,
              messages: newMessages,
              max_tokens: 2000,
            });
            // OpenRouter path: no tool-loop yet; append a single assistant text turn.
            finalMessages = [...newMessages, { role: "assistant", content: reply }];
          }
          // Persist the FULL final conversation (including any read_file tool turns).
          const updated: LoadedSession = {
            ...session,
            system: sysPrompt,
            messages: finalMessages,
          };
          saveSession(sessionPath, updated);
        } else {
          // FALLBACK PATH — no session seed (e.g. spec extracted with older v2.0
          // extract_specs.py, or planner provider/model differs from what produced
          // the seed). Single call with self-contained system prompt.
          if (cfg.planner.provider === "anthropic") {
            const r = await callPlannerAnthropic({
              model: cfg.planner.model,
              system: SPEC_AGENT_FALLBACK_SYSTEM,
              messages: [{ role: "user", content: askUserMessage }],
              max_tokens: 2000,
            });
            reply = r.text;
          } else {
            reply = await callPlannerOpenRouter({
              model: cfg.planner.model,
              system: SPEC_AGENT_FALLBACK_SYSTEM,
              messages: [{ role: "user", content: askUserMessage }],
              max_tokens: 2000,
            });
          }
        }

        const elapsedMs = Date.now() - start;
        const continuityTag = session ? "session_continuity" : "single_shot_fallback";
        return {
          content: [{
            type: "text",
            text: reply.trim()
              + `\n\n[planner: ${cfg.planner.provider}:${cfg.planner.model}, ${elapsedMs}ms, mode=${continuityTag}]`,
          }],
          details: { planner: cfg.planner, elapsedMs, mode: continuityTag },
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
