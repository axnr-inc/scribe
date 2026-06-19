/**
 * Langfuse tracing for SCRIBE harness runs (Sentinel eval and others).
 *
 * Gated by LANGFUSE_ENABLED=1 plus LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY.
 * One deterministic trace id per (run_out_dir, task_id) so spec extraction
 * (Python) and executor/planner (Node) land on the same trace.
 */
import { createHash } from "crypto";
import { Langfuse } from "langfuse";
import type { LangfuseTraceClient } from "langfuse";

let client: Langfuse | null = null;

export function isLangfuseEnabled(): boolean {
  if (process.env.LANGFUSE_ENABLED !== "1") return false;
  return Boolean(process.env.LANGFUSE_PUBLIC_KEY && process.env.LANGFUSE_SECRET_KEY);
}

export function makeTraceId(runOutDir: string, taskId: string): string {
  const seed = `${runOutDir}:${taskId}`;
  return createHash("sha256").update(seed).digest("hex").slice(0, 32);
}

export function langfuseHost(): string {
  return (process.env.LANGFUSE_HOST || "https://cloud.langfuse.com").replace(/\/$/, "");
}

export function langfuseTraceUrl(traceId: string, projectId?: string | null): string {
  const host = langfuseHost();
  if (projectId) return `${host}/project/${projectId}/traces/${traceId}`;
  return `${host}/trace/${traceId}`;
}

function getClient(): Langfuse {
  if (!client) {
    client = new Langfuse({
      publicKey: process.env.LANGFUSE_PUBLIC_KEY!,
      secretKey: process.env.LANGFUSE_SECRET_KEY!,
      baseUrl: langfuseHost(),
    });
  }
  return client;
}

export async function shutdownLangfuse(): Promise<void> {
  if (client) {
    try {
      await client.shutdownAsync();
    } catch {}
    client = null;
  }
}

export interface TaskTraceMeta {
  task_id: string;
  run_out_dir: string;
  notes?: string;
  executor_model?: string;
  planner_model?: string | null;
}

export class LangfuseTaskTracer {
  readonly traceId: string;
  readonly trace: LangfuseTraceClient;
  private executorTurn = 0;
  private plannerTurn = 0;

  private constructor(trace: LangfuseTraceClient, traceId: string) {
    this.trace = trace;
    this.traceId = traceId;
  }

  static start(meta: TaskTraceMeta, existingTraceId?: string | null): LangfuseTaskTracer | null {
    if (!isLangfuseEnabled()) return null;
    const traceId = existingTraceId || makeTraceId(meta.run_out_dir, meta.task_id);
    const lf = getClient();
    const trace = lf.trace({
      id: traceId,
      name: `scribe/${meta.task_id}`,
      sessionId: meta.run_out_dir,
      tags: ["scribe", "sentinel_eval"],
      metadata: {
        task_id: meta.task_id,
        run_out_dir: meta.run_out_dir,
        notes: meta.notes ?? "",
        executor_model: meta.executor_model ?? "",
        planner_model: meta.planner_model ?? "",
      },
      input: { task_id: meta.task_id },
    });
    const tracer = new LangfuseTaskTracer(trace, traceId);
    return tracer;
  }

  logExecutorGeneration(args: {
    model: string;
    inputTokens: number;
    outputTokens: number;
    inputPreview?: string;
    outputPreview?: string;
    toolNames?: string[];
  }): void {
    if (args.inputTokens <= 0 && args.outputTokens <= 0) return;
    this.executorTurn += 1;
    const gen = this.trace.generation({
      name: `executor/turn-${this.executorTurn}`,
      model: args.model,
      input: args.inputPreview?.slice(0, 4000) ?? "",
      metadata: {
        role: "executor",
        ...(args.toolNames?.length ? { tools: args.toolNames } : {}),
      },
    });
    gen.end({
      output: args.outputPreview?.slice(0, 4000) ?? "",
      usage: {
        promptTokens: args.inputTokens,
        completionTokens: args.outputTokens,
        totalTokens: args.inputTokens + args.outputTokens,
      },
    });
  }

  /** Tool-only executor step (no LLM usage on this message_end — common on OpenRouter). */
  logExecutorToolTurn(args: { toolNames: string[]; outputPreview?: string }): void {
    if (!args.toolNames.length) return;
    this.executorTurn += 1;
    const span = this.trace.span({
      name: `executor/turn-${this.executorTurn} (tools)`,
      input: { tools: args.toolNames },
      metadata: { role: "executor", kind: "tool_call" },
    });
    span.end({
      output: args.outputPreview?.slice(0, 2000) ?? "",
    });
  }

  logPlannerGeneration(args: {
    model: string;
    provider: string;
    inputTokens: number;
    outputTokens: number;
    latencyMs: number;
    inputPreview?: string;
    outputPreview?: string;
  }): void {
    this.plannerTurn += 1;
    const gen = this.trace.generation({
      name: `planner/call-${this.plannerTurn}`,
      model: args.model,
      input: args.inputPreview?.slice(0, 4000) ?? "",
      metadata: { role: "planner", provider: args.provider },
    });
    gen.end({
      output: args.outputPreview?.slice(0, 4000) ?? "",
      usage: {
        promptTokens: args.inputTokens,
        completionTokens: args.outputTokens,
        totalTokens: args.inputTokens + args.outputTokens,
      },
      metadata: { latency_ms: args.latencyMs },
    });
  }

  finish(args: {
    status: "ok" | "error";
    outputPreview?: string;
    metadata?: Record<string, unknown>;
  }): void {
    this.trace.update({
      output: args.outputPreview?.slice(0, 8000) ?? "",
      metadata: {
        status: args.status,
        ...(args.metadata ?? {}),
      },
    });
  }
}
