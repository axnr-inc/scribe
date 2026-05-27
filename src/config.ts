import * as fs from "fs";
import * as yaml from "js-yaml";
import type { ThinkingLevel } from "@mariozechner/pi-agent-core";

export interface ModelConfig {
  provider: string;
  model: string;
  thinking: ThinkingLevel;
  prompt_caching: boolean;
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
}

export interface ToolsConfig {
  run_python: boolean;
  run_sql: boolean;
  search_context: boolean;
  read_file: boolean;
  context_mgmt: boolean;
  graphrag: boolean;
  graphrag_url: string;
}

export interface ContextManagement {
  enabled: boolean;
  context_window: number;
  warn_threshold_pct: number;
}

export interface ExecutionConfig {
  mode: "quick" | "deep";
  max_iterations: number | null;
  tool_execution: "sequential" | "parallel";
  rate_limit_retries: number;
  overloaded_retries: number;
}

export interface ConnectionConfig {
  dialect: string;
  dataset: string;
  project_id: string;
  credential_path: string;
  context_dir: string;
  python_bin: string;
}

export interface PlannerConfig {
  /** API provider. Anthropic for Sonnet/Opus/Haiku, OpenRouter for Kimi/GPT-5/etc. */
  provider: "anthropic" | "openrouter";
  /** Model ID. For Anthropic: "claude-sonnet-4-6". For OpenRouter: "openai/gpt-5", "moonshotai/kimi-k2.6". */
  model: string;
}

export interface HarnessConfig {
  model: ModelConfig;
  prompt_version: string;
  tools: ToolsConfig;
  context_mgmt: ContextManagement;
  execution: ExecutionConfig;
  connection: ConnectionConfig;
  /** Optional. If present AND --specs CLI flag is provided, the harness wires up
   *  the `ask_planner` tool so the executor can escalate when stuck. */
  planner?: PlannerConfig | null;
}

export interface DatasetConfig {
  name: string;
  dialect: string;
  connection: Record<string, string>;
  context_dir: string | null;
  questions_file: string | null;
  /** `default` — harness JSON fields; `dabstep` — task_id/question/guidelines rows from adyen/DABstep */
  questions_schema: string;
  prompt_overrides: Record<string, string>;
}

export interface Question {
  id: string;
  text: string;
  follow_up: string | null;
  metadata: Record<string, unknown>;
}

const DEFAULT_MODEL: ModelConfig = {
  provider: "anthropic",
  model: "claude-opus-4-6",
  thinking: "off" as ThinkingLevel,
  prompt_caching: true,
  temperature: null,
  top_p: null,
  max_tokens: null,
};

const DEFAULT_TOOLS: ToolsConfig = {
  run_python: true,
  run_sql: false,
  search_context: false,
  read_file: false,
  context_mgmt: false,
  graphrag: false,
  graphrag_url: "http://localhost:8787",
};

const DEFAULT_CONTEXT: ContextManagement = {
  enabled: false,
  context_window: 200_000,
  warn_threshold_pct: 0.9,
};

const DEFAULT_EXECUTION: ExecutionConfig = {
  mode: "quick",
  max_iterations: null,
  tool_execution: "sequential",
  rate_limit_retries: 5,
  overloaded_retries: 10,
};

const DEFAULT_CONNECTION: ConnectionConfig = {
  dialect: "BigQuery",
  dataset: "",
  project_id: "",
  credential_path: "",
  context_dir: "",
  python_bin: "python3",
};

export interface VariantDef {
  name: string;
  prompt_version: string;
  thinking: string;
  tools?: Partial<ToolsConfig>;
  context_mgmt?: Partial<ContextManagement>;
  model?: Partial<ModelConfig>;
  execution?: Partial<ExecutionConfig>;
}

