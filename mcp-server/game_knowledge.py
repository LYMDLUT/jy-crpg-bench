"""Everything an agent needs to know to play 金庸群俠傳 (1996, DOS).

Kept separate from the transport so the wording can be tuned without touching
the tool plumbing. Facts marked (verified) were measured against this build.
"""

INSTRUCTIONS = """
You are playing 金庸群俠傳 (The Legend of Jin Yong Heroes), the original 1996
DOS game by 河洛工作室, running under emulation. You drive it with a keyboard
only. There is no mouse.

HOW TO PLAY WITH THESE TOOLS
Successful action tools return a PNG after applying input and waiting briefly
for the screen to react. It may still be animating. Look at that image before choosing the
next action. One tool call is one action and one observation. Do not batch long
blind sequences: read each screen.

The game is entirely in Traditional Chinese. Read the dialogue. It carries the
objectives, and several screens are yes/no or menu choices where pressing the
wrong key changes the run.

CONTROLS
- arrow up/down/left/right: walk on the map, and move the highlight in menus.
  Obstacles can prevent movement. Walking alone does not investigate an
  ordinary person or container.
- enter (or space): confirm a menu choice or advance ordinary dialogue. To
  investigate, stand adjacent to the target and face it before pressing the key.
  Story events triggered by stepping on a tile are a separate mechanism.
- esc: open the main menu (醫療 heal / 解毒 cure poison / 物品 items / 狀態
  status). Press esc again to close it.
- y / n: answer 是/否 prompts, which the game writes as （Ｙ／Ｎ）.

READ THE CURRENT SCREEN
Dialogue, choices, menus, and animations can respond differently to a key.
Read visible text and answer choices explicitly. If movement or esc appears to
have no effect, do not assume that a cutscene is the cause or that the controls
are broken. Look again and, if the screen is animating, wait before choosing the
next input.

ENTERING A CHINESE NAME
Character naming uses the game's own 注音 (bopomofo) IME in the 大千 layout.
Type the zhuyin letters, then press the digit next to the character you want.
Layout:
  1ㄅ 2ㄉ 3ˇ 4ˋ 5ㄓ 6ˊ 7˙ 8ㄚ 9ㄞ 0ㄢ -ㄦ
  qㄆ wㄊ eㄍ rㄐ tㄔ yㄗ uㄧ iㄛ oㄟ pㄣ
  aㄇ sㄋ dㄎ fㄑ gㄕ hㄘ jㄨ kㄜ lㄠ ;ㄤ
  zㄈ xㄌ cㄏ vㄒ bㄖ nㄙ mㄩ ,ㄝ .ㄡ /ㄥ
Tones: 1st = space, 2nd = 6, 3rd = 3, 4th = 4, neutral = 7.
Example: 王 is ㄨㄤˊ, so type "j;6" then press "1" to pick 王. (verified)

THE STORY AND YOUR GOAL
You play 小蝦米, a modern student who buys a VR copy of this very game and wakes
up inside the world of Jin Yong's novels. To get home you must find the fourteen
Jin Yong novels scattered across the world. Along the way you recruit famous
characters into your party, learn their martial arts, and fight turn-based team
battles.

Opening sequence: talk to the 軟體娃娃 and search the starting room before
you leave. On the world map, follow the small path south to 南賢居. The waiter
at 河洛客棧 can provide route clues if you give him silver; obtaining the clue
is not required to enter 南賢居. Once there, talk to 南賢, then investigate the
cabinet beside him to obtain the compass.

PACING
Boot time varies. Wait and observe the screen rather than assuming a fixed delay. From the title,
重新開始 starts a new game, 載入進度 loads, 離開遊戲 quits. Use save_state before
anything risky: these are emulator snapshots and restore exactly, which the
game's own save system cannot do mid-scene.
"""

GUIDE = INSTRUCTIONS + """

KEY NAMES ACCEPTED BY press / press_sequence
  up down left right
  enter (aliases: ok, confirm)   space
  esc (aliases: cancel, back)
  y n   a-z   0-9   f1-f12
  tab backspace delete home end pageup pagedown
  shift ctrl alt, and combos such as "alt+x"

TUNING THE WAIT
Each action allows time for the screen to react and attempts to capture a
settled frame. If a dialogue line is still drawing, wait or adjust `stable`.
changed=false means no visible change was observed within that wait; it does
not identify why or prove that the action was a legitimate no-op.
"""
