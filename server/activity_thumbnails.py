"""Rebuild bounded previews from frames preceding a legacy action marker."""
import base64
from contextlib import nullcontext
import io
import json
import math
import struct
import zlib

from PIL import Image

MAX_DELTA = 4 * 1024 * 1024
MAX_PIXELS = 1024 * 1024


class RecordedScreen:
    def __init__(self):
        self.image = None
        self.geometry = None

    def apply(self, encoded):
        compressed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, MAX_DELTA + 1)
        if len(raw) > MAX_DELTA or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
            raise ValueError('invalid or oversized compressed frame')
        if len(raw) < 13:
            raise ValueError('truncated frame header')
        key, width, height, tw, th, cols, rows, count = struct.unpack_from('<BHHBBHHH', raw)
        if not all((width, height, tw, th, cols, rows)) or width * height > MAX_PIXELS:
            raise ValueError('invalid or oversized frame geometry')
        if cols != (width + tw - 1) // tw or rows != (height + th - 1) // th:
            raise ValueError('invalid frame grid')
        span, offset = tw * th * 3, 13 + count * 2
        if len(raw) != offset + count * span:
            raise ValueError('invalid frame payload length')
        tiles = struct.unpack_from(f'<{count}H', raw, 13)
        if len(set(tiles)) != count or any(tile >= cols * rows for tile in tiles):
            raise ValueError('invalid frame tile indices')
        geometry = width, height, tw, th, cols, rows
        if key:
            if count != cols * rows:
                raise ValueError('incomplete keyframe')
            self.image = Image.new('RGB', (width, height))
            self.geometry = geometry
        elif self.image is None or self.geometry != geometry:
            raise ValueError('frame requires a matching keyframe')
        for index, tile in enumerate(tiles):
            begin = offset + index * span
            pixels = Image.frombytes('RGB', (tw, th), raw[begin:begin + span])
            self.image.paste(pixels, ((tile % cols) * tw, (tile // cols) * th))

    def thumbnail(self):
        if self.image is None:
            return None
        preview = self.image.copy()
        preview.thumbnail((160, 160), Image.Resampling.NEAREST)
        output = io.BytesIO()
        preview.save(output, 'WEBP', quality=72, method=0)
        return 'data:image/webp;base64,' + base64.b64encode(output.getvalue()).decode()


def restore_thumbnails(path, entries):
    restored = 0
    # Do not replace original thumbnails. Never use a frame after the marker,
    # including frames with an equal (millisecond-rounded) timestamp.
    candidates = [r for r in entries if r['verb'] == 'GET'][-40:]
    with (nullcontext(path) if hasattr(path, 'read') else open(path, 'rb')) as stream:
        for row in candidates:
            start, end = row.get('_keyframe_offset'), row.get('recording_offset')
            if row.get('thumb') or start is None or end is None:
                continue
            stream.seek(start)
            screen, last_time = RecordedScreen(), None
            try:
                while stream.tell() < end:
                    line = stream.readline(min(end - stream.tell(), MAX_DELTA))
                    if not line.endswith(b'\n'):
                        raise ValueError('truncated or oversized recording frame')
                    if b'"d"' not in line:
                        continue
                    event = json.loads(line)
                    if not event.get('d'):
                        continue
                    timestamp = event.get('t')
                    if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                        raise ValueError('invalid frame timestamp')
                    screen.apply(event['d'])
                    last_time = row['recording_started'] + timestamp
                thumb = screen.thumbnail()
                if thumb:
                    row.update(thumb=thumb, thumb_source='recording', thumb_at=last_time)
                    restored += 1
            except (ValueError, TypeError, KeyError, struct.error, zlib.error):
                # A missing/corrupt frame is not a license to fabricate a shot.
                continue
    return restored