export function loadHarnessConfig(configPath: string): HarnessConfig {
  const raw = yaml.load(fs.readFileSync(configPath, "utf-8")) as Record<string, unknown>;
  const plannerRaw = raw.planner as Partial<PlannerConfig> | undefined;
  return {
    model: { ...DEFAULT_MODEL, ...(raw.model as Partial<ModelConfig> || {}) },
    prompt_version: (raw.prompt_version as string) || "v2_read_fully",
    tools: { ...DEFAULT_TOOLS, ...(raw.tools as Partial<ToolsConfig> || {}) },
    context_mgmt: { ...DEFAULT_CONTEXT, ...(raw.context_mgmt as Partial<ContextManagement> || {}) },
    execution: { ...DEFAULT_EXECUTION, ...(raw.execution as Partial<ExecutionConfig> || {}) },
    connection: { ...DEFAULT_CONNECTION, ...(raw.connection as Partial<ConnectionConfig> || {}) },
    planner: plannerRaw && plannerRaw.provider && plannerRaw.model
      ? { provider: plannerRaw.provider as "anthropic" | "openrouter", model: plannerRaw.model }
      : null,
  };
}

export function loadConfigWithVariants(configPath: string): { base: HarnessConfig; variants: VariantDef[] } {
  const raw = yaml.load(fs.readFileSync(configPath, "utf-8")) as Record<string, unknown>;
  const base: HarnessConfig = {
    model: { ...DEFAULT_MODEL, ...(raw.model as Partial<ModelConfig> || {}) },
    prompt_version: (raw.prompt_version as string) || "v2_read_fully",
    tools: { ...DEFAULT_TOOLS, ...(raw.tools as Partial<ToolsConfig> || {}) },
    context_mgmt: { ...DEFAULT_CONTEXT, ...(raw.context_mgmt as Partial<ContextManagement> || {}) },
    execution: { ...DEFAULT_EXECUTION, ...(raw.execution as Partial<ExecutionConfig> || {}) },
    connection: { ...DEFAULT_CONNECTION, ...(raw.connection as Partial<ConnectionConfig> || {}) },
  };
  const variants = (raw.variants as VariantDef[]) || [];
  return { base, variants };
}

export function resolveVariant(base: HarnessConfig, variant: VariantDef): HarnessConfig {
  const tools = { ...base.tools, ...(variant.tools || {}) };
  if (!variant.tools || (variant.tools.run_python === undefined && variant.tools.run_sql === undefined)) {
    tools.run_python = true;
  }
  const isConscious = tools.context_mgmt ?? false;
  return {
    model: { ...base.model, ...(variant.model || {}), thinking: (variant.thinking || base.model.thinking) as any },
    prompt_version: variant.prompt_version || base.prompt_version,
    tools,
    context_mgmt: { ...base.context_mgmt, enabled: isConscious, ...(variant.context_mgmt || {}) },
    execution: { ...base.execution, ...(variant.execution || {}) },
    connection: base.connection,
  };
}

export function loadDatasetConfig(path: string): DatasetConfig {
  const raw = yaml.load(fs.readFileSync(path, "utf-8")) as Record<string, unknown>;
  return {
    name: (raw.name as string) || "",
    dialect: (raw.dialect as string) || "BigQuery",
    connection: (raw.connection as Record<string, string>) || {},
    context_dir: (raw.context_dir as string) || null,
    questions_file: (raw.questions_file as string) || null,
    questions_schema: (raw.questions_schema as string) || "default",
    prompt_overrides: (raw.prompt_overrides as Record<string, string>) || {},
  };
}

export function applyOverrides(config: HarnessConfig, overrides: Record<string, unknown>): HarnessConfig {
  const cloned = JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
  for (const [key, value] of Object.entries(overrides)) {
    const parts = key.split(".");
    let target = cloned;
    for (let i = 0; i < parts.length - 1; i++) {
      target = target[parts[i]] as Record<string, unknown>;
    }
    target[parts[parts.length - 1]] = value;
  }
  return cloned as unknown as HarnessConfig;
}

export function configForHashing(config: HarnessConfig): Record<string, unknown> {
  const { connection: _, ...rest } = config;
  return rest as unknown as Record<string, unknown>;
}
