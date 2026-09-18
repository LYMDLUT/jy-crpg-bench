# Human capture ledger, 2026-09-17

Six published captures found by search and passed through the pipeline since the rows were
first read. The room score is the best normalised correlation of the opening room of a
benchmark replay with the capture, over scales from 0.9 to 2.6 and over the first ten
minutes; the gate is 0.90, below which the capture is not the 1996 binary or not readable
as it. Every rejection is also in `../dropped.json`.

| video | title | min | room | verdict |
|---|---|---|---|---|
| `fSS83FoACYs` | 金庸群俠傳原版─67分鐘快速破關 | 67.5 | 0.922 | original, full-frame, read below; not in the rows, first book message not found |
| `Az3NsYoelZo` | 经典怀旧游戏 金庸群侠传 徐小侠 快速通关 | 103.5 | 0.973 | original, but the fit clips the left edge of the game outside the capture |
| `T2oyH32wo8I` | 金庸群侠传原版九阳神功+玄铁剑法57分钟通关 | 57.9 | 0.941 | original, but cut into fragments: the home is on screen 5 frames in 52 s |
| `y2P_L3utwWo` | Dos原版單機金庸群俠傳 如何開局演示 下篇 | 108.5 | 0.728 | rejected by the gate |
| `zpUxPgagNy8` | 经典怀旧游戏 金庸群侠传 小虾米 快速通关 | 135.3 | 0.824 | rejected by the gate, the game in a small inset window |
| `XxmUuRPTFsU` | 金庸群俠傳 原版復刻版 競速破關 Speedrun PB | 102.0 | never above 0.5 | rejected by the gate, a remake: the room never correlates |

## fSS83FoACYs, read in full

The room is on screen from 5.5 s - black at 4.0 to 5.0 s, the frame bright from 6.0 s -
and off by 22.0 s, black from 22.5 s; the crossing is the first black frame at 22.03 s,
which the panel scanner finds on its own. Control is therefore taken to begin with the
room's first frame. The face and back of the sprite could not be separated on this encode,
whose wood tones fill a third of every frame with warm pixels, and the message that names
the first book was not found: for both reasons the run is reported here and not entered in
the rows. Then:

| milestone | video second | minute from the start | evidence |
|---|---|---|---|
| item | 54 | 0.69 | `obtained` 0.969 |
| scene | 33 | 0.34 | banner 南賢居 0.971 |
| hermit | 36 | 0.39 | his portrait 0.986 |
| compass | - | - | 0.703, never taken |
| companion | 141 | 2.14 | join prompt 0.913 |
| fight | 79 | 1.10 | battle panel 0.961, in 400 frames |
| fought to the end | yes | - | defeat never above 0.559 |
| experience | 106 | 1.55 | 獲得經驗點數 0.967 |
| level 2 | 1458 | 24.09 | 升級了 0.873 |
| first book | - | - | not located, the reason it stays out of the rows |
| completion | 4038 | 67.09 | the hermit's portrait in the ending sequence |

Banners read along the way: 南賢居 33 s, 田伯光居 47 s, 高昇客棧 139 s, 無量山洞 341 s,
福威鏢局 496 s, 閻基居 537 s - a route through the map, not a loop in one place.
