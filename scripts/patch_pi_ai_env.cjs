#!/usr/bin/env node
/**
 * SCRIBE — patch pi-ai's provider→env-var map to include the three Kimi
 * inference providers we use (fireworks, fireworks2, baseten). pi-ai's
 * env-api-keys.js hardcodes a known-provider list; we extend it.
 *
 * Idempotent — re-running this script is safe. Run after every `npm install`.
 */
const fs = require("fs");
const path = require("path");

const TARGET = path.join(
  __dirname,
  "..",
  "node_modules",
  "@mariozechner",
  "pi-ai",
  "dist",
  "env-api-keys.js"
);

if (!fs.existsSync(TARGET)) {
  console.error(
    "ERROR: pi-ai env-api-keys.js not found at", TARGET,
    "\n  Run `npm install` first."
  );
  process.exit(1);
}

const original = fs.readFileSync(TARGET, "utf-8");

const PATCH_ENTRIES = `        baseten: "BASETEN_API_KEY",\n        fireworks: "FIREWORKS_API_KEY",\n        fireworks2: "FIREWORKS_API_KEY2",\n`;

// If already patched, no-op.
if (original.includes("BASETEN_API_KEY") &&
    original.includes("FIREWORKS_API_KEY") &&
    original.includes("FIREWORKS_API_KEY2")) {
  console.log("pi-ai env-api-keys.js already patched. No-op.");
  process.exit(0);
}

// Find the closing `};` after `"kimi-coding": "KIMI_API_KEY",` and insert
// our entries before it. (kimi-coding is the last builtin entry in pi-ai.)
const ANCHOR = '"kimi-coding": "KIMI_API_KEY",';
if (!original.includes(ANCHOR)) {
  console.error("ERROR: anchor line not found; pi-ai version may have changed.");
  process.exit(2);
}

const patched = original.replace(
  ANCHOR + "\n    };",
  ANCHOR + "\n" + PATCH_ENTRIES + "    };"
);

if (patched === original) {
  console.error("ERROR: patch did not apply; investigate env-api-keys.js by hand.");
  process.exit(3);
}

fs.writeFileSync(TARGET, patched);
console.log("pi-ai env-api-keys.js patched (+baseten, +fireworks, +fireworks2).");
