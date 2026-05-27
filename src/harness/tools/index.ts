/**
 * Tool registry helpers.
 *
 * Our `ToolDefinition` interface is a slimmer, harness-local description of a tool
 * (name, parameters schema via TypeBox, and an `execute` function). `toAgentTool`
 * adapts it into the shape `@mariozechner/pi-agent-core` expects so the agent
 * loop can call our tools.
 *
 * `buildToolRegistry([...])` is what `src/run.ts` calls to hand the agent its tools.
 * In scribe the registry is always `[makeRunPythonTool(repl)]` — one tool, the
 * Python REPL. Add more `make<Whatever>Tool` factories here if you want to extend.
 *
 * The re-export of `Type` is so tool factories can `import { Type } from "./index.js"`
 * and define their parameter schemas without importing TypeBox directly.
 */
import { Type, type TObject } from "@sinclair/typebox";
import type { AgentTool, AgentToolResult } from "@mariozechner/pi-agent-core";

export interface ToolResult {
  content: string;
  isError: boolean;
}

export interface ToolDefinition {
  name: string;
  label: string;
  description: string;
  parameters: TObject;
  execute: (toolCallId: string, params: any) => Promise<AgentToolResult<unknown>>;
}

export function toAgentTool(def: ToolDefinition): AgentTool {
  return {
    name: def.name,
    label: def.label,
    description: def.description,
    parameters: def.parameters,
    execute: def.execute as AgentTool["execute"],
  };
}

export function buildToolRegistry(tools: ToolDefinition[]): AgentTool[] {
  return tools.map(toAgentTool);
}

export { Type };
