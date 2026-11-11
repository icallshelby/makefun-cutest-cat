#!/usr/bin/env python3
"""make.fun cutest-cat-01 entry, v4: "Mochi", a chibi kitten waving.

Pure Python 3 standard library (no PIL, no numpy, no network, no
assets). A round-faced cream-ginger kitten with a huge fluffy head,
deep jewel-teal eyes with limbal rings and triple sparkles, an open
happy mouth with two tiny fangs, a bell collar, one paw raised in a
wave (toe beans to the viewer) and the other resting on its yarn
ball, sitting on a plump cushion -- rendered from signed-distance
shapes with analytic anti-aliasing and layered radial shading, then
written as a byte-for-byte deterministic PNG to /output/entry.png
(or $MAKEFUN_OUTPUT_DIR/entry.png when that is set).

Every shape paints only inside its own tight bounding box, so the
whole picture costs a few seconds on one CPU.

Run:  python3 main.py
"""

import math
import os
import struct
import zlib

SIZE = 1024
DIST = math.hypot
TAU = math.tau


# ------------------------------------------------------------------ image

class Pic:
    """An RGB raster we blend shapes into, back to front."""

    def __init__(self, size):
        self.size = size
        self.buf = bytearray(size * size * 3)

    def _put(self, i, rgb, a):
        if a >= 1.0:
            self.buf[i] = rgb[0]
            self.buf[i + 1] = rgb[1]
            self.buf[i + 2] = rgb[2]
        elif a > 0.0:
            b = self.buf
            ia = 1.0 - a
            b[i] = int(rgb[0] * a + b[i] * ia + 0.5)
            b[i + 1] = int(rgb[1] * a + b[i + 1] * ia + 0.5)
            b[i + 2] = int(rgb[2] * a + b[i + 2] * ia + 0.5)

    def wash(self, fn):
        """Fill the whole raster from fn(x, y) -> (rgb, alpha)."""
        s = self.size
        for y in range(s):
            row = y * s * 3
            for x in range(s):
                rgb, a = fn(x, y)
                if a > 0.0:
                    self._put(row + x * 3, rgb, a)

    def shape(self, box, sdf, rgb):
        """Solid fill: sdf(x, y) <= 0 inside, 1.6 px feathered edge."""
        x0, y0, x1, y1 = self._clip(box)
        s = self.size
        for y in range(y0, y1 + 1):
            row = y * s * 3
            for x in range(x0, x1 + 1):
                d = sdf(x, y)
                if d < 0.8:
                    a = 1.0 if d <= -0.8 else (0.8 - d) / 1.6
                    self._put(row + x * 3, rgb, a)

    def shade(self, box, fn):
        """Per-pixel fill: fn(x, y) -> (rgb, alpha) or None."""
        x0, y0, x1, y1 = self._clip(box)
        s = self.size
        for y in range(y0, y1 + 1):
            row = y * s * 3
            for x in range(x0, x1 + 1):
                out = fn(x, y)
                if out is not None and out[1] > 0.0:
                    a = out[1] if out[1] < 1.0 else 1.0
                    self._put(row + x * 3, out[0], a)

    def _clip(self, box):
        m = self.size - 1
        return (max(0, box[0]), max(0, box[1]),
                min(m, box[2]), min(m, box[3]))


# -------------------------------------------------------------- sdf toolbox

def clamp01(v):
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def smooth(a, b, v):
    t = clamp01((v - a) / (b - a))
    return t * t * (3.0 - 2.0 * t)


def blend(c1, c2, t):
    return (int(c1[0] + (c2[0] - c1[0]) * t + 0.5),
            int(c1[1] + (c2[1] - c1[1]) * t + 0.5),
            int(c1[2] + (c2[2] - c1[2]) * t + 0.5))


def cover(d):
    """Alpha for a signed distance: solid deep inside, gone outside."""
    return clamp01(0.8 - d)


def dst_disc(x, y, cx, cy, r):
    return DIST(x - cx, y - cy) - r


def dst_oval(x, y, cx, cy, rx, ry):
    return (DIST((x - cx) / rx, (y - cy) / ry) - 1.0) * min(rx, ry)


def dst_seg(x, y, ax, ay, bx, by):
    ex, ey = bx - ax, by - ay
    t = clamp01(((x - ax) * ex + (y - ay) * ey) / (ex * ex + ey * ey))
    return DIST(x - ax - ex * t, y - ay - ey * t)


def dst_path(x, y, pts):
    d = 1e18
    for i in range(len(pts) - 1):
        di = dst_seg(x, y, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        if di < d:
            d = di
    return d


def dst_tri(x, y, ax, ay, bx, by, cx, cy):
    def cross(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    s1 = cross(ax, ay, bx, by, x, y)
    s2 = cross(bx, by, cx, cy, x, y)
    s3 = cross(cx, cy, ax, ay, x, y)
    inside = (s1 >= 0 and s2 >= 0 and s3 >= 0) or \
             (s1 <= 0 and s2 <= 0 and s3 <= 0)
    d = min(dst_seg(x, y, ax, ay, bx, by),
            dst_seg(x, y, bx, by, cx, cy),
            dst_seg(x, y, cx, cy, ax, ay))
    return -d if inside else d


def arc(cx, cy, r, a0, a1, n=26):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
             cy + r * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def cubic(p0, p1, p2, p3, n=26):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0]
                    + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1]
                    + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def quad(p0, p1, p2, n=22):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def bounds(pts, pad):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (int(min(xs) - pad), int(min(ys) - pad),
            int(max(xs) + pad), int(max(ys) + pad))


