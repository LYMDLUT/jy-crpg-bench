"""The save decoder against the game's own shipped data.

`game/RANGER.GRP` is the new-game archive the original release ships. Every
offset this decoder uses is checked against it, so a wrong field is a failing
test and never a plausible-looking number on the board.
"""
import os
import pathlib
import struct
import unittest

import save_state as S

GAME = pathlib.Path(__file__).resolve().parent.parent / "game"
RANGER = GAME / "RANGER.GRP"
RANGER_IDX = GAME / "RANGER.IDX"


def shipped():
    if not RANGER.is_file() or not RANGER_IDX.is_file():
        raise unittest.SkipTest("the game is not present; see README")
    return RANGER.read_bytes(), RANGER_IDX.read_bytes()


class LayoutTests(unittest.TestCase):
    def test_record_sizes_are_the_shipped_ones(self):
        grp, idx = shipped()
        ends = struct.unpack_from("<6I", idx, 0)
        self.assertEqual(ends[0], S.BASE_BYTES)                       # 836
        self.assertEqual(ends[1] - ends[0], S.CHAR_BYTES)             # 320 x 182
        self.assertEqual(ends[2] - ends[1], S.ITEM_SLOTS * S.ITEM_SZ)  # 200 x 190
        self.assertEqual(ends[-1], len(grp))

    def test_carried_item_slots_close_the_character_record(self):
        # item[4] then itemCount[4] are the last two fields, so the record ends
        # exactly there. This is the pair an earlier reader dismissed as AI
        # scratch space.
        self.assertEqual(S.C_ITEM_COUNT + S.CARRY_ITEMS * 2, S.CHAR_SZ)


class BookTests(unittest.TestCase):
    def test_the_fourteen_are_the_novels_the_game_ships(self):
        grp, idx = shipped()
        names = S.decode_items(S.split_archive(grp, idx)[S.SEC_ITEMS])
        self.assertEqual(tuple(names[i] for i in S.BOOK_IDS), S.BOOK_NAMES)
        self.assertEqual(len(S.BOOK_IDS), 14)

    def test_the_compass_is_the_item_the_game_ships(self):
        grp, idx = shipped()
        names = S.decode_items(S.split_archive(grp, idx)[S.SEC_ITEMS])
        self.assertEqual(names[S.COMPASS_ID], S.COMPASS_NAME)

    def test_books_are_counted_from_the_bag_and_from_the_party(self):
        self.assertEqual(S.books_held({144: 1, 3: 9}), [144])
        self.assertEqual(
            S.books_held({}, [{"carrying": {157: 1}}]), [157])
        # one book in two places is still one book
        self.assertEqual(
            S.books_held({144: 1}, [{"carrying": {144: 1}}]), [144])
        self.assertEqual(S.books_held({3: 1}, [{"carrying": {9: 1}}]), [])


class TableTests(unittest.TestCase):
    """The tables the save-slot browser reads names out of.

    Record sizes are derived from the shipped sections, so a wrong one is a
    non-integer count here rather than a plausible-looking name later.
    """

    def sections(self):
        grp, idx = shipped()
        sections = S.split_archive(grp, idx)
        self.assertIsNotNone(sections)
        return sections

    def test_the_sections_hold_whole_records(self):
        sections = self.sections()
        self.assertEqual(len(sections[S.SEC_SUBMAPS]), S.SUBMAP_SLOTS * S.SUBMAP_SZ)
        self.assertEqual(len(sections[S.SEC_SKILLS]), S.SKILL_SLOTS * S.SKILL_SZ)

    def test_the_names_are_the_game_own(self):
        sections = self.sections()
        skills = S.decode_skills(sections[S.SEC_SKILLS])
        places = S.decode_submaps(sections[S.SEC_SUBMAPS])
        items = S.decode_item_table(sections[S.SEC_ITEMS])
        self.assertEqual(skills[0], "普通攻擊")
        self.assertEqual(skills[1], "野球拳")
        self.assertEqual(places[0], "胡斐居")      # the room a new game starts in
        self.assertEqual(len(skills), S.SKILL_SLOTS)
        self.assertEqual(len(places), S.SUBMAP_SLOTS)
        self.assertEqual(items[1]["name"], "精氣丸")
        self.assertEqual(items[1]["kind"], "medicine")
        self.assertEqual(items[144]["name"], S.BOOK_NAMES[0])
        self.assertEqual({v["kind"] for v in items.values()}, set(S.ITEM_KINDS))

    def test_a_skill_rank_is_one_to_ten(self):
        self.assertEqual(S.skill_rank(0), 1)
        self.assertEqual(S.skill_rank(99), 1)
        self.assertEqual(S.skill_rank(100), 2)
        self.assertEqual(S.skill_rank(900), 10)
        self.assertEqual(S.skill_rank(5000), 10)


