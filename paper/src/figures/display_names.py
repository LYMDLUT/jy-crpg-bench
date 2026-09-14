"""Canonical labels for paper-facing model names.

Raw agent ids remain the keys used for grouping, filtering, and statistics.
Only strings rendered in prose, tables, and figures should pass through
``display_agent``.
"""
import re

_EXACT = {
    "random-baseline": "Random Baseline",
    "gpt-5.6-sol": "GPT-5.6 SOL",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-6-astra": "GPT-6 Astra",
    "glm-5.3-flash": "GLM-5.3 Flash",
    "grok-4.5": "Grok 4.5",
    "grok-4.6": "Grok 4.6",
    "gemini-3.6-flash": "Gemini 3.6 Flash",
    "gemini-3.7-flash": "Gemini 3.7 Flash",
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "claude-sonnet5": "Claude Sonnet 5",
    "claude-sonnet-5": "Claude Sonnet 5",
    "claude-opus5": "Claude Opus 5",
    "claude-fable5.1": "Claude Fable 5.1",
    "claude-fable-5.1": "Claude Fable 5.1",
    "qwen3.8-flash": "Qwen 3.8 Flash",
    "qwen3.8-27b-nvfp4": "Qwen 3.8 27B NVFP4",
}


def display_agent(agent: str) -> str:
    """Return the canonical human-facing label without changing the raw id."""
    raw = str(agent)
    suffix = ""
    base = raw
    if base.endswith("-high"):
        base = base[:-5]
        suffix = " (high)"
    for prefix in ("codex-cli--", "vista-codex-", "vista-", "codex-"):
        if base.startswith(prefix):
            client = prefix.rstrip("-").replace("-", " ").title()
            rest = base[len(prefix):]
            label = f"{client} / {display_agent(rest)}"
            return label + suffix
    key = base.lower().replace("_", "-")
    if key in _EXACT:
        return _EXACT[key] + suffix
    # Conservative fallback for labels newly added to the catalogue: preserve
    # the identifier while making the vendor/model separators readable.
    words = re.split(r"[-_]+", base)
    if words and words[0].lower() in {"gpt", "glm"}:
        words[0] = words[0].upper()
    elif words and words[0].lower() in {"qwen", "gemini", "claude", "grok", "random"}:
        words[0] = words[0].title()
    return " ".join(words) + suffix
