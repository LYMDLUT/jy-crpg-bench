"""Decode the game's own save layout out of a serialised machine image.

The game keeps its whole persistent state in one archive, `RANGER.GRP` for a
new game and `R<n>.GRP` for slot n, whose first three sections are the ones
worth reading:

    section 0   836 bytes    position, party roster, and the shared bag
    section 1   58240 bytes  320 character records of 182 bytes
    section 2   38000 bytes  200 item records of 190 bytes, with names

A running machine holds two copies of this state and they are not equivalent,
which decides how everything below is read. Measured by pausing a session,
picking one item up, and comparing serialised images:

* The bag immediately preceding the character records is the working copy and
  updates the moment an item is taken. The character records sit directly
  after it, in the same working region.
* A second copy of the whole 836-byte block, carrying the party roster and the
  world square, is the image the game loaded and it does not move while the
  player does. It refreshes when the game itself saves.

So `from_memory` reads the working copy and reports what a run has actually
done; the roster and the map square are only meaningful from an archive, which
`from_archive` reads. Field layouts come from the hojy reimplementation
(`ref-hojy`, GPLv3), and every one of them is checked against the shipped
`game/RANGER.GRP` by `server/test_save_state.py`.

Nothing here writes. Reading progress out of the machine is what keeps it
honest: an agent drives the game through keys and cannot reach these numbers,
so it cannot move them except by playing.
"""

import struct

# ---------------------------------------------------------------- section 0
BASE_HEADER = 12                     # int16: onShip, subMap, mainX, mainY, ...
TEAM_SLOTS = 6                       # BaseData.members
BAG_SLOTS = 200                      # BaseData.items, (id, count) pairs
BASE_BYTES = BASE_HEADER * 2 + TEAM_SLOTS * 2 + BAG_SLOTS * 4      # 836
TEAM_AT = BASE_HEADER * 2                                          # 24
BAG_AT = TEAM_AT + TEAM_SLOTS * 2                                  # 36

# ---------------------------------------------------------------- section 1
CHAR_SLOTS = 320
CHAR_SZ = 182
CHAR_BYTES = CHAR_SLOTS * CHAR_SZ                                  # 58240
# Offsets inside one character record.
C_ID, C_NAME, C_LEVEL, C_EXP = 0, 8, 30, 32
C_HP, C_MAXHP, C_STAMINA = 34, 36, 42
C_MP, C_MAXMP, C_ATTACK = 82, 84, 86
C_INTEGRITY, C_REPUTATION, C_POTENTIAL = 112, 118, 120
C_SKILL_ID, C_SKILL_LEVEL = 126, 146      # 10 each
C_ITEM, C_ITEM_COUNT = 166, 174           # 4 each, the items this character carries
LEARN_SKILLS = 10
CARRY_ITEMS = 4

# ---------------------------------------------------------------- section 2
ITEM_SLOTS = 200
ITEM_SZ = 190
I_ID, I_NAME, I_DESC, I_TYPE = 0, 2, 42, 82
# itemType, as the game files it: 0 story, 1 equipment, 2 manual, 3 medicine,
# 4 thrown.
ITEM_KINDS = ("story", "equipment", "manual", "medicine", "thrown")

# ---------------------------------------------------------------- section 3
# The places. Only the name is read: it is what a person watching a run wants
# to see instead of a pair of coordinates.
SUBMAP_SLOTS = 84
SUBMAP_SZ = 52
M_NAME = 2

# ---------------------------------------------------------------- section 4
SKILL_SLOTS = 93
SKILL_SZ = 136
K_NAME = 2
# The game keeps a skill's level in hundreds and shows a rank of one to ten.
SKILL_LEVEL_STEP = 100
SKILL_RANK_MAX = 10