def scaled(pts, cx, cy, f):
    return [(cx + (x - cx) * f, cy + (y - cy) * f) for (x, y) in pts]


def sparkle_pts(cx, cy, r):
    pts = []
    for i in range(8):
        ang = math.pi * i / 4.0
        rad = r if i % 2 == 0 else r * 0.28
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


# ----------------------------------------------------------------- palette

PAPER_HI = (255, 247, 236)
PAPER_LO = (255, 206, 184)
HALO = (255, 253, 244)
FUR = (246, 166, 92)            # ginger coat
FUR_HI = (255, 207, 142)        # sunlit coat
FUR_LO = (230, 136, 60)         # coat shadow / outline pass
FUR_TABBY = (196, 108, 42)      # stripes
CREAM = (255, 243, 224)         # bib, muzzle, ear fluff
MUZZLE = (255, 248, 238)
ROSE = (244, 114, 152)
ROSE_SOFT = (252, 183, 203)
NOSE = (238, 95, 124)
BLUSH = (250, 140, 150)
MOUTH_IN = (146, 54, 74)
TONGUE = (247, 130, 158)
LINE = (104, 64, 40)
WHISK = (128, 90, 60)
IRIS_TOP = (16, 112, 104)
IRIS_MID = (46, 196, 166)
IRIS_LOW = (168, 244, 214)
IRIS_RIM = (8, 84, 76)
PUPIL = (22, 20, 24)
WHITE = (255, 255, 255)
COLLAR = (226, 70, 116)
COLLAR_HI = (244, 120, 158)
BELL = (250, 198, 88)
BELL_LO = (219, 148, 42)
BELL_HI = (255, 236, 168)
YARN = (238, 106, 148)
YARN_LO = (200, 66, 110)
BOW = (240, 84, 130)
BOW_LO = (198, 48, 98)
BOW_HI = (252, 150, 182)


# ------------------------------------------------------------ soft painting

def glow_spot(pic, box, cx, cy, rx, ry, rgb, peak, grow=1.25):
    """A radial-falloff ellipse: full strength at the middle, easing
    to nothing before a slightly enlarged boundary, so it can never
    clip against its own box."""
    gx, gy = rx * grow, ry * grow

    def fn(x, y):
        u = ((x - cx) / gx) ** 2 + ((y - cy) / gy) ** 2
        if u >= 1.0:
            return None
        return (rgb, peak * (1.0 - u) ** 1.6)
    pic.shade(box, fn)


def coat_shading(pic, box, sdf, cx, cy, rx, ry):
    """Plush shading over a fur silhouette given by sdf: a warm light
    blooming from the upper left and a soft shadow rim that follows
    the silhouette's own edge."""
    def light(x, y):
        if sdf(x, y) >= 0.8:
            return None
        d = DIST(x - (cx - rx * 0.38), y - (cy - ry * 0.46)) / (rx * 1.3)
        a = 0.32 * max(0.0, 1.0 - d) ** 2
        return (FUR_HI, a) if a > 0.004 else None

    def rim(x, y):
        d = sdf(x, y)
        if d >= 0.8 or d < -46.0:
            return None
        a = 0.16 * smooth(-46.0, 0.0, d)
        return (FUR_TABBY, a) if a > 0.004 else None

    pic.shade(box, light)
    pic.shade(box, rim)


