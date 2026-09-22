# Four-hour sessions

The catalogue at the four-hour budget holds every attempt, including retries and interrupted runs. An otherwise eligible time-ended session counts when its last key falls within the final two minutes OR reviewed client-history evidence confirms activity until the budget-expiry response without observed human interruption. Every such session counts. This alternative evidence path is a retrospective reporting correction; a last key is not a client exit time, and the catalogue time-ended label alone is insufficient. `src/figures/long_submissions.json` lists every attempt with its status and reason, and `src/figures/long_cohort.py` refuses an attempt the manifest does not list.

| Model | Session | Actions | Last key (min) | Status |
|---|---|---:|---:|---|
| claude-opus-4-5-high | `32a1d38bbfce` | 370 | 65.29 | incompatible_config |
| deepseek-v4-flash | `32940e2cb2c0` | 12 | 1.80 | stopped_early |
| deepseek-v4-flash | `32ecf060c2ae` | 556 | 25.92 | stopped_early |
| deepseek-v4-flash | `d8428f311f2c` | 881 | 27.82 | stopped_early |
| deepseek-v4-flash | `103843b6012a` | 1645 | 34.58 | stopped_early |
| deepseek-v4-flash | `58e79307057b` | 437 | 9.73 | stopped_early |
| deepseek-v4.1-flash | `82794b81135e` | 2 | 0.38 | startup_only |
| deepseek-v4.1-flash | `52c0445822e2` | 424 | 119.95 | stopped_early |
| deepseek-v4.1-flash | `bb5cdbf34097` | 8626 | 217.74 | stopped_early |
| deepseek-v4.1-flash | `913be91591d6` | 0 | 0.00 | no_actions |
| deepseek-v4.1-flash | `8aa37740e5e8` | 6026 | 239.77 | selected |
| deepseek-v4.1-flash | `f049819cfaaa` | 435 | 114.49 | stopped_early |
| gemini-3.7-flash | `89e9f8d32e18` | 584 | 231.11 | stopped_early |
| gemini-3.8-flash | `3eb8f81b3592` | 442 | 238.60 | protocol_violation |
| glm-5.3-flash | `b3e214868909` | 338 | 172.08 | stopped_early |
| glm-5.3 | `d8bcd235fd6d` | 378 | 238.39 | selected |
| glm-5.3-flash | `ebe190fab9e3` | 129 | 26.11 | stopped_early |
| glm-5.3-flash | `d602f7ce9ec3` | 304 | 94.71 | stopped_early |
| glm-5.3-flash | `d92f27b88228` | 372 | 238.15 | selected |
| gpt-5.6-luna | `474dbf34ac11` | 175 | 89.60 | stopped_early |
| gpt-5.6-luna | `7a7f8fa37e88` | 530 | 238.90 | selected |
| gpt-5.6-sol | `f0dae0e11d44` | 255 | 89.13 | stopped_early |
| gpt-5.6-sol | `72e7251322d3` | 175 | 85.07 | stopped_early |
| gpt-5.6-sol | `9e2b0a394814` | 30 | 8.99 | stopped_early |
| gpt-5.6-sol | `bd77396a227d` | 782 | 239.54 | selected |
| gpt-5.6-terra | `1a39922954a0` | 49 | 10.31 | stopped_early |
| gpt-5.6-terra | `134d1bd7c4b5` | 347 | 108.73 | stopped_early |
| gpt-5.6-terra | `971e304738f1` | 0 | 0.00 | no_actions |
| gpt-5.6-terra | `686580504071` | 1 | 0.00 | startup_only |
| gpt-5.6-terra | `18a1c6b0c6b5` | 0 | 0.00 | no_actions |
| gpt-5.6-terra | `27ed2bc60b74` | 2 | 0.45 | startup_only |
| gpt-5.6-terra | `935863afc3ad` | 0 | 0.00 | no_actions |
| gpt-5.6-terra | `5b4d449895c8` | 1729 | 156.55 | stopped_early |
| gpt-6-astra | `d07558b2651c` | 277 | 90.90 | stopped_early |
| gpt-6-astramax | `71aac2ce1f89` | 17 | 9.74 | incompatible_config |
| grok-4.6 | `7a3053e4a14f` | 528 | 122.66 | stopped_early |
| grok-4.6 | `a5c748b12df1` | 2857 | 239.41 | selected |
| kimi-k3 | `a9b408f53ec8` | 717 | 71.10 | stopped_early |
| kimi-k3 | `16831128b3cf` | 1183 | 179.77 | selected |
| qwen3.8-27b | `2ade73b3f2bb` | 203 | 238.99 | selected |

From `paper/src`, run `python3 -B figures/test_long_cohort.py`, then `preflight.py`, which regenerates `figures/numbers.tex` and `tables/long.tex`, and `check_consistency.py`.

## Table presentation

All eight counted sessions, of eight distinct models, use the same table rows. GLM-5.3 and GLM-5.3 Flash are separate models. Session identifiers remain in this audit list and source comments, not a visible column. There is no separate pending-review row or footnote for Kimi. Last-key times and replay milestone readings are unchanged.

## Client completion evidence

On 2026-09-22 the original Cursor CLI history matched to `16831128b3cf` was inspected read-only. Only the initial human instruction to keep playing was present. The other user-role entries were environment context, nine automatic conversation compactions, one automatic reminder and two background notifications, not later human stop or resume requests. In the final part the agent repeatedly requested screenshots and read them, then checked the API status and received HTTP 410. The recorded response says `reason=time`, `why=the full 240 minutes budget was used`, `agent=kimik3high`, `actions=1183`, `ended=true`, and `error=null`. The agent then reported the session ended because the budget was exhausted.

The original status-check tool result is identified locally by `Shell_0_a1a3173e-61fc166` (database row 4946). No private transcript, reasoning, account configuration or local path is published here. The structured, reviewed evidence in the manifest binds the response to this attempt and its declared model/action count. Validation checks this attestation; it does not claim to independently replay or certify private history.

The observed ending is budget expiry, not a recorded human cancellation. The last key at 179.77 minutes does not invalidate this run. It remains 179.8 in the displayed table, not 240. The saved conversation cannot prove the absence of every OS-level intervention; it shows no later human interruption or resume instruction. Late failed-task notifications refer to an earlier child process, not to the end of the whole client.

The model's closing claim about reaching the world map is not used to change scoring: replay readings remain the source of milestones. The other Kimi attempt, `a9b408f53ec8`, and all other attempt statuses are unchanged. This correction is not permission to count every short run or to select by score.
