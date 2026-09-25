# Four-hour sessions

The catalogue at the four-hour budget holds every attempt, including retries and interrupted runs. A session counts when the service ended it at the budget and its last key falls within the final two minutes, and every such session counts, as every played session counts at the hour. One more session, `ac1e0b048aa4` of claude-opus-5.5, counts as a special case: the service ended it at the budget, its last key came at minute 229, and it is the one four-hour session that goes beyond the opening. `src/figures/long_submissions.json` lists every attempt with its status and reason, and `src/figures/long_cohort.py` refuses an attempt the manifest does not list. The session id of each row of Table 5 is a comment above the row in `src/tables/long.tex`.

| Model | Session | Actions | Last key (min) | Status |
|---|---|---:|---:|---|
| claude-opus-4-5-high | `32a1d38bbfce` | 370 | 65.29 | incompatible_config |
| claude-opus-5.5 | `b0dbef24e731` | 0 | 0.00 | no_actions |
| claude-opus-5.5 | `ac1e0b048aa4` | 11850 | 229.31 | selected (special case) |
| claude-opus-5.5 | `a424a8d10d55` | 5310 | 234.23 | stopped_early |
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
| gemini-3.8-flash | `b90f223b4e54` | 672 | 139.94 | stopped_early |
| gemini-3.8-flash | `54cd9429d714` | 62 | 30.74 | stopped_early |
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
| gpt-6-astra | `755a21baf0d7` | 349 | 185.39 | stopped_early |
| gpt-6-astra | `f9eb8dceb896` | 82 | 22.18 | stopped_early |
| gpt-6-astramax | `71aac2ce1f89` | 17 | 9.74 | incompatible_config |
| grok-4.6 | `7a3053e4a14f` | 528 | 122.66 | stopped_early |
| grok-4.6 | `a5c748b12df1` | 2857 | 239.41 | selected |
| grok-4.7 | `7b8280a83748` | 1274 | 68.90 | stopped_early |
| kimi-k3 | `a9b408f53ec8` | 717 | 71.10 | stopped_early |
| kimi-k3 | `16831128b3cf` | 1183 | 179.77 | stopped_early |
| qwen3.8-27b | `2ade73b3f2bb` | 203 | 238.99 | selected |

From `paper/src`, run `python3 -B figures/test_long_cohort.py`, then `preflight.py`, which regenerates `figures/numbers.tex` and `tables/long.tex`, and `check_consistency.py`.
