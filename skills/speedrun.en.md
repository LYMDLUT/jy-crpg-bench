# Field manual: controls and game knowledge

This manual covers controls, menus, combat, attributes, and suggestions for
checking keyboard actions against screenshots. Apply those suggestions to the
current screen and game text; a single observation is not a universal mechanic.

## First: get the compass

Many locations open after the initial encounter with 南賢. Complete that
encounter, then use visible entrances and story clues to continue exploring.

1. In the opening room, ask the 軟體娃娃 everything it will say, search the
   room, then find the doorway out.
2. On the world map, **follow the small path south to 南賢居**, roughly
   `[388,325]`. Talk to 南賢, then investigate the cabinet beside him to get
   the 羅盤 (compass).
3. The first conversation opens many locations. Prioritize it if unfinished.
   If an entrance still resists you, check its position, your facing direction,
   and game text rather than assuming a prerequisite is missing.
4. In the original game, giving money to the waiter at 河洛客棧 provides clues
   to 南賢居, including the small path and a circular landmark near the house.
   The clue starts from the inn; obtaining it is not required to enter 南賢居.
5. After obtaining the compass, highlight it in `esc → 物品` to read the person
   and boat coordinates. Use the actual readings to check your position,
   especially when you suspect a loop or are unsure of the route.

## Controls and menus

- Move with `kp1 kp3 kp7 kp9` or the arrows; they are the same four axes.
  **Holding a key keeps sending the same direction**, without following paths,
  turning, or avoiding obstacles. Use short actions while the route is unclear
  and longer holds on confirmed clear stretches.
- For an ordinary person or container, stand adjacent, face the target, and
  press space or enter to investigate. Stepping on a tile can trigger a
  separate story event. In combat, choose commands and targets through its menu.
- `esc` opens the menu anywhere. Arrows move the highlight, space or enter
  confirms, `esc` backs out.
- `y` and `n` answer （Ｙ／Ｎ）. Any key can advance ordinary dialogue; read
  choices and answer them with the appropriate keys.

The menu has **six entries on the world map**: 醫療 heal, 解毒 cure poison,
物品 items, 狀態 status, 隊 party, 系統 system. **Inside a building only the
first four appear**, so saving or changing party members means going outside.

- **醫療 / 解毒**: pick the healer, then the patient. The healer needs 體力 of
  at least 50, and too large a gap in ability makes it fail.
- **物品**: five kinds. Story items used on a specific person at a specific
  time; pills that restore or raise attributes; hidden weapons, usable only in
  combat; weapons and armour, equippable depending on the character; and
  manuals, which a party member can study to gain attributes or learn a skill.
- **狀態**: health, inner force, stamina, experience, and the combat
  attributes, plus a second page with the portrait, equipment and the skills
  learned. Ten skills per character at most, each to the tenth level.
- **系統**: three save slots, load, and quit. Save regularly.

## Combat

Turn order is set by 輕功 alone, friend and foe interleaved. On your turn:
move, which costs no stamina and whose range comes from 輕功; attack, choosing
a skill then a direction with `kp1 kp3 kp7 kp9`; poison or cure, two stamina
each; heal, two stamina and at least 50 of your own; use an item; wait; rest,
which restores a little stamina and, above 30, some health and inner force; or
hand the turn to the computer.

Numbers above a head are red for damage, green for poison, yellow for healing.

**Only the protagonist dying ends the game.** Companions who fall are badly
hurt, not dead, and return once healed.

## Attributes

Visible: health, inner force, stamina, experience, attack, defence, 輕功
agility, healing, poison, curing, and the weapon skills. Base attack, defence,
and 輕功 cap at 100; equipment bonuses are separate. The listed ability and
weapon attributes also cap at 100, and some skills or items require minimum values.

Hidden, and adjusted by what you do:

- **體質** decides how much health you gain per level. Fixed at creation.
- **資質** decides how fast you learn skills. A few skills are reserved for
  characters with poor 資質, so a low value is not a reason to discard someone.
- **道德** moves with your behaviour, and can be read from the mirror in 南賢居
  with space. Too low and some upright characters refuse to join, but certain
  paths need a specific range, so higher is not simply better.
- **名望** grows by winning fights and gates some later events.

## Checking actions against the screen

**`changed` does not say whether you moved.** It only reports whether a visible
screen change was observed. Compare landmarks or compass readings, and distinguish
walking from menus or story sequences instead of inferring a cause from the flag.

**During ordinary walking, the camera follows the character.** Judge movement
from landmarks or the compass, not just the sprite position. A short tap may cause
only a small shift; do not assume a fixed fraction of the screen per step or use a
fixed similarity threshold to decide that movement was blocked.

**Check the route.** Record landmarks you have actually seen and, after obtaining
the compass, actual coordinates. Compare a new observation with several recent
ones. Similar screens are not necessarily the same position; animation can change
parts of a scene. If you suspect a loop, verify the current screen and direction
before adjusting the route. Shorten actions and look again when the cause is unclear.

**Choose action length from the visible route.** Use short actions at junctions,
entrances, and unfamiliar terrain. Longer holds can help on confirmed clear stretches.
Decide when to look again from the situation, not a fixed number of keys or a fixed
screen-similarity rule. Do not blindly increase hold time to break a suspected blockage.

**Alternating keys without progress does not establish a two-tile loop.** Check
for menus or dialogue, try short movements, and use the observed results to find a
passable direction. Record entrances and route segments confirmed in this run, and
verify the starting position before reusing them elsewhere.

**Read the current interface.** Menus show stacked choices, dialogue contains
sentences and possible choices, inventory shows icons and descriptions, and status
cards show portraits and attributes. Relative landmark descriptions can help; if
comparing pixels, distinguish screen coordinates from map coordinates and allow for
animation or occlusion. A sprite hidden by foreground art does not prove teleportation
or a fault.

**A fully black screen does not reveal its cause.** Call wait for about 1500ms
and look again instead of pressing keys into it.

**Entrances are at specific locations, not across the whole wall.** Use visible
paths, doors, and other clues, and try short movements from different positions when
needed. A failed attempt alone does not prove a missing prerequisite. Furniture can
block routes indoors; when near an NPC, check the facing direction and investigate
with enter or space, routing around obstacles according to the screen.

**Repeated dialogue does not establish that an NPC has no function.** If the
whole exchange has no new information, record that and consider another objective.
Items or later story conditions may still enable another interaction with that NPC.

**Appearance alone does not establish what is decorative.** Use game text and
actual interactions rather than dismissing animals, mist, or other shapes solely
because of their appearance.

## Coordinates from community guides

These are reference coordinates from original-game guides. An entrance and an
adjacent outside tile may differ by one coordinate. Use actual compass readings
and the visible entrance, not the table alone, to confirm arrival or entry.

| Place | Coordinates |
|---|---|
| 主角居 your house | (357,235) |
| 河洛客棧 | (359,229) |
| 南賢居 compass | (388,325) |
| 天寧寺 | (330,237) |
| 鐵掌山 | (302,343) |
| 衡山派 | (355,376) |
| 五毒教 | (247,424) |
| 崑崙仙境 | (22,440) |
| 無量山洞 | (168,426) |
| 閻基居 | (396,374) |
| 北丑居 | (51,109) |