def taper_stroke(paint, pts, rgb, r0):
    """Stroke a path in three runs of shrinking radius so it tapers
    like a whisker. paint(box, sdf, rgb) is Pic.shape or a wrapper."""
    n = len(pts)
    for (i0, i1, f) in ((0, n // 3 + 1, 1.0), (n // 3, 2 * n // 3 + 1, 0.7),
                        (2 * n // 3, n, 0.45)):
        seg = pts[i0:i1]
        if len(seg) < 2:
            continue
        r = r0 * f
        paint(bounds(seg, int(r) + 3),
              lambda x, y, s=seg, rr=r: dst_path(x, y, s) - rr, rgb)


# ------------------------------------------------------------------- scene

def draw():
    pic = Pic(SIZE)

    # -------------------------------------------------------- backdrop
    # warm paper gradient, a halo behind the kitten, a gentle
    # deepening toward the corners, and quiet bokeh floating over it
    def backdrop_fn(x, y):
        base = blend(PAPER_HI, PAPER_LO, y / (SIZE - 1))
        halo = max(0.0, 1.0 - DIST(x - 512, y - 400) / 620.0) ** 2
        if halo > 0.003:
            base = blend(base, HALO, 0.55 * halo)
        edge = DIST(x - 512, y - 470) / 760.0
        if edge > 0.62:
            base = blend(base, (250, 188, 168), 0.35 * (edge - 0.62) / 0.38)
        return (base, 1.0)
    pic.wash(backdrop_fn)

    for (bx, by, br, tint, al) in (
        (118, 292, 36, WHITE, 0.13), (922, 250, 46, WHITE, 0.11),
        (846, 636, 27, ROSE_SOFT, 0.13), (148, 690, 23, WHITE, 0.10),
        (66, 108, 19, ROSE_SOFT, 0.14), (962, 84, 25, WHITE, 0.12),
        (566, 108, 15, WHITE, 0.09), (306, 168, 13, ROSE_SOFT, 0.10),
        (716, 150, 11, WHITE, 0.08), (88, 470, 12, WHITE, 0.09),
    ):
        glow_spot(pic, (bx - br * 2, by - br * 2, bx + br * 2, by + br * 2),
                  bx, by, br, br, tint, al, 1.0)

    # warm window light pooling in from the upper left corner
    glow_spot(pic, (0, 0, 560, 520), 40, 30, 330, 300,
              (255, 252, 238), 0.20, 1.3)

    # sparkles drifting in the corners
    for (sx, sy, sr, tint, al) in (
        (206, 118, 17, WHITE, 0.9), (872, 342, 13, ROSE_SOFT, 0.75),
        (112, 548, 11, ROSE_SOFT, 0.7), (934, 762, 12, WHITE, 0.8),
        (660, 84, 10, WHITE, 0.7), (158, 372, 10, WHITE, 0.85),
        (318, 330, 8, ROSE_SOFT, 0.7),
    ):
        pts = sparkle_pts(sx, sy, sr)
        pic.shape(bounds(pts, 3),
                  lambda x, y, p=pts: dst_path(x, y, p + [p[0]]) - 1.6, tint)

    # ------------------------------------------------------ floor + rug
    glow_spot(pic, (60, 800, 964, 950), 512, 878, 352, 48,
              (224, 152, 120), 0.50, 1.25)
    # a scalloped round rug under the kitten: overlapping discs
    rug_c = [(512 + 236 * math.cos(TAU * i / 14.0),
              884 + 40 * math.sin(TAU * i / 14.0)) for i in range(14)]

    def rug_sdf(x, y):
        d = dst_oval(x, y, 512, 884, 252, 46)
        for (cx, cy) in rug_c:
            di = dst_disc(x, y, cx, cy, 23)
            if di < d:
                d = di
        return d
    pic.shape((196, 812, 828, 956), rug_sdf, (243, 178, 164))
    pic.shape((206, 820, 818, 948),
              lambda x, y: dst_oval(x, y, 512, 884, 238, 38), (250, 198, 182))

    # a plump cushion the kitten sits on: a fat squashed oval with a
    # lighter top face and a soft shadow pooling underneath it
    glow_spot(pic, (170, 846, 854, 972), 512, 916, 330, 42,
              (216, 138, 104), 0.34, 1.25)

    def cushion_fn(x, y):
        d = dst_oval(x, y, 512, 884, 292, 54)
        if d >= 0.8:
            return None
        t = clamp01((y - 838) / 92.0)
        col = blend((252, 196, 178), (240, 152, 130), t)
        dl = DIST(x - 420, y - 856) / 260.0
        if dl < 1.0:
            col = blend(col, (255, 226, 208), 0.5 * (1.0 - dl) ** 2)
        return (col, cover(d))
    pic.shade((212, 822, 812, 946), cushion_fn)
    # two little tuft buttons dimpled into the cushion front
    for bx2 in (392, 632):
        glow_spot(pic, (bx2 - 26, 884, bx2 + 26, 928), bx2, 906, 13, 8,
                  (228, 138, 116), 0.35, 1.0)

    # faint paw prints wandering across the corners of the floor
    for (pxx, pyy, ang) in ((128, 928, -0.4), (196, 958, 0.2),
                            (884, 946, 0.5), (820, 972, -0.2)):
        ca, sa = math.cos(ang), math.sin(ang)

        def paw_sdf(x, y, a=ca, b=sa, cx=pxx, cy=pyy):
            lx = cx + (x - cx) * a + (y - cy) * b
            ly = cy - (x - cx) * b + (y - cy) * a
            d = dst_oval(lx, ly, cx, cy + 6, 13, 10)
            for (tx, ty) in ((-14, -8), (-5, -13), (5, -13), (14, -8)):
                di = dst_disc(lx, ly, cx + tx, cy + ty, 5)
                if di < d:
                    d = di
            return d
        pic.shape((pxx - 30, pyy - 26, pxx + 30, pyy + 26), paw_sdf,
                  (238, 172, 156))

    # ------------------------------------------------------------- tail
    # one plump tail sweeping out on the viewer's right, cream-tipped
    tail = cubic((628, 806), (852, 812), (902, 690), (852, 576), 30)
    tail_box = bounds(tail, 58)
    pic.shape(tail_box, lambda x, y: dst_path(x, y, tail) - 44, FUR_LO)
    pic.shape(tail_box, lambda x, y: dst_path(x, y, tail) - 36, FUR)
    for i in (13, 19):
        seg = [tail[i], tail[i + 1]]
        pic.shape(bounds(seg, 46),
                  lambda x, y, s=seg: dst_path(x, y, s) - 37, FUR_TABBY)
    tip = tail[-7:]
    pic.shape(bounds(tip, 50), lambda x, y: dst_path(x, y, tip) - 36, CREAM)
    # soften the seam where the cream tip meets the ginger
    glow_spot(pic, bounds(tip, 56), tail[-7][0], tail[-7][1], 44, 44,
              FUR, 0.38, 1.0)

    # ------------------------------------------------------------- body
    # a small plump body: the head is the star, the body just a base
    BODY = (512, 754, 208, 172)
    body_sdf = lambda x, y: dst_oval(x, y, *BODY)
    pic.shape((296, 574, 728, 934), body_sdf, FUR_LO)
    pic.shape((304, 582, 720, 926),
              lambda x, y: dst_oval(x, y, 512, 748, 198, 164), FUR)
    coat_shading(pic, (310, 588, 714, 920), body_sdf, *BODY)
    # cream bib with a fluffy scalloped top edge
    pic.shape((372, 640, 652, 916),
              lambda x, y: dst_oval(x, y, 512, 788, 132, 128), CREAM)
    for k in range(5):
        ang = math.radians(196 + 32 * k)
        scx = 512 + 128 * math.cos(ang)
        scy = 788 + 124 * math.sin(ang)
        pic.shape((int(scx - 30), int(scy - 30), int(scx + 30), int(scy + 30)),
                  lambda x, y, a=scx, b=scy: dst_disc(x, y, a, b, 27), CREAM)
    # a soft shadow pooled under the chin, grounding the big head
    glow_spot(pic, (330, 606, 694, 700), 512, 650, 168, 30,
              (219, 146, 92), 0.30, 1.25)
    # haunches flanking the base
    for hcx in (356, 668):
        pic.shape((hcx - 106, 716, hcx + 106, 912),
                  lambda x, y, c=hcx: dst_oval(x, y, c, 816, 98, 88), FUR_LO)
        pic.shape((hcx - 98, 724, hcx + 98, 904),
                  lambda x, y, c=hcx: dst_oval(x, y, c, 812, 90, 80), FUR)
    # little toe ticks curving over the front of each foot
    for hcx in (356, 668):
        for off in (-27, 3):
            pts = quad((hcx + off, 852), (hcx + off + 2, 868),
                       (hcx + off + 5, 882), 10)
            taper_stroke(pic.shape, pts, FUR_LO, 2.8)

    # ------------------------------------------------------- collar+bell
    # a shallow rose band hugging the neck under the chin, and a gold
    # bell hanging at its centre onto the chest
    collar_arc = arc(512, 468, 170, math.radians(60), math.radians(120), 30)
    pic.shape(bounds(collar_arc, 22),
              lambda x, y: dst_path(x, y, collar_arc) - 15, COLLAR)
    collar_hi = arc(512, 468, 170, math.radians(70), math.radians(110), 22)
    pic.shape(bounds(collar_hi, 16),
              lambda x, y: dst_path(x, y, collar_hi) - 5, COLLAR_HI)

    def bell_fn(x, y):
        d = dst_disc(x, y, 512, 656, 29)
        if d >= 0.8:
            return None
        t = clamp01((y - 630) / 54.0)
        col = blend(BELL_HI, BELL, t)
        dl = DIST(x - 501, y - 643) / 42.0
        if dl < 1.0:
            col = blend(col, (255, 248, 214), 0.55 * (1.0 - dl) ** 2)
        return (col, cover(d))
    pic.shade((476, 620, 548, 692), bell_fn)
    band = [(488, 663), (536, 663)]
    pic.shape(bounds(band, 8), lambda x, y: dst_path(x, y, band) - 3.2, BELL_LO)
    pic.shape((504, 648, 520, 664), lambda x, y: dst_disc(x, y, 512, 656, 5.2),
              BELL_LO)

    # --------------------------------------------------------- yarn ball
    # the favourite toy on the viewer's right, under the resting paw
    ycx, ycy, yr = 748, 866, 58
    ybox = (ycx - yr - 9, ycy - yr - 9, ycx + yr + 9, ycy + yr + 9)
    pic.shape(ybox, lambda x, y: dst_disc(x, y, ycx, ycy, yr), YARN_LO)
    pic.shape(ybox, lambda x, y: dst_disc(x, y, ycx, ycy, yr - 6), YARN)
    for pts in (
        arc(ycx, ycy, yr * 0.58, 3.3, 5.7),
        arc(ycx, ycy, yr * 0.78, 2.5, 4.5),
        arc(ycx, ycy, yr * 0.50, 0.3, 2.3),
        cubic((ycx - 44, ycy + 30), (ycx - 6, ycy + 50),
              (ycx + 26, ycy + 44), (ycx + 46, ycy + 12)),
    ):
        pic.shape(bounds(pts, 9), lambda x, y, p=pts: dst_path(x, y, p) - 5,
                  YARN_LO)
    hl = arc(ycx, ycy, yr * 0.85, 3.7, 4.7)
    pic.shape(bounds(hl, 7), lambda x, y, p=hl: dst_path(x, y, p) - 3.4,
              ROSE_SOFT)
    strand = cubic((790, 900), (838, 924), (876, 888), (898, 910), 20)
    strand += cubic((898, 910), (918, 926), (934, 900), (914, 884), 10)[1:]
    pic.shape(bounds(strand, 9), lambda x, y: dst_path(x, y, strand) - 5,
              YARN_LO)

    # resting paw over the yarn (viewer right)
    pcx, pcy = 660, 838
    pic.shape((pcx - 84, pcy - 50, pcx + 84, pcy + 50),
              lambda x, y: dst_oval(x, y, pcx, pcy, 76, 42), FUR_LO)
    pic.shape((pcx - 77, pcy - 43, pcx + 77, pcy + 43),
              lambda x, y: dst_oval(x, y, pcx, pcy, 69, 35), FUR)
    for (tx, ty, trx, tryy) in ((-30, -6, 11, 9), (0, -13, 12, 10),
                                (30, -6, 11, 9), (0, 15, 24, 16)):
        pic.shape((pcx + tx - trx - 3, pcy + ty - tryy - 3,
                   pcx + tx + trx + 3, pcy + ty + tryy + 3),
                  lambda x, y, a=pcx + tx, b=pcy + ty, c=trx, d=tryy:
                  dst_oval(x, y, a, b, c, d), ROSE_SOFT)

    # --------------------------------------------------------------- head
    # One big fluffy head, tipped five degrees for charm. Everything
    # on the face is drawn in head space and mapped through the tip.
    HX, HY = 512, 382
    TIP = math.radians(-5.0)
    CT, ST = math.cos(TIP), math.sin(TIP)

    def to_head(x, y):
        dx, dy = x - HX, y - HY
        return (HX + dx * CT + dy * ST, HY - dx * ST + dy * CT)

    def head_shape(hbox, sdf, rgb):
        x0, y0, x1, y1 = hbox
        pad = int(abs(ST) * (x1 - x0 + y1 - y0) / 2) + 7
        pic.shape((x0 - pad, y0 - pad, x1 + pad, y1 + pad),
                  lambda x, y: sdf(*to_head(x, y)), rgb)

    def head_shade(hbox, fn):
        x0, y0, x1, y1 = hbox
        pad = int(abs(ST) * (x1 - x0 + y1 - y0) / 2) + 7
        pic.shade((x0 - pad, y0 - pad, x1 + pad, y1 + pad),
                  lambda x, y: fn(*to_head(x, y)))

    # ears first, behind the head: broad triangles with a tuft spike,
    # a rose inner ear and cream fluff zig-zagging out of it
    for (ex, sgn) in ((338, -1), (686, 1)):
        tri = [(ex - 92, 268), (ex + sgn * 16, 96), (ex + 104, 256)]
        gx = sum(p[0] for p in tri) / 3.0
        gy = sum(p[1] for p in tri) / 3.0
        ebox = bounds(tri, 8)
        head_shape(ebox, lambda x, y, t=tri: dst_tri(x, y, *t[0], *t[1], *t[2]),
                   FUR_LO)
        head_shape(ebox, lambda x, y, t=scaled(tri, gx, gy, 0.87):
                   dst_tri(x, y, *t[0], *t[1], *t[2]), FUR)
        head_shape(ebox, lambda x, y, t=scaled(tri, gx, gy, 0.58):
                   dst_tri(x, y, *t[0], *t[1], *t[2]), ROSE_SOFT)
        head_shape(ebox, lambda x, y, t=scaled(tri, gx, gy, 0.40):
                   dst_tri(x, y, *t[0], *t[1], *t[2]), (253, 210, 224))
        for k in range(3):
            fx = gx - 26 + 26 * k
            spike = [(fx - 11, gy + 52), (fx + 4, gy + 16), (fx + 15, gy + 52)]
            head_shape(bounds(spike, 4),
                       lambda x, y, t=spike: dst_tri(x, y, *t[0], *t[1], *t[2]),
                       CREAM)
        tip_tri = [(tri[1][0] - 7, tri[1][1] + 16), (tri[1][0] + sgn * 3,
                    tri[1][1] - 16), (tri[1][0] + 13, tri[1][1] + 14)]
        head_shape(bounds(tip_tri, 4),
                   lambda x, y, t=tip_tri: dst_tri(x, y, *t[0], *t[1], *t[2]),
                   FUR)

    # the head silhouette: a big oval plus fluff bumps on the cheeks
    # and forehead, so the outline reads plush instead of machined
    FLUFF = ((282, 500, 44), (742, 500, 44), (302, 566, 34), (722, 566, 34),
             (440, 158, 41), (512, 146, 47), (584, 158, 41))

    def head_sdf(x, y):
        d = dst_oval(x, y, HX, HY, 268, 238)
        for (fx, fy, fr) in FLUFF:
            di = dst_disc(x, y, fx, fy, fr)
            if di < d:
                d = di
        return d
    head_box = (228, 84, 796, 640)
    head_shape(head_box, lambda x, y: head_sdf(x, y) + 7, FUR_LO)
    head_shape(head_box, head_sdf, FUR)
    # plush shading in head space, one pass: a warm light blooming
    # from the upper left, else a soft rim following the fluff edge
    def head_plush(x, y):
        d = head_sdf(x, y)
        if d >= 0.8:
            return None
        dl = DIST(x - (HX - 102), y - (HY - 110)) / 348.0
        la = 0.32 * max(0.0, 1.0 - dl) ** 2
        if la > 0.004:
            return (FUR_HI, la)
        if d >= -52.0:
            ra = 0.15 * smooth(-52.0, 0.0, d)
            if ra > 0.004:
                return (FUR_TABBY, ra)
        return None
    head_shade(head_box, head_plush)

    # tabby stripes: five across the forehead, two soft on each cheek
    for pts in (
        [(452, 168), (447, 214), (452, 252)],
        [(512, 158), (512, 208), (512, 248)],
        [(572, 168), (577, 214), (572, 252)],
        [(402, 188), (393, 224), (400, 250)],
        [(622, 188), (631, 224), (624, 250)],
    ):
        head_shape(bounds(pts, 15),
                   lambda x, y, p=pts: dst_path(x, y, p) - 10, FUR_TABBY)

    # muzzle: a small cream patch, low and centred
    head_shape((372, 446, 652, 616),
               lambda x, y: dst_oval(x, y, HX, 528, 134, 80), MUZZLE)

    # --------------------------------------------------------------- eyes
    # Enormous jewel eyes, low on the face. Iris: deep teal melting
    # down into mint, a dark limbal ring for depth, an eyelid shadow
    # across the top, triple sparkles and a tiny star.
    for ecx in (390, 634):
        ebox = (ecx - 86, 322, ecx + 86, 540)
        head_shape(ebox, lambda x, y, c=ecx: dst_oval(x, y, c, 430, 76, 96),
                   WHITE)

        def iris_fn(x, y, c=ecx):
            d = dst_oval(x, y, c, 434, 66, 86)
            if d >= 0.8:
                return None
            t = clamp01((y - 348) / 172.0)
            if t < 0.5:
                col = blend(IRIS_TOP, IRIS_MID, t * 2.0)
            else:
                col = blend(IRIS_MID, IRIS_LOW, (t - 0.5) * 2.0)
            # dark limbal ring hugging the iris edge
            ring = smooth(-13.0, -2.0, d)
            col = blend(col, IRIS_RIM, 0.65 * ring)
            # crescent of light pooled at the bottom of the iris
            dl = DIST(x - c, y - 492) / 60.0
            if dl < 1.0:
                col = blend(col, WHITE, 0.21 * (1.0 - dl) ** 2)
            return (col, cover(d))
        head_shade(ebox, iris_fn)

        def lid_fn(x, y, c=ecx):
            d = dst_oval(x, y, c, 434, 66, 86)
            if d >= 0.0:
                return None
            a = 0.20 * smooth(420.0, 356.0, y)
            return (IRIS_RIM, a) if a > 0.004 else None
        head_shade(ebox, lid_fn)
        # pupil, tall and soft-edged
        head_shape(ebox, lambda x, y, c=ecx: dst_oval(x, y, c, 440, 29, 53),
                   PUPIL)
        # sparkles: one big, one medium, one tiny, and a small star
        head_shape(ebox, lambda x, y, c=ecx: dst_disc(x, y, c - 21, 398, 22),
                   WHITE)
        head_shape(ebox, lambda x, y, c=ecx: dst_disc(x, y, c + 18, 468, 11),
                   WHITE)
        head_shape(ebox, lambda x, y, c=ecx: dst_disc(x, y, c + 25, 388, 5.5),
                   WHITE)
        star = sparkle_pts(ecx - 24, 470, 10)
        head_shape(bounds(star, 3),
                   lambda x, y, p=star: dst_path(x, y, p + [p[0]]) - 1.4,
                   WHITE)
        # glossy lash line with a little wing at the outer corner
        sgn = -1 if ecx < HX else 1
        lash = arc(ecx, 428, 74, math.radians(192), math.radians(348), 20)
        lash = [(lx, 428 + (ly - 428) * 1.30) for (lx, ly) in lash]
        wing = [(ecx + sgn * 72, 372), (ecx + sgn * 88, 360)]
        head_shape(bounds(lash, 11),
                   lambda x, y, p=lash: dst_path(x, y, p) - 6.4, LINE)
        head_shape(bounds(wing, 9),
                   lambda x, y, p=wing: dst_path(x, y, p) - 5.0, LINE)

    # ------------------------------------------------------ nose + mouth
    # a small heart-ish nose with a shine dot
    nose = [(486, 494), (538, 494), (512, 526)]
    head_shape(bounds(nose, 7), lambda x, y: dst_tri(x, y, *nose[0], *nose[1],
                                                     *nose[2]), NOSE)
    head_shape((488, 490, 514, 514), lambda x, y: dst_disc(x, y, 499, 502, 6.5),
               (255, 208, 220))
    # philtrum down to an open, happy little mouth with one fang
    stem = [(512, 524), (512, 538)]
    head_shape(bounds(stem, 7), lambda x, y: dst_path(x, y, stem) - 4.4, LINE)
    head_shape((478, 530, 546, 590),
               lambda x, y: dst_oval(x, y, 512, 558, 27, 22), MOUTH_IN)
    head_shape((486, 550, 538, 586),
               lambda x, y: dst_oval(x, y, 512, 570, 19, 13), TONGUE)
    fang = [(488, 542), (506, 542), (496, 562)]
    head_shape(bounds(fang, 4), lambda x, y: dst_tri(x, y, *fang[0], *fang[1],
                                                     *fang[2]), WHITE)
    fang2 = [(520, 542), (534, 542), (528, 556)]
    head_shape(bounds(fang2, 4), lambda x, y: dst_tri(x, y, *fang2[0],
                                                      *fang2[1], *fang2[2]),
               WHITE)

    # -------------------------------------------------------------- blush
    # big soft blush low on both cheeks, with tiny anime cheek marks
    for bcx in (322, 702):
        def blush_fn(x, y, c=bcx):
            u = ((x - c) / 56.0) ** 2 + ((y - 522) / 30.0) ** 2
            if u >= 1.0:
                return None
            return (BLUSH, 0.54 * (1.0 - u) ** 1.5)
        head_shade((bcx - 74, 480, bcx + 74, 564), blush_fn)
        for k in range(3):
            mx = bcx - 18 + 18 * k
            mark = [(mx - 7, 540 + (k % 2) * 5), (mx + 7, 532 + (k % 2) * 5)]
            head_shape(bounds(mark, 6),
                       lambda x, y, p=mark: dst_path(x, y, p) - 2.4,
                       (252, 178, 186))

    # ----------------------------------------------------------- whiskers
    # three a side, fine and long, fanning low from the muzzle
    for sgn in (-1, 1):
        for (wy, drop) in ((492, -2), (519, 15), (546, 34)):
            pts = quad((HX + sgn * 104, wy), (HX + sgn * 204, wy + drop * 0.3),
                       (HX + sgn * 298, wy + drop), 22)
            taper_stroke(head_shape, pts, WHISK, 2.6)
    # tiny whisker pores dotted on the muzzle
    for sgn in (-1, 1):
        for (dx, dy) in ((64, 506), (82, 518), (66, 528)):
            head_shape((HX + sgn * dx - 5, dy - 5, HX + sgn * dx + 5, dy + 5),
                       lambda x, y, a=HX + sgn * dx, b=dy:
                       dst_disc(x, y, a, b, 2.3), (196, 138, 92))

    # -------------------------------------------------------- raised paw
    # the waving paw, drawn over the cheek fluff on the viewer's
    # left: a plump arm rising from the body, beans to the viewer
    arm = cubic((348, 722), (302, 650), (250, 582), (238, 540), 22)
    pic.shape(bounds(arm, 52), lambda x, y: dst_path(x, y, arm) - 40, FUR_LO)
    pic.shape(bounds(arm, 52), lambda x, y: dst_path(x, y, arm) - 33, FUR)
    # a soft light running along the arm's upper edge, plush-style
    arm_hl = cubic((340, 718), (292, 646), (242, 578), (230, 540), 22)

    def arm_light(x, y):
        d = dst_path(x, y, arm_hl)
        if d >= 16.0:
            return None
        a = 0.30 * (1.0 - d / 16.0) ** 1.5
        return (FUR_HI, a) if a > 0.004 else None
    pic.shade(bounds(arm_hl, 20), arm_light)
    PAW = (232, 478)
    paw_rot = -0.25
    ca, sa = math.cos(paw_rot), math.sin(paw_rot)

    def paw_local(x, y):
        dx, dy = x - PAW[0], y - PAW[1]
        return (PAW[0] + dx * ca + dy * sa, PAW[1] - dx * sa + dy * ca)

    def paw_sdf(x, y):
        lx, ly = paw_local(x, y)
        return dst_oval(lx, ly, PAW[0], PAW[1], 47, 57)
    paw_box = (PAW[0] - 80, PAW[1] - 86, PAW[0] + 80, PAW[1] + 86)
    pic.shape(paw_box, lambda x, y: paw_sdf(x, y) + 6, FUR_LO)
    pic.shape(paw_box, paw_sdf, FUR)
    glow_spot(pic, paw_box, PAW[0] - 12, PAW[1] - 18, 40, 48, FUR_HI, 0.30)
    # beans: three toes in an arc over one big heel pad
    for (tx, ty, tr) in ((-24, -22, 10.5), (0, -30, 11.5), (24, -22, 10.5),
                         (0, 13, 21)):
        def bean_sdf(x, y, a=tx, b=ty, r=tr):
            lx, ly = paw_local(x, y)
            return dst_oval(lx, ly, PAW[0] + a, PAW[1] + b, r, r * 0.86)
        pic.shape(paw_box, bean_sdf, ROSE_SOFT)
    # little toe separation ticks above the beans
    for sgn2 in (-1, 1):
        def tick_sdf(x, y, s2=sgn2):
            lx, ly = paw_local(x, y)
            return dst_seg(lx, ly, PAW[0] + s2 * 13, PAW[1] - 44,
                           PAW[0] + s2 * 15, PAW[1] - 34) - 2.0
        pic.shape(paw_box, tick_sdf, FUR_LO)

    # ---------------------------------------------------------------- bow
    # a two-layer bow with ribbon tails, perched by the right ear
    bx, by = 700, 138
    BA = 0.32
    BC, BS = math.cos(BA), math.sin(BA)

    def bow_shape(bbox, sdf, rgb):
        def wrapped(x, y):
            dx, dy = x - bx, y - by
            return sdf(bx + dx * BC + dy * BS, by - dx * BS + dy * BC)
        pic.shape(bbox, wrapped, rgb)
    bow_box = (bx - 150, by - 120, bx + 150, by + 150)
    # tails first, hanging below the loops: filled ribbon strips
    for sgn in (-1, 1):
        t1 = [(bx + sgn * 6, by + 12), (bx + sgn * 58, by + 28),
              (bx + sgn * 46, by + 92)]
        t2 = [(bx + sgn * 6, by + 12), (bx + sgn * 46, by + 92),
              (bx + sgn * 10, by + 76)]
        for t in (t1, t2):
            bow_shape(bow_box, lambda x, y, tt=t:
                      dst_tri(x, y, *tt[0], *tt[1], *tt[2]), BOW_LO)
        for t in (t1, t2):
            bow_shape(bow_box, lambda x, y, tt=scaled(t, bx, by + 14, 0.78):
                      dst_tri(x, y, *tt[0], *tt[1], *tt[2]), BOW)
    # rounded plump loops: tilted ovals instead of stiff triangles
    def loop_sdf(x, y, s, grow=0.0):
        cx, cy = bx + s * 55, by - 2
        dx, dy = x - cx, y - cy
        ca2 = math.cos(s * 0.38)
        sa2 = math.sin(s * 0.38)
        lx = cx + dx * ca2 + dy * sa2
        ly = cy - dx * sa2 + dy * ca2
        return dst_oval(lx, ly, cx, cy, 52 + grow, 33 + grow)

    for sgn in (-1, 1):
        bow_shape(bow_box, lambda x, y, s=sgn: loop_sdf(x, y, s), BOW_LO)
        bow_shape(bow_box, lambda x, y, s=sgn: loop_sdf(x, y, s) + 5, BOW)
        # a soft sheen pooling on the loop's upper face
        bow_shape(bow_box, lambda x, y, s=sgn:
                  dst_oval(x, y, bx + s * 57, by - 13, 27, 13), BOW_HI)
        # a fold shadow pinching the loop where it meets the knot
        bow_shape(bow_box, lambda x, y, s=sgn:
                  dst_oval(x, y, bx + s * 26, by + 8, 15, 22), BOW_LO)
    bow_shape(bow_box, lambda x, y: dst_disc(x, y, bx, by, 25), BOW_LO)
    bow_shape(bow_box, lambda x, y: dst_disc(x, y, bx, by, 19), BOW)
    bow_shape(bow_box, lambda x, y: dst_disc(x, y, bx - 6, by - 6, 6.5),
              ROSE_SOFT)

    # ------------------------------------------------------ floating hearts
    def heart(cx, cy, s, rgb, alpha):
        def fn(x, y):
            lx = (x - cx) / s
            ly = (cy - y) / s
            v = (lx * lx + ly * ly - 1) ** 3 - lx * lx * ly ** 3
            return (rgb, alpha) if v < 0 else None
        pad = int(s * 1.5)
        pic.shade((cx - pad, cy - pad, cx + pad, cy + pad), fn)
    heart(158, 262, 28, ROSE, 0.78)
    heart(132, 448, 10, ROSE, 0.55)
    heart(880, 452, 20, ROSE, 0.62)
    heart(866, 190, 14, ROSE, 0.52)
    heart(104, 402, 13, ROSE, 0.5)

    return pic


# --------------------------------------------------------------------- PNG

def encode_png(pic):
    s = pic.size
    stride = s * 3
    raw = bytearray()
    for y in range(s):
        raw.append(0)
        raw += pic.buf[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", s, s, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    out += chunk(b"IEND", b"")
    return bytes(out)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    data = encode_png(draw())
    with open(os.path.join(out_dir, "entry.png"), "wb") as fh:
        fh.write(data)


if __name__ == "__main__":
    main()
