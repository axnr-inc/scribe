import { getModel } from "@mariozechner/pi-ai";
import type { Api, Model } from "@mariozechner/pi-ai";
import type { HarnessConfig } from "./config.js";

/** HF router catalog entry used only as OpenAI-compat / cost defaults for arbitrary HF model IDs */
const HF_COMPAT_TEMPLATE_ID = "Qwen/Qwen3-Coder-480B-A35B-Instruct";
/** OpenRouter catalog entry templated for arbitrary OpenRouter model IDs. Reasoning:true so thinking models work; harness skips the param when thinking=off anyway. */
const OPENROUTER_COMPAT_TEMPLATE_ID = "deepseek/deepseek-v3.2";

export function resolveHarnessModel(config: HarnessConfig): Model<Api> {
  const provider = config.model.provider || "anthropic";
  const modelId = config.model.model;

  const registered = getModel(provider as any, modelId as any);
  if (registered) return registered as Model<Api>;

  if (provider === "huggingface") {
    const template = getModel("huggingface", HF_COMPAT_TEMPLATE_ID as any);
    if (!template) {
      throw new Error(`Missing HF catalog template "${HF_COMPAT_TEMPLATE_ID}" — update @mariozechner/pi-ai or pick another template in src/model_resolver.ts`);
    }
    return {
      ...template,
      id: modelId,
      name: modelId,
      reasoning: false,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    };
  }

  if (provider === "openrouter") {
    const template = getModel("openrouter", OPENROUTER_COMPAT_TEMPLATE_ID as any);
    if (!template) {
      throw new Error(`Missing OpenRouter catalog template "${OPENROUTER_COMPAT_TEMPLATE_ID}" — update @mariozechner/pi-ai or pick another template in src/model_resolver.ts`);
    }
    return {
      ...template,
      id: modelId,
      name: modelId,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    };
  }

  if (provider === "anthropic") {
    // Fallback for Anthropic models newer than pi-ai's pinned catalog
    // (e.g. claude-opus-4-7, claude-opus-4-8 when on an older pi-ai).
    // Clone the closest known Anthropic template and override the model id;
    // pi-ai's anthropic provider sends the model string as-is to the API.
    const ANTHROPIC_COMPAT_TEMPLATE_ID = "claude-opus-4-6";
    const template = getModel("anthropic", ANTHROPIC_COMPAT_TEMPLATE_ID as any);
    if (!template) {
      throw new Error(`Missing Anthropic catalog template "${ANTHROPIC_COMPAT_TEMPLATE_ID}" — update @mariozechner/pi-ai or pick another template in src/model_resolver.ts`);
    }
    return {
      ...template,
      id: modelId,
      name: modelId,
      // Opus 4.7/4.8 pricing per shared/models.md (May 2026): $5/$25 per 1M, cache read 0.1x, write 1.25x.
      cost: { input: 5.0, output: 25.0, cacheRead: 0.5, cacheWrite: 6.25 },
    };
  }

  if (provider === "baseten" || provider === "fireworks" || provider === "fireworks2") {
    // Reuse the OpenRouter openai-completions template, override baseUrl + provider.
    // env-api-keys.js (node_modules patch) maps baseten→BASETEN_API_KEY,
    // fireworks→FIREWORKS_API_KEY, fireworks2→FIREWORKS_API_KEY2.
    const template = getModel("openrouter", OPENROUTER_COMPAT_TEMPLATE_ID as any);
    if (!template) {
      throw new Error(`Missing OpenRouter catalog template "${OPENROUTER_COMPAT_TEMPLATE_ID}"`);
    }
    const baseUrl =
      provider === "baseten"
        ? "https://inference.baseten.co/v1"
        : "https://api.fireworks.ai/inference/v1";
    return {
      ...template,
      id: modelId,
      name: modelId,
      provider: provider as any,
      baseUrl,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    };
  }

  throw new Error(`Unknown model "${modelId}" for provider "${provider}". Add it to pi-ai's catalog, or use provider "huggingface" with HF_TOKEN for router-hosted models.`);
}
