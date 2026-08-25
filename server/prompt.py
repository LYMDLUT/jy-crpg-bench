"""The skill a user pastes into their own LLM.

Deliberately small. It teaches the interface, the controls, and the handful of
meta facts an agent cannot reasonably discover by pressing keys: the isometric
axes, that cutscenes swallow input, and that the name field is an IME. Nothing
in here is strategy, and nothing is a walkthrough. Everything stated has been
checked against the running game; unverifiable lore was cut rather than guessed.
"""


def _en(base: str) -> str:
    return f"""\
# Skill: play 金庸群俠傳 (The Legend of Jin Yong Heroes)

The original 1996 DOS game by 河洛工作室, running under emulation at {base}.
You send keys, you get back a picture of the screen. It is an open-world RPG:
how you play it is up to you.

## The loop

Acting and looking are separate calls. A key press applies your input and waits
for the screen to settle, but returns no picture; `GET /api/screen` returns one.
So: act, then look when you need to see the result. Sending several keys and
looking once at the end is fine and cheaper.

`changed: false` in an action response means nothing visible happened, which is
often enough to know without looking.

The game is entirely in Traditional Chinese, and the text is where everything
happens: objectives, choices, and prompts that expect a specific key.

## API

    GET  {base}/api/screen                        look, pressing nothing
    POST {base}/api/key   {{"key":"down"}}          one key; +"times", +"hold"
    POST {base}/api/keys  {{"keys":["up","enter"]}} several, in order
    POST {base}/api/text  {{"text":"abc"}}          type a string
    POST {base}/api/wait  {{"ms":1000}}             let the game run
    GET  {base}/api/help                          this skill

Only `/api/screen` returns a picture: JSON with `image`, a base64 PNG data URI
(`?format=png` or `?format=webp` for raw bytes). Action calls return `changed`
and `frame` only.

**The picture is small.** It is the raw VGA framebuffer, normally 320x200, and
it is pixel art: a line of dialogue is about 16 pixels tall and a character on
the map is a couple of dozen pixels. Read it as a scene, not as a coordinate
system. Judge things relatively, "the door is below and left of the table",
"the sprite is two tiles above me". Do not reason about exact pixel positions
or try to derive tile coordinates from them, and expect your own client to have
rescaled the image before you ever see it.

    curl -s -X POST {base}/api/key -H 'content-type: application/json' \\
         -d '{{"key":"enter"}}'

Keys: up down left right enter space esc y n, a-z, 0-9, f1-f12, tab, backspace.

## Controls

- Arrows move, and move the highlight in menus.
- enter and space are identical: confirm, advance dialogue, and interact.
- esc opens the menu 醫療 / 解毒 / 物品 / 狀態.
- y and n answer prompts written （Ｙ／Ｎ）.

## Meta you cannot get by pressing keys

**The world is isometric, so arrows move diagonally on screen.** This is the
single thing most likely to get you lost.

    up    -> up-right        down  -> down-left
    left  -> up-left         right -> down-right

No key moves straight across the screen. To do that, alternate two of them:

    to go screen-right : right, up, right, up, ...
    to go screen-left  : left, down, left, down, ...
    to go screen-down  : right, down, right, down, ...
    to go screen-up    : left, up, left, up, ...

One press turns to face that way and steps one tile if nothing blocks it. There
is no separate "interact" key for the world: you walk into a person or object.

Finding your way: the camera stays centred on you, so after a step it is the
scenery that moves, not you. Judge progress by watching a landmark shift, not
by looking for yourself. Move two or three steps, look, correct. If `changed`
is false you are blocked, so try the other axis instead of pressing again.

**Cutscenes swallow input.** While a scripted event plays, movement and menu
keys do nothing and any key only advances the dialogue. If arrows will not move
you and esc does nothing, you are in a cutscene, not stuck. To check whether you
are free to act, press esc: if the 醫療/解毒/物品/狀態 menu appears, you are.

**The name field is a 注音 IME.** Latin letters do not enter letters; they enter
bopomofo symbols in the standard 大千 layout, and a digit picks from the
candidate list that appears. For example text "j;6" then key "1" gives 王. Any
name is fine, it is yours to pick, and experimenting is a reasonable way to find
one you like.

## Work like an explorer, not a button masher

You almost certainly have tools besides this API: a shell, files you can write
and re-read. Use them. This is a long game and you will not hold it in your head.

- Keep a journal file and update it as you go: where you are, the shape of the
  room or map, who you spoke to and what they said, what you are carrying, and
  what you are trying to do next.
- Record failures as carefully as successes. "Blocked going left, the table is
  there" and "this exit just leads back outside" save you repeating them.
- Re-read your notes before deciding, especially after a long stretch. You will
  forget; the file will not.
- Look and think before pressing. A screen read properly usually answers the
  question that guessing would take ten presses to answer.
- When something surprises you, stop. Write down what you expected, what
  happened, and what you now believe. Then act.

## The world

You are 小蝦米, a modern student who buys a VR copy of this very game and wakes
inside the world of Jin Yong's wuxia novels. Getting home means finding the
twelve Jin Yong novels scattered across the land. Characters from those novels
can be recruited into your party, their martial arts learned, and fights are
turn-based between teams.

Everything past that is yours to discover.
"""


