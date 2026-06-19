#!/usr/bin/env node
/**
 * SCRIBE — patch pi-ai after npm install:
 *  1. env-api-keys.js — add fireworks / fireworks2 / baseten providers
 *  2. anthropic.js — Opus 4.7/4.8 need adaptive thinking (budget_tokens → 400)
 *  3. models.js — supportsXhigh for Opus 4.7/4.8
 *
 * Idempotent — re-running this script is safe. Run after every `npm install`.
 */
const fs = require("fs");
const path = require("path");

const PI_AI_DIST = path.join(__dirname, "..", "node_modules", "@mariozechner", "pi-ai", "dist");
const ENV_KEYS = path.join(PI_AI_DIST, "env-api-keys.js");
const ANTHROPIC = path.join(PI_AI_DIST, "providers", "anthropic.js");
const MODELS = path.join(PI_AI_DIST, "models.js");

function patchEnvApiKeys() {
  if (!fs.existsSync(ENV_KEYS)) {
    console.error("ERROR: pi-ai env-api-keys.js not found — run npm install first.");
    process.exit(1);
  }
  const original = fs.readFileSync(ENV_KEYS, "utf-8");
  const PATCH_ENTRIES = `        baseten: "BASETEN_API_KEY",\n        fireworks: "FIREWORKS_API_KEY",\n        fireworks2: "FIREWORKS_API_KEY2",\n`;
  if (original.includes("FIREWORKS_API_KEY2")) {
    console.log("pi-ai env-api-keys.js already patched.");
    return;
  }
  const ANCHOR = '"kimi-coding": "KIMI_API_KEY",';
  if (!original.includes(ANCHOR)) {
    console.error("ERROR: env-api-keys anchor not found; pi-ai version may have changed.");
    process.exit(2);
  }
  const patched = original.replace(ANCHOR + "\n    };", ANCHOR + "\n" + PATCH_ENTRIES + "    };");
  if (patched === original) {
    console.error("ERROR: env-api-keys patch did not apply.");
    process.exit(3);
  }
  fs.writeFileSync(ENV_KEYS, patched);
  console.log("pi-ai env-api-keys.js patched (+baseten, +fireworks, +fireworks2).");
}

function patchAnthropicOpus47() {
  if (!fs.existsSync(ANTHROPIC)) {
    console.warn("WARN: pi-ai anthropic.js not found — skipping Opus 4.7 patch.");
    return;
  }
  let src = fs.readFileSync(ANTHROPIC, "utf-8");
  const OLD_ADAPTIVE = `function supportsAdaptiveThinking(modelId) {
    // Opus 4.6 and Sonnet 4.6 model IDs (with or without date suffix)
    return (modelId.includes("opus-4-6") ||
        modelId.includes("opus-4.6") ||
        modelId.includes("sonnet-4-6") ||
        modelId.includes("sonnet-4.6"));
}`;
  const NEW_ADAPTIVE = `function supportsAdaptiveThinking(modelId) {
    // Opus/Sonnet 4.6+ use adaptive thinking; budget_tokens 400s on 4.7/4.8.
    return (modelId.includes("opus-4-6") ||
        modelId.includes("opus-4.6") ||
        modelId.includes("opus-4-7") ||
        modelId.includes("opus-4.7") ||
        modelId.includes("opus-4-8") ||
        modelId.includes("opus-4.8") ||
        modelId.includes("sonnet-4-6") ||
        modelId.includes("sonnet-4.6"));
}`;
  if (src.includes('modelId.includes("opus-4-7")')) {
    console.log("pi-ai anthropic.js Opus 4.7 patch already applied.");
  } else if (src.includes(OLD_ADAPTIVE)) {
    src = src.replace(OLD_ADAPTIVE, NEW_ADAPTIVE);
    const OLD_XHIGH = `        case "xhigh":
            return modelId.includes("opus-4-6") || modelId.includes("opus-4.6") ? "max" : "high";`;
    const NEW_XHIGH = `        case "xhigh":
            return (modelId.includes("opus-4-6") || modelId.includes("opus-4.6") ||
                modelId.includes("opus-4-7") || modelId.includes("opus-4.7") ||
                modelId.includes("opus-4-8") || modelId.includes("opus-4.8")) ? "max" : "high";`;
    if (src.includes(OLD_XHIGH)) {
      src = src.replace(OLD_XHIGH, NEW_XHIGH);
    }
    fs.writeFileSync(ANTHROPIC, src);
    console.log("pi-ai anthropic.js patched (Opus 4.7/4.8 adaptive thinking).");
  } else {
    console.warn("WARN: anthropic.js supportsAdaptiveThinking block not found — patch manually.");
  }
}

function patchModelsXhigh() {
  if (!fs.existsSync(MODELS)) return;
  let src = fs.readFileSync(MODELS, "utf-8");
  const OLD = `    if (model.id.includes("opus-4-6") || model.id.includes("opus-4.6")) {
        return true;
    }`;
  const NEW = `    if (model.id.includes("opus-4-6") || model.id.includes("opus-4.6") ||
        model.id.includes("opus-4-7") || model.id.includes("opus-4.7") ||
        model.id.includes("opus-4-8") || model.id.includes("opus-4.8")) {
        return true;
    }`;
  if (src.includes('model.id.includes("opus-4-7")')) {
    console.log("pi-ai models.js xhigh patch already applied.");
  } else if (src.includes(OLD)) {
    fs.writeFileSync(MODELS, src.replace(OLD, NEW));
    console.log("pi-ai models.js patched (supportsXhigh for Opus 4.7/4.8).");
  }
}

patchEnvApiKeys();
patchAnthropicOpus47();
patchModelsXhigh();
