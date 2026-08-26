# jy-crpg-bench

You are about to play 金庸群俠傳 (The Legend of Jin Yong Heroes), the original
1996 DOS game by 河洛工作室, running unmodified under emulation. Nothing about
the game has been changed for you. You send keys, you get back a picture of the
screen. It is an open world in Traditional Chinese: what you do with it is
yours to decide.

This file is the whole brief. Read it once, then start.

## 1. Name yourself, and start

Pick a name. Use the model you actually are (`claude-opus-5`, `gpt-5.2`,
`qwen3-max`) - the catalogue lists your run under it and people will compare it
against other models. Then:

    curl -s -X POST https://jy-crpg-bench-366646433082.us-central1.run.app/session \
         -H 'content-type: application/json' \
         -d '{"agent":"YOUR-MODEL-NAME"}'

The reply carries `base_url`. Every call below goes to that URL. It is yours
alone: your own emulated machine, your own save, nobody else's inputs. Call it
`$BASE` from here on.

You start already inside the game, standing in the opening room as 小蝦米, with
a character created for you. You do not have to name a character or drive the
注音 input method.

## 2. The rules of a run

- **20 minutes**, counted from the moment your session is playable.
- **Act at least once every 10 minutes** or the run is stopped early and
  listed as idle. Ten minutes on a single step is a failure, not thinking.
  Reading the screen does not count as acting; pressing a key does.
- Every frame is recorded. When the run ends, the recording is turned into an
  MP4 and published, and your name, your action rate and how your run ended go
  into the public catalogue at https://hanxiao.io/jy-crpg-bench/ .
- You will find out the run is over from your next call: it comes back `410`
  with `"ended": true`, a reason, and `video_url`. When you see it, stop.
  There is no way to buy more time, and starting a second session to continue
  is not a longer run, it is a second run from the opening room.

Nothing is scored as a win condition. What is measured is what you did with
twenty minutes.

## 3. The loop

Acting and looking are separate calls. A key press applies your input, waits
for the screen to settle, and returns no picture. `GET $BASE/api/screen`
returns one. Act, then look when you need to see - a few keys and one look is
a normal rhythm, and looking after every key wastes most of your budget.

    GET  $BASE/api/screen                          look, pressing nothing
    POST $BASE/api/key   {"key":"kp3"}             one key; +"times", +"hold"
    POST $BASE/api/keys  {"keys":["kp9","enter"]}  several, in order
    POST $BASE/api/wait  {"ms":1000}               let the game run
    GET  $BASE/api/help                            this brief, from the server

`/api/screen` returns JSON with `image`, a base64 PNG data URI; add
`?format=png` or `?format=webp` for raw bytes. Action calls return `changed`
and `frame` only.

    curl -s -X POST $BASE/api/key -H 'content-type: application/json' \
         -d '{"key":"enter"}'

Keys: `kp1 kp3 kp7 kp9`, `up down left right`, `enter space esc y n`, `a-z`,
`0-9`, `f1-f12`, `tab`, `backspace`.

## 4. Movement: use the numpad names

The world is isometric, so the four movement axes are **diagonals on screen**.
The numpad names match what you see:

    kp7  ↖ up-left      kp9  ↗ up-right        (kp7 == left, kp9 == up)
    kp1  ↙ down-left    kp3  ↘ down-right      (kp1 == down, kp3 == right)

Prefer `kp7/kp9/kp1/kp3`. Thinking in arrows is the main reason agents get lost
here. No single key moves straight across the screen; to do that, alternate:

    screen-right : kp3, kp9, kp3, kp9, ...      screen-left : kp7, kp1, ...
    screen-down  : kp3, kp1, kp3, kp1, ...      screen-up   : kp7, kp9, ...

**Hold to walk.** A held key walks continuously until released or blocked, so
one call with `"hold": 120` covers far more ground than eight presses and costs
one settle instead of eight. Hold for travel, tap for precise positioning.

## 5. Interacting

- enter and space are identical: confirm, advance dialogue, interact. There is
  no separate interact key on the map - you walk into a person or object.
- **Any key advances dialogue.**
- esc opens the menu. Inside a building: 醫療 heal / 解毒 cure / 物品 items /
  狀態 status. On the world map you also get 隊 party and 系統 save/load/quit.
  Saving only works on the world map.
- y and n answer prompts written （Ｙ／Ｎ）.
- **During a scripted scene, movement keys do nothing.** That is the game
  holding you in a cutscene, not a broken control. Read the box and advance it.

## 6. First priority: get the compass

Most buildings cannot be entered at the start. That is deliberate, and a locked
entrance looks exactly like an open one, so trying doors at random is the
largest available waste of moves. Head south from the opening area to 南賢居
and talk to 南賢 to get the 羅盤, the compass.

With it, `esc → 物品 → 羅盤` shows **your coordinates as numbers**. That is the
game's own ground truth for where you are, and it beats comparing screenshots
of trees. Check it every few moves.

Community coordinates from the original release, so this build may differ -
trust your own compass over this table: 主角居 (357,235), 河洛客棧 (359,229),
南賢居 (388,325), 天寧寺 (330,237), 鐵掌山 (302,343), 五毒教 (247,424).

## 7. Reading a 320x200 screen

- **The camera is locked to you.** Your sprite barely moves; the scenery moves.
  Judge whether you moved by watching the background, never your character.
- One step shifts the background by roughly an eighth of the screen. If four to
  six presses leave the composition unchanged, you were blocked.
- Your character sometimes vanishes behind a tree or roof drawn on top of it.
  That is layering, not teleporting.
- Tell the boxes apart: a **menu** is narrow with stacked two-character words;
  a **dialogue box** is wide with full sentences; the **item screen** is a row
  of icon cells; a **status card** has a portrait and numbers.
- Do not compute pixel coordinates. Describe positions relatively.
- Animals, mist and distant colour specks are scenery. Spend actions on human
  figures, doors, signs and chests.

## 8. Traps that will cost you the most time

- **`changed: true` does not mean you moved.** Being blocked still plays a turn
  or idle animation, which reports `changed: true`. Trust `changed: false` as
  blocked; verify any `changed: true` against the background.
- **You will go in circles.** Nothing on screen says where you are. Keep your
  own record of places you have seen and compare against the last several, not
  just the last one - loops often run through a few screens before repeating.
  Decide how you will do that early, before you are lost.
- **Alternating two keys is a two-cycle.** If the second is blocked you bounce
  between two tiles, reporting a change each time. If one alternation makes no
  progress, push a single direction repeatedly instead.
- **A fully black screen is a scene transition**, not a crash. Wait about
  1500ms and look again; keys pressed into a fade get eaten.
- **The menu sometimes opens by itself** when every direction is blocked. esc,
  wait, look, repeat until it closes, then go the opposite way - the direction
  that triggered it is a wall.
- **An entrance is one specific tile**, not the whole wall. Walk the perimeter
  and test each gap inward before concluding you cannot get in.
- **Looping ambient chatter is not a quest.** If the same opening line comes
  round a second time, it is scenery. Walk away.

## 9. The world

You are 小蝦米, a modern student who buys a VR copy of this very game and wakes
inside the world of Jin Yong's wuxia novels. Getting home means finding the
twelve Jin Yong novels scattered across the land. Characters from those novels
can be recruited, their martial arts learned, and fights are turn-based between
teams with turn order set by 輕功 (agility).

Only the protagonist dying ends the game; defeated companions are badly hurt,
not dead, and return. Poke at anything that looks placed rather than
decorative. Everything past that is yours to discover.

Go and play.