# The fourteen novels that end the game, contiguous in the item table. The
# names are carried here so a mismatch against the shipped data is a test
# failure and not a silent zero.
BOOK_IDS = tuple(range(144, 158))
BOOK_NAMES = ("飛狐外傳", "雪山飛狐", "連城訣", "天龍八部", "射鵰英雄傳",
              "白馬嘯西風", "鹿鼎記", "笑傲江湖", "書劍恩仇錄", "神鵰俠侶",
              "俠客行", "倚天屠龍記", "碧血劍", "鴛鴦刀")

# The compass from the hermit's cabinet: the only source of coordinates the
# game offers, and the first event of the opening that sits behind a
# conversation rather than a door. Named here so a mismatch against the
# shipped data is a test failure and not a silent zero.
COMPASS_ID = 182
COMPASS_NAME = "羅盤"

MAX_ITEM_ID = ITEM_SLOTS - 1


def _text(raw):
    return raw.split(b"\0")[0].decode("big5", "replace")


def decode_team(base_block):
    """Character ids in the party, in slot order, empty slots dropped."""
    ids = struct.unpack_from(f"<{TEAM_SLOTS}h", base_block, TEAM_AT)
    return [i for i in ids if i >= 0]


def decode_position(base_block):
    """Where the party stands: which submap, and the world-map square.

    ``submap`` is the scene's id plus one, so zero means the party is on the
    world map itself and nothing else. That is what the game writes when it
    saves, and it is why the shipped R1-R3 slots start a loaded game outdoors
    while a new game starts in a room.
    """
    on_ship, submap, main_x, main_y, sub_x, sub_y = struct.unpack_from(
        "<6h", base_block, 0)
    return {"submap": submap, "on_world_map": submap == 0,
            "x": main_x, "y": main_y,
            "sub_x": sub_x, "sub_y": sub_y, "on_ship": bool(on_ship)}


def decode_bag(base_block):
    """``{item_id: count}`` for the shared bag, or None when implausible.

    Occupied slots are packed at the front, so a gap followed by an entry
    means this is not a bag and some unrelated region matched.
    """
    values = struct.unpack_from(f"<{BAG_SLOTS * 2}h", base_block, BAG_AT)
    bag, empty_seen = {}, False
    for slot in range(BAG_SLOTS):
        item_id, count = values[slot * 2], values[slot * 2 + 1]
        if item_id == -1 and count == 0:
            empty_seen = True
            continue
        if (empty_seen or not 0 <= item_id <= MAX_ITEM_ID
                or not 0 < count <= 32767 or item_id in bag):
            return None
        bag[item_id] = count
    return bag


def decode_character(chars, cid):
    """One character record as a dictionary, or None for an id out of range."""
    if not 0 <= cid < CHAR_SLOTS:
        return None
    r = chars[cid * CHAR_SZ:(cid + 1) * CHAR_SZ]
    if len(r) < CHAR_SZ:
        return None
    skills = struct.unpack_from(f"<{LEARN_SKILLS}h", r, C_SKILL_ID)
    levels = struct.unpack_from(f"<{LEARN_SKILLS}h", r, C_SKILL_LEVEL)
    carried = struct.unpack_from(f"<{CARRY_ITEMS}h", r, C_ITEM)
    counts = struct.unpack_from(f"<{CARRY_ITEMS}h", r, C_ITEM_COUNT)
    return {
        "id": struct.unpack_from("<h", r, C_ID)[0],
        "name": _text(r[C_NAME:C_NAME + 10]),
        "level": struct.unpack_from("<h", r, C_LEVEL)[0],
        "exp": struct.unpack_from("<H", r, C_EXP)[0],
        "hp": struct.unpack_from("<h", r, C_HP)[0],
        "maxhp": struct.unpack_from("<h", r, C_MAXHP)[0],
        "mp": struct.unpack_from("<h", r, C_MP)[0],
        "maxmp": struct.unpack_from("<h", r, C_MAXMP)[0],
        "attack": struct.unpack_from("<h", r, C_ATTACK)[0],
        "reputation": struct.unpack_from("<h", r, C_REPUTATION)[0],
        "potential": struct.unpack_from("<h", r, C_POTENTIAL)[0],
        "skills": sum(1 for s in skills if s > 0),
        "skill_levels": [lv for s, lv in zip(skills, levels) if s > 0],
        "carrying": {i: c for i, c in zip(carried, counts) if i >= 0 and c > 0},
    }


