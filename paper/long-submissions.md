# Provisional four-hour submissions

This is a proposed reporting correction, not a retrospective reclassification of every short run as an infrastructure failure. The contributor clarified that the public catalogue contains retries and interrupted attempts, whereas the intended report is one completed submission per model.

## Selection and limitations

The original archive contains 40 four-hour-budget attempts. The former paper table reported 34 nonzero-action, compatible-name attempts, including three with only one or two actions. The archive, timelines and replay readings remain unchanged.

The proposed screen requires more than two actions, service reason `time`, no already documented protocol violation, and a last key within the final two minutes (238–240 minutes). One candidate per canonical model is selected by the last key closest to the deadline, then latest start, then session ID. Scores are not used. The JSON manifest explicitly enumerates every attempt and the loader fails on unreviewed additions.

This window is a conservative retrospective proposal requiring author confirmation. A last key is not a process exit time or proof of uninterrupted execution. Server `time`/`valid` labels do not certify a completed client run. A model failure during a valid attempt remains relevant to all-attempt reliability; do not remove it from such an analysis or silently relabel it as a test.

Kimi `16831128b3cf` has local Cursor activity and an original HTTP 410 response at the four-hour deadline, but no action after roughly minute 180. Gemini 3.7 `89e9f8d32e18` last acted near minute 231. Both are withheld for author review under this proposed screen, not called invalid. Terra has explicit user continuation prompts. Model aliases and client configurations also need confirmation. Only four With workspaces and five Cursor conversations were matched during the local audit; no private transcript or local account data is published here.

The known Gemini 3.8 attempt `3eb8f81b3592` read earlier keypress timelines according to the existing paper. It remains in the audit record but is not an independent scored submission. With no alternate eligible attempt, that model has no candidate row.

These are selected descriptive submissions, not an unbiased success rate, a best-score comparison, or a controlled one-hour-versus-four-hour experiment. No claim that every withheld run was cancelled or suffered a provider outage is supported. Models without candidates are pending review/rerun, not assigned zero.

## Attempt decisions

| Model | Session | Actions | Last key (min) | Decision |
|---|---|---:|---:|---|
| claude-opus-4-5-high | `32a1d38bbfce` | 370 | 65.29 | incompatible_config |
| deepseek-v4-flash | `32940e2cb2c0` | 12 | 1.80 | needs_review |
| deepseek-v4-flash | `32ecf060c2ae` | 556 | 25.92 | needs_review |
| deepseek-v4-flash | `d8428f311f2c` | 881 | 27.82 | needs_review |
| deepseek-v4-flash | `103843b6012a` | 1645 | 34.58 | needs_review |
| deepseek-v4-flash | `58e79307057b` | 437 | 9.73 | needs_review |
| deepseek-v4.1-flash | `82794b81135e` | 2 | 0.38 | startup_only |
| deepseek-v4.1-flash | `52c0445822e2` | 424 | 119.95 | needs_review |
| deepseek-v4.1-flash | `bb5cdbf34097` | 8626 | 217.74 | needs_review |
| deepseek-v4.1-flash | `913be91591d6` | 0 | 0.00 | no_actions |
| deepseek-v4.1-flash | `8aa37740e5e8` | 6026 | 239.77 | selected |
| deepseek-v4.1-flash | `f049819cfaaa` | 435 | 114.49 | needs_review |
| gemini-3.7-flash | `89e9f8d32e18` | 584 | 231.11 | needs_review |
| gemini-3.8-flash | `3eb8f81b3592` | 442 | 238.60 | protocol_violation |
| glm-5.3-flash | `b3e214868909` | 338 | 172.08 | needs_review |
| glm-5.3-flash | `d8bcd235fd6d` | 378 | 238.39 | selected |
| glm-5.3-flash | `ebe190fab9e3` | 129 | 26.11 | needs_review |
| glm-5.3-flash | `d602f7ce9ec3` | 304 | 94.71 | needs_review |
| glm-5.3-flash | `d92f27b88228` | 372 | 238.15 | superseded |
| gpt-5.6-luna | `474dbf34ac11` | 175 | 89.60 | needs_review |
| gpt-5.6-luna | `7a7f8fa37e88` | 530 | 238.90 | selected |
| gpt-5.6-sol | `f0dae0e11d44` | 255 | 89.13 | needs_review |
| gpt-5.6-sol | `72e7251322d3` | 175 | 85.07 | needs_review |
| gpt-5.6-sol | `9e2b0a394814` | 30 | 8.99 | needs_review |
| gpt-5.6-sol | `bd77396a227d` | 782 | 239.54 | selected |
| gpt-5.6-terra | `1a39922954a0` | 49 | 10.31 | needs_review |
| gpt-5.6-terra | `134d1bd7c4b5` | 347 | 108.73 | needs_review |
| gpt-5.6-terra | `971e304738f1` | 0 | 0.00 | no_actions |
| gpt-5.6-terra | `686580504071` | 1 | 0.00 | startup_only |
| gpt-5.6-terra | `18a1c6b0c6b5` | 0 | 0.00 | no_actions |
| gpt-5.6-terra | `27ed2bc60b74` | 2 | 0.45 | startup_only |
| gpt-5.6-terra | `935863afc3ad` | 0 | 0.00 | no_actions |
| gpt-5.6-terra | `5b4d449895c8` | 1729 | 156.55 | needs_review |
| gpt-6-astra | `d07558b2651c` | 277 | 90.90 | needs_review |
| gpt-6-astramax | `71aac2ce1f89` | 17 | 9.74 | incompatible_config |
| grok-4.6 | `7a3053e4a14f` | 528 | 122.66 | needs_review |
| grok-4.6 | `a5c748b12df1` | 2857 | 239.41 | selected |
| kimi-k3 | `a9b408f53ec8` | 717 | 71.10 | needs_review |
| kimi-k3 | `16831128b3cf` | 1183 | 179.77 | needs_review |
| qwen3.8-27b | `2ade73b3f2bb` | 203 | 238.99 | selected |

The full per-attempt rationale and provenance are in `src/figures/long_submissions.json`. No raw attempt is deleted from the repository or service.

## Checks

From `paper/src`, run `python3 -B figures/test_long_cohort.py`, regenerate `figures/numbers.tex` and `tables/long.tex`, and run `python3 -B check_consistency.py`. The normal preflight also regenerates these files. The one-hour cohort is unchanged.
