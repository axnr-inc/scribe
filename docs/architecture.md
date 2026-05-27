# SCRIBE architecture

SCRIBE — **S**pec-**C**onditioned **R**eAct with **I**nline **B**ackreview **E**scalation — is a three-role decomposition of a data-analysis agent. Each role is played by a model chosen for that role, and a frozen-spec contract carries between them.

## Roles

### 1. Spec Agent (frontier model)

- Reads the task, the source documents (manual.md, schemas, rule catalogs), and the question.
- Emits a structured `computation_plan` — an ordered list of high-level steps describing the algorithm + the `expected_output_format`.
- **The spec is frozen** — the executor cannot rewrite it. It is the *contract* between roles.
- Default model: GPT-5 via OpenRouter.
- Code: `scripts/extract_specs.py` (`call_anthropic` / `call_openrouter`).

### 2. ReAct Executor (smaller open-weights model)

- Reads the spec + has access to a Python REPL via the `run_python` tool.
- Runs a standard ReAct loop: think → act (run_python) → observe → repeat → final answer.
- Has the `ask_spec_agent` tool: when uncertain, it sends a STRUCTURED SUMMARY of its work to the Review Agent.
- Default model: Kimi-K2.6 via Fireworks (or Baseten, or OpenRouter).
- Code: `src/run.ts` + `src/harness/tools/run_python.ts`.

### 3. Review Agent (same frontier model as Spec; same session continuation)

- Activated when the executor calls `ask_spec_agent`.
- Continues the same conversation seeded by the Spec Agent (session continuity preserves the docs/spec context).
- Reads source documents via `read_file` to verify the executor's assumptions against the *manual*, not just the *spec*.
- Either: (a) confirms with `[No flag]` + doc quotes, or (b) flags a mistake with `[Flag: mistake detected]` + a *revised spec*.
- Default model: GPT-5 via OpenRouter (same as Spec — same session).
- Code: `src/harness/tools/ask_planner.ts`.

## Asymmetric model assignment

The key architectural lever: the frontier model (GPT-5) runs only on the Spec + Review roles — both involve reading documents and reasoning about contracts. The ReAct Executor — which generates the bulk of the tokens (run_python calls, intermediate code) — runs on a smaller open-weights model (Kimi-K2.6).

This is the cost-vs-accuracy lever that lets SCRIBE match or beat a single-model-throughout pipeline (e.g. DS-STAR with GPT-5 throughout) at substantially lower per-task cost.

## Failure-mode mapping

The name *Spec-Conditioned ReAct with Inline Backreview Escalation* encodes three architectural fixes, one per failure-mode class observed in our taxonomy (see `docs/failure_analysis/`):

| Failure mode | Architectural fix | Role responsible |
|---|---|---|
| **Definition-shift** — model quotes manual correctly, then writes code that contradicts the quote | **Spec freeze**: a separate agent commits the formula to text; executor can't drift mid-trajectory | Spec Agent |
| **Action-bias** — executor commits to a wrong interpretation without flagging ambiguity | **Backreview**: executor's `ask_spec_agent` call sends a STRUCTURED SUMMARY; review reads docs again | Review Agent |
| **Iteration-cap** — executor grinds past max_iter without progress | **Escalation**: structured-summary protocol gives the executor a productive exit when stuck | Both |

## Spec format

```json
{
  "merchant": { /* extracted attributes */ },
  "filters": { /* date/aggregation/grouping */ },
  "matching_logic": "pandas-notation predicates with wildcard handling",
  "computation_plan": [
    "Step 1: ...",
    "Step 2: ...",
    "Step N: print f-string with target precision."
  ],
  "expected_output_format": "Comma-separated list of N integers ..."
}
```

The full schema is defined in `scripts/extract_specs.py` (`SAVE_SPEC_TOOL.input_schema`).

## Escalation protocol

When the executor calls `ask_spec_agent`, it sends a structured summary using these five headers verbatim:

```
# Step
[Which step of the computation_plan you're on.]

# Computed so far
[Concrete numbers / dataframes / sample values.]

# Pseudo-code
[The pandas you intend to run.]

# Assumptions
[Bullet-list each assumption, especially:
 - null/wildcard semantics
 - which aggregation
 - tie-breaking rules]

# Question
[Your specific question.]
```

The Review Agent has two reply modes:

- **`[No flag]`** + doc quotes — the executor's interpretation is consistent with the docs.
- **`[Flag: mistake detected]`** + doc quote + revised spec — the executor was wrong; the revised spec replaces the original from this turn onward.

The protocol enforces (a) executor self-summarization (catches a real-conscious uncertainty even when the executor would otherwise blunder ahead), and (b) review re-grounding via mandatory `read_file` (catches errors the executor wouldn't even know to ask about).

## Why this works

The architecture is motivated by an empirical observation: a single LLM doing ReAct on docs-heavy data analysis fails predictably on **definition-shift** — the model quotes the manual correctly in its `thinking` block and then writes pandas code that implements a different formula. By splitting the "plan from docs" role (Spec) and the "execute pandas" role (Executor), and by giving the Executor a contracted-but-not-self-overrideable spec, definition-shift is structurally eliminated for that step.

Backreview adds a second mechanism: the Executor *can* flag uncertainty, but our prior failure analysis showed that ReAct agents are poor at self-flagging (cf. `docs/experiments/06_minimal_prompt_experiment.md`). So we add a STRUCTURED SUMMARY contract — every `ask_spec_agent` call must lay out assumptions explicitly — and a separate model (Review) re-grounds against docs. Even when the Executor's question is wrong, the Review path's mandatory `read_file` discipline tends to surface the right answer.

## What SCRIBE does NOT do (yet) — pre-hoc disambiguation

SCRIBE is *post-hoc*: ambiguity is resolved AFTER the executor encounters it. The residual failure analysis (`docs/failure_analysis/`) shows that ~30% of remaining failures are "definition-shift in the spec itself" — the Spec Agent commits to a wrong default when the docs are silent on aggregation choice (volume-weighted vs count-weighted, etc.). A pre-hoc disambiguation role — call it the *Probe Agent* — would generate 2–3 candidate interpretations, test each on a small data probe, and commit to the one whose result-shape matches the question's `expected_output_format`. This is **future work**, documented in the paper's Discussion section as SCRIBE+.