class DetailTests(unittest.TestCase):
    def test_a_new_game_reads_as_one_medicine_carrying_hero(self):
        grp, idx = shipped()
        d = S.from_archive(grp, idx)["detail"]
        self.assertTrue(d["position"]["on_world_map"])
        self.assertEqual(d["position"]["place"], "")
        self.assertEqual(len(d["team"]), 1)
        lead = d["team"][0]
        self.assertEqual([k["rank"] for k in lead["learned"]], [1])
        self.assertEqual({i["kind"] for i in d["bag"]}, {"medicine"})
        self.assertEqual(sum(i["count"] for i in d["bag"]), 12)
        self.assertEqual([b["name"] for b in d["books"]], list(S.BOOK_NAMES))
        self.assertFalse(any(b["held"] for b in d["books"]))

    def test_a_book_in_the_bag_lights_its_tile(self):
        grp, idx = shipped()
        sections = list(S.split_archive(grp, idx))
        base = bytearray(sections[S.SEC_BASE])
        struct.pack_into("<2h", base, S.BAG_AT, 144, 1)   # the first novel
        sections[S.SEC_BASE] = bytes(base)
        d = S.detail(sections)
        held = [b for b in d["books"] if b["held"]]
        self.assertEqual([b["name"] for b in held], [S.BOOK_NAMES[0]])
        row = next(i for i in d["bag"] if i["id"] == 144)
        self.assertTrue(row["book"])
        self.assertEqual(row["kind"], "story")
        self.assertEqual(row["desc"], "一本小說")


class ArchiveTests(unittest.TestCase):
    def test_a_new_game_reads_as_one_character_at_level_one(self):
        grp, idx = shipped()
        s = S.from_archive(grp, idx)
        self.assertEqual(s["team_size"], 1)
        self.assertEqual(s["team_level"], 1)
        self.assertEqual(s["level"], 1)
        self.assertEqual(s["exp"], 0)
        self.assertEqual(s["books"], 0)
        self.assertEqual(s["items_distinct"], 4)
        self.assertEqual(s["position"]["x"], 357)
        self.assertEqual(s["position"]["y"], 235)

    def test_a_torn_archive_is_refused(self):
        grp, idx = shipped()
        self.assertIsNone(S.from_archive(grp[:100], idx))
        self.assertIsNone(S.from_archive(grp, idx[:8]))


class PositionTests(unittest.TestCase):
    def test_the_shipped_slots_are_saved_on_the_world_map(self):
        # submap is the scene id plus one, so the game writes zero for the
        # world map. The three slots the release ships were saved there, which
        # is why loading one from the title lands outdoors.
        grp, idx = shipped()
        for name in ("R1", "R2", "R3"):
            path = GAME / f"{name}.GRP"
            index = GAME / f"{name}.IDX"
            if not path.is_file():
                continue
            s = S.from_archive(path.read_bytes(), index.read_bytes())
            self.assertIsNotNone(s, name)
            self.assertTrue(s["position"]["on_world_map"], name)
        # RANGER carries the same zero: the title screen decides where a new
        # game starts, so the template's square is never used as written.
        self.assertTrue(S.from_archive(grp, idx)["position"]["on_world_map"])


