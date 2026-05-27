/**
 * `run_python(code: str) -> str` — the ONLY tool the agent has in scribe.
 *
 * Hands the code string to a `PythonREPL` process (persistent across calls within
 * a single task — so variables, imports, and loaded DataFrames stay alive between
 * tool calls). Returns whatever the REPL printed to stdout/stderr.
 *
 * The preamble code that boots the REPL (loaded once before any tool call) is
 * built in `src/run.ts` (`buildPreamble`) and exposes:
 *   - `CONTEXT_DIR` (absolute path string)
 *   - `context_path(*parts)` (joins paths under CONTEXT_DIR)
 *   - pre-imported: pd, np, json, csv, os
 *
 * If you need a richer tool description (the model sees `description` when
 * choosing to call the tool), pass `descriptionOverride`. We currently leave it
 * generic and rely on the system prompt (`src/prompts/dabstep_*.yaml`) to teach
 * the agent how to use it.
 */
import { Type } from "@sinclair/typebox";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { PythonREPL } from "../services/python_repl.js";
import type { ToolDefinition } from "./index.js";

export function makeRunPythonTool(repl: PythonREPL, descriptionOverride?: string): ToolDefinition {
  return {
    name: "run_python",
    label: "Run Python",
    description: descriptionOverride ?? "Execute Python code in a persistent session. Use print() for output.",
    parameters: Type.Object({
      code: Type.String({ description: "Python code to execute. Use print() for output." }),
    }),
    execute: async (_toolCallId: string, params: any): Promise<AgentToolResult<unknown>> => {
      const { output } = await repl.execute(params.code as string);
      return { content: [{ type: "text", text: output }], details: {} };
    },
  };
}
