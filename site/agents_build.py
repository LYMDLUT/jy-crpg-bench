#!/usr/bin/env python3
"""Assemble agents.md, one per language, from the skills in ../skills.

The brief an agent reads is the same text the server hands out at /api/help,
plus a preamble about how a benchmark run starts and ends. Generating it here
rather than keeping a second copy means the skill cannot drift from the one the
game itself serves.

Chinese output is Simplified, but the words that appear on the game's own
screen stay Traditional: an agent matches what it reads against 1996 Taiwanese
text, and 罗盘 would never match 羅盤.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
SKILLS = HERE.parent / "skills"
BACKEND = "https://jy-crpg-bench-366646433082.us-central1.run.app"

# Everything in this list is text the agent will see rendered by the game, or a
# proper name the game uses. Masked before conversion so it survives.
ON_SCREEN = [
    "金庸群俠傳", "河洛工作室", "軟體世界娃娃", "軟體娃娃", "小蝦米",
    "崑崙仙境", "無量山洞", "河洛客棧", "天寧寺", "鐵掌山", "五毒教",
    "衡山派", "閻基居", "北丑居", "南賢居", "主角居", "南賢",
    "羅盤", "醫療", "解毒", "物品", "狀態", "離隊",
    "內力", "經驗", "攻擊", "防禦", "用毒", "御劍", "耍刀", "暗器", "自動", "升級", "移動",
    "輕功", "體力", "體質", "資質", "道德", "名望", "注音",
    # 隊 and 系統 are menu labels in some places and ordinary words in others.
    # Protecting the bare characters left prose reading "團隊回合制" and
    # "選單系統", so only the label contexts are held back.
    "隊 與 系統", "狀態、隊、系統", "「隊」和「系統」", "**隊**", "**系統**",
    "離隊與系統", "離隊、系統", "「系統」",
]

PRE_ZH = """# jy-crpg-bench

你即将游玩《金庸群俠傳》，1996 年河洛工作室的原版 DOS 游戏，未经修改，跑在模拟器上。
你送出按键，并取得画面。游戏是繁体中文。

## 开局

    curl -s -X POST {backend}/session \\
         -H 'content-type: application/json' \\
         -d '{{"agent":"YOUR-MODEL-NAME","minutes":{minutes}}}'

`agent` 填模型名和思考档位。`minutes` 是这一局的游玩时长，这份说明对应 {minutes} 分钟。
回应里的 `base_url` 以下称 `$BASE`，所有呼叫都送到那里。

开局时你已经在游戏里，站在开场房间，角色已经建好并有名字。不要改名，也不要碰注音输入法。

---

"""

PRE_EN = """# jy-crpg-bench

You are about to play 金庸群俠傳 (The Legend of Jin Yong Heroes), the original
1996 DOS game by 河洛工作室, running unmodified under emulation. You send keys
and fetch the screen. The game is in Traditional Chinese.

## Start

    curl -s -X POST {backend}/session \\
         -H 'content-type: application/json' \\
         -d '{{"agent":"YOUR-MODEL-NAME","minutes":{minutes}}}'

`agent` names the model and its thinking level. `minutes` is the playtime of
the run; this brief is the {minutes} minute one. The reply carries `base_url`,
called `$BASE` below. Every call goes there.

You start inside the game, in the opening room, with a character already made
and named. Do not change the name or touch the 注音 input method.

---

"""


def to_simplified(text: str) -> str:
    """Simplify the prose, leave the game's own words alone."""
    from zhconv import convert
    terms = sorted(set(ON_SCREEN), key=len, reverse=True)
    holes = {}
    for n, t in enumerate(terms):
        if t in text:
            key = f"\x00{n}\x00"
            holes[key] = t
            text = text.replace(t, key)
    text = convert(text, "zh-hans")
    for key, t in holes.items():
        text = text.replace(key, t)
    return text


def skill(lang: str) -> str:
    text = (SKILLS / f"play.{lang}.md").read_text(encoding="utf-8").rstrip()
    text += "\n\n" + (SKILLS / f"speedrun.{lang}.md").read_text(encoding="utf-8")
    # The markdown carries doubled braces in its JSON examples; un-double them
    # before the {BASE} substitution, so a doubled {{BASE}} would land at
    # $BASE instead of the corrupted {$BASE}.
    text = text.replace("{{", "{").replace("}}", "}").replace("{BASE}", "$BASE")
    # a scored session answers 404 to emulator snapshots; do not list them
    text = re.sub(r"^[ \t]*(?:GET|POST)[ \t]+\$BASE/api/(?:slots|save|load)\b.*\n", "",
                  text, flags=re.M)
    return text.strip() + "\n"


def build(lang: str, minutes: int = 60) -> str:
    pre = (PRE_EN if lang == "en" else PRE_ZH).format(backend=BACKEND,
                                                      minutes=minutes)
    body = skill(lang)
    if lang == "zh":
        body = to_simplified(body)
    return pre + body


# The page carries the chosen playtime in the URL it hands out rather than in
# the text of the line, so what a reader copies is just an address. One file
# per option, all generated from the same source, so they cannot drift. The
# first option is the default and lives at the root.
OPTIONS = [240, 20, 60, 480, 1440]


def main():
    made = []
    for lang, root in (("zh", HERE), ("en", HERE / "en")):
        for m in OPTIONS:
            d = root if m == OPTIONS[0] else root / f"{m}m"
            d.mkdir(parents=True, exist_ok=True)
            out = d / "agents.md"
            out.write_text(build(lang, m), encoding="utf-8")
            made.append(out)
    print(f"  {len(made)} briefs, {len(OPTIONS)} playtimes x 2 languages")
    for p in made[:1] + made[-1:]:
        print(f"    {p.relative_to(HERE.parent)}  {len(p.read_text())} chars")


if __name__ == "__main__":
    main()
