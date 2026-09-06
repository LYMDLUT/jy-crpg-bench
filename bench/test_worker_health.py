import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import broker


class WorkerFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_stopped_worker_is_reaped_without_touching_good_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            bad=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
            good=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
            try:
                sessions={}
                for sid,proc in [('bad',bad),('good',good)]:
                    work=root/sid
                    sessions[sid]=dict(id=sid,agent='test',proc=proc,work=work,started_clock=broker.clock()-1)
                    broker.write_json(work/'health/heartbeat.json',dict(pid=proc.pid,at=broker.clock()-(20 if sid=='bad' else 0),phase='running'))
                os.kill(bad.pid,signal.SIGSTOP)
                with mock.patch.object(broker,'sessions',sessions),mock.patch.object(broker,'RESULT_DIR',root/'results'):
                    await broker.check_workers()
                    result=broker.result_of('bad')
                self.assertIsNotNone(bad.poll())
                self.assertIsNone(good.poll())
                self.assertFalse(result['valid'])
                self.assertEqual(result['reason'],'worker_unresponsive')
                self.assertFalse((root/'results/good.json').exists())
            finally:
                for proc in (bad,good):
                    if proc.poll() is None:proc.kill()
                    proc.wait()

    async def test_missing_result_is_not_reported_as_success(self):
        result=broker.ended_payload({'id':'missing','agent':'test'},None)
        self.assertFalse(result['ok'])
        self.assertFalse(result['valid'])

    async def test_stall_at_time_limit_cannot_write_a_normal_result(self):
        import warden
        old=dict(warden.run)
        health=mock.Mock()
        async def stalled(_frames):
            raise RuntimeError('frame clock stalled')
        try:
            warden.run.update(playable=__import__('time').time()-warden.BUDGET-1,done=None,credit=0)
            with mock.patch.object(warden,'write_result') as write:
                await warden.warden({'events':[]},health,asyncio.Lock(),stalled)
                write.assert_not_called()
                health.fail.assert_called_once_with('core_stalled')
        finally:
            warden.run.clear();warden.run.update(old)
