"""Disposable sparse disk indexes over immutable recording prefixes.

The original JSONL remains the source of truth. Only action metadata and
validated complete-frame offsets are indexed; neither frames nor the whole
event list are loaded into memory. Steps are a per-reader disk-backed table.
"""
from collections import Counter
import hashlib
import itertools
import json
import math
import os
import sqlite3
import threading

from history_frames import complete_frame
from recording import Snapshot

INDEX_LOCK = threading.Lock()
SCHEMA = 2
SETTLE = 1.0


def normalize(event):
    """Preserve old agent actions and newer numbered action labels."""
    who = event.get('who')
    if not event.get('history') and (not who or who == 'web'):
        return None
    act = event.get('act')
    if isinstance(act, str) and act:
        result = {'act': act[:32], 'on': str(event.get('on', ''))[:4096]}
        kind = 1
    elif type(act) in (int, float) and isinstance(event.get('label'), str):
        verb, _, target = event['label'][:4128].partition(' ')
        result = {'act': verb or 'KEY', 'on': target}
        kind = 1
    elif event.get('key') and event.get('down'):
        result = {'act': 'KEY', 'on': str(event['key'])[:4096]}
        kind = 2
    else:
        return None
    result['who'] = str(who or '')[:256]
    if 'detail' in event:
        result['detail'] = str(event['detail'])[:4096]
    if 'phase' in event:
        result['phase'] = str(event['phase'])[:32]
    if 'ok' in event:
        result['ok'] = event['ok'] if type(event['ok']) is bool else None
    if 'history' in event:
        result['history'] = bool(event['history'])
    return kind, result


