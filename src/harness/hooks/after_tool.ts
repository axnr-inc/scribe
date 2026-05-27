/**
 * `afterToolCall` hook — runs after every tool call returns, BEFORE the result
 * is fed back to the model.
 *
 * Two responsibilities in scribe:
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

    const isToolError = ctx.isError || (toolName === "run_python" && resultText.startsWith("Python error:"));
    const resultType = isToolError ? "error" : "success";

    sessionLogger.logToolCall(toolName, ctx.args, toolId);
    sessionLogger.logToolResult(toolName, resultType, toolId, resultText.slice(0, 5000));
    sessionLogger.incrementIteration();

    const loopWarning = detectLoop(sessionLogger, ctx);
    if (loopWarning) {
      return { content: [{ type: "text", text: loopWarning }], isError: true };
    }

    if (config.context_mgmt.enabled && toolName === "run_python") {
      const tokens = tokenTracker.lastContextTokens || tokenTracker.estimateContextTokens([]);
      const pct = (tokens / config.context_mgmt.context_window) * 100;
      let statsLine = `\n\n[${tokens.toLocaleString()}/${config.context_mgmt.context_window.toLocaleString()} tokens (${pct.toFixed(1)}%)]`;

      if (pct >= config.context_mgmt.warn_threshold_pct * 100) {
        statsLine += `\nWARNING: Context window nearly full! Use view_context() to see your messages, then edit_context([indices]) to remove ones you no longer need.`;
      }

      return { content: [{ type: "text", text: resultText + statsLine }] };
    }

    return undefined;
  };
}
