import os
from pathlib import Path
import tempfile
import unittest

from lobby import lobby_page
from multiuser import UserStore


class LobbyTests(unittest.TestCase):
    def test_save_order_escaping_and_no_recording_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'template';game.mkdir();(game/'PLAY.BAT').touch()
            store=UserStore(root/'users',game)
            first=store.create('Older');second=store.create('<script>" & new')
            for user,stamp in [(first,1000),(second,2000)]:
                saves=store.paths(user['id'])[2]
                (saves/'live.state').touch();os.utime(saves/'live.state',(stamp,stamp))
                # The lobby must not open the recording or start a worker.
                (saves/'recording.jsonl').symlink_to(root/'unreadable-recording')
            page=lobby_page(store,{second['id']})
            self.assertLess(page.index('data-name="&lt;script&gt;'),page.index('data-name="Older"'))
            self.assertNotIn('<script>" & new',page)
            self.assertIn('data-saved="2000.0"',page)
            self.assertEqual(page.count('data-session-tools='),2)
            self.assertEqual(page.count('class="state is-active"'),1)

    def test_missing_save_and_external_state_symlink_are_not_presented_as_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'template';game.mkdir();(game/'PLAY.BAT').touch()
            store=UserStore(root/'users',game);user=store.create('New game')
            (root/'outside.state').touch()
            (store.paths(user['id'])[2]/'live.state').symlink_to(root/'outside.state')
            page=lobby_page(store)
            self.assertIn('尚未保存',page)
            self.assertIn('data-saved="0"',page)


if __name__=='__main__':unittest.main()
