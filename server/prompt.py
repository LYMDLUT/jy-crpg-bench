"""The skill a user pastes into their own LLM.

The text lives in ../skills/*.md so it can be edited and reviewed as prose
rather than as a Python string. {BASE} is substituted with this host's URL so a
copied skill always points at the server the reader loaded it from.
"""
import pathlib

SKILLS = pathlib.Path(__file__).resolve().parent.parent / "skills"
_cache: dict[str, str] = {}


def _load(name: str) -> str:
    if name not in _cache or not _cache[name]:
        path = SKILLS / f"play.{name}.md"
        _cache[name] = path.read_text(encoding="utf-8")
    return _cache[name]


def system_prompt(base: str, lang: str = "en") -> str:
    name = "zh" if str(lang).lower().startswith("zh") else "en"
    # the markdown carries doubled braces so the JSON examples survive editing
    return _load(name).replace("{BASE}", base).replace("{{", "{").replace("}}", "}")
