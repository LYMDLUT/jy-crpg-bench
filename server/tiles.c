/* Tile-delta encoder for streaming the VGA framebuffer to a browser.
 *
 * The game is a 2D RPG: most frames change only where the dialogue box or a
 * sprite is. So instead of shipping a whole picture we diff against the last
 * frame the client acknowledged and ship only the 16x10 tiles that moved. The
 * result is deflated by the caller before it goes on the wire. */
#include "CoreHost.h"
#include <stdlib.h>
#include <string.h>

#define TILE_W 16
#define TILE_H 10

static uint8_t *g_prev;      /* last encoded frame, RGB */
static int g_prev_w, g_prev_h;

static void put_u16(uint8_t *p, unsigned v) { p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; }

/* Returns bytes written, or -1 if the buffer is too small / no frame yet. */
int fb_encode_delta(uint8_t *out, int out_cap, int force_key) {
    core_lock();
    const int w = core_width(), h = core_height(), pitch = core_pitch();
    const uint8_t *src = core_pixels();
    if (w <= 0 || h <= 0 || !src) { core_unlock(); return -1; }

    const int cols = (w + TILE_W - 1) / TILE_W;
    const int rows = (h + TILE_H - 1) / TILE_H;
    const int ntiles = cols * rows;
    const int tilebytes = TILE_W * TILE_H * 3;

    int keyframe = force_key || !g_prev || g_prev_w != w || g_prev_h != h;
    if (keyframe) {
        free(g_prev);
        g_prev = calloc((size_t)w * h * 3, 1);
        g_prev_w = w;
        g_prev_h = h;
        if (!g_prev) { core_unlock(); return -1; }
    }

    const int header = 1 + 2 + 2 + 1 + 1 + 2 + 2 + 2;
    if (out_cap < header + ntiles * (2 + tilebytes)) { core_unlock(); return -1; }

    uint8_t *idxp = out + header;
    uint8_t *datap = idxp + ntiles * 2;   /* provisional; compacted below */
    int count = 0;

    for (int ty = 0; ty < rows; ty++) {
        for (int tx = 0; tx < cols; tx++) {
            uint8_t tile[TILE_W * TILE_H * 3];
            memset(tile, 0, sizeof(tile));
            int changed = 0;
            for (int y = 0; y < TILE_H; y++) {
                const int sy = ty * TILE_H + y;
                if (sy >= h) break;
                const uint32_t *row = (const uint32_t *)(src + (size_t)sy * pitch);
                uint8_t *prow = g_prev + ((size_t)sy * w + tx * TILE_W) * 3;
                uint8_t *trow = tile + y * TILE_W * 3;
                for (int x = 0; x < TILE_W; x++) {
                    const int sx = tx * TILE_W + x;
                    if (sx >= w) break;
                    const uint32_t p = row[sx];
                    const uint8_t r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
                    trow[x * 3] = r; trow[x * 3 + 1] = g; trow[x * 3 + 2] = b;
                    if (!changed && (prow[x * 3] != r || prow[x * 3 + 1] != g || prow[x * 3 + 2] != b))
                        changed = 1;
                }
            }
            if (!changed && !keyframe) continue;

            /* commit the tile into prev and into the payload */
            for (int y = 0; y < TILE_H; y++) {
                const int sy = ty * TILE_H + y;
                if (sy >= h) break;
                memcpy(g_prev + ((size_t)sy * w + tx * TILE_W) * 3,
                       tile + y * TILE_W * 3,
                       (size_t)(tx * TILE_W + TILE_W <= w ? TILE_W : w - tx * TILE_W) * 3);
            }
            put_u16(idxp + count * 2, (unsigned)(ty * cols + tx));
            memcpy(datap + (size_t)count * tilebytes, tile, tilebytes);
            count++;
        }
    }
    core_unlock();

    /* close the gap left by reserving room for every possible index */
    uint8_t *finaldata = idxp + count * 2;
    if (finaldata != datap && count > 0)
        memmove(finaldata, datap, (size_t)count * tilebytes);

    out[0] = keyframe ? 1 : 0;
    put_u16(out + 1, (unsigned)w);
    put_u16(out + 3, (unsigned)h);
    out[5] = TILE_W;
    out[6] = TILE_H;
    put_u16(out + 7, (unsigned)cols);
    put_u16(out + 9, (unsigned)rows);
    put_u16(out + 11, (unsigned)count);
    return header + count * 2 + count * tilebytes;
}

/* Whole framebuffer as RGB, nearest-neighbour scaled. Used by the REST API,
 * which hands agents a PNG rather than a tile delta. */
/* Mean brightness of the frame, 0..255, on a sparse grid.
   A fully black screen is how this game changes scene, and the fade is over
   in a few frames, so it has to be sampled while waiting rather than after.
   Every eighth pixel of every fourth row is far more than enough to tell black
   from not-black, and keeps this cheap enough to call once per frame. */
int fb_luma(void) {
    core_lock();
    const int w = core_width(), h = core_height(), pitch = core_pitch();
    const uint8_t *src = core_pixels();
    if (w <= 0 || h <= 0 || !src) { core_unlock(); return -1; }
    unsigned long sum = 0;
    int n = 0;
    for (int y = 0; y < h; y += 4) {
        const uint32_t *row = (const uint32_t *)(src + (size_t)y * pitch);
        for (int x = 0; x < w; x += 8) {
            const uint32_t p = row[x];
            /* green is most of perceived brightness; one channel is enough
               to answer "is this black" and costs a third of the loads */
            sum += (p >> 8) & 0xFF;
            n++;
        }
    }
    core_unlock();
    return n ? (int)(sum / n) : -1;
}

int fb_snapshot(uint8_t *out, int cap, int scale, int *w_out, int *h_out) {
    if (scale < 1) scale = 1;
    if (scale > 6) scale = 6;
    core_lock();
    const int w = core_width(), h = core_height(), pitch = core_pitch();
    const uint8_t *src = core_pixels();
    if (w <= 0 || h <= 0 || !src) { core_unlock(); return -1; }
    const int ow = w * scale, oh = h * scale;
    if (cap < ow * oh * 3) { core_unlock(); return -1; }
    for (int y = 0; y < h; y++) {
        const uint32_t *row = (const uint32_t *)(src + (size_t)y * pitch);
        for (int sy = 0; sy < scale; sy++) {
            uint8_t *o = out + ((size_t)(y * scale + sy) * ow) * 3;
            for (int x = 0; x < w; x++) {
                const uint32_t p = row[x];
                const uint8_t r = (p >> 16) & 0xFF, g = (p >> 8) & 0xFF, b = p & 0xFF;
                for (int sx = 0; sx < scale; sx++) {
                    *o++ = r; *o++ = g; *o++ = b;
                }
            }
        }
    }
    core_unlock();
    if (w_out) *w_out = ow;
    if (h_out) *h_out = oh;
    return ow * oh * 3;
}

void fb_reset(void) {
    free(g_prev);
    g_prev = NULL;
    g_prev_w = g_prev_h = 0;
}
