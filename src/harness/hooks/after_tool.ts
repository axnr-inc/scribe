/**
 * `afterToolCall` hook — runs after every tool call returns, BEFORE the result
 * is fed back to the model.
 *
 * Three responsibilities in scribe:
 *
 * 1. **Logging**: append `tool_call` + `tool_call_result` events to the session
 *    JSONL via `SessionLogger`. This is how we get the trace we later analyze.
 *
 * 2. **Loop detection**: if the agent calls the SAME tool with IDENTICAL
 *    arguments `LOOP_THRESHOLD` times in a row, we inject a warning into the
 *    tool result ("You are in a loop. STOP calling this tool."). This catches
 *    the failure mode where Kimi/Opus gets stuck running the same diagnostic
 *    print repeatedly. The warning is appended to the tool result so the agent
 *    sees it on its next turn.
 *
 * 3. **EC5 — conditional escalation reminder**: after iter `EC5_SOFT_FROM`,
 *    we append a short footer to every tool_call_result reminding the model that
 *    `ask_planner_agent` is available. The footer escalates tone over time and
 *    GOES SILENT once the model has actually escalated at least once — to avoid
 *    nagging a model that already complied. This addresses the empirically
 *    observed "context decay" failure mode where the system prompt's mandatory
 *    iter-15 rule gets buried under many tool_call_result blocks and the model
 *    forgets to escalate. Cost: ~10-30 tokens per call when active.
 *
 * Returning `null` from the hook means "pass result through unchanged". Returning
 * a `{ modifiedResult }` lets us inject text the agent will see.
 *
 * Configured per-session in `runOneTask` (src/run.ts) via
 * `makeAfterToolCallHook(sessionLogger, tokenTracker, config)`.
 */
import type { AfterToolCallContext, AfterToolCallResult } from "@mariozechner/pi-agent-core";
import type { SessionLogger } from "../services/session_logger.js";
import type { TokenTracker } from "../services/token_tracker.js";
import type { HarnessConfig } from "../../config.js";

const LOOP_THRESHOLD = 3;

// EC5 — context-decay mitigation. Tunable thresholds.
const EC5_SOFT_FROM = 10;   // start gentle reminders at iter 10
const EC5_URGENT_FROM = 15; // escalate tone at iter 15
const EC5_ESCALATION_TOOLS = new Set(["ask_planner_agent", "ask_spec_agent", "ask_planner"]);

function ec5Footer(iterCount: number, escalationCount: number, maxIter: number | null): string {
  // If the executor has escalated at least once, stay silent — it has the
  // ask_planner_agent affordance in working memory already.
  if (escalationCount >= 1) return "";
  const maxStr = maxIter !== null ? `${maxIter}` : "?";
  if (iterCount >= EC5_URGENT_FROM) {
    return `\n\n[iter ${iterCount}/${maxStr}] You have not escalated yet. If uncertain about correctness, blocked on an ambiguity, or considering a "Not Applicable" commit, escalate via ask_planner_agent now.`;
  }
  if (iterCount >= EC5_SOFT_FROM) {
    return `\n\n[iter ${iterCount}/${maxStr}] If uncertain about correctness or stuck, escalate via ask_planner_agent.`;
  }
  return "";
}

function getResultText(ctx: AfterToolCallContext): string {
  return ctx.result.content.map(c => ("text" in c ? c.text : "")).join("");
}

function detectLoop(sessionLogger: SessionLogger, ctx: AfterToolCallContext): string | null {
  const entries = sessionLogger.readAll();
  const toolCalls = entries.filter(e => e.type === "tool_call");
  if (toolCalls.length < LOOP_THRESHOLD) return null;

  const currentSig = `${ctx.toolCall.name}:${JSON.stringify(ctx.args).slice(0, 200)}`;
  const recent = toolCalls.slice(-LOOP_THRESHOLD);
  if (recent.every(h => `${h.toolName}:${JSON.stringify(h.toolArgs).slice(0, 200)}` === currentSig)) {
    return [
      `WARNING: You called ${ctx.toolCall.name} with identical arguments ${LOOP_THRESHOLD} times.`,
      `Result: ${getResultText(ctx).slice(0, 200)}`,
      `You are in a loop. STOP calling this tool. Move on or finish.`,
    ].join("\n");
  }
  return null;
}

export function makeAfterToolCallHook(
  sessionLogger: SessionLogger,
  tokenTracker: TokenTracker,
  config: HarnessConfig,
) {
  return async (ctx: AfterToolCallContext): Promise<AfterToolCallResult | undefined> => {
    const toolName = ctx.toolCall.name;
    const toolId = ctx.toolCall.id || `tc_${Date.now()}`;
    const resultText = getResultText(ctx);

    const isToolError = ctx.isError || ((toolName === "run_python" || toolName === "run_sql") && resultText.startsWith("Python error:"));
    const resultType = isToolError ? "error" : "success";

    sessionLogger.logToolCall(toolName, ctx.args, toolId);
    sessionLogger.logToolResult(toolName, resultType, toolId, resultText.slice(0, 5000));
    sessionLogger.incrementIteration();

    const loopWarning = detectLoop(sessionLogger, ctx);
    if (loopWarning) {
      return { content: [{ type: "text", text: loopWarning }], isError: true };
    }

    // Compose all the footer pieces (EC5 + context_mgmt) and emit one result.
    let footer = "";

    // EC5 — conditional escalation reminder. Read the full session to count
    // tool_call_result events (= iter) and ask_planner_agent invocations.
    const entries = sessionLogger.readAll();
    const iterCount = entries.filter(e => e.type === "tool_call_result").length;
    const escalationCount = entries.filter(
      e => e.type === "tool_call" && EC5_ESCALATION_TOOLS.has(String(e.toolName ?? "")),
    ).length;
    footer += ec5Footer(iterCount, escalationCount, config.execution.max_iterations);

    if (config.context_mgmt.enabled && toolName === "run_python") {
      const tokens = tokenTracker.lastContextTokens || tokenTracker.estimateContextTokens([]);
      const pct = (tokens / config.context_mgmt.context_window) * 100;
      footer += `\n\n[${tokens.toLocaleString()}/${config.context_mgmt.context_window.toLocaleString()} tokens (${pct.toFixed(1)}%)]`;
      if (pct >= config.context_mgmt.warn_threshold_pct * 100) {
        footer += `\nWARNING: Context window nearly full! Use view_context() to see your messages, then edit_context([indices]) to remove ones you no longer need.`;
      }
    }

    if (footer) {
      return { content: [{ type: "text", text: resultText + footer }] };
    }
    return undefined;
  };
}
