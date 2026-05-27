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
