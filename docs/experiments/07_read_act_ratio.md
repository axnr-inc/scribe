# 07 — Read vs Act ratio analysis on Kimi K2.6 DABStep traces

**Question**: Bird-Interact found that agents concentrate ~61% of actions in `submit` + `ask` (trial-and-error execution and user clarification) and **under-use** the cheaper read-the-environment tools (`retrieve_knowledge`, `get_schema`, `retrieve_column_meaning`). They framed this as **pre-training bias toward guess-and-check over reading the environment**.

Does the same bias hold for Kimi K2.6 running our DABStep harness?

**Short answer: NO. Kimi reads more than it acts.** The Bird-Interact framing does not transfer to our setup. The bottleneck is somewhere else.

## Method

We have full session logs for 450 Kimi DABStep runs (under `sandbox/dabstep_full_*` and `dabstep_full_resume_*`). Each `run_python` tool call was classified by inspecting its `code` argument with regex patterns:

| Tag | Trigger |
|---|---|
| `READ_DOC` | Opens `manual.md`, `payments-readme.md`, `fees.json`, `merchant_data.json`, etc. |
| `READ_SCHEMA` | `.columns`, `.dtypes`, `.head()`, `.info()`, `.describe()`, `.sample()`, `.shape` |
| `READ_INSPECT` | `print(type(...))`, `print(len(...))`, `.keys()`, `.items()`, json indent-dumps |
| `ACT_COMPUTE` | `.groupby`, `.agg`, `.merge`, `.sum/mean/count`, `.value_counts`, `.pivot`, `.apply`, `.transform`, `.sort_values`, `.query`, etc. |

Each call also gets a **primary label**:
- `ACT` if any `ACT_COMPUTE` signal is present (intent is to compute, even if it also reads)
- `READ` if any `READ_*` tag and no `ACT_COMPUTE`
- `DIAGNOSTIC` otherwise (short prints, variable creation, no read/act signal)

Analysed 446 of 450 tasks (4 skipped — no session log or no run_python calls).

## Headline numbers

**Overall (446 tasks, 5,744 run_python calls):**

| Primary label | Calls | % |
|---|---|---|
| **READ** | 2,267 | **39.5%** |
| **ACT** | 1,519 | **26.4%** |
| DIAGNOSTIC | 1,958 | 34.1% |

**Tag-level (per-call instances; a single call can have multiple tags):**

| Tag | Instances | % of all calls |
|---|---|---|
| `READ_DOC` (opens manual / readme / fees.json) | 1,448 | 25.2% |
| `READ_INSPECT` | 1,170 | 20.4% |
| `READ_SCHEMA` | 872 | 15.2% |
| `ACT_COMPUTE` | 1,519 | 26.4% |

**Read : Act ratio per task** — mean **1.79**, median **1.50**. Kimi reads ~1.5–1.8× as often as it acts.

**Tasks that touched manual.md / readme / fees.json at least once**: **435 / 446 = 97.5%**.

**First-action pattern (what does Kimi do BEFORE its first ACT call?):**

| Pattern | Tasks | % |
|---|---|---|
| `doc_read_first` (manual / readme / fees.json read before any compute) | 345 | **77.4%** |
| `no_act_at_all` (never reached a compute step) | 94 | 21.1% |
| `schema_or_inspect_first` (read schema/structure but not docs) | 6 | 1.3% |
| `jumped_straight_to_act` (computed without any prior reading) | **1** | **0.2%** |

**Only 1 task out of 446 jumped straight to compute.** Kimi essentially always reads first.

## Comparison with Bird-Interact

| Metric | Bird-Interact agents | Kimi on our DABStep harness |
|---|---|---|
| Action-class share (submit+ask analog: our `ACT`) | **~61%** | **26.4%** |
| Read-class share (retrieve_knowledge / get_schema / retrieve_column_meaning analog: our `READ`) | ~39% | **39.5%** + 34.1% diagnostic = 73.6% non-act |
| "Jumps straight to acting without reading" | yes — under-uses retrieval | **0.2% (1/446 tasks)** |

**Conclusion**: the pre-training-bias-toward-action framing does not transfer to Kimi in our setup. Two structural reasons:

1. **Our system prompt explicitly nudges toward reading.** `src/prompts/dabstep.yaml`'s "Required workflow" tells the agent: *"ALWAYS read the relevant documentation FIRST, in its own run_python call, before any data loading."* This bias was baked in by hand. So if anything, our setup is the opposite of "let the model do what it wants."
2. **Our read tool is coarse, not granular.** Bird-Interact's `retrieve_knowledge` / `retrieve_column_meaning` return one entity per call — a thoughtful agent makes 5–10 retrieval calls. Our `open(manual.md).read()` returns the whole document in one shot, so a single read is sufficient. The COUNT of read calls is not comparable.

## Passed vs Failed — is the failure mode "didn't read enough"?

| | Passed (n=222) | Failed (n=224) |
|---|---|---|
| READ share of calls | 42.9% | 37.6% |
| ACT share of calls | 29.7% | 24.7% |
| DIAGNOSTIC share of calls | 27.4% | **37.7%** |
| `doc_read_first` | 76.1% | 78.6% |
| Touched manual.md at all | 95.9% | **99.1%** |
| Read:Act ratio (mean per task) | 1.61 | **1.97** |

