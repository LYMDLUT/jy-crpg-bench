"""Presentation-only names for agent labels.

The catalogue keys are stable identifiers and remain lowercase (or retain
their upstream spelling).  This module is the single display boundary used by
tables, generated prose macros, and figure labels; it must never be used for
grouping or metric calculations.
"""

import re


def _model_name(label):
    """Format a model key after harness prefixes have been removed."""
    raw = label
    low = raw.lower()

    # The Qwen keys are inconsistent in the published catalogue.  Treat the
    # leading version as a model number, then title-case the product family
    # and hardware suffix without changing the identifier itself.
    m = re.fullmatch(r"qwen(\d+(?:\.\d+)?)-(.*)", raw, flags=re.I)
    if m:
        suffix = m.group(2).replace("-", " ")
        suffix = re.sub(r"\bflash\b", "Flash", suffix, flags=re.I)
        suffix = re.sub(r"\bnext\b", "Next", suffix, flags=re.I)
        suffix = re.sub(r"\bnvfp\b", "NVFP", suffix, flags=re.I)
        return f"Qwen {m.group(1)} {suffix}".strip()

    m = re.fullmatch(r"(claude)-(opus|sonnet|fable)-(.+)", low)
    if m:
        family = m.group(2).capitalize()
        # The source key uses a hyphen in Fable 5-1; retain that model
        # spelling while making the product name readable.
        return f"Claude {family} {m.group(3)}"

    m = re.fullmatch(r"(gemini)-(\d+(?:\.\d+)?)-(flash)", low)
    if m:
        return f"Gemini {m.group(2)} Flash"

    m = re.fullmatch(r"(gpt)-(\d+(?:\.\d+)?)-(sol|codex)", low)
    if m:
        return f"GPT-{m.group(2)} {m.group(3).upper() if m.group(3) == 'sol' else 'Codex'}"

    m = re.fullmatch(r"(glm)-(\d+(?:\.\d+)?)-(flash)", low)
    if m:
        return f"GLM-{m.group(2)} Flash"

    m = re.fullmatch(r"(grok)-(\d+(?:\.\d+)?)", low)
    if m:
        return f"Grok {m.group(2)}"

    if low == "random-baseline":
        return "Random Baseline"
    return raw


def display_agent(label):
    """Return the official-looking display name for one catalogue key."""
    if label == "codex-cli--gpt-5.6-sol--pi":
        return "Codex CLI / GPT-5.6 SOL / Pi"
    if label.startswith("vista-codex-"):
        return "Vista / Codex / " + _model_name(label[len("vista-codex-"):])
    if label.startswith("vista-"):
        return "Vista / " + _model_name(label[len("vista-"):])
    if label.startswith("probe-"):
        return label
    return _model_name(label)