class MemoryTests(unittest.TestCase):
    """The working copy: the bag in front of the character records."""

    def image(self, bag, lead_level=1, lead_exp=0):
        pad = 4096
        slots = []
        for item_id, count in bag.items():
            slots += [item_id, count]
        slots += [-1, 0] * (S.BAG_SLOTS - len(bag))
        bag_bytes = struct.pack(f"<{S.BAG_SLOTS * 2}h", *slots)
        chars = bytearray(S.CHAR_BYTES)
        chars[S.C_NAME:S.C_NAME + 2] = "王".encode("big5")
        struct.pack_into("<h", chars, S.C_LEVEL, lead_level)
        struct.pack_into("<H", chars, S.C_EXP, lead_exp)
        struct.pack_into("<h", chars, S.C_HP, 50)
        struct.pack_into("<h", chars, S.C_MAXHP, 50)
        struct.pack_into("<h", chars, S.C_SKILL_ID, 1)
        return bytes(pad * b"\0" + bag_bytes + bytes(chars)), pad + len(bag_bytes)

    def test_the_working_bag_is_read_from_in_front_of_the_records(self):
        mem, base = self.image({0: 3, 2: 3})
        s = S.from_memory(mem, base)
        self.assertEqual(s["items"], 6)
        self.assertEqual(s["items_distinct"], 2)
        self.assertEqual(s["level"], 1)
        self.assertEqual(s["skills"], 1)
        self.assertEqual(s["source"], "memory")

    def test_books_in_the_working_bag_are_counted(self):
        mem, base = self.image({144: 1, 157: 1, 3: 2})
        s = S.from_memory(mem, base)
        self.assertEqual(s["books"], 2)
        self.assertEqual(s["book_ids"], [144, 157])

    def test_a_hole_in_the_bag_is_read_through_and_a_bad_id_is_refused(self):
        mem, base = self.image({0: 3})
        holed = bytearray(mem)
        struct.pack_into("<4h", holed, base - S.BAG_SLOTS * 4, -1, 0, 5, 1)
        self.assertEqual(S.from_memory(bytes(holed), base)["bag"], {5: 1})
        broken = bytearray(mem)
        struct.pack_into("<2h", broken, base - S.BAG_SLOTS * 4, 250, 1)
        self.assertIsNone(S.from_memory(bytes(broken), base))

    def test_the_live_party_and_square_are_read_beside_the_records(self):
        mem, base = self.image({0: 3})
        live = bytearray(mem) + bytes(S.LIVE_REL + 64)
        struct.pack_into("<6h", live, base + S.LIVE_REL, 0, 29, -1, -1, -1, -1)
        struct.pack_into("<i", live, base + S.LIVE_REL + 12, 256)
        struct.pack_into("<ii", live, base + S.LIVE_REL + S.LIVE_X_AT, 385, 306)
        self.assertEqual(S.read_live(bytes(live), base), {"x": 385, "y": 306, "party": [0, 29]})
        struct.pack_into("<i", live, base + S.LIVE_REL + S.LIVE_X_AT, 9000)
        self.assertIsNone(S.read_live(bytes(live), base))
        struct.pack_into("<ii", live, base + S.LIVE_REL + S.LIVE_X_AT, 385, 306)
        struct.pack_into("<h", live, base + S.LIVE_REL, 7)          # not led by the protagonist
        self.assertIsNone(S.read_live(bytes(live), base))
        self.assertIsNone(S.read_live(mem, base))                    # image too short: no reading
        self.assertIsNone(S.read_live(mem, None))

    def test_an_offset_with_no_room_for_a_bag_is_refused(self):
        mem, base = self.image({0: 3})
        self.assertIsNone(S.from_memory(mem, 4))
        self.assertIsNone(S.from_memory(mem, None))


if __name__ == "__main__":
    unittest.main()