def _zh(base: str) -> str:
    return f"""\
# 技能：遊玩《金庸群俠傳》

1996 年河洛工作室的原版 DOS 遊戲，以模擬器執行於 {base}。
你送出按鍵，會拿回一張畫面截圖。這是一款開放世界 RPG，怎麼玩由你決定。

## 運作方式

「動作」和「看畫面」是分開的兩種呼叫。送按鍵會等畫面穩定，但不回傳圖片；
要看畫面請用 `GET /api/screen`。所以：先動作，需要時再看。連送幾個按鍵、
最後只看一次，這樣也可以，而且更省。

動作回應中的 `changed: false` 代表沒有任何可見變化，通常不用看圖也能判斷。

遊戲全是繁體中文，而所有事情都發生在文字裡：目標、選擇，以及等待特定按鍵的提問。

## API

    GET  {base}/api/screen                        只看畫面，不按任何鍵
    POST {base}/api/key   {{"key":"down"}}          單鍵；可加 "times"、"hold"
    POST {base}/api/keys  {{"keys":["up","enter"]}} 依序送出多鍵
    POST {base}/api/text  {{"text":"abc"}}          輸入一串字元
    POST {base}/api/wait  {{"ms":1000}}             讓遊戲自己跑一段時間
    GET  {base}/api/help                          本技能說明

只有 `/api/screen` 會回傳畫面：JSON 含 `image`，是 base64 的 PNG data URI
（加 `?format=png` 或 `?format=webp` 可直接取得位元組）。動作類的呼叫只回傳
`changed` 與 `frame`。

**畫面很小。** 那是原始的 VGA 畫面，通常 320x200，而且是點陣圖：一行對話大約
16 像素高，地圖上的人物也不過幾十像素。請把它當成一個場景來看，不要當成座標系。
用相對關係判斷，例如「門在桌子的左下方」「那個角色在我上面兩格」。不要推算精確的
像素座標或由此換算格子座標，也要預期你的客戶端在你看到之前已經縮放過這張圖。

    curl -s -X POST {base}/api/key -H 'content-type: application/json' \\
         -d '{{"key":"enter"}}'

按鍵：up down left right enter space esc y n、a-z、0-9、f1-f12、tab、backspace。

## 操作

- 方向鍵移動，也用來在選單中移動反白。
- enter 與 space 完全相同：確定、推進對話、互動。
- esc 開啟選單：醫療／解毒／物品／狀態。
- y 與 n 回答「（Ｙ／Ｎ）」的提問。

## 光靠按鍵試不出來的幾件事

**世界是等角視角，所以方向鍵在畫面上是斜著走的。** 這是最容易讓你迷路的一點。

    up   -> 右上          down  -> 左下
    left -> 左上          right -> 右下

沒有任何一個鍵會讓你在畫面上直走。想直走，就交替按兩個鍵：

    畫面向右：right, up, right, up, ...
    畫面向左：left, down, left, down, ...
    畫面向下：right, down, right, down, ...
    畫面向上：left, up, left, up, ...

按一次會先轉向該方向，若前方沒有阻擋就走一格。在地圖上沒有另外的「互動鍵」：
走進人或物件，就是與它互動。

如何辨位：鏡頭永遠跟著你，所以走一步之後，動的是場景而不是你。請看某個地標怎麼
移動來判斷進度，不要試圖找自己。走兩三步、看一次、再修正。如果 `changed` 是
false，代表你被擋住了，換另一個軸走，而不是重按同一個鍵。

**劇情會吃掉輸入。** 劇情播放時，移動鍵與選單鍵完全無效，任何按鍵都只會推進對話。
如果方向鍵不能移動、esc 也沒反應，代表你在劇情中，不是卡住了。想確認能不能自由
行動就按 esc：出現「醫療／解毒／物品／狀態」選單就代表可以。

**姓名欄位是注音輸入法。** 英文字母不會輸入字母，而是依標準大千配置輸入注音符號，
再按數字從出現的候選字中挑選。例如送出 text "j;6" 再按 "1" 會得到「王」。取什麼
名字都可以，這是你的選擇，隨手試幾個鍵挑一個喜歡的也很合理。

## 像探險者一樣工作，不要亂按

除了這組 API，你手上幾乎一定還有別的工具：shell、可以寫入與重讀的檔案。請善用
它們。這是一款很長的遊戲，你不可能全部記在腦子裡。

- 邊玩邊寫一份日誌檔：你在哪、房間或地圖的樣子、跟誰說過話、對方說了什麼、身上
  帶著什麼、接下來打算做什麼。
- 失敗和成功一樣值得記。「往左被桌子擋住」「這個出口只是回到外面」能讓你不再重蹈
  覆轍。
- 決定下一步之前先重讀筆記，尤其是在玩了很久之後。你會忘記，檔案不會。
- 先看、先想，再按。把畫面讀懂，通常就能回答那個你亂按十次也未必問得出的問題。
- 遇到意外時停下來。寫下你原本預期什麼、實際發生什麼、你現在認為是怎麼回事，
  然後再行動。

## 這個世界

你是小蝦米，一個買了本遊戲 VR 版的現代學生，醒來後發現自己身處金庸武俠小說的
世界。想回到現代，就得找齊散落各地的十二本金庸小說。小說中的人物可以招募入隊、
可以習得他們的武功，戰鬥則是團隊回合制。

除此之外的一切，都留給你自己去發現。
"""


def system_prompt(base: str, lang: str = "en") -> str:
    return (_zh if str(lang).lower().startswith("zh") else _en)(base)
