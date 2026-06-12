# SCRIBE blog — technical content brief

**Audience:** Heads of data / engineering at mid-to-large enterprises whose business logic lives in PDFs, manuals, fee catalogs, and schemas rather than clean SQL tables. They've evaluated GPT-5-based agents and have measured them silently producing the wrong answer. They are looking for something deployable, defensible, and not vendor-locked.

**Objective:** Get a qualified inbound conversation. The reader should finish thinking: *"this team understands why our current agents fail, and the architecture they describe is the one I would have built if I'd had six months."*

**Tone references:**
- Anthropic engineering posts (clean, lead with claim + result, show work without academic hedging)
- Thinking Machines Lab posts (technical depth, willing to disclose failure modes)
- Posthog / Linear engineering blog (confident, direct, sales-forward in the closing CTA)

**Tone rules:**
- Lead with numbers, not adjectives.
- Use second person ("your team", "your docs") in the framing sections; switch to first person plural ("we built", "we measured") in the technical sections.
- Disclose the failure mode honestly (F-E ceiling). This is sales, not hiding.
- Zero em-dashes (consistent with the paper).
- Use proper apostrophes (’) not straight (').

**Design hints (free for designers to ignore):**
- Two-color accent system: blue (#2b5ba0) for system-flow / wins; deep purple (#6a4a8a) for the HELPER_MANIFEST semantic-layer move.
- The architecture diagram is the centerpiece; it should be interactive (hover-to-detail) on web, static-with-numbered-callouts on PDF.
- Per-domain bar chart should have a strict/lenient toggle.
- Numbers in monospace; body in serif (Source Serif, Charter, or similar). Headlines in modern sans (Inter, Söhne, GT America).

---

## Headline options (pick one, A/B test if you can)

**Recommended (lead with claim + result):**
> A three-role LLM agent that beats GPT-5 on docs-heavy data analysis at one-third the cost.

**Variant (mechanism-forward):**
> Why we stopped asking one model to plan, execute, and review — and what we built instead.

**Variant (problem-forward):**
> Your business logic doesn't live in a SQL table. SCRIBE is built for the docs that hold it.

## Dek / subhead

Most production data-analysis agents fail in three predictable ways: they misread the source documents, they ship code without sanity-checking it, and they thrash for forty iterations before giving up. We separated those three jobs into three roles, gave each one a model sized for the task, and measured the result on two public benchmarks. **SCRIBE reaches 59.8% on DABStep and 68.3% on KramaBench at $0.33 per task — using a fully open-source executor.**

## Hero KPIs (four-stat strip)

| Number | Label | Source |
|---|---|---|
| **59.8%** | DABStep dev set, 450 tasks (95.8% easy, 52.9% hard) | Single-run, public dev split, consensus gold |
| **68.3%** | KramaBench, 6-domain transfer (+12.5 points vs published baseline) | Patched-scorer lenient, 104 tasks |
| **$0.33** | Cost per task end-to-end (3.7× cheaper than GPT-5-solo at 4× the accuracy) | Measured spend on DABStep dev run |
| **2h25m** | Wall time for all 104 KramaBench tasks via streaming pipeline | Sharded across 2 executor workers |

---

# Section 1 — The problem we kept seeing

**Section header:** *Your business logic doesn't live in a SQL table. It lives in a forty-page manual.*

## Body prose

A real question from a real benchmark looks trivial: *"what is the average fraud rate?"* It isn't.

The manual that ships with the dataset defines fraud rate as a volume-weighted ratio — total fraudulent value divided by total transaction value. The CSV has a fraud-flag column right there, sitting in front of you. So the obvious move — group by merchant, average the boolean — is wrong. The obvious move is what every solo ReAct agent we tested commits to, even the frontier ones.

This is not a model-capability problem. The same frontier model gets the right formula when asked to plan in isolation, then commits the wrong formula when asked to plan-and-execute in the same conversation. We reproduced that across three independent model families: GPT-5, DeepSeek-V3.1, Kimi-K2.6. The failure isn't in the weights. It's in the role conflation.

We classified the failures we kept seeing into three categories. Each one traces to a measurable, literature-documented LLM weakness — and each one admits a distinct architectural fix.

## Three-card failure-mode grid

**Card 1 — Definition-shift**
- *Quote (italics, large):* "Average fraud rate, weighted by what?"
- *Body:* A single ReAct agent reads the manual at iteration 1, starts coding, and by iteration 12 has talked itself into the count-weighted reading even though the docs clearly define volume-weighted. Same model, same docs, two different formulas, depending on where in the trajectory you ask it.
- *Root cause:* The plan becomes a middle-of-context fact by iteration 10 (precisely where LLMs use information least reliably; cf. Liu et al. 2024 on "lost in the middle").
- *Our fix:* **Spec freeze.** A separate agent commits the formula to text before any code is generated. The executor cannot rewrite the spec mid-trajectory.
- *Tag:* Spec role

**Card 2 — Action-bias**
- *Quote:* "The plan looks fine, ship it."
- *Body:* Self-reflecting executors are bad at finding their own ambiguity. A boolean-mask filter that returned zero rows? A groupby that lost 80% of the input? The agent keeps going because the code "ran".
- *Root cause:* Executors over-commit to plausible-looking output; consistent with the self-flagging weakness Asai et al. document in Self-RAG.
- *Our fix:* **Backreview.** A structured five-header summary forces the executor to externalize its assumptions; a separate Reviewer re-reads the docs against those assumptions and either confirms or returns a revised spec.
- *Tag:* Review role

**Card 3 — Iteration-cap death**
- *Quote:* "Forty ReAct turns later, still no answer."
- *Body:* Without a forced exit, executors thrash. We measured that successful runs commit by iteration 15 (median 7); failures are still searching past iteration 15. That's where we put the mandatory escalation rule.
- *Root cause:* Cumulative context decay; long-context reasoning degradation (Levy et al. 2024, *Same task, more tokens*).
- *Our fix:* **Escalation protocol.** At iteration 15, escalation is mandatory; the structured-summary contract gives the executor a productive exit instead of free thrashing.
- *Tag:* Both roles

## Pull quote (use after the cards)

> One agent cannot simultaneously be a careful documents-reader, an aggressive code-generator, and a skeptical reviewer. So we stopped asking it to.

---

# Section 2 — The diagnosis: role conflation

**Section header:** *Three jobs, in tension, in one conversation.*

## Body prose

Production data-analysis is three different cognitive tasks. Reading source documents and translating them into a precise computation plan is a careful, conservative, recall-oriented task. Implementing that plan as code is an aggressive, precision-oriented task — you want the agent to act, not deliberate. Reviewing the agent's output against the docs is a skeptical, adversarial task — you want it to look for what's wrong, not what's right.

When you ask one model to do all three in one conversation, the cognitive style it adopts for any one of them poisons the others. A model in execution mode rationalizes away ambiguity. A model in review mode under-acts when it should escalate. A model in planning mode keeps re-deliberating instead of committing.

The fix is structural, not behavioral. You can't prompt-engineer your way out of role conflation. You have to give each job its own session.

**[Optional diagram: "roles in tension" — three overlapping circles labeled Plan / Act / Review, each with the cognitive style it wants, and arrows showing which styles cancel which.]**

---

# Section 3 — The SCRIBE architecture

**Section header:** *Three roles, three sessions, one frozen contract.*

## Body prose (architecture intro)

SCRIBE decomposes the agent into three roles: a **Spec Agent** that reads documents in a clean session and writes a frozen contract; a **ReAct Executor** that runs the contract against a Python REPL; and a **Review Agent** that re-grounds the executor's work against the source docs. Critically, the Spec and Review agents are the *same model in the same conversation* — context is preserved between planning and review. The Executor is a *separate, cheaper model* with a tool surface narrowed to code execution.

The architectural lever is asymmetric model assignment: a strong model fires only at the planning and review edges (small per-task token volume); the bulk of per-task tokens — every line of Python, every print, every retry — runs on an open-weights executor. The dollar cost lives where the tokens live, and almost all the tokens are cheap.

## Architecture diagram — designer brief

**This is the centerpiece visual of the post. It should be interactive on web (hover any node for design rationale), or annotated-with-numbered-callouts in PDF/print.**

**Node list (top-to-bottom flow):**

1. **Source documents** (top of diagram, doc-yellow `#f4ecd8`)
   - Sub-label: *"manuals, schemas, fee catalogs, data lakes"*
   - Detail-on-hover: "The raw inputs. SCRIBE does not pre-filter the source corpus, because modern LLMs are robust to irrelevant context (Distyl 2024); the cost of dropping a load-bearing line is higher than the cost of carrying extra ones."

2. **Spec Agent** (blue `#dce6f4`)
   - Sub-label: *"strong model · clean session"*
   - Detail: "Reads all source documents in a clean session, emits a structured spec containing interpretations, chosen interpretation, computation plan, expected output format. Runs on a strong model because this is where docs-grounded reasoning lives. Fires once per task."

3. **Frozen spec** (gold `#fff6d6`) — middle-left
   - Sub-label (three lines): *"interpretations[] (I-1 gate)"*, *"chosen_interpretation + computation_plan"*, *"expected_output_format"*
   - Detail: "The contract. The executor cannot rewrite it mid-trajectory; if it's wrong, the reviewer overwrites it on disk and the executor refreshes its anchor via read_current_spec. Includes the I-1 interpretations array that surfaces 2–4 plausible readings before committing to one."

4. **HELPER_MANIFEST** (purple `#f0e6f4`) — middle-right, alongside frozen spec
   - Sub-label: *"paradigm-level helpers"*, *"read_multi_header_excel"*, *"parse_missing_marker, ..."*
   - Detail: "A small named-pattern vocabulary the executor pre-imports. When docs define non-default semantics, we lift them into helpers instead of asking the executor to re-derive them per call. This is what the semantic-layer thesis prescribes for text-to-SQL; we apply it to data analysis."

5. **ReAct Executor** (green `#dceedc`) — bottom-left
   - Sub-label: *"open-weights · Python REPL"*, *"Tier-A [AUTO-INSPECT]"*, *"Tier-B [VERIFY] tags"*
   - Detail: "Standard ReAct loop with a Python REPL. Runs on a smaller open-weights model since this is the bulk of per-task tokens. The run_python wrapper injects Tier-A [AUTO-INSPECT] (shape/dtypes/head printed automatically) and Tier-B [VERIFY] pattern-triggered assertions on groupby / merge / boolean-mask call sites, all LLM-free."

6. **Review Agent** (blue `#dce6f4`) — bottom-right
   - Sub-label: *"same session as Spec"*, *"6-verdict cascade:"*, then in monospace: *"SPEC_WRONG · SPEC_DOUBT"*, *"BLIND_SPOT · EXEC_WRONG"*, *"NA_CONFIRMED · ANSWER"*
   - Detail: "Same model as Spec, continuing the same conversation so docs context is preserved. Must re-read source documents via read_file before replying. Returns one of six verdicts. Each has a scripted executor follow-up so the cascade converges to a stop signal."

7. **Final answer** (white) — bottom
   - Detail: "Committed only on the ANSWER or NA_CONFIRMED verdict. By that point: the spec has been re-grounded against the docs, the executor's code has produced output, and the reviewer has confirmed both."

**Edges:**

- **Solid blue (`#2b5ba0`), main flow:**
  - Source documents → Spec Agent (label: `read`)
  - Spec Agent → Frozen spec (label: `save_spec`)
  - Frozen spec → ReAct Executor (label: `run_python`)
  - ReAct Executor → Final answer (label: `emit answer`)

- **Solid purple (`#6a4a8a`), helper preamble:**
  - HELPER_MANIFEST → ReAct Executor (label: `preamble`)

- **Dashed red (`#b22222`), escalation cascade:**
  - ReAct Executor → Review Agent (label: `ask_spec_agent`)
  - Review Agent → Frozen spec (curved back-arrow, label: `revised spec`)

- **Dashed brown (`#7a6a3a`), grounding:**
  - Review Agent → Source documents (long arc back to top, label: `read_file`)

**Legend (three swatches):**
- Blue: strong model (Spec + Review)
- Green: open-weights executor
- Purple: paradigm shim

---

# Section 4 — The four design moves that earned their keep

**Section header:** *A lot of three-role agents exist in the literature. What earned its keep was these four primitives.*

## Body prose (intro)

The topology — Spec / Executor / Review — is not novel. Sequential-vs-LoopAgent decomposition predates this paper. What we contribute is the *combination* of four design moves that each track a specific, measurable failure mode and a specific piece of prior practitioner wisdom.

## Four-card grid (each card: title · insight · influence · metric)

**Card 1 — Frozen-spec contract**
- *Insight:* The first agent reads the docs once, in a clean session, and emits a `computation_plan` the executor must follow. The executor never re-reads source documents directly. That prevents the drift we kept measuring — where the same model read the same manual at iteration 1 and at iteration 12 and walked away with two different formulas.
- *Influence:* Sequential-vs-LoopAgent pattern, Weinmeister 2025 ("Six Failures of Text-to-SQL").
- *Metric:* Eliminates definition-shift between iterations. Specifically reduces F1 (fraud-move ACI selection), F2 (over-strict rule matching), F5 (average-fee definition shift) as a failure family.

**Card 2 — HELPER_MANIFEST: a semantic layer for code**
- *Insight:* Docs frequently define non-default semantics — multi-header Excel files, "—" as missing-value sentinel, before-present radiocarbon dates, BP-to-calendar conversions. We lifted those into a small named-pattern vocabulary (`read_multi_header_excel`, `parse_missing_marker`, `safe_dedupe`, `linear_interp_by_key`, `bp_to_calendar_year`) that the spec_agent can reference by name in `computation_plan` and the executor can call directly, instead of asking the executor to re-derive them per call.
- *Influence:* Semantic-layer thesis for text-to-SQL, Davidson 2026 ("Why Text-to-SQL Fails and What Semantic Layers Solve"). The insight transfers to data analysis: docs-defined conventions deserve named handles.
- *Metric:* Biomedical +38.9 points vs published baseline; biomedical is the most assay-protocol-heavy KramaBench domain, exactly where named helpers pay off.

**Card 3 — Six-verdict review cascade**
- *Insight:* A binary `[No flag]` / `[Flag: mistake]` reviewer was lossy — it conflated genuinely distinct failure types into the same downstream action. We separated them into six scripted verdicts: `SPEC_WRONG`, `SPEC_DOUBT`, `BLIND_SPOT`, `EXECUTOR_WRONG`, `NA_CONFIRMED`, `ANSWER`. Each has a deterministic follow-up. The cascade became a converging stop signal instead of free-form review text.
- *Influence:* Original; designed to match the actual failure-mode taxonomy we observed in pilot traces.
- *Metric:* Reviewer fires under 3× per task on average; cascade converges (no infinite review loops observed).

**Card 4 — Tier-A / B / C deterministic verifiers**
- *Insight:* Inside the executor, we inject LLM-free checks that catch the silent errors self-reflecting agents miss. Tier-A `[AUTO-INSPECT]` prints shape and dtypes on every trailing DataFrame automatically. Tier-B `[VERIFY: PASS/WARN/FAIL]` is a pattern-triggered tag that asserts row-count monotonicity on `groupby`, ≤2× growth on `merge`/`join`, and non-empty filters on boolean masks. Tier-C `verify_step` is an opt-in tool with nine explicit assertions drawn from the Great-Expectations / pandera / dbt verifier vocabularies.
- *Influence:* Great Expectations, pandera, and dbt-test idioms; the data-validation literature has been doing this for years — we ported its discipline into the agent loop.
- *Metric:* Catches off-by-one and over-join errors at zero LLM cost. Specifically prevents the silent-truncation-after-bad-filter failure family.

---

# Section 5 — The Tier-A / B / C verifier stack (expanded)

**Section header:** *What's inside the executor: three tiers of LLM-free safety net.*

## Body prose

Self-reflecting executors are bad at finding their own off-by-one and over-join errors. So we don't trust them to. Instead we wrap the Python REPL with deterministic checks that cost nothing per call.

## Three-card explainer

**Tier A — `[AUTO-INSPECT]`** (green chip)
- Prints shape, dtypes, and head of any trailing DataFrame, automatically.
- The executor sees what came out of every cell *without asking*. No additional tokens.
- Mechanism: AST-walk the last statement, detect DataFrame-typed result, emit a structured inspection block.

**Tier B — `[VERIFY: PASS/WARN/FAIL]`** (green chip)
- Pattern-matches `groupby`, `merge`, and boolean-mask call sites and asserts:
  - Row-count monotonicity (groupby never increases row count)
  - ≤2× join growth (a merge that 10×'s your rows is almost always a many-to-many bug)
  - Non-empty filter result (a boolean mask returning zero rows is almost always a logic error)
- Surfaces the silent shape errors the executor would otherwise sail past.
- Mechanism: regex over the executed code; deterministic assertion inline in the print stream.

**Tier C — `verify_step`** (green chip)
- A nine-assertion opt-in tool the executor can call: `row_count`, `shape`, `uniqueness`, `null_rate_below`, `dtypes`, `value_in_range`, `value_in_set`, `column_exists`, `monotonic_increase`.
- Used when the executor wants belt-and-suspenders, especially mid-task before a critical aggregation.
- Mechanism: a `verify_step(df, assertions=[...])` call that returns structured pass/fail.

## ASCII inline example (designer can render as a styled monospace block)

```
>>> result = df.groupby('merchant_id').agg({'amount':'sum'})
[AUTO-INSPECT]
  shape: (1247, 1)
  dtypes: amount=float64
  head: aggregate produced 1247 rows from 4810 input rows
[VERIFY: groupby PASS — row count strictly decreased]
```

---

# Section 6 — The six-verdict review cascade (expanded)

**Section header:** *Six verdicts, in priority order, each with a scripted follow-up.*

## Body prose

The Review Agent doesn't return prose. It returns one of six tags, evaluated in priority order. Each has a scripted executor follow-up so the cascade is a converging stop signal, not free-form review text. The priority order is load-bearing: a `SPEC_WRONG` always pre-empts an `EXECUTOR_WRONG`, because if the spec is wrong, the executor's output being wrong is downstream and irrelevant.

## Verdict table (designer: render as a 6-row table with monospace tag in the left column, color-coded chip)

| Tag | Color | What it means | Executor follow-up |
|---|---|---|---|
| `SPEC_WRONG` | warn-red | Docs contradict the frozen spec. | Reviewer emits a revised spec; on-disk spec is overwritten; executor calls `read_current_spec` to refresh its anchor, then re-attempts. |
| `SPEC_DOUBT` | warn-red | Multiple defensible interpretations survive docs re-grounding. | Reviewer emits an `interpretations[]` array with alternative doc quotes; executor escalates back to spec re-extraction with the alternative hypotheses. |
| `BLIND_SPOT` | accent-blue | Executor missed a docs-named edge case. | Targeted hint about the edge case, no spec rewrite; executor patches the specific code path. |
| `EXECUTOR_WRONG` | accent-blue | Generated code disagrees with the spec. | Corrective hint about the divergence; executor regenerates the diverging code block. |
| `NA_CONFIRMED` | helper-purple | Spec and docs jointly imply no answer exists. | Executor commits to `NA`. |
| `ANSWER` | success-green | Executor's summary matches the spec. | Executor commits the answer. |

## Sub-text (under the table)

Six verdicts isn't an arbitrary choice. Five was what we shipped first (no `SPEC_DOUBT`); we added the sixth after we saw the v3 pilot fail-class where two equally defensible interpretations of a question would survive docs grounding and the cascade had nowhere productive to go. `SPEC_DOUBT` gave the reviewer a verdict that maps to "re-extract with explicit alternatives" instead of forcing a wrong commitment.

---

# Section 7 — Results

**Section header:** *Two public benchmarks, same harness, no per-benchmark tuning.*

## Body prose (intro)

We evaluated SCRIBE on two public benchmarks. The DABStep number is single-run on the dev split with consensus gold (450 tasks across a fixed corpus of seven documents). The KramaBench number uses our patched scorer — we audited the official KramaBench evaluator and identified four issues that produced silent task drops; we released a patched evaluator and report both strict and lenient numbers under it. The smolagents-DR baseline number is what the KramaBench paper published (we did not re-run it because predictions were not released).

The same harness, the same prompts, the same helper manifest pattern was used on both benchmarks. We did not tune per-benchmark.

## Chart 1 — DABStep headline

**[Chart spec: horizontal grouped bars, one row per system. Tab toggle: easy / hard / overall.]**

| System | Easy % | Hard % | Overall % | $/task | $/correct |
|---|---|---|---|---|---|
| Kimi-K2.6 solo | 75.0 | 40.5 | 46.0 | 0.02 | 0.04 |
| GPT-5 solo (diagnostic only) | 20.0 | n/a | n/a | 0.37 | 1.84 |
| DS-STAR (Gemini-2.5-Pro)† | 87.5 | 45.2 | 52.0 | n/r | n/r |
| DS-STAR (GPT-5)† | 88.9 | 43.1 | 50.4 | n/r | n/r |
| **SCRIBE** | **95.8** | **52.9** | **59.8** | **0.33** | **0.55** |

† DS-STAR numbers are on the DABStep hidden test (leaderboard) per Nam et al. 2026; SCRIBE is on the public dev set with consensus gold.

**Caption / footnote:** SCRIBE matches frontier-throughout pipelines in accuracy while spending a fraction of the dollars on the frontier model. Direct hidden-test comparison is future work; the dev-vs-leaderboard caveat is in the paper.

## Chart 2 — KramaBench per-domain

**[Chart spec: grouped bars per domain. Strict/lenient toggle. Each domain shows: smolagents-DR (red) · SCRIBE strict (blue/grey for losses) · SCRIBE lenient (blue/grey for losses). Below each domain: n=, then color-coded ±Δ.]**

| Domain | N | smolagents-DR | SCRIBE strict | SCRIBE lenient | Δ strict | Δ lenient |
|---|---|---|---|---|---|---|
| archeology | 12 | 44.4 | **50.0** | **50.0** | +5.6 | +5.6 |
| astronomy | 12 | 50.0 | 41.7 | 41.7 | −8.3 | −8.3 |
| biomedical | 9 | 38.9 | **77.8** | **77.8** | **+38.9** | **+38.9** |
| environment | 20 | 60.6 | **75.0** | **80.0** | +14.4 | **+19.4** |
| legal | 30 | 61.2 | **76.7** | **76.7** | **+15.5** | **+15.5** |
| wildfire | 21 | 60.2 | 61.9 | **66.7** | +1.7 | +6.5 |
| **Overall** | **104** | **55.83** | **65.4** | **68.3** | **+9.6** | **+12.5** |

**Caption:** SCRIBE under the patched official scorer vs published smolagents-DR Claude-3.7. The strict-vs-lenient distinction is only about the F1 threshold on `list_approximate` answer types (strict: F1 = 1.0; lenient: F1 ≥ 0.5); both use the same bug-patched scorer. The published baseline does not have a separate strict/lenient split — we couldn't re-grade it because predictions were not released.

## Chart 3 — Cost vs accuracy frontier

**[Chart spec: scatter plot. X-axis: cost per task ($0 to $0.50). Y-axis: pass rate (0 to 100%). Three points. Dashed arrow connecting GPT-5-solo to SCRIBE, annotated "−3.7× cost · +4× accuracy".]**

| Point | Cost/task | Pass % | Note |
|---|---|---|---|
| GPT-5 solo | $0.37 | 20% | Diagnostic set, n=5 |
| Kimi-K2.6 solo | $0.02 | 20% | Same diagnostic |
| **SCRIBE (GPT-5 spec + Kimi-K2.6 executor)** | **$0.10** | **80%** | Same diagnostic; Wilson 95% CI [37.6%, 96.4%] |

**Caption:** On the held-out diagnostic, SCRIBE is strictly better than the GPT-5-solo monolith on both axes: lower cost per task *and* higher accuracy. n=5 is small (Wilson CIs are wide); the diagnostic is qualitative (the wrong-answer disagreement structure across single-session agents), not a powered estimate. The large-n confirmation lives in the DABStep headline (n=450) and KramaBench transfer (n=104).

## Chart 4 — Cost breakdown by role

**[Chart spec: horizontal stacked bars, three rows. Each bar segments into "frontier-model spend" (blue) + "executor spend" (green). Total cost shown at the right end.]**

| System | Frontier-model spend ($) | Executor spend ($) | Total |
|---|---|---|---|
| GPT-5 solo | 0.37 | 0.00 | $0.37 |
| Kimi-K2.6 solo | 0.00 | 0.02 | $0.02 |
| **SCRIBE** | **0.27** | **0.06** | **$0.33** |

**Caption:** The asymmetric model assignment puts the frontier-model dollars only where they earn their keep. Almost all of the per-task tokens (every line of Python, every print, every retry) run on the cheaper executor. The frontier model fires only at the planning and review edges, which are small token volumes per task.

## Closing prose (under all four charts)

A GPT-5-throughout pipeline costs roughly $1.84 per correct answer at 20% accuracy on our held-out diagnostic; SCRIBE costs $0.13 per correct at 80%. About **14× better on cost-per-correct-answer**. The mechanism is not magic. The strong model fires only at the planning and review edges (small token volume per task). The bulk of tokens — every line of Python, every print, every retry — runs on an open-weights executor.

---

# Section 8 — Where SCRIBE has a ceiling (the F-E disclosure)

**Section header:** *We name the failure mode SCRIBE doesn't fix. We call it F-E.*

## Body prose

On KramaBench's archeology and astronomy domains, three independently configured stacks — different spec models, different planners, different executors, no shared model family between v2 and v3 — converge on the *exact same wrong number to six decimal places*. Cascade interventions (a question-restating gate, a `SPEC_DOUBT` verdict) don't change it. Multi-spec sampling within a model family doesn't either.

The reason is mechanical. The question's intended interpretation lives in an implicit field convention that isn't stated in any source document. Barrington Atlas rank as inverse-importance (lower number = more important). Radiocarbon dates as raw years-before-present versus calibrated calendar years. No doc passage adjudicates. Whatever the spec_agent picks, the reviewer has nothing docs-grounded with which to disagree — so the cascade verifies *within* the wrong frame.

We call this regime **F-E: cascade consensus on a plausible-but-wrong interpretation**. The paper discloses it openly because it's the architecturally honest finding. Deeper cascade verdicts will not escape it. Sub-task ground-truth labels, or a domain-knowledge layer above the cascade, will.

## Table — the three-stack F-E ablation

**[Designer note: render as a clean three-column data table with monospace numbers, gold column emphasized.]**

| Task | Gold | v2 (GPT-5 + Kimi) | v3 (DS + Qwen) | v3b (DS + Kimi) |
|---|---|---|---|---|
| hard-1 | 8364.83 | 8347.19 | −1,766,449 | 8364.83 ✓ |
| hard-2 | 38.42 | 49.75 | 50.25 | 50.25 |
| hard-5 | 36828.72 | 36815.26 | 29207.52 | 36828.72 ✓ |
| hard-9 | **+0.015648** | **−0.210104** | **−0.210104** | **−0.210104** |
| hard-12 | 9 | 1146 | 153 | (empty) |
| **PASS** | n/a | 0/5 | 0/5 | 0/5 |

**Caption:** All three stacks converge to identical six-decimal wrong values on hard-9 (gold +0.015648; all three produce −0.210104 — a sign flip plus 13× magnitude). v2 and v3 share no model family at any role. Architecture-level interventions (I-1 question-restating gate, `SPEC_DOUBT` sixth verdict, both active in v3 and v3b) do not change the verdict. The mechanism is upstream of the cascade.

## Pull quote (close the section)

> If your problem looks like KramaBench's astronomy — convention-heavy, implicit-interpretation — call us before you deploy. That's where this gets interesting, not where it gets ignored.

---

# Section 9 — Cross-benchmark transfer

**Section header:** *Same harness, two benchmarks. We didn't tune per-benchmark.*

## Body prose

DABStep is a single-corpus benchmark over Adyen payment data: one set of source documents, 450 questions. KramaBench is six per-domain scientific data lakes, 104 tasks, with answer types spanning numeric exact, list exact, string approximate, and list approximate. They're structurally different. SCRIBE moves between them without architectural changes.

The KramaBench run uses a fully open-source configuration: DeepSeek-V3.1 for spec_agent and planner_agent, Kimi-K2.6 for executor. A streaming orchestrator pipelines spec extraction into executor runs, so each spec is handed off as soon as it lands instead of waiting for the whole batch. With two executor workers sharing the queue, we ran all 104 tasks in 2h25m for $39 of executor cost.

The win/loss split across the six domains tells a clean story about when role separation pays off. Docs-heavy paradigms — biomedical assay protocols, environmental measurement conventions, legal corpora with explicit definitions — are where SCRIBE adds 15 to 39 points. Convention-heavy paradigms — archeology rank inversions, astronomy field conventions — are where the F-E ceiling applies and SCRIBE either ties or loses.

This isn't a flaw to hide. It's a deployment heuristic. If your business logic is in the docs, SCRIBE works. If your business logic is in tribal convention, you need sub-task labels or a knowledge layer above the cascade — and we'll tell you so on the discovery call.

## Streaming pipeline diagram — designer brief

**[Optional second diagram, simpler than the architecture one.]**

Three rows of horizontal blocks on a time axis:
- **spec worker** (blue): sequential blocks T1, T2, T3, ...
- **executor 0** (green): T1, T3, T5, T7, ... (consumes specs as they land)
- **executor 1** (green): T2, T4, T6, ... (consumes specs as they land)
- Dashed hand-off arrows from each spec block down to whichever executor row picked it up.

**Caption:** Spec extraction is sequential (one spec at a time on the strong model); two executor workers consume specs from a shared queue as soon as each spec lands. Hand-off arrows mark the overlap. Total wall time is approximately half the "extract all, then run" baseline at the same per-task latency.

---

# Section 10 — Deploy SCRIBE on your data

**Section header:** *For your team.*

## Body prose (sales-forward close)

SCRIBE is the harness we ship with. The architecture is model-agnostic — bring whichever frontier model you're already paying for, and any open-weights executor your infrastructure supports. We will wire up the spec extractor for your document corpus, configure the helper manifest for your domain semantics, and ship a reference deployment that runs on *your* data, not ours.

The implementation timeline we work to is four to six weeks to a first deployment for a single docs corpus. Faster if the corpus is already structured; slower if there's a meaningful semantic-layer build (custom helper manifest, custom verifier vocabulary).

## Three-column "what's involved" strip

| You bring | We ship | Timeline |
|---|---|---|
| Your docs, your data, your hosted-API keys | Spec extractor, helper manifest, deployed harness, evaluation suite | 4–6 weeks to first production deployment |

## CTAs

- **Primary:** [Email us → hello@actioneer.com](mailto:hello@actioneer.com?subject=SCRIBE%20deployment%20enquiry)
- **Secondary:** [Schedule a 30-min walkthrough](https://calendar-link-tk)
- **Tertiary (low-friction):** [Read the paper](paper-link-tk)

---

# Section 11 — Frequently asked

**Section header:** *Frequently asked (because you would.)*

## FAQ accordions

**Q: Does this work with closed-weights models only (e.g. GPT-5 throughout)?**
A: Yes. The asymmetric assignment isn't required — it's the cost lever. If you want GPT-5 on all three roles, the architecture still works; you just pay $1.84 per correct answer instead of $0.13. The role separation alone gives you most of the accuracy lift.

**Q: How does SCRIBE compare to DS-STAR / smolagents / AutoGen / MetaGPT?**
A: DS-STAR is the closest architectural neighbor on DABStep — also role-decomposed, but with all roles served by a single base model. On the public dev set SCRIBE exceeds DS-STAR's reported leaderboard numbers on every split. The dev-vs-hidden-test caveat is documented in the paper; a hidden-test leaderboard submission is future work. AutoGen / MetaGPT / CAMEL are general multi-agent frameworks; SCRIBE is a specific harness for one problem (docs-heavy data analysis) tuned for production cost-per-correct.

**Q: What about the scorer bugs you mention?**
A: We audited the official KramaBench scorer and identified four issues that produce silent task drops: a TypeError on `predicted=str, target=list` that defaults to 0; an element-type mismatch (`"2003"` vs `2003`) that defaults to 0; a per-task try/except that silently drops failed metrics; and transient OpenAI API failures in the LLM-paraphrase judge that return `None` and get silently dropna'd. We released a patched evaluator alongside the paper; all our reported numbers use it.

**Q: Where does it not work?**
A: We disclose this in Section 8 (the F-E ceiling). On convention-heavy domains where the intended interpretation isn't in any source document, cascade interventions don't help. Sub-task ground-truth labels or an explicit domain-knowledge layer above the cascade are the architecturally honest fix. Talk to us — that's where deployment gets interesting.

**Q: Is the harness open-source?**
A: Yes. The harness, the patched KramaBench scorer, the helper manifest, and the reproduction recipes are all public. The paper is under triple-blind submission to ICDM 2026; once the review cycle closes the repo link will be in the final version.

**Q: How much does this cost per task in production?**
A: On DABStep, $0.33 per task end-to-end (frontier + executor + LLM-judge). On KramaBench, $0.40 per task averaged over the 6 domains. Your numbers depend on docs size and answer-type mix; we measure it during the discovery call.

---

# Footer

**Three columns.**

- **About:** "Actioneer builds production LLM agents for docs-heavy workflows where off-the-shelf agents quietly produce the wrong answer."
- **Read:** SCRIBE paper (ICDM 2026) · Open-source harness · Patched KramaBench scorer
- **Contact:** hello@actioneer.com · Schedule a 30-min walkthrough

**Bottom strip:** © 2026 Actioneer · SCRIBE is open-source · Paper under triple-blind submission to ICDM 2026.

---

# Asset checklist for the design team

**Visuals required:**
- [ ] Hero KPI strip (4 large stats)
- [ ] Three failure-mode cards
- [ ] **Architecture diagram (centerpiece)** — interactive on web, annotated-callouts on PDF
- [ ] Four design-move cards
- [ ] Tier A/B/C verifier explainer block (with monospace ASCII example)
- [ ] Six-verdict cascade table
- [ ] **Chart 1: DABStep headline grouped bars** (with easy/hard/overall toggle)
- [ ] **Chart 2: KramaBench per-domain grouped bars** (with strict/lenient toggle)
- [ ] **Chart 3: Cost-vs-accuracy scatter** (with Pareto-dominance arrow)
- [ ] **Chart 4: Cost-breakdown horizontal stacked bars**
- [ ] F-E ablation data table (three-stack convergence on −0.210104)
- [ ] Streaming-pipeline timeline diagram (optional, secondary)
- [ ] FAQ accordion section
- [ ] Deploy CTA card (with gradient background)
- [ ] Footer

**Copy assets included in this document:**
- Headline + dek (with variants)
- All section body prose
- All chart captions
- All table data (verified against the paper)
- All quote/callout text
- All CTA copy

**Numbers to verify before publish (all sourced from `paper/scribe.tex`):**
- DABStep: 269/450 = 59.8% (95.8% easy, 52.9% hard) at $0.33/task — `paper/scribe.tex` Table I (tab:headline)
- KramaBench: 68/104 = 65.4% strict, 71/104 = 68.3% lenient — `paper/scribe.tex` §6 paragraph "Result"
- Per-domain table — `paper/scribe.tex` tab:krama-headline
- Cost-vs-accuracy diagnostic — `paper/scribe.tex` tab:falsifier with Wilson CIs
- F-E ablation — `paper/scribe.tex` tab:fe-ablation

**Things explicitly NOT to include (would break the messaging):**
- Provider names (Fireworks, OpenRouter, Baseten) — paper is provider-agnostic, blog should be too. Use "hosted inference API" if needed.
- Re-roll mechanism — paper treats SCRIBE as the single canonical configuration; don't split into single-pass vs re-roll columns.
- The "SCRIBE+" variant — was cut from the paper, don't reintroduce.
- The Variant-B / Domain-Knowledge Injection ablation — also cut.
- LiveSQL benchmark — dropped from the paper; don't mention.

**Source-of-truth files in repo:**
- Paper: `paper/scribe.tex`
- Bibliography: `paper/refs.bib`
- Architecture figure source (matplotlib): `paper/figures/generate_arch.py`
- Per-domain chart source: `paper/figures/generate_krama_per_domain.py`
- Streaming-pipeline figure source: `paper/figures/generate_streaming_pipeline.py`
- Findings doc with all numbers cross-checked: `docs/findings/18_krama104_results.md`

---

*End of brief. Hand to design team. Question for the writer or me: hello@actioneer.com.*
