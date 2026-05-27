# OpenRouter

## Status
The repo is **not** explicitly wired for OpenRouter (no variant in `config.yaml`), but it works out of the box because the `pi-ai` dependency ships an `openrouter` provider with a full model catalog. `OPENROUTER_API_KEY` is already present in `.env`.

## Configure
Pick any OpenRouter catalog id (e.g. `anthropic/claude-sonnet-4.5`, `openai/gpt-5`, `google/gemini-2.5-pro`) and set it in `model_config.yaml` or `config.yaml`:

```yaml
model:
  provider: openrouter
  model: anthropic/claude-sonnet-4.5
  prompt_caching: false   # Anthropic-direct only — keep false for OpenRouter
```

Or override at the command line without editing files:

```bash
npx tsx src/run.ts adhoc -d <dataset> -q "..." \
  --override '{"model.provider":"openrouter","model.model":"anthropic/claude-sonnet-4.5","model.prompt_caching":false}'
```

If you use a variant (`-v`), put the same fields under `model:` inside the variant block in `config.yaml` (see the `dabstep_qwen25_coder_hf` variant for the pattern).

## Run
```bash
npx tsx src/run.ts list-datasets         # see available datasets
npx tsx src/run.ts list-variants         # see configured variants
npx tsx src/run.ts adhoc -d <dataset> -q "your question"
npx tsx src/run.ts start -d <dataset> -v <variant>   # batch run
```

## Notes
- Model id must exist in `pi-ai`'s OpenRouter catalog (`node_modules/@mariozechner/pi-ai/dist/models.generated.js`). Unknown ids throw unless `provider: huggingface` (which has a fallback template).
- `prompt_caching: true` only works on Anthropic-direct; leave it `false` for OpenRouter.
- The default `python3` on macOS lacks `pandas`. For the `dabstep` dataset, override `connection.python_bin` to a Python with `pandas`/`numpy` (e.g. a conda env): `"connection.python_bin":"/Users/suraj/miniconda3/envs/bench/bin/python3"`.
- `config.yaml` defines variants — if any variant exists, `adhoc`/`start` require `-v <variant>`. For OpenRouter ad-hoc runs, pick the closest variant (e.g. `dabstep_qwen25_coder_hf` for dabstep) and override the model fields.

## Verified working command (qwen3-coder on dabstep)
Single-question (adhoc):
```bash
npx tsx src/run.ts adhoc \
  -d dabstep \
  -v dabstep_qwen25_coder_hf \
  -q "Which issuing country has the highest number of transactions? Answer with just the country code." \
  --override '{"model.provider":"openrouter","model.model":"qwen/qwen3-coder","model.prompt_caching":false,"connection.python_bin":"/Users/suraj/miniconda3/envs/bench/bin/python3"}'
```

Full dev set (batch):
```bash
ls sandbox | grep '^dabstep_local_session_' | sort > /tmp/dabstep_sandbox_before.txt

npx tsx src/run.ts start \
  -d dabstep \
  -v dabstep_qwen25_coder_hf \
  -n "openrouter qwen3-coder full dev run" \
  --override '{"model.provider":"openrouter","model.model":"qwen/qwen3-coder","model.prompt_caching":false,"connection.python_bin":"/Users/suraj/miniconda3/envs/bench/bin/python3","execution.max_iterations":30}'

python3 scripts/score_dabstep.py --before /tmp/dabstep_sandbox_before.txt
```

## DABStep prompt + tool affordance (May 2026)
The `src/prompts/dabstep.yaml` prompt was rewritten to:
- Enumerate every file in `CONTEXT_DIR` with a one-liner.
- Mandate reading `manual.md` for rule/fee tasks and `payments-readme.md` before any `payments.csv` query, each in its own `run_python` call.
- Force schema inspection (`print(df.columns, df.dtypes, df.head(2))`) before filtering.
- Ban row-by-row iteration over `payments.csv` (≈3M rows; REPL has a 5-minute kill timeout).
- Surface the literal `CONTEXT_DIR` value via `{{CONTEXT_DIR}}` substitution and tell the model not to redefine `context_path`.

`makeReadFileTool(sandboxDir, extraReadRoots[])` (`src/harness/tools/read_file.ts`) now accepts an extra-roots allow-list; `src/run.ts` passes `[config.connection.context_dir]` when `read_file: true`. Previously the tool was hard-scoped to the per-session sandbox dir, which meant it could never read any dataset file.

Effect on DABStep task 1681 (`qwen/qwen3-235b-a22b-thinking-2507`, `thinking: high`): old prompt → "Not Applicable"; new prompt → 9-of-10 expected fee IDs correct, 0 REPL timeouts.

## Storage layout
- Per-question traces: `sandbox/dabstep_<sessionHash>/sessions/normal_agent.jsonl` (or `conscious_agent.jsonl` when `context_mgmt` is on). Each line is one event: `user_message`, `tool_call`, `tool_call_result`, `assistant_response`, `assistant_thinking`.
- Python REPL preamble for that session: `sandbox/dabstep_<sessionHash>/preamble.py`.
- The user message stored in the trace includes the task `guidelines` appended after a blank line — the scorer matches by the first line (the bare task question).
- Remote logging (`@exp-logger/tracker`) is optional; without it the run uses a local tracker and prints `using local tracker fallback (no remote logging)`.

