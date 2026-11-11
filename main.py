#!/usr/bin/env python3
"""make.fun cutest-cat-01 entry: draws the cutest cat we can, in code.

Pure Python 3 standard library (no PIL, no numpy, no network).
Renders a soft storybook kitten -- huge sparkling eyes, a tilted head,
rosy blush, a pink bow and one paw resting on its ball of yarn -- with
signed-distance shapes and a 1-pixel analytic anti-aliasing band,
then writes a deterministic PNG to /output/entry.png
(or $MAKEFUN_OUTPUT_DIR/entry.png outside the grader container).

Every shape is painted only inside its own tight bounding box, which
keeps the whole render at a few seconds on one CPU.

Run:  python3 main.py
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024
HYPOT = math.hypot


# ---------------------------------------------------------------- canvas

class Canvas:
    """RGB bytearray canvas; shapes paint colour where their SDF <= 0."""

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def set_bg(self, top, bottom):
        w, h, px = self.w, self.h, self.px
        for y in range(h):
            t = y / (h - 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            row = y * w * 3
            line = bytes((r, g, b)) * w
            px[row:row + w * 3] = line

    def paint(self, bbox, dist_fn, color):
        """dist_fn(x, y) <= 0 is inside; 1.5 px AA band on the edge."""
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(self.w - 1, x1); y1 = min(self.h - 1, y1)
        px, w = self.px, self.w
        cr, cg, cb = color
        for y in range(y0, y1 + 1):
            base = y * w * 3
            for x in range(x0, x1 + 1):
                d = dist_fn(x, y)
                if d < 0.75:
                    a = 1.0 if d <= -0.75 else (0.75 - d) / 1.5
                    i = base + x * 3
                    ia = 1.0 - a
                    px[i] = int(cr * a + px[i] * ia + 0.5)
                    px[i + 1] = int(cg * a + px[i + 1] * ia + 0.5)
                    px[i + 2] = int(cb * a + px[i + 2] * ia + 0.5)

    def paint_fn(self, bbox, fn):
        """fn(x, y) -> (color, alpha) or None, for shaded shapes."""
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(self.w - 1, x1); y1 = min(self.h - 1, y1)
        px, w = self.px, self.w
        for y in range(y0, y1 + 1):
            base = y * w * 3
            for x in range(x0, x1 + 1):
                out = fn(x, y)
                if out is not None:
                    color, a = out
                    if a > 0.0:
                        if a > 1.0:
                            a = 1.0
                        i = base + x * 3
                        ia = 1.0 - a
                        px[i] = int(color[0] * a + px[i] * ia + 0.5)
                        px[i + 1] = int(color[1] * a + px[i + 1] * ia + 0.5)
                        px[i + 2] = int(color[2] * a + px[i + 2] * ia + 0.5)


# ------------------------------------------------------- distance helpers

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def cov(d):
    """Coverage from a signed distance (px): 1 deep inside, 0 outside."""
    return clamp(0.75 - d, 0.0, 1.0)


def d_circle(x, y, cx, cy, r):
    return HYPOT(x - cx, y - cy) - r


def d_ellipse(x, y, cx, cy, rx, ry):
    return (HYPOT((x - cx) / rx, (y - cy) / ry) - 1.0) * (rx if rx < ry else ry)


def d_segment(x, y, ax, ay, bx, by):
    px, py = x - ax, y - ay
    dx, dy = bx - ax, by - ay
    t = clamp((px * dx + py * dy) / (dx * dx + dy * dy), 0.0, 1.0)
    return HYPOT(px - dx * t, py - dy * t)


def d_polyline(x, y, pts):
    best = 1e18
    for i in range(len(pts) - 1):
        d = d_segment(x, y, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if d < best:
            best = d
    return best


def d_triangle(x, y, ax, ay, bx, by, cx, cy):
    def edge(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    s1 = edge(ax, ay, bx, by, x, y)
    s2 = edge(bx, by, cx, cy, x, y)
    s3 = edge(cx, cy, ax, ay, x, y)
    inside = (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)
    d = min(
        d_segment(x, y, ax, ay, bx, by),
        d_segment(x, y, bx, by, cx, cy),
        d_segment(x, y, cx, cy, ax, ay),
    )
    return -d if inside else d


def arc_pts(cx, cy, r, a0, a1, n=24):
    return [
        (cx + r * math.cos(a0 + (a1 - a0) * i / n),
         cy + r * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]


def bezier_pts(p0, p1, p2, p3, n=24):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def bbox_of(pts, pad):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (int(min(xs) - pad), int(min(ys) - pad),
            int(max(xs) + pad), int(max(ys) + pad))


def shrink(pts, cx, cy, f):
    return [(cx + (x - cx) * f, cy + (y - cy) * f) for (x, y) in pts]


# ---------------------------------------------------------------- palette

CREAM_TOP = (255, 241, 226)
CREAM_BOT = (255, 213, 195)
FUR = (246, 166, 90)          # warm ginger
FUR_DARK = (226, 132, 56)     # soft outline of the fur
FUR_DEEP = (198, 106, 38)     # tabby stripes
BELLY = (255, 240, 219)
MUZZLE = (255, 246, 232)
PINK = (244, 114, 152)
PINK_SOFT = (252, 183, 203)
NOSE = (240, 98, 128)
BLUSH = (250, 138, 150)
LINE = (110, 70, 44)          # mouth / whisker line
EYE_IRIS = (42, 156, 136)     # teal-green iris
EYE_IRIS_LT = (116, 218, 190)
EYE_DARK = (24, 22, 26)
WHITE = (255, 255, 255)
YARN = (240, 110, 150)
YARN_DARK = (203, 70, 114)
BOW = (238, 82, 128)
BOW_DARK = (203, 52, 100)


# ---------------------------------------------------------------- drawing

def draw():
    cv = Canvas(W, H)
    cv.set_bg(CREAM_TOP, CREAM_BOT)

    # ground shadow
    cv.paint((172, 806, 852, 918), lambda x, y: d_ellipse(x, y, 512, 862, 330, 40),
             (234, 178, 150))

    # ---------------------------------------------------------- tail (one!)
    # A single tail curls from behind the body around the cat's right
    # side (viewer's right) and lifts at the end with a cream tip.
    tail_path = bezier_pts((640, 800), (836, 802), (884, 690), (838, 592), 30)
    tail_bb = bbox_of(tail_path, 52)
    cv.paint(tail_bb, lambda x, y: d_polyline(x, y, tail_path) - 40, FUR_DARK)
    cv.paint(tail_bb, lambda x, y: d_polyline(x, y, tail_path) - 33, FUR)
    # two narrow tabby bands across the tail (half-segment long each)
    for i in (10, 17):
        a_pt = tail_path[i]
        b_pt = tail_path[i + 1]
        seg = [a_pt, ((a_pt[0] + b_pt[0]) / 2, (a_pt[1] + b_pt[1]) / 2)]
        cv.paint(bbox_of(seg, 44), lambda x, y, s=seg: d_polyline(x, y, s) - 34, FUR_DEEP)
    # cream tip
    tip_path = tail_path[-7:]
    cv.paint(bbox_of(tip_path, 45), lambda x, y: d_polyline(x, y, tip_path) - 33, BELLY)

    # --------------------------------------------------------------- body
    cv.paint((266, 524, 758, 902), lambda x, y: d_ellipse(x, y, 512, 726, 238, 196), FUR_DARK)
    cv.paint((274, 532, 750, 894), lambda x, y: d_ellipse(x, y, 512, 720, 228, 188), FUR)
    # belly patch
    cv.paint((356, 610, 668, 890), lambda x, y: d_ellipse(x, y, 512, 756, 148, 138), BELLY)
    # haunches at the base, either side
    for hcx in (348, 676):
        cv.paint((hcx - 112, 702, hcx + 112, 898),
                 lambda x, y, c=hcx: d_ellipse(x, y, c, 800, 104, 92), FUR_DARK)
        cv.paint((hcx - 104, 710, hcx + 104, 890),
                 lambda x, y, c=hcx: d_ellipse(x, y, c, 796, 96, 85), FUR)

    # ---------------------------------------------------------- yarn ball
    # the favourite toy, peeking out from under the cat's right paw
    ycx, ycy, yr = 740, 860, 60
    ybb = (ycx - yr - 8, ycy - yr - 8, ycx + yr + 8, ycy + yr + 8)
    cv.paint(ybb, lambda x, y: d_circle(x, y, ycx, ycy, yr), YARN_DARK)
    cv.paint(ybb, lambda x, y: d_circle(x, y, ycx, ycy, yr - 6), YARN)
    for pts in (
        arc_pts(ycx, ycy, yr * 0.60, 3.4, 5.6),
        arc_pts(ycx, ycy, yr * 0.78, 2.6, 4.4),
        arc_pts(ycx, ycy, yr * 0.52, 0.4, 2.2),
        bezier_pts((ycx - 46, ycy + 32), (ycx - 8, ycy + 52),
                   (ycx + 28, ycy + 46), (ycx + 48, ycy + 14)),
    ):
        cv.paint(bbox_of(pts, 9), lambda x, y, p=pts: d_polyline(x, y, p) - 5, YARN_DARK)
    # loose strand curling away on the ground
    strand = bezier_pts((782, 898), (830, 920), (868, 888), (892, 908), 20)
    strand += bezier_pts((892, 908), (912, 922), (926, 900), (910, 884), 10)[1:]
    cv.paint(bbox_of(strand, 9), lambda x, y: d_polyline(x, y, strand) - 5, YARN_DARK)

    # ---------------------------------------------------------- front paws
    # two clumsy oversized front paws; the right one rests on the yarn
    for (pcx, pcy, prx, pry) in ((406, 860, 74, 40), (644, 832, 76, 42)):
        pbb = (pcx - prx - 8, pcy - pry - 8, pcx + prx + 8, pcy + pry + 8)
        cv.paint(pbb, lambda x, y, a=pcx, b=pcy, c=prx, d=pry:
                 d_ellipse(x, y, a, b, c, d), FUR_DARK)
        cv.paint(pbb, lambda x, y, a=pcx, b=pcy, c=prx - 7, d=pry - 7:
                 d_ellipse(x, y, a, b, c, d), FUR)
        for tx in (-26, 0, 26):
            seg = [(pcx + tx, pcy + pry - 34), (pcx + tx, pcy + pry - 13)]
            cv.paint(bbox_of(seg, 6), lambda x, y, s=seg: d_polyline(x, y, s) - 3.2, FUR_DEEP)

    # --------------------------------------------------------------- head
    # Head group tilted ~7 degrees for charm: points are evaluated in
    # head space; each shape carries its own tight head-space bbox,
    # widened a little to cover the rotation.
    HX, HY = 512, 402
    TILT = math.radians(-7.0)
    CT, ST = math.cos(TILT), math.sin(TILT)

    def head_paint(hbb, fn, color):
        (x0, y0, x1, y1) = hbb
        pad = int((abs(ST) * (x1 - x0 + y1 - y0)) / 2) + 6
        def wrapped(x, y):
            dx, dy = x - HX, y - HY
            return fn(HX + dx * CT + dy * ST, HY - dx * ST + dy * CT)
        cv.paint((x0 - pad, y0 - pad, x1 + pad, y1 + pad), wrapped, color)

    def head_fn(hbb, fn):
        (x0, y0, x1, y1) = hbb
        pad = int((abs(ST) * (x1 - x0 + y1 - y0)) / 2) + 6
        def wrapped(x, y):
            dx, dy = x - HX, y - HY
            return fn(HX + dx * CT + dy * ST, HY - dx * ST + dy * CT)
        cv.paint_fn((x0 - pad, y0 - pad, x1 + pad, y1 + pad), wrapped)

    # ears: rounded triangles, fur inset, pink inner ear
    for (ex, sgn) in ((356, -1), (668, 1)):
        tri = [(ex - 96, 274), (ex + sgn * 30, 120), (ex + 96, 274)]
        gx = sum(p[0] for p in tri) / 3
        gy = sum(p[1] for p in tri) / 3
        fur_tri = shrink(tri, gx, gy, 0.86)
        in_tri = shrink(tri, gx, gy, 0.52)
        ebb = bbox_of(tri, 6)
        head_paint(ebb, lambda x, y, t=tri: d_triangle(x, y, *t[0], *t[1], *t[2]), FUR_DARK)
        head_paint(ebb, lambda x, y, t=fur_tri: d_triangle(x, y, *t[0], *t[1], *t[2]), FUR)
        head_paint(ebb, lambda x, y, t=in_tri: d_triangle(x, y, *t[0], *t[1], *t[2]), PINK_SOFT)

    # head disc: big and round (kitten proportions)
    head_paint((262, 176, 762, 628), lambda x, y: d_ellipse(x, y, HX, HY, 252, 228), FUR_DARK)
    head_paint((270, 184, 754, 620), lambda x, y: d_ellipse(x, y, HX, HY, 242, 218), FUR)
    # gentle lighter crown
    head_fn((272, 190, 632, 390),
            lambda x, y: ((255, 216, 164), 0.32 * cov(d_ellipse(x, y, 452, 272, 180, 112)))
            if d_ellipse(x, y, 452, 272, 180, 112) < 0.75 else None)

    # tabby stripes on the forehead
    for pts in (
        [(452, 192), (448, 238), (452, 274)],
        [(512, 182), (512, 230), (512, 268)],
        [(572, 192), (576, 238), (572, 274)],
    ):
        head_paint(bbox_of(pts, 14), lambda x, y, p=pts: d_polyline(x, y, p) - 11, FUR_DEEP)

    # muzzle patch
    head_paint((356, 424, 668, 620), lambda x, y: d_ellipse(x, y, HX, 522, 148, 92), MUZZLE)

    # ------------------------------------------------------------- eyes
    # Huge sparkling eyes, set low on the face (kitten proportions).
    for ecx in (398, 626):
        ebb = (ecx - 76, 338, ecx + 76, 522)
        head_paint(ebb, lambda x, y, c=ecx: d_ellipse(x, y, c, 428, 66, 82), WHITE)

        def iris_fn(x, y, c=ecx):
            d = d_ellipse(x, y, c, 432, 56, 74)
            if d >= 0.75:
                return None
            t = clamp((y - 358) / 148.0, 0.0, 1.0)
            col = tuple(int(EYE_IRIS_LT[i] + (EYE_IRIS[i] - EYE_IRIS_LT[i]) * t)
                        for i in range(3))
            return (col, cov(d))
        head_fn(ebb, iris_fn)
        # pupil
        head_paint(ebb, lambda x, y, c=ecx: d_ellipse(x, y, c, 436, 27, 47), EYE_DARK)
        # sparkles: one big, one small
        head_paint(ebb, lambda x, y, c=ecx: d_circle(x, y, c - 16, 400, 19), WHITE)
        head_paint(ebb, lambda x, y, c=ecx: d_circle(x, y, c + 14, 460, 9), WHITE)
        # soft dark lash arc over the eye
        lash = arc_pts(ecx, 428, 66, math.radians(195), math.radians(345), 18)
        lash = [(lx, 428 + (ly - 428) * 1.24) for (lx, ly) in lash]
        head_paint(bbox_of(lash, 10), lambda x, y, p=lash: d_polyline(x, y, p) - 6, LINE)

    # ------------------------------------------------------- nose + mouth
    nose = [(484, 500), (540, 500), (512, 534)]
    head_paint(bbox_of(nose, 6), lambda x, y: d_triangle(x, y, 484, 500, 540, 500, 512, 534), NOSE)
    head_paint((486, 496, 512, 520), lambda x, y: d_circle(x, y, 498, 508, 7), (255, 205, 218))
    # a small "w" smile under the nose
    mouth_l = arc_pts(486, 528, 26, math.radians(15), math.radians(160), 12)
    mouth_r = arc_pts(538, 528, 26, math.radians(20), math.radians(165), 12)
    for pts in (mouth_l, mouth_r):
        head_paint(bbox_of(pts, 8), lambda x, y, p=pts: d_polyline(x, y, p) - 5, LINE)
    stem = [(512, 530), (512, 546)]
    head_paint(bbox_of(stem, 8), lambda x, y: d_polyline(x, y, stem) - 5, LINE)
    # tiny tongue peeking out, touching the mouth
    head_paint((488, 552, 536, 592), lambda x, y: d_ellipse(x, y, 512, 572, 20, 15), PINK)
    tline = [(512, 566), (512, 582)]
    head_paint(bbox_of(tline, 5), lambda x, y: d_polyline(x, y, tline) - 2.2, (222, 90, 130))

    # ------------------------------------------------------------- blush
    for bcx in (344, 680):
        head_fn((bcx - 52, 458, bcx + 52, 526),
                lambda x, y, c=bcx: (BLUSH, 0.5 * cov(d_ellipse(x, y, c, 492, 46, 27)))
                if d_ellipse(x, y, c, 492, 46, 27) < 0.75 else None)

    # ---------------------------------------------------------- whiskers
    for (wy, sgn) in ((502, -1), (530, -1), (502, 1), (530, 1)):
        seg = [(HX + sgn * 104, wy), (HX + sgn * 288, wy + (12 if wy == 502 else 28))]
        head_paint(bbox_of(seg, 7), lambda x, y, s=seg: d_polyline(x, y, s) - 2.8, LINE)

    # ---------------------------------------------------------------- bow
    # a pink bow perched by the cat's right ear (viewer's right)
    bx, by = 678, 156
    BC, BS = math.cos(0.35), math.sin(0.35)

    def bow_paint(bbox, fn, color):
        def wrapped(x, y):
            dx, dy = x - bx, y - by
            return fn(bx + dx * BC + dy * BS, by - dx * BS + dy * BC)
        cv.paint(bbox, wrapped, color)

    BOW_BB = (bx - 130, by - 100, bx + 130, by + 100)
    bow_paint(BOW_BB, lambda x, y: d_triangle(x, y, bx, by, bx - 88, by - 44, bx - 84, by + 48), BOW_DARK)
    bow_paint(BOW_BB, lambda x, y: d_triangle(x, y, bx, by, bx + 88, by - 44, bx + 84, by + 48), BOW_DARK)
    bow_paint(BOW_BB, lambda x, y: d_triangle(x, y, bx, by, bx - 78, by - 36, bx - 74, by + 40), BOW)
    bow_paint(BOW_BB, lambda x, y: d_triangle(x, y, bx, by, bx + 78, by - 36, bx + 74, by + 40), BOW)
    bow_paint(BOW_BB, lambda x, y: d_circle(x, y, bx, by, 24), BOW_DARK)
    bow_paint(BOW_BB, lambda x, y: d_circle(x, y, bx, by, 18), BOW)
    bow_paint(BOW_BB, lambda x, y: d_circle(x, y, bx - 6, by - 6, 6), PINK_SOFT)

    # ------------------------------------------- two tiny floating hearts
    def heart(cx, cy, s, color, alpha):
        def fn(x, y):
            lx = (x - cx) / s
            ly = (cy - y) / s
            v = (lx * lx + ly * ly - 1) ** 3 - lx * lx * ly ** 3
            return (color, alpha) if v < 0 else None
        pad = int(s * 1.5)
        cv.paint_fn((cx - pad, cy - pad, cx + pad, cy + pad), fn)
    heart(168, 268, 26, PINK, 0.75)
    heart(864, 330, 19, PINK, 0.6)

    return cv


# ------------------------------------------------------------------- PNG

def write_png(cv, path):
    w, h = cv.w, cv.h
    raw = bytearray()
    rowlen = w * 3
    for y in range(h):
        raw.append(0)  # filter: none
        raw += cv.px[y * rowlen:(y + 1) * rowlen]

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        c += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return c

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    cv = draw()
    write_png(cv, os.path.join(out_dir, "entry.png"))


if __name__ == "__main__":
    main()
