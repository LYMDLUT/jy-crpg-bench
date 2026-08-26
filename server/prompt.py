"""The skill a user pastes into their own LLM.

The text lives in ../skills/*.md so it can be edited and reviewed as prose
rather than as a Python string. {BASE} is substituted with this host's URL so a
copied skill always points at the server the reader loaded it from.
"""
import pathlib

SKILLS = pathlib.Path(__file__).resolve().parent.parent / "skills"
_cache: dict[str, str] = {}


def _load(stem: str) -> str:
    if stem not in _cache or not _cache[stem]:
        _cache[stem] = (SKILLS / f"{stem}.md").read_text(encoding="utf-8")
    return _cache[stem]


def system_prompt(base: str, lang: str = "en", core_only: bool = False) -> str:
    """The whole briefing: how to drive the game, then the field manual.

    Served complete by default. ?part=core trims to the first half for a
    context budget that cannot take the manual.
    """
    name = "zh" if str(lang).lower().startswith("zh") else "en"
    text = _load(f"play.{name}")
    if not core_only:
        text = text.rstrip() + "\n\n" + _load(f"speedrun.{name}")
    # the markdown carries doubled braces so the JSON examples survive editing
    return text.replace("{BASE}", base).replace("{{", "{").replace("}}", "}")
