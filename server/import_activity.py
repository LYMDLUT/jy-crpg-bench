"""Import legacy recording action markers while the target server is stopped."""
import argparse
from collections import deque
import json
import math
from pathlib import Path

from activity import ActivityStore, MAX_ENTRIES


def read_actions(path):
    """Scan a fixed file prefix with bounded memory, without decoding frames."""
    rows = deque(maxlen=MAX_ENTRIES)
    count = 0
    with Path(path).open('rb') as stream:
        end = stream.seek(0, 2)
        stream.seek(0)
        header = json.loads(stream.readline())
        started = header.get('started')
        if type(started) not in (int, float) or not math.isfinite(started):
            raise ValueError('recording has no valid start time')
        while stream.tell() < end:
            line = stream.readline(min(end - stream.tell(), 4 * 1024 * 1024))
            if not line.endswith(b'\n'):
                if stream.tell() == end:
                    break  # an uncommitted final append
                raise ValueError('recording line exceeds size limit')
            if b'"act"' not in line:
                continue
            event = json.loads(line)
            if not event.get('act'):
                continue
            timestamp = event.get('t')
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError('invalid action timestamp')
            count += 1
            rows.append(dict(id=count, at=started + timestamp,
                             src=event.get('who', ''), verb=event['act'],
                             target=event.get('on', ''),
                             detail='from recording; result unknown', ok=None))
    return list(rows), count


def import_recording(recording, history):
    if Path(recording).resolve() == Path(history).resolve():
        raise ValueError('recording and history must be different files')
    rows, count = read_actions(recording)
    store = ActivityStore(history)
    existing = store.load()
    # Existing richer entries win if the same marker was imported previously.
    merged = {(r['at'], r['src'], r['verb'], r['target']): r for r in rows + existing}
    retained = sorted(merged.values(), key=lambda r: r['at'])[-MAX_ENTRIES:]
    for seq, row in enumerate(retained, 1):
        row['id'] = seq
    store.save(retained)
    return {'recording_actions': count, 'existing_entries': len(existing),
            'retained_entries': len(retained)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording', required=True)
    parser.add_argument('--history', required=True)
    args = parser.parse_args()
    print(json.dumps(import_recording(args.recording, args.history)))
