/**
 * read_current_spec() — executor-side tool to refresh its view of the current spec.
 *
 * EC1 mitigation: the spec is injected into the executor's first user message
 * at task start, but the planner can overwrite the spec file with a revision
 * mid-task (on a [Verdict: SPEC_WRONG] reply). The original spec stays in the
 * executor's conversation history, which can cause drift if the executor
 * scrolls past the revision turn.
 *
 * This tool lets the executor re-read whatever the CURRENT spec is on disk at
 * any point — deterministic, zero-LLM-cost. The executor's prompt instructs it
 * to call this after receiving a SPEC_WRONG verdict, or any time it wants to
 * double-check what version of the spec is active.
 */
import { Type } from "@sinclair/typebox";
import * as fs from "fs";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { ToolDefinition } from "./index.js";
import { renderSpecFromPath } from "../spec_renderer.js";

export function makeReadCurrentSpecTool(specPath: string): ToolDefinition {
  return {
    name: "read_current_spec",
    label: "Read Current Spec",
    description: (
      "Re-read the CURRENT spec from disk. The spec you saw in your initial " +
      "user message MAY have been replaced by the planner_agent after a " +
      "[Verdict: SPEC_WRONG] revision. Call this tool whenever you want to " +
      "confirm the active spec. Returns the spec rendered in the same markdown " +
      "format you saw originally. Zero-cost; no LLM call involved."
    ),
    parameters: Type.Object({}),
    execute: async (_toolCallId: string, _params: any): Promise<AgentToolResult<unknown>> => {
      if (!fs.existsSync(specPath)) {
        return {
          content: [{ type: "text", text: `(no spec file found at ${specPath})` }],
          details: { exists: false, path: specPath },
        };
      }
      const rendered = renderSpecFromPath(specPath, fs);
      if (rendered === null) {
        return {
          content: [{ type: "text", text: `Error reading/parsing spec at ${specPath}` }],
          details: { error: "render_failed", path: specPath },
        };
      }
      const bytes = fs.statSync(specPath).size;
      return {
        content: [{ type: "text", text: rendered }],
        details: { exists: true, path: specPath, bytes },
      };
    },
  };
}