class HistoryIndex:
    def __init__(self, pin):
        self.source = Snapshot(**pin)
        self.cancelled = threading.Event()
        self.db = None
        self.closed = False
        self.scanned = self.source.begin
        self.total = self.source.end
        self.steps = 0
        self.base = 0.0
        self.summary = {}

    def build(self):
        acquired = False
        try:
            while not self.cancelled.is_set():
                if INDEX_LOCK.acquire(timeout=.1):
                    acquired = True
                    break
            if not acquired:
                return
            self._index()
        finally:
            if acquired:
                INDEX_LOCK.release()

    def _index(self):
        source = self.source
        stat = os.fstat(source.fd)
        signature = hashlib.sha256(json.dumps(source.header, sort_keys=True).encode()).hexdigest()[:20]
        folder = source.path.parent / '.history-index'
        folder.mkdir(exist_ok=True)
        self.path = folder / f'v{SCHEMA}-{stat.st_dev}-{stat.st_ino}-{signature}.sqlite3'
        self.db = db = sqlite3.connect(self.path, timeout=30, check_same_thread=False,
                                       isolation_level=None)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA cache_size=-2048')
        db.execute('PRAGMA temp_store=FILE')
        db.execute('PRAGMA temp.cache_size=-2048')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS frames (off INTEGER PRIMARY KEY, t REAL);
            CREATE INDEX IF NOT EXISTS frame_time ON frames(t,off);
            CREATE TABLE IF NOT EXISTS marks (off INTEGER PRIMARY KEY, t REAL, kind INTEGER, data TEXT);
            CREATE INDEX IF NOT EXISTS mark_kind ON marks(kind,off);
            CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT);
            CREATE TABLE IF NOT EXISTS prefixes (end INTEGER PRIMARY KEY, events INTEGER, damaged INTEGER);
        ''')
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('SELECT data FROM state WHERE id=1').fetchone()
            state = json.loads(row[0]) if row else {}
            if state.get('end', 0) > stat.st_size:
                db.execute('DELETE FROM frames')
                db.execute('DELETE FROM marks')
                db.execute('DELETE FROM prefixes')
                state = {}
            start = state.get('end', source.begin)
            self.scanned = min(start, self.total)
            last = state.get('last', 0.0)
            events, damaged = state.get('events', 0), state.get('damaged', 0)
            checkpoint = start
            if start < self.total:
                for offset, line in source.lines(start):
                    if self.cancelled.is_set():
                        db.execute('ROLLBACK')
                        return
                    self.scanned = offset + len(line)
                    try:
                        event = json.loads(line)
                        when = float(event['t'])
                        if not isinstance(event, dict) or not math.isfinite(when) or when < 0:
                            raise ValueError('invalid recording event')
                    except (ValueError, TypeError, KeyError):
                        damaged += 1
                        if self.scanned - checkpoint >= 1 << 20:
                            db.execute('INSERT OR REPLACE INTO prefixes VALUES (?,?,?)',
                                       (self.scanned, events, damaged))
                            checkpoint = self.scanned
                        continue
                    events += 1
                    last = max(last, when)
                    if complete_frame(event):
                        db.execute('INSERT OR REPLACE INTO frames VALUES (?,?)', (offset, last))
                    mark = normalize(event)
                    if mark:
                        kind, data = mark
                        db.execute('INSERT OR REPLACE INTO marks VALUES (?,?,?,?)',
                                   (offset, last, kind, json.dumps(data, ensure_ascii=False)))
                    if self.scanned - checkpoint >= 1 << 20:
                        db.execute('INSERT OR REPLACE INTO prefixes VALUES (?,?,?)',
                                   (self.scanned, events, damaged))
                        checkpoint = self.scanned
                state = dict(end=self.scanned, last=last, events=events, damaged=damaged)
                db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (json.dumps(state),))
                db.execute('INSERT OR REPLACE INTO prefixes VALUES (?,?,?)', (self.scanned, events, damaged))
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK')
            raise
        if self.cancelled.is_set():
            return
        self._steps()
        # Concurrent readers can build a longer prefix before this one starts.
        # Recover exact counters from the nearest bounded checkpoint.
        if state.get('end') != self.total:
            row = db.execute('SELECT end,events,damaged FROM prefixes WHERE end<=? ORDER BY end DESC LIMIT 1',
                             (self.total,)).fetchone()
            start, events, damaged = row or (source.begin, 0, 0)
            for _, line in source.lines(start):
                try:
                    event = json.loads(line)
                    when = float(event['t'])
                    if not isinstance(event, dict) or not math.isfinite(when) or when < 0:
                        raise ValueError('invalid recording event')
                    events += 1
                except (ValueError, TypeError, KeyError):
                    damaged += 1
        self.summary.update(events=events, damaged_lines=damaged)

    def _steps(self):
        db, end = self.db, self.source.end
        origin = db.execute('SELECT off,t FROM frames WHERE off<? ORDER BY off LIMIT 1', (end,)).fetchone()
        db.execute('CREATE TEMP TABLE steps (seq INTEGER PRIMARY KEY, data TEXT)')
        if origin is None:
            self.summary = {'actors': [], 'verbs': {}}
            return
        first_offset, self.base = origin
        first_act = db.execute(
            'SELECT t FROM marks WHERE kind=1 AND off>? AND off<? ORDER BY off LIMIT 1',
            (first_offset, end)).fetchone()
        boundary = first_act[0] if first_act else math.inf
        rows = db.execute('SELECT off,t,data FROM marks WHERE off>? AND off<? '
                          'AND (kind=1 OR (kind=2 AND t<?)) ORDER BY off',
                          (first_offset, end, boundary))
        marks = (dict(json.loads(data), t=max(0.0, when-self.base), _when=when, _offset=offset)
                 for offset, when, data in rows)
        current = next(marks, None)
        verbs, actors, shown, batch = Counter(), [], -1.0, []
        if current is not None:
            for following in itertools.chain(marks, (None,)):
                if self.cancelled.is_set():
                    return
                immediate = (current['act'] == 'GET' or current.get('phase') == 'after'
                             or current.get('ok') is False)
                absolute_cutoff = current['_when'] if immediate else min(current['_when'] + SETTLE,
                                  following['_when'] if following is not None else math.inf)
                cutoff = absolute_cutoff - self.base
                # Rich history deliberately retains repeated/failed actions.
                if not self.steps or cutoff > shown or current.get('history'):
                    step = dict(current, cutoff=round(cutoff, 3), _cutoff=absolute_cutoff)
                    step['t'] = round(step['t'], 3)
                    if immediate:
                        step['_end'] = current['_offset']
                    elif following is not None and absolute_cutoff == following['_when']:
                        step['_end'] = following['_offset']
                    self.steps += 1
                    batch.append((self.steps, json.dumps(step, ensure_ascii=False)))
                    verbs[step['act']] += 1
                    if step['who'] not in actors and len(actors) < 8:
                        actors.append(step['who'])
                    shown = cutoff
                    if len(batch) >= 256:
                        db.executemany('INSERT INTO steps VALUES (?,?)', batch)
                        batch.clear()
                current = following
        if batch:
            db.executemany('INSERT INTO steps VALUES (?,?)', batch)
        self.summary = {'actors': actors, 'verbs': dict(verbs)}

    def step(self, index):
        if not 0 <= index < self.steps:
            raise ValueError('invalid step')
        return json.loads(self.db.execute('SELECT data FROM steps WHERE seq=?', (index + 1,)).fetchone()[0])

    def page(self, start, count):
        rows = self.db.execute('SELECT data FROM steps WHERE seq>? AND seq<=? ORDER BY seq',
                               (start, min(start + count, self.steps))).fetchall()
        return [{key: value for key, value in json.loads(data).items() if not key.startswith('_')}
                for (data,) in rows]

    def close(self):
        if not self.closed:
            self.closed = True
            if self.db is not None:
                self.db.close()
            self.source.close()