def decode_items(item_block):
    """``{item_id: name}`` from the item table."""
    out = {}
    for k in range(ITEM_SLOTS):
        r = item_block[k * ITEM_SZ:(k + 1) * ITEM_SZ]
        if len(r) < ITEM_SZ:
            break
        name = _text(r[I_NAME:I_NAME + 20])
        if name:
            out[struct.unpack_from("<h", r, I_ID)[0]] = name
    return out


def decode_item_table(item_block):
    """The item table as the browser wants it: name, kind, and description."""
    out = {}
    for k in range(ITEM_SLOTS):
        r = item_block[k * ITEM_SZ:(k + 1) * ITEM_SZ]
        if len(r) < ITEM_SZ:
            break
        name = _text(r[I_NAME:I_NAME + 20])
        if not name:
            continue
        kind = struct.unpack_from("<h", r, I_TYPE)[0]
        out[struct.unpack_from("<h", r, I_ID)[0]] = {
            "name": name,
            "kind": ITEM_KINDS[kind] if 0 <= kind < len(ITEM_KINDS) else "",
            "desc": _text(r[I_DESC:I_DESC + 30]),
        }
    return out


def _names(block, slots, size, at, length):
    """Slot index to name, for the fixed-size tables that carry one."""
    out = {}
    for k in range(slots):
        r = block[k * size:(k + 1) * size]
        if len(r) < size:
            break
        name = _text(r[at:at + length])
        if name:
            out[k] = name
    return out


def decode_skills(skill_block):
    """``{skill_id: name}``: skills are addressed by their slot."""
    return _names(skill_block, SKILL_SLOTS, SKILL_SZ, K_NAME, 10)


def decode_submaps(submap_block):
    """``{submap_id: name}``: the places, addressed by their slot."""
    return _names(submap_block, SUBMAP_SLOTS, SUBMAP_SZ, M_NAME, 10)


