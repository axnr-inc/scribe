/**
 * `onPayload` hook — runs RIGHT BEFORE pi-ai sends the request payload to the
 * provider. We tag the final `system` block and the final `tools` block with
 * Anthropic's `cache_control: { type: "ephemeral" }` so they get cached for
 * 5 minutes (Anthropic prompt caching).
 *
 * Effect on cost: on the second and subsequent turns of the SAME task, the
 * large system prompt + tool schema are billed at cache-hit rate (10% of
 * normal input price), not full input rate. Since system prompts on DABStep
 * grafted runs are non-trivial (the spec is appended to the user message but
 * the system prompt itself is ~2 KB), this is a meaningful saving.
 *
 * Only enabled when `config.model.prompt_caching: true` in the YAML config
 * (which is true for `*_opus.yaml` and `*_haiku.yaml`; false for Kimi via
 * OpenRouter, which doesn't expose Anthropic's cache_control field).
 *
 * Wired in `runOneTask` (src/run.ts) — `onPayload: makeOnPayload()`.
 */
import type { Model } from "@mariozechner/pi-ai";

export function makeOnPayload(): (payload: unknown, model: Model<any>) => unknown {
  return (payload: unknown, _model: Model<any>): unknown => {
    if (!payload || typeof payload !== "object") return payload;
    const p = payload as Record<string, unknown>;
    injectCacheControl(p, "system");
    injectCacheControl(p, "tools");
    return p;
  };
}

function injectCacheControl(payload: Record<string, unknown>, field: string): void {
  const arr = payload[field];
  if (!Array.isArray(arr) || arr.length === 0) return;
  const last = arr[arr.length - 1];
  if (last && typeof last === "object") {
    (last as Record<string, unknown>).cache_control = { type: "ephemeral" };
  }
}
