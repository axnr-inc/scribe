# DataAgentBench — Ablation Results (Executor / Planner stacks)

All numbers are **DAB stratified Pass@1**, scored with the official per-query
`validate.py`. Unless noted, runs are **54 tasks × 1 trial** with the **same
harness, same `dab_final_specs` (Opus-extracted), same `--run-index 0`,
`max_iterations=40`**, on `/Users/suraj/dab_clone`.

Reviewer = the online `ask_planner_agent` role (5-verdict cascade). Spec
extraction is a one-time Opus cost (**$8.10** total, $0.15/task) shared by every
config that reuses `dab_final_specs`.

---

## Config A — Opus 4.7, all three roles  (the SCRIBE baseline)

Executor + planner + reviewer all `claude-opus-4-7`. Native config: `thinking: xhigh`, `prompt_caching: true`.

| Metric | Value |
|---|---|
| **Pass@1** | **0.7025**  (41/54 trials) |
| Executor tokens | 13,918,662 in / 271,747 out |
| Reviewer tokens | 1,543,400 in / 46,932 out |
| Executor cost | $22.72 |
| Reviewer cost | $8.89 |
| Run cost (exec+review) | **$31.61** |
| + spec extraction | $39.71 |
| Cost / task | $0.585 run · $0.735 incl spec |
| Wall time (sum) | 85.8 min · 95.3 s/task |
| Iter-cap hits | 0 |

---

## Config B — Kimi-K2.6 executor + Opus 4.7 planner/reviewer

Executor `kimi-k2p6` (Fireworks, `thinking: null`, no caching); planner+reviewer `claude-opus-4-7`. Specs reused from Opus (identical to Config A).

| Metric | Value |
|---|---|
| **Pass@1** | **0.5492**  (33/54 trials) |
| Executor tokens | 21,418,455 in / 537,312 out |
| Reviewer tokens | 1,468,507 in / 56,656 out |
| Executor cost | $14.19 |
| Reviewer cost | $8.76 |
| Run cost (exec+review) | **$22.95** |
| + spec extraction | $31.05 |
| Cost / task | $0.425 run · $0.575 incl spec |
| Wall time (sum) | 144.8 min · 160.9 s/task |
| Iter-cap hits | 3 |

---

## Config C — GLM-5.1 planner + Kimi-K2.6 executor  (historical, NOT comparable)

Older open-stack run. **Caveats:** 51 tasks / **11 datasets (no patents)**, **GLM-extracted specs**, **pre-leakage-cleanup, pre-hardened-sandbox**, and **cost/token not tracked** (predates the per-model accounting).

| Metric | Value |
|---|---|
| **Pass@1** | **0.5236**  (27/51 trials, 11 datasets) |
| Cost / tokens / time | not captured |

---

## Comparison — accuracy vs cost vs time vs tokens

| Config | Pass@1 | Run $ | +spec $ | $/task | Exec tok (in/out) | Review tok (in/out) | Wall min | Acc/run$ |
|---|---|---|---|---|---|---|---|---|
| **A. Opus all-roles** | **0.7025** | $31.61 | $39.71 | $0.585 | 13.9M / 272K | 1.54M / 47K | 85.8 | 0.0222 |
| **B. Kimi exec + Opus planner** | 0.5492 | $22.95 | $31.05 | $0.425 | 21.4M / 537K | 1.47M / 57K | 144.8 | 0.0239 |
| C. GLM plan + Kimi exec (old) | 0.5236* | — | — | — | — | — | — | — |

\* 11 datasets, GLM specs, pre-cleanup — not comparable.

### Per-dataset Pass@1 (Config A vs Config B)

| Dataset | Opus all | Kimi+Opus | winner |
|---|---|---|---|
| agnews | 0.250 | 0.000 | Opus+ |
| bookreview | 1.000 | 1.000 | |
| crmarenapro | 0.846 | 0.769 | Opus+ |
| deps_dev_v1 | 0.500 | 0.000 | Opus+ |
| github_repos | 0.500 | 0.500 | |
| googlelocal | 1.000 | 0.750 | Opus+ |
| music_brainz_20k | 0.667 | 0.333 | Opus+ |
| pancancer_atlas | 0.667 | 0.667 | |
| patents | 0.000 | 0.000 | |
| stockindex | 1.000 | 1.000 | |
| stockmarket | 1.000 | 1.000 | |
| yelp | 1.000 | 0.571 | Opus+ |

---

## Caveats (read before quoting)

1. **Native-config comparison, not strict single-variable.** Config A's Opus executor runs with `thinking: xhigh` + prompt caching; Config B's Kimi has neither (Fireworks can't do Anthropic thinking — it's forced). So A↔B is "each model in its standard deployable mode," **not** "only the model string changed." A strict isolation arm (Opus exec with thinking/caching OFF) has not been run.
2. **Single-trial (54×1).** Compare A↔B to each other, not to the 5-trial submission. Config A single-trial (0.7025) reproduces the published **5-trial 0.7199** within variance — baseline validated.
3. **Prompt caching** lowers Opus's *input* cost (cached input ~$0.50 vs $5/1M); Kimi has none. The cost gap is real but caching-aided on Opus's side.
4. **Patents = 0.00 in both** (the hardest dataset; unsolved by either stack).
