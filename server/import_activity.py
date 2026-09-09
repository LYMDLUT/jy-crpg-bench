"""Import legacy recording action markers while the target server is stopped."""
import argparse
from contextlib import nullcontext
from collections import deque, defaultdict
import json
import math
from pathlib import Path

from activity import ActivityStore, MAX_ENTRIES
from activity_thumbnails import restore_thumbnails


LEGACY_TIME_TOLERANCE = 0.001


def read_actions(path):
    """Scan a fixed prefix and retain offsets for the latest action markers."""
    rows = deque(maxlen=MAX_ENTRIES)
    count = 0
    with (nullcontext(path) if hasattr(path, 'read') else Path(path).open('rb')) as stream:
        end = stream.seek(0, 2)
        stream.seek(0)
        header_line = stream.readline(65537)
        if len(header_line) > 65536 or not header_line.endswith(b'\n'):
            raise ValueError('invalid recording header')
        header = json.loads(header_line)
        started = header.get('started')
        if type(started) not in (int, float) or not math.isfinite(started):
            raise ValueError('recording has no valid start time')
        keyframe = None
        while stream.tell() < end:
            offset = stream.tell()
            line = stream.readline(min(end - stream.tell(), 4 * 1024 * 1024))
            if not line.endswith(b'\n'):
                if stream.tell() == end:
                    break  # an uncommitted final append
                raise ValueError('recording line exceeds size limit')
            if b'"d"' in line and b'"k"' in line:
                event = json.loads(line)
                if event.get('d') and event.get('k'):
                    keyframe = offset
            if b'"act"' not in line:
                continue
            event = json.loads(line)
            act = event.get('act')
            if isinstance(act, str) and act:
                verb, target = act, event.get('on', '')
            elif type(act) in (int, float) and isinstance(event.get('label'), str):
                # Numbered benchmark markers carry the verb in their label,
                # "KEY down", the way history_index.normalize reads them.
                verb, _, target = event['label'].partition(' ')
                verb = verb or 'KEY'
            else:
                continue
            timestamp = event.get('t')
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError('invalid action timestamp')
            count += 1
            rows.append(dict(id=count, at=started + timestamp,
                             src=event.get('who', ''), verb=verb,
                             target=target,
                             detail='from recording; result unknown', ok=None,
                             recording_offset=offset, recording_started=started,
                             _keyframe_offset=keyframe))
    return list(rows), count


def import_recording(recording, history):
    if Path(recording).resolve() == Path(history).resolve():
        raise ValueError('recording and history must be different files')
    with Path(recording).open('rb') as source:
        rows, count = read_actions(source)
        store = ActivityStore(history)
        existing = store.load()
        # Use the action's byte offset, not its rounded timestamp, as identity.
        # Upgrade earlier imports without this identity by matching each old row once.
        by_origin = {(r['recording_started'], r['recording_offset']): i for i, r in enumerate(rows)}
        by_content = defaultdict(list)
        for i, row in enumerate(rows):
            by_content[(row['src'], row['verb'], row['target'])].append(i)
        used = set()
        for old in existing:
            offset = old.get('recording_offset')
            started = old.get('recording_started')
            index = None
            if type(offset) is int and offset >= 0:
                index = by_origin.get((started, offset))
            else:
                # Early imports had no byte identity and the recording stores
                # timestamps rounded to milliseconds. Consume candidates in
                # recording order so equal-time actions cannot be reused or
                # paired with a later duplicate.
                candidates = by_content[(old['src'], old['verb'], old['target'])]
                for candidate in candidates:
                    if candidate in used:
                        continue
                    if abs(rows[candidate]['at'] - old['at']) <= LEGACY_TIME_TOLERANCE:
                        index = candidate
                        break
            if index is None:
                rows.append(old)
            else:
                rows[index].update(old)
                used.add(index)
        retained = sorted(rows, key=lambda r: r['at'])[-MAX_ENTRIES:]
        thumbnails = restore_thumbnails(source, retained)
        for seq, row in enumerate(retained, 1):
            row['id'] = seq
        store.save(retained)
    return {'recording_actions': count, 'existing_entries': len(existing),
            'retained_entries': len(retained), 'restored_thumbnails': thumbnails}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', required=True)
    parser.add_argument('--history', required=True)
    args = parser.parse_args()
    print(json.dumps(import_recording(args.recording, args.history)))
