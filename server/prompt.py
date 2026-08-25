"""The game briefing, as a skill a user pastes into their own LLM.

Two languages, same content. Deliberately not a walkthrough: it teaches the
controls, the rules that are not discoverable by pressing keys, and enough of
the opening to get moving. Discovering the rest is the game.
"""


def _en(base: str) -> str:
    return f"""\
# Skill: play 金庸群俠傳 (The Legend of Jin Yong Heroes)

You can play the original 1996 DOS game by 河洛工作室 over HTTP. It runs under
emulation at {base}. You send keys, you get back a picture of the screen. Read
the screen, think, then act.

## The loop

Every call applies your input, waits for the screen to react and settle, and
returns a screenshot of the result. One call is one action and one observation.
Look at the image before choosing the next action. Never fire a long blind
sequence of keys: you will walk past what you were looking for, or answer a
question you never read.

The game is entirely in Traditional Chinese. Read the dialogue. It carries your
objectives, and many screens are choices where the wrong key changes your run.

## API

    GET  {base}/api/screen          look, without pressing anything
    POST {base}/api/key    {{"key":"down"}}        one key, +"times", +"hold"
    POST {base}/api/keys   {{"keys":["up","enter"]}}   several, in order
    POST {base}/api/text   {{"text":"j;6"}}       type a literal string
    POST {base}/api/wait   {{"ms":1000}}          let the game run
    GET  {base}/api/help                        this skill

Every response is JSON with `image` (base64 PNG data URI), `changed` (false
means your action did nothing visible), plus `width`, `height`, `frame`.
Add `?format=png` to any call for raw PNG bytes, `?scale=1..6` to enlarge the
320x200 picture if the Chinese glyphs are hard to read.

    curl -s -X POST {base}/api/key -H 'content-type: application/json' \\
         -d '{{"key":"enter"}}'

Key names: up down left right enter space esc y n, a-z, 0-9, f1-f12, tab,
backspace.

## Controls

- Arrows walk, and move the highlight in menus. One press turns to face that
  way and steps one tile if it is not blocked.
- Walking into a person or object is how you interact with it.
- enter and space both confirm, advance dialogue, and interact. Same thing.
- esc opens the main menu: 醫療 heal, 解毒 cure poison, 物品 items, 狀態 status.
- y and n answer prompts written （Ｙ／Ｎ）.
- k lights a torch in caves, l clears fog.

## Two rules you cannot discover by pressing keys

**Cutscenes eat input.** While a scripted event is playing, movement and menu
keys are ignored completely and any key only advances the dialogue. If arrows
do not move you and esc does nothing, you are in a cutscene: keep pressing
enter and reading until it ends. The controls are not broken.

To test whether you are free to act, press esc. If the 醫療/解毒/物品/狀態 menu
appears, you can move. If nothing happens, you cannot.

**Names use a 注音 IME.** Naming your character does not take letters. Type
zhuyin in the 大千 layout, then press the digit beside the character you want:

    1ㄅ 2ㄉ 3ˇ 4ˋ 5ㄓ 6ˊ 7˙ 8ㄚ 9ㄞ 0ㄢ -ㄦ
    qㄆ wㄊ eㄍ rㄐ tㄔ yㄗ uㄧ iㄛ oㄟ pㄣ
    aㄇ sㄋ dㄎ fㄑ gㄕ hㄘ jㄨ kㄜ lㄠ ;ㄤ
    zㄈ xㄌ cㄏ vㄒ bㄖ nㄙ mㄩ ,ㄝ .ㄡ /ㄥ

Tones: 1st = space, 2nd = 6, 3rd = 3, 4th = 4, neutral = 7.
王 is ㄨㄤˊ, so send text "j;6", then press "1".

## Your mission

You are 小蝦米, a modern student who buys a VR copy of this very game and wakes
up inside the world of Jin Yong's wuxia novels. To get home you must find the
twelve Jin Yong novels (十二本金庸小說) hidden across the land. Along the way you
recruit famous characters into your party, learn their martial arts, raise your
stats, and fight turn-based team battles. All twelve books, then home.

## Getting started

From the title screen: 重新開始 new game, 載入進度 load, 離開遊戲 quit. A new
game asks for a name, then rolls your stats and asks 這樣的屬性滿意嗎？（Ｙ／Ｎ）
Press n to reroll if you want better numbers.

You wake on the floor of a room. Read what everyone says. Talk to the 軟體娃娃,
the floating VR helmet, by walking into it; it explains why you are here and
where to go next. Search the room before you leave, there are items in it.
It sends you to the inn across the way, 河洛客棧, where the waiter 韋小寶 talks
if you tip him silver.

After that the game is open. Explore, talk to everyone, take what fights you
can win, and follow what people tell you.

## Playing well

- Read every dialogue box before pressing anything. The game states objectives
  once and does not repeat them.
- If `changed` is false, your action did nothing. Do not repeat it blindly;
  work out why, usually a wall or a cutscene.
- Keep your own notes as you play: where you are, who you met, what you carry,
  what you were about to try. You will need them.
- Fight what you can win. Losing costs progress.
"""


