"""Reconstruct one action's recorded picture from a bounded disk window."""
import base64
import io
import json
import math
import struct
import zlib

from activity_thumbnails import MAX_DELTA, MAX_PIXELS, RecordedScreen


def complete_frame(event):
    """Check the payload, since old JSON k markers were only timer hints."""
    encoded = event.get('d')
    if not isinstance(encoded, str):
        return False
    try:
        prefix = base64.b64decode(encoded[:4096], validate=True)
        header = zlib.decompressobj().decompress(prefix, 13)
        if len(header) != 13:
            return False
        flag, width, height, tw, th, cols, rows, count = struct.unpack('<BHHBBHHH', header)
        if not (flag and width and height and tw and th and cols and rows
                and width * height <= MAX_PIXELS
                and cols == (width + tw - 1) // tw
                and rows == (height + th - 1) // th
                and count == cols * rows
                and 13 + count * (2 + tw * th * 3) <= MAX_DELTA):
            return False
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(encoded, validate=True), MAX_DELTA + 1)
        if (len(raw) != 13 + count * (2 + tw * th * 3) or not decoder.eof
                or decoder.unconsumed_tail or decoder.unused_data):
            return False
        tiles = struct.unpack_from(f'<{count}H', raw, 13)
        return len(set(tiles)) == count and all(tile < count for tile in tiles)
    except (ValueError, TypeError, struct.error, zlib.error):
        return False


def render_frame(index, step):
    """GET ends before its marker; old KEY waits for its recorded result."""
    cutoff = step.get('_cutoff', step['cutoff'] + index.base)
    boundary = step.get('_end', index.source.end)
    row = index.db.execute(
        'SELECT off,t FROM frames WHERE t<=? AND off<? ORDER BY t DESC,off DESC LIMIT 1',
        (cutoff, boundary)).fetchone()
    if row is None:
        raise ValueError('no complete recorded frame before this action')
    screen = RecordedScreen()
    last_time = None
    monotonic_time = row[1]
    for offset, line in index.source.lines(row[0]):
        if offset >= boundary:
            break
        try:
            event = json.loads(line)
            when = float(event['t'])
            if not isinstance(event, dict) or not math.isfinite(when) or when < 0:
                raise ValueError('invalid recorded timestamp')
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError('damaged recording in the requested frame window') from error
        when = monotonic_time = max(monotonic_time, when)
        if when > cutoff:
            break
        if event.get('d'):
            try:
                screen.apply(event['d'])
            except (ValueError, TypeError, struct.error, zlib.error) as error:
                raise ValueError('damaged frame in the requested recording window') from error
            last_time = when
    if screen.image is None:
        raise ValueError('no recorded picture for this action')
    output = io.BytesIO()
    screen.image.save(output, 'PNG')
    return output.getvalue(), last_time


def iter_frames(index, steps=None):
    """Yield action pictures without repeatedly decoding the same deltas.

    Each result is ``(step, image, last_time, frame_end)``. The original step
    metadata, including its private precision and offset bounds, is retained.
    Images belong to this iterator and can change on its next advance; callers
    retaining an image must copy it. ``frame_end`` is the byte immediately after
    the last applied frame, so unchanged pictures have the same disk identity.
    """
    if steps is None:
        rows = index.db.execute('SELECT data FROM steps ORDER BY seq')
        steps = (json.loads(data) for (data,) in rows)
    screen = None
    pending = lines = None
    pending_event = pending_time = None
    position = last_cutoff = last_boundary = None
    last_time = frame_end = monotonic_time = None
    for step in steps:
        if index.cancelled.is_set():
            return
        cutoff = step.get('_cutoff', step['cutoff'] + index.base)
        boundary = step.get('_end', index.source.end)
        anchor = index.db.execute(
            'SELECT off,t FROM frames WHERE t<=? AND off<? ORDER BY t DESC,off DESC LIMIT 1',
            (cutoff, boundary)).fetchone()
        if anchor is None:
            raise ValueError('no complete recorded frame before this action')
        # A later complete frame replaces every pixel. Jump directly to it
        # instead of decoding idle footage between the requested actions.
        # Rich immediate markers can move either bound backwards; those need
        # the same fresh reconstruction as a standalone frame request.
        if (screen is None or cutoff < last_cutoff or boundary < last_boundary
                or anchor[0] >= position):
            screen = RecordedScreen()
            lines = index.source.lines(anchor[0])
            pending = None
            pending_event = pending_time = None
            position, monotonic_time = anchor
            last_time = frame_end = None
        while True:
            if index.cancelled.is_set():
                return
            if pending is None:
                pending = next(lines, None)
            if pending is None:
                break
            offset, line = pending
            if offset >= boundary:
                break
            if pending_event is None:
                try:
                    event = json.loads(line)
                    when = float(event['t'])
                    if not isinstance(event, dict) or not math.isfinite(when) or when < 0:
                        raise ValueError('invalid recorded timestamp')
                except (ValueError, TypeError, KeyError) as error:
                    raise ValueError('damaged recording in the requested frame window') from error
                pending_event, pending_time = event, max(monotonic_time, when)
            event, when = pending_event, pending_time
            if when > cutoff:
                break
            if event.get('d'):
                try:
                    screen.apply(event['d'])
                except (ValueError, TypeError, struct.error, zlib.error) as error:
                    raise ValueError('damaged frame in the requested recording window') from error
                last_time = when
                frame_end = offset + len(line)
            position = offset + len(line)
            monotonic_time = when
            pending = None
            pending_event = pending_time = None
        if screen.image is None:
            raise ValueError('no recorded picture for this action')
        last_cutoff, last_boundary = cutoff, boundary
        yield step, screen.image, last_time, frame_end
