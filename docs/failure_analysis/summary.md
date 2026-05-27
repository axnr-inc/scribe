# Failure analysis: kimi-k2.6

- Total tasks: **450**
- Tasks with ground truth: **450** (100%)
- Correct (where ground truth exists): **206** (45.8% of judged, 45.8% of total)

## Failure-mode histogram

| classification | count | pct |
|---|---|---|
| correct | 206 | 45.8% |
| iter_capped | 97 | 21.6% |
| incorrect | 76 | 16.9% |
| no_assistant_response | 35 | 7.8% |
| format_only_mismatch | 32 | 7.1% |
| na_answered | 3 | 0.7% |
| connection_error | 1 | 0.2% |

## Per-level breakdown

| level | connection_error | iter_capped | no_assistant_response | na_answered | incorrect | format_only_mismatch | correct | total |
|---|---|---|---|---|---|---|---|---|
| easy | 0 | 1 | 2 | 1 | 13 | 2 | 53 | 72 |
| hard | 1 | 96 | 33 | 2 | 63 | 30 | 153 | 378 |

## Top 10 sessions by tool-call count (likely the most expensive)

| task_id | level | classification | tool_calls | thinking | session_hash |
|---|---|---|---|---|---|
| 2769 | hard | iter_capped | 75 | 0 | `ytjyknod` |
| 2644 | hard | incorrect | 62 | 0 | `83xvmy2c` |
| 1738 | hard | na_answered | 59 | 0 | `eg10teuj` |
| 2536 | hard | incorrect | 39 | 0 | `xhr1gl55` |
| 2691 | hard | format_only_mismatch | 35 | 0 | `ls46sth5` |
| 2761 | hard | format_only_mismatch | 32 | 0 | `f50diij0` |
| 1712 | hard | correct | 30 | 0 | `vihlt59n` |
| 2528 | hard | iter_capped | 28 | 0 | `99gjx1np` |
| 2719 | hard | iter_capped | 28 | 0 | `ae2gr5t3` |
| 1696 | hard | correct | 26 | 0 | `p5o49jbs` |

## Top 10 fastest correct answers (low tool-call count)

| task_id | level | tool_calls | answer |
|---|---|---|---|
| 1 | easy | 2 | `138236` |
| 72 | easy | 2 | `Belles_cookbook_store,Crossfit_Hanna,Golfclub_Baron_Friso,Ma` |
| 2 | easy | 3 | `91.852` |
| 3 | easy | 3 | `27647` |
| 4 | easy | 3 | `NL` |
| 5 | easy | 3 | `NL` |
| 6 | easy | 3 | `73.150` |
| 7 | easy | 3 | `89.999711` |
| 8 | easy | 3 | `Ecommerce` |
| 9 | easy | 3 | `64` |

## How to dig deeper

- All sessions for a task: `ls analysis/kimi-k2.6/tasks/<task_id>/`
- Full event journal: `cat analysis/kimi-k2.6/tasks/<task_id>/trace.jsonl | jq -s '.'`
- Filter: `jq 'select(.classification=="iter_capped" and .level=="hard")' analysis/kimi-k2.6/index.jsonl`

