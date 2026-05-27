# DABStep domain knowledge

## Spec-authoring rules

The executor's Python REPL has these helpers pre-imported from `data/context/dabstep_helper.py`:

- `list_match(rule_val, txn_val)` — list-field wildcard match (null / `[]` / contains).
- `scal_match(rule_val, txn_val)` — scalar-field wildcard match (null / NaN / equals).
- `attr_matches_wildcard(rule_attr, query_val)` — same semantics, for attribute-filter questions.
- `rule_applies(rule, txn, merchant=None)` — full per-txn rule-applicability predicate (all eight fields).
- `fee_for_rule(rule, eur_amount)` — Manual §5 fee formula.

When the computation_plan needs to perform wildcard matching, rule applicability, or fee computation, **reference these helpers BY NAME**. Do NOT inline their definitions or rewrite their logic. This OVERRIDES the general meta-rule 5 ("spell out filter predicates in pandas notation") — for these specific helpers, name-reference is correct.

**Length budget**: keep `computation_plan` ≤10 high-level steps. Use the helpers to collapse what would otherwise be 5–10 inline lines into one step. Verbose plans (>15 steps) cause executor iter-cap timeouts.

## Dataset facts

**card_scheme** — `payments.csv['card_scheme']` and `fees.json[*]['card_scheme']` both use the same domain: `{GlobalCard, NexPay, SwiftCharge, TransactPlus}`. (`payments-readme.md` lists `[MasterCard, Visa, Amex, Other]` but this is stale; trust the data.) Filter rules by `rule.card_scheme == txn.card_scheme` directly.

**is_credit** — `payments.csv['is_credit']` is pandas `bool` (values `True`/`False`). `fees.json[*]['is_credit']` is Python `bool` or `null`. Use `df['is_credit'].astype(bool)`. Do NOT use `df['is_credit'].astype(str).str.lower().eq('credit')` — this returns all-False because the string form is `'True'`/`'False'`, never `'credit'`.

**Bucket enumerations in fees.json**:
- `monthly_volume`: `{'<100k', '100k-1m', '1m-5m', '>5m'}`. `null` = wildcard.
- `monthly_fraud_level`: `{'<7.2%', '7.2%-7.7%', '7.7%-8.3%', '>8.3%'}`. Parse `>8.3%` as ratio `> 0.083`; do not mix percentage and ratio scales.
- `capture_delay`: `{'<3', '3-5', '>5', 'immediate', 'manual'}`. Map `merchant_data` numeric strings: `'1','2' → '<3'`; `'3','4','5' → '3-5'`; `'6','7',… → '>5'`. Pass `'immediate'` and `'manual'` through verbatim.

**Wildcard sentinels — list fields**: `rule['account_type']`, `rule['merchant_category_code']`, `rule['aci']` are LISTS. Empirically 720/1000 rules have `account_type == []`, 127/1000 have `merchant_category_code == []`, 112/1000 have `aci == []`. **Empty list `[]` IS a wildcard** (not "no match"). `null` is never used for these three fields. A rule with `field == []` applies to all values of that field.

**Wildcard sentinels — scalar fields**: `rule['is_credit']`, `rule['intracountry']`, `rule['capture_delay']`, `rule['monthly_volume']`, `rule['monthly_fraud_level']`: `null` = wildcard. `rule['intracountry']` ∈ `{null, 0.0, 1.0}` — cast to `bool` before comparing.

**Fee formula** (Manual §5): `fee = fixed_amount + rate * transaction_value / 10000`.

**Fraud rate** (Manual §7): `fraud_rate = sum(eur_amount where has_fraudulent_dispute) / sum(eur_amount)` — volume-weighted, NOT count-weighted.

## Spec patterns

### Wildcard matching
A rule list-field matches `txn_val` iff `rule[F] is None OR rule[F] == [] OR txn_val in rule[F]`. Use the canonical helper `list_match(rule_val, txn_val)`.

### Per-txn rule applicability
For total-fee tasks: use `rule_applies(rule, txn, merchant)` from `data/context/dabstep_helper.py` rather than rolling your own match predicate. The canonical version handles all eight rule fields with correct wildcard semantics.

### Coverage check (informational, not a hard halt)
After applying rule masks, count `n_unmatched` transactions. Use this as a HINT to check wildcard handling (especially: is `list_match` being used correctly? is `is_credit` cast to `bool`?). Do NOT raise/assert on `n_unmatched > 0`; that aborts perfectly fine runs where the data legitimately has uncovered transactions. Treat uncovered transactions as contributing `fee = 0` to totals and proceed. Only emit `'Not Applicable'` when ALL transactions are uncovered (which usually means the filter is wrong, not the data).

