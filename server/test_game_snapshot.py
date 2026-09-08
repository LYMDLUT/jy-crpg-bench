"""The gate that decides whether the game will save.

The game only offers 存檔 from the world map, and it says so by how tall its
menu is. These numbers were measured on the running game: the panel's left
border is a white column at x 21 starting at y 23, 122 pixels long for the
six-row world-map menu and 82 for the four-row one a scene offers.
"""
import importlib.util
import pathlib
import sys
import unittest

SERVER_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
SPEC = importlib.util.spec_from_file_location("qunxia_menu_server", SERVER_DIR / "server.py")
game_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(game_server)

W, H = 320, 200
MEASURED = {6: 122, 5: 102, 4: 82}      # rows -> border length in pixels


def frame(border=None, extra=()):
    """An RGB frame with the menu's left border, plus any stray white."""
    px = bytearray(W * H * 3)
    for y in range(H):
        for x in range(W):
            at = (y * W + x) * 3
            px[at:at + 3] = b"\x30\x60\x30"          # grass, not white
    def white(x, y):
        at = (y * W + x) * 3
        px[at:at + 3] = b"\xff\xff\xff"
    if border is not None:
        top, length = border
        for y in range(top, top + length):
            white(game_server.MENU_X, y)
    for x, y0, y1 in extra:
        for y in range(y0, y1):
            white(x, y)
    return bytes(px)


class FakeCore:
    def __init__(self, data):
        self.data = data

    def fb_snapshot(self, buf, cap, scale, w, h):
        w._obj.value, h._obj.value = W, H
        game_server.SNAP[0:len(self.data)] = self.data
        return len(self.data)


class MenuRowTests(unittest.TestCase):
    def rows(self, data):
        original = game_server.LIB
        game_server.LIB = FakeCore(data)
        try:
            return game_server.menu_rows()
        finally:
            game_server.LIB = original

    def test_the_measured_panels_read_back_as_themselves(self):
        for rows, length in MEASURED.items():
            self.assertEqual(self.rows(frame(border=(23, length))), rows)

    def test_no_menu_is_no_rows(self):
        self.assertEqual(self.rows(frame()), 0)

    def test_clouds_do_not_grow_the_panel(self):
        # This is the failure it was written for: the world map's drifting
        # clouds are white, and a bounding box over the panel's whole width
        # counted them, reading the six-row menu as seven and refusing to save
        # somewhere the game would have saved.
        clouds = ((21, 5, 15), (21, 150, 160), (40, 30, 45))
        self.assertEqual(self.rows(frame(border=(23, MEASURED[6]), extra=clouds)), 6)

    def test_a_white_column_somewhere_else_is_not_the_menu(self):
        self.assertEqual(self.rows(frame(extra=((21, 90, 190),))), 0)


if __name__ == "__main__":
    unittest.main()