**Counterintuitive but clear**: failed tasks read MORE, not less. They have a higher READ:ACT ratio and they touch manual.md slightly MORE often than passed tasks. The biggest delta is in DIAGNOSTIC calls — **failed trajectories spend 37.7% of their calls on diagnostic prints, vs 27.4% for passed**. That's the signature of a trace stuck in debug-print loops, not of an agent that "didn't bother to read."

So Kimi's failure isn't "didn't read" — it's:
- **Reads but doesn't extract the right rule** (interpretation failure), OR
- **Reads correctly but applies wrong in the compute step** (translation failure), OR
- **Reads, computes, gets a confusing result, and spirals into print-debug loops** without recovering (debug-loop failure).

The 37.7% diagnostic share in failures is the smoking gun for the third mode.

## Per-topic patterns on failures (where doc-reading discipline does/doesn't predict success)

```
FAILED tasks                                           PASSED tasks
topic           n   doc_first  jumped  touched_manual  |  n   doc_first  jumped  touched_manual
fee_rule        56   89.3%      0%      100%          |  32  100.0%      0%      100%
date_specific   41   95.1%      0%      100%          |  41   95.1%      0%      100%
delta_what_if   58   65.5%      0%      100%          |  62   45.2%      0%       98.4%
aci_format      45   68.9%      0%      100%          |  26   88.5%      0%      100%
fraud_metric     8   75.0%      0%       75.0%        |  10   90.0%      0%      100%
merchant_lookup  8   75.0%      0%      100%          |   —   —          —        —
```

Interesting per-topic readings:

- **fee_rule**: 100% of passes read doc first vs 89.3% of failures. The 10.7% gap (6 failed tasks) is consistent with the "didn't read first" hypothesis FOR FEE_RULE SPECIFICALLY — but the absolute effect is small (6 tasks out of 56 failures).
- **delta_what_if**: failures read doc first MORE than passes (65.5% vs 45.2%). Doc-reading discipline does NOT predict success here. The failure mechanism on delta_what_if is something else (likely: counterfactual reasoning over two scenarios, not text comprehension).
- **aci_format**: passes read doc first more (88.5% vs 68.9%). Here doc-reading discipline IS correlated with success.
- **date_specific**: identical (95.1% in both). Doc-reading is universal but not differentiating.

## What this re-frames in our broader analysis

1. The narrative "Kimi fails because it doesn't read the manual" is **wrong**. Kimi reads. The failure is downstream of reading.

2. The narrative "agents have pre-training bias toward acting" (Bird-Interact's framing) does not generalise to our setup. **Their finding may be specific to Bird-Interact's tool affordances** (granular retrieval, conversational `ask` step) rather than a universal pre-training property.

3. Our memo `01_iter_capped.md` and `02_experiment_F_results.md` hypothesised that iter_capped sometimes contains the correct answer buried in the trace. This is consistent with the diagnostic-loop finding here: 37.7% of failed calls are diagnostic prints, which would buildup in iter_capped traces specifically.

4. For SFT curation: optimising for "more reading" is the wrong axis. The high-value training signal is **clean read → correct interpretation → focused compute → committed answer**. The 222 passed Kimi tasks already have this shape; the 224 failed ones don't, but not because of reading deficits.

## Implications for the memory-grafting experiment (proposed next)

Memory grafting from Bird-Interact transplants the **clarification/planning** stage from a better model. Translating to our setup, the analog would graft a **plan / rule-extraction** output — i.e. "Here are the fee rules that apply, here are the columns to filter on" — into Kimi.

Given the read/act finding here, the bottleneck for fee_rule failures isn't reading — it's **rule extraction and rule application**. So a useful grafting target would be:

> Have Sonnet 4.6 read manual.md + fees.json and emit a STRUCTURED, MACHINE-READABLE specification of which rules apply to the task (e.g. "filter on merchant=X, monthly_volume_tier=Y, ACI in {A,B,C}, then sum fee.rate × payment.amount"). Inject that into Kimi as additional system context. Then see if Kimi can execute the plan.

If Kimi succeeds with grafted RULE EXTRACTION → bottleneck confirmed at rule extraction (interpretation of natural-language rules into formal predicates).

If Kimi still fails → bottleneck is at COMPUTE, not at rule extraction.

This is a sharper experiment than "graft the clarification" because Kimi doesn't have a clarification deficit in our setup.

## Caveats

- Regex-based classifier; misses code that does compute via non-pandas idioms (e.g. raw Python loops with aggregation). Manual spot-check on 5 samples suggested classification is ~90% accurate.
- `READ_DOC` regex is anchored to the specific filenames in our DABStep context dir. If Kimi reads via a different path or string, we'd miss it.
- The "DIAGNOSTIC" bucket may be over-broad — includes variable-creation calls that prepare for later compute. Still, the 37.7% vs 27.4% pass/fail split in DIAGNOSTIC is large and unlikely to be an artifact.
- 4 of 450 tasks had no run_python calls and were skipped.

## Artefacts

- Script: `scripts/read_act_analysis.py`
- Per-task data: `analysis/research_notes/07_read_act_data.json` (446 rows, ~125KB)
- This memo: `analysis/research_notes/07_read_act_ratio.md`