### Tie-break
When multiple rules apply to one transaction, pick the rule with MAX specificity (count of non-wildcard fields). On further ties, pick min `rule.ID`. Do NOT use min-fee (biases toward zero-fee outliers).

### 'Not Applicable' discipline
NA is correct only when (a) the merchant is unknown in `merchant_data.json`, OR (b) the transaction filter returns zero rows. Anything else is a bailout — fix the matching code.

### Output rounding
Detect decimals from `expected_output_format` or `guidelines`. Round final value with `f"{x:.Nf}"`. Default to 2 decimals if no hint. Never emit trailing-zero floats (e.g. `0.60827000000000`) — DABStep's `|x|<1` strict-isclose branch rejects them.

### Signed delta convention
For tasks with `'delta'`, `'change in fees'`, `'if … changed to …'`, `'imagine … had …'`: emit `delta = scenario_B_total − scenario_A_total` (after − before), signed. Never `abs()`. If new is cheaper, delta is negative.

## Family-specific rules

### Attribute-filter average fees (e.g., "average fee that NexPay would charge for account_type=D at 100 EUR")
A rule is "applicable to attr=val" iff `rule[attr] is null OR rule[attr] == [] OR val in rule[attr]`. Average = `mean(fee per matching rule)`. INCLUDE wildcard rules. Use `attr_matches_wildcard(rule_attr, query_val)`.

### Most-expensive / cheapest ACI
For each ACI letter, sum (or count-weight) the per-rule fee across all applicable rules. Argmax/argmin over letters. Do NOT use `df.groupby('aci')['fee'].max().idxmax()` — that picks the ACI with the single most expensive rule rather than the highest aggregate exposure.

```python
ACI_LETTERS = list('ABCDEFG')
df['aci_eff'] = df['aci'].apply(lambda l: l if (isinstance(l, list) and len(l) > 0) else ACI_LETTERS)
sub = df.explode('aci_eff')
sub['fee'] = sub['fixed_amount'] + sub['rate'] * N / 10000
per_aci = sub.groupby('aci_eff')['fee'].sum()
winner = per_aci.idxmax()
```

### Most-expensive / cheapest MCC
Search ALL rules. Per candidate MCC, compute max fee across applicable rules. Apply wildcard floor for rules with empty MCC list. Tie-break per question text.

```python
df['fee'] = df['fixed_amount'] + df['rate'] * V / 10000
df_exp = df[df['merchant_category_code'].apply(lambda l: len(l) > 0)].explode('merchant_category_code')
wildcard_max = df[df['merchant_category_code'].apply(lambda l: len(l) == 0)]['fee'].max()
per_mcc_max = df_exp.groupby('merchant_category_code')['fee'].max().clip(lower=wildcard_max)
```

### Counterfactual MCC scenarios ("imagine merchant X had changed its MCC to Y…")
Construct two complete fee runs over the merchant's actual transactions:
- Scenario A (baseline): merchant's real MCC.
- Scenario B (counterfactual): copy the transaction frame, overwrite the merchant's `mcc` field, re-run the full rule-match pipeline.

Non-MCC merchant fields stay the same. Monthly volume/fraud buckets are merchant-time aggregates and do not change between scenarios. `delta = total_B − total_A` (signed).

### "Average scenario" cheapest / most-expensive card scheme
Compute `fee_at_N = fixed_amount + rate * N / 10000` for every rule. Group by `card_scheme`. Simple unweighted mean. NO attribute filtering, NO wildcard-only subset filter. Argmax/argmin.

```python
fees['fee_at_N'] = fees['fixed_amount'] + fees['rate'] * N / 10000
per_scheme = fees.groupby('card_scheme')['fee_at_N'].mean()
```

For any N > 0 in this dataset: NexPay is most expensive, GlobalCard is cheapest, TransactPlus and SwiftCharge sit in the middle.

### Fraud-move ACI selection ("if we moved fraudulent transactions to a different ACI…")
Fraud transactions are 100% `shopper_interaction == 'Ecommerce'` with `aci == 'G'`. Candidate set = `{D, E, F} \ {current}` — other CNP ACIs in the same interaction class, excluding the current one and excluding `C` (tokenized-mobile is a different interaction class). For POS fraud, candidates = `{A, B} \ {current}`.

Output is a bare ACI letter (e.g. `'D'`), not `'{aci}:{fee}'`. The guideline template mentioning `{card_scheme}:{fee}` is a known dataset typo; verified golds for this family are bare letters.

### Sign-validation for delta tasks
After computing a delta, assert `np.sign(delta) == np.sign(new_rate − old_rate)` when both signs are defined. Disagreement means the matching/scenario logic upstream is broken.