## Verifying it really hit OpenRouter
Override `globalThis.fetch` and log hostnames before calling pi-ai. Network host should be `openrouter.ai`. Resolver-level check (no network) also works:
```bash
npx tsx -e "import('./src/model_resolver.ts').then(m => console.log(m.resolveHarnessModel({model:{provider:'openrouter',model:'qwen/qwen3-coder',thinking:'off',prompt_caching:false,temperature:null,top_p:null,max_tokens:null}})))"
```
(use a small wrapper file if `tsx -e` errors on package exports.)

## Reasoning / thinking on OpenRouter
pi-ai gates the `reasoning: {effort}` request body on **both**:
1. `config.model.thinking !== "off"` (the agent converts `"off"` → undefined and skips it), and
2. The model's catalog entry having `reasoning: true` (in `node_modules/@mariozechner/pi-ai/dist/models.generated.js`).

`qwen/qwen3-coder` has `reasoning: false` → setting `thinking: high` does nothing. Confirmed thinking-capable Qwen ids on OpenRouter: `qwen/qwen3-235b-a22b-thinking-2507`, `qwen/qwen3-30b-a3b-thinking-2507`, `qwen/qwen3-max-thinking`, `qwen/qwen3-next-80b-a3b-thinking`, `qwen/qwq-32b`.

**Recipe to turn it on for one run:**
```bash
npx tsx src/run.ts adhoc \
  -d dabstep -v dabstep_qwen25_coder_hf \
  -q "<question>" \
  --override '{"model.provider":"openrouter","model.model":"qwen/qwen3-235b-a22b-thinking-2507","model.thinking":"high","model.prompt_caching":false,"connection.python_bin":"/Users/suraj/miniconda3/envs/bench/bin/python3"}'
```
Successful runs produce `assistant_thinking` events in the session jsonl (one per reasoning block).

**Verify the wire payload contains `{"reasoning":{"effort":"high"}}`** by wrapping `globalThis.fetch` and calling `complete(model, {messages:[...]}, {apiKey, reasoningEffort: "high"})`. Pass options as the THIRD arg to `complete` — putting `reasoningEffort` in the context (second arg) is silently ignored and pi-ai falls back to `"effort":"none"`.

## Adding non-OpenRouter providers to the grafting_v2 harness (Baseten, Fireworks)
Both Baseten (`https://inference.baseten.co/v1`) and Fireworks (`https://api.fireworks.ai/inference/v1`) are OpenAI-compatible and accept Bearer auth, so they plug into pi-ai's `openai-completions` provider with minimal work.

Two changes are required:

1. **Patch `node_modules/@mariozechner/pi-ai/dist/env-api-keys.js`** — add the provider→env-var mapping (pi-ai has a hardcoded `envMap`):
   ```js
   baseten: "BASETEN_API_KEY",
   fireworks: "FIREWORKS_API_KEY",
   ```
   This patch is overwritten on `npm install`; re-apply after any pi-ai upgrade.

2. **Extend `src/model_resolver.ts`** with a `baseten | fireworks` case that clones the OpenRouter openai-completions template (`deepseek/deepseek-v3.2`) and overrides `baseUrl`, `id`, `name`, `provider`. pi-ai then routes the chat-completions request to the new base URL and reads the right env var via `getEnvApiKey(model.provider)`.

3. **Config**: any harness config can now use `provider: baseten` / `provider: fireworks`. Model IDs verified working:
   - Baseten: `moonshotai/Kimi-K2.6`
   - Fireworks: `accounts/fireworks/models/kimi-k2p6`

This unblocks 3-way parallelism: OpenRouter + Baseten + Fireworks against the same DABStep tasks, sharing the same GPT-5 spec-agent via OpenRouter. Smoke test: `npx tsx scripts/smoke_provider.ts baseten moonshotai/Kimi-K2.6`.

To plug in a second Fireworks account (different rate-limit pool), add provider `fireworks2` → env `FIREWORKS_API_KEY2` to both `env-api-keys.js` and the `model_resolver.ts` branch (same baseUrl). With KEY2 wired, there are 4 independent Kimi-K2.6 channels usable in parallel: openrouter, baseten, fireworks, fireworks2.

## OpenRouter credit-tier gotchas (observed during real run)
The free/low-credit OpenRouter tier caps prompt tokens (saw ~50K cap) and `max_tokens` requested. Long DABStep hard tasks (large context loads, big list answers) hit:
- `402 Prompt tokens limit exceeded: 124619 > 50365` — needs paid credits to raise the per-request prompt cap.
- `402 This request requires more credits, or fewer max_tokens. You requested up to 4096 tokens, but can only afford N` — wallet drained; either top up or reduce `model.max_tokens`.
The harness logs these as `Agent error:` and continues to the next question, so the run finishes and produces traces for all sessions (the failed ones just have no `assistant_response` event).