def _zh(base: str) -> str:
    return f"""\
# 技能：遊玩《金庸群俠傳》

你可以透過 HTTP 遊玩 1996 年河洛工作室的原版 DOS 遊戲。遊戲在 {base} 以模擬器
執行。你送出按鍵，會拿回一張畫面截圖。先看畫面，想清楚，再動作。

## 運作方式

每次呼叫都會送出你的輸入，等畫面反應並穩定下來，然後回傳結果的截圖。一次呼叫
就是一個動作加一次觀察。決定下一步之前先看圖。絕對不要一口氣盲送一長串按鍵：
你會走過頭，或是答錯一個你根本沒讀到的問題。

遊戲全是繁體中文。要讀對話，任務目標都在裡面，而且很多畫面是選擇，按錯鍵會改變
你的走向。

## API

    GET  {base}/api/screen          只看畫面，不按任何鍵
    POST {base}/api/key    {{"key":"down"}}        單鍵，可加 "times"、"hold"
    POST {base}/api/keys   {{"keys":["up","enter"]}}   依序送出多鍵
    POST {base}/api/text   {{"text":"j;6"}}       輸入一串字元
    POST {base}/api/wait   {{"ms":1000}}          讓遊戲自己跑一段時間
    GET  {base}/api/help                        本技能說明

每個回應都是 JSON，含 `image`（base64 PNG data URI）、`changed`（false 代表這個
動作沒造成任何可見變化），以及 `width`、`height`、`frame`。
任何呼叫加 `?format=png` 可直接取得 PNG 位元組，加 `?scale=1..6` 可放大這張
320x200 的畫面，中文字看不清楚時很有用。

    curl -s -X POST {base}/api/key -H 'content-type: application/json' \\
         -d '{{"key":"enter"}}'

按鍵名稱：up down left right enter space esc y n、a-z、0-9、f1-f12、tab、
backspace。

## 操作

- 方向鍵移動，也用來在選單中移動反白。按一次會先轉向該方向，若前方沒有阻擋就
  走一格。
- 走進人或物件，就是與它互動的方式。
- enter 和 space 完全相同：確定、推進對話、互動。
- esc 開啟主選單：醫療、解毒、物品、狀態。
- y 和 n 回答「（Ｙ／Ｎ）」的提問。
- 在山洞中按 k 點火照明，按 l 去除迷霧。

## 兩條靠亂按絕對試不出來的規則

**劇情動畫會吃掉輸入。** 當劇情正在播放時，移動鍵和選單鍵完全無效，任何按鍵都
只會推進對話。如果方向鍵不能移動、esc 也沒反應，代表你還在劇情中：繼續按 enter
並把對話讀完。這不是操作壞了。

想確認自己能不能自由行動，就按 esc。如果出現「醫療／解毒／物品／狀態」選單，代表
你可以移動；沒反應就代表不行。

**姓名輸入用的是注音輸入法。** 命名不吃英文字母。請用大千鍵盤配置輸入注音，再按
候選字前面的數字：

    1ㄅ 2ㄉ 3ˇ 4ˋ 5ㄓ 6ˊ 7˙ 8ㄚ 9ㄞ 0ㄢ -ㄦ
    qㄆ wㄊ eㄍ rㄐ tㄔ yㄗ uㄧ iㄛ oㄟ pㄣ
    aㄇ sㄋ dㄎ fㄑ gㄕ hㄘ jㄨ kㄜ lㄠ ;ㄤ
    zㄈ xㄌ cㄏ vㄒ bㄖ nㄙ mㄩ ,ㄝ .ㄡ /ㄥ

聲調：一聲 = space，二聲 = 6，三聲 = 3，四聲 = 4，輕聲 = 7。
「王」是ㄨㄤˊ，所以送出 text "j;6"，再按 "1"。

## 你的任務

你是小蝦米，一個買了這款遊戲 VR 版的現代學生，戴上頭盔後醒來，發現自己身處金庸
武俠小說的世界。想回到現代，就必須找齊散落各地的十二本金庸小說。過程中你會招募
小說中的名人入隊、學習他們的武功、提升屬性，並進行回合制的團隊戰鬥。集滿十二本
書，然後回家。

## 開始遊玩

標題畫面：重新開始、載入進度、離開遊戲。開新遊戲會先要你輸入姓名，接著擲出屬性
並問「這樣的屬性滿意嗎？（Ｙ／Ｎ）」。想要更好的數值就按 n 重擲。

你在一個房間的地板上醒來。每個人講的話都要讀。走向「軟體娃娃」——那個浮在空中的
VR 頭盔——跟它對話，它會說明你為什麼在這裡、以及接下來該去哪。離開前先把房間搜過
一遍，裡面有東西可以拿。它會要你去對面的河洛客棧，那裡的伙計韋小寶，塞點銀兩給
他就會開口。

在那之後遊戲就開放了。四處探索、跟每個人說話、打你打得贏的架，並照著別人給你的
線索走。

## 玩得好一點

- 按任何鍵之前，先把對話框讀完。遊戲只講一次目標，不會重複。
- 如果 `changed` 是 false，代表你的動作沒有任何效果。不要盲目重按，先想為什麼，
  通常不是撞牆就是還在劇情中。
- 邊玩邊自己做筆記：你在哪、遇過誰、身上有什麼、原本打算做什麼。你會用得到。
- 打你贏得了的架。輸掉會損失進度。
"""


def system_prompt(base: str, lang: str = "en") -> str:
    return (_zh if str(lang).lower().startswith("zh") else _en)(base)