def skill_rank(level):
    """One to ten, the way the game's own status screen shows it."""
    return min(SKILL_RANK_MAX, max(0, level // SKILL_LEVEL_STEP) + 1)


def books_held(bag, team_records=()):
    """Which of the fourteen are held, in the bag or carried by the party."""
    held = {i for i in bag if i in BOOK_IDS}
    for rec in team_records:
        held |= {i for i in rec.get("carrying", {}) if i in BOOK_IDS}
    return sorted(held)


# Where the character array sits in a machine image. Anchored on a name that
# occurs once and confirmed by two neighbours at the right stride: a first hit
# is not enough, because these names appear more than once and the serialised
# layout moves between runs.
CHAR_ANCHOR = ("程靈素", 2)
CHAR_CONFIRM = (("胡斐", 1), ("苗人鳳", 3))


def locate_characters(mem):
    """Offset of the 320 character records in a machine image, or None."""
    pattern = CHAR_ANCHOR[0].encode("big5")
    at = mem.find(pattern)
    while at != -1:
        base = at - C_NAME - CHAR_ANCHOR[1] * CHAR_SZ
        if base >= 0 and all(
                mem[base + cid * CHAR_SZ + C_NAME:
                    base + cid * CHAR_SZ + C_NAME + 10].split(b"\0")[0]
                == name.encode("big5") for name, cid in CHAR_CONFIRM):
            return base
        at = mem.find(pattern, at + 1)
    return None


def _plausible_base(mem, at, chars):
    """Does a 836-byte window at `at` read as the game's own BaseData?

    The block is found by what it contains rather than by its distance from
    anything else. A running machine holds more than one copy of the bag, and
    only one of them carries the party and the world square in front of it, so
    the party, the square and the bag all have to agree before a window is
    accepted.
    """
    if at < 0 or at + BASE_BYTES > len(mem):
        return None
    block = mem[at:at + BASE_BYTES]
    on_ship, submap, main_x, main_y = struct.unpack_from("<4h", block, 0)
    if on_ship not in (0, 1) or not 0 <= main_x < 512 or not 0 <= main_y < 512:
        return None
    if not -1 <= submap < 512:
        return None
    ids = struct.unpack_from(f"<{TEAM_SLOTS}h", block, TEAM_AT)
    seen, empty = [], False
    for cid in ids:
        if cid == -1:
            empty = True
            continue
        if empty or not 0 <= cid < CHAR_SLOTS:      # occupied slots pack first
            return None
        seen.append(cid)
    if not seen:
        return None
    for cid in seen:                                 # each must be a real record
        rec = decode_character(chars, cid)
        if rec is None or not rec["name"] or not 0 < rec["level"] <= 99:
            return None
    if decode_bag(block) is None:
        return None
    return block


def locate_base(mem, chars, hint=None):
    """Offset of the BaseData block in a machine image, or None.

    `hint` is the offset this session last found it at. The layout is stable
    while a machine runs, so the hint turns a scan of a three megabyte image
    into one comparison, and the scan below only runs when a machine is new or
    has moved its state.
    """
    if hint is not None and _plausible_base(mem, hint, chars) is not None:
        return hint
    # These are arrays of int16, so only even offsets can start one. Reading
    # through one cast view and rejecting on the header keeps the scan to a
    # few cheap comparisons per candidate; the expensive bag walk runs only on
    # what survives.
    words = memoryview(mem)[:len(mem) // 2 * 2].cast("h")
    limit = len(words) - BASE_BYTES // 2
    team0 = TEAM_AT // 2
    for w in range(limit):
        if words[w] not in (0, 1):                       # onShip
            continue
        if not 0 <= words[w + 2] < 512:                  # mainX
            continue
        if not 0 <= words[w + 3] < 512:                  # mainY
            continue
        lead = words[w + team0]
        if not 0 <= lead < CHAR_SLOTS:                   # the party is never empty
            continue
        if _plausible_base(mem, w * 2, chars) is not None:
            return w * 2
    return None


def summarise(base_block, chars):
    """The in-game semantics of one machine image: who, where, and what.

    Returns None when the block does not decode as a bag, which is the signal
    that the region was matched by accident.
    """
    bag = decode_bag(base_block)
    if bag is None:
        return None
    team = decode_team(base_block)
    records = [r for r in (decode_character(chars, cid) for cid in team) if r]
    lead = records[0] if records else None
    held = books_held(bag, records)
    return {
        "position": decode_position(base_block),
        "team_size": len(records),
        "team": [{"id": r["id"], "name": r["name"], "level": r["level"],
                  "exp": r["exp"], "hp": r["hp"], "maxhp": r["maxhp"],
                  "skills": r["skills"]} for r in records],
        "team_level": sum(r["level"] for r in records),
        "level": lead["level"] if lead else None,
        "exp": lead["exp"] if lead else None,
        "hp": lead["hp"] if lead else None,
        "maxhp": lead["maxhp"] if lead else None,
        "skills": lead["skills"] if lead else None,
        "reputation": lead["reputation"] if lead else None,
        "potential": lead["potential"] if lead else None,
        "items": sum(bag.values()),
        "items_distinct": len(bag),
        "bag": bag,
        "books": len(held),
        "book_ids": held,
    }


def detail(sections):
    """Everything a person would want to read out of one save.

    The compact numbers above are what a run is scored on; this is what the
    save-slot browser shows: who is in the party and what each of them has
    learned and carries, the whole shared bag with the game's own names and
    descriptions, where the party stands, and which of the fourteen are in.
    """
    base, chars = sections[SEC_BASE], sections[SEC_CHARS]
    bag = decode_bag(base)
    if bag is None:
        return None
    items = decode_item_table(sections[SEC_ITEMS])
    skills = decode_skills(sections[SEC_SKILLS])
    places = decode_submaps(sections[SEC_SUBMAPS])
    where = decode_position(base)
    # subMap is the scene's id plus one, so zero is the world map itself.
    where["place"] = "" if where["on_world_map"] else places.get(where["submap"] - 1, "")

    def named(item_id, count):
        row = items.get(item_id, {})
        return {"id": item_id, "count": count, "name": row.get("name", f"#{item_id}"),
                "kind": row.get("kind", ""), "desc": row.get("desc", ""),
                "book": item_id in BOOK_IDS}

    team = []
    for cid in decode_team(base):
        rec = decode_character(chars, cid)
        if rec is None:
            continue
        r = chars[cid * CHAR_SZ:(cid + 1) * CHAR_SZ]
        ids = struct.unpack_from(f"<{LEARN_SKILLS}h", r, C_SKILL_ID)
        levels = struct.unpack_from(f"<{LEARN_SKILLS}h", r, C_SKILL_LEVEL)
        rec["learned"] = [{"name": skills.get(sid, f"#{sid}"),
                           "rank": skill_rank(lv)}
                          for sid, lv in zip(ids, levels) if sid > 0]
        rec["items"] = [named(i, c) for i, c in sorted(rec.pop("carrying").items())]
        rec.pop("skill_levels", None)
        team.append(rec)

    return {
        "position": where,
        "team": team,
        "bag": [named(i, c) for i, c in sorted(bag.items())],
        "books": [{"id": i, "name": items.get(i, {}).get("name", f"#{i}"),
                   "held": i in books_held(bag, team)} for i in BOOK_IDS],
    }


# --------------------------------------------------------------- entry points
GRP_SECTIONS = 6
SEC_BASE, SEC_CHARS, SEC_ITEMS, SEC_SUBMAPS, SEC_SKILLS = 0, 1, 2, 3, 4


def split_archive(grp, idx):
    """Sections of a RANGER/R<n> archive, or None when the pair disagrees.

    The index is a list of little-endian end offsets, one per section.
    """
    if len(idx) < GRP_SECTIONS * 4:
        return None
    ends = struct.unpack_from(f"<{GRP_SECTIONS}I", idx, 0)
    out, start = [], 0
    for end in ends:
        if end < start or end > len(grp):
            return None
        out.append(grp[start:end])
        start = end
    if len(out[SEC_BASE]) != BASE_BYTES or len(out[SEC_CHARS]) != CHAR_BYTES:
        return None
    return out


def from_archive(grp, idx):
    """Everything the game itself persists: party, world square, bag, levels."""
    sections = split_archive(grp, idx)
    if sections is None:
        return None
    summary = summarise(sections[SEC_BASE], sections[SEC_CHARS])
    if summary is None:
        return None
    summary["source"] = "archive"
    summary["item_names"] = decode_items(sections[SEC_ITEMS])
    summary["detail"] = detail(sections)
    return summary


def from_memory(mem, char_base):
    """What a run has done, from the working copy in a serialised machine.

    `char_base` is where the character records start. The bag sits in the
    800 bytes in front of them. The party roster and the world square are
    deliberately absent: the only copy of those in memory is the one the game
    loaded, which does not follow the player.
    """
    if char_base is None or char_base < BAG_SLOTS * 4:
        return None
    bag_at = char_base - BAG_SLOTS * 4
    block = b"\0" * BAG_AT + mem[bag_at:char_base]
    if len(block) != BASE_BYTES:
        return None
    bag = decode_bag(block)
    if bag is None:
        return None
    chars = mem[char_base:char_base + CHAR_BYTES]
    lead = decode_character(chars, 0)
    if lead is None:
        return None
    held = books_held(bag, [lead])
    return {
        "source": "memory",
        "level": lead["level"], "exp": lead["exp"],
        "hp": lead["hp"], "maxhp": lead["maxhp"],
        "skills": lead["skills"],
        "reputation": lead["reputation"], "potential": lead["potential"],
        "items": sum(bag.values()), "items_distinct": len(bag),
        "bag": bag, "books": len(held), "book_ids": held,
    }
