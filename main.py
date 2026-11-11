#!/usr/bin/env python3
"""make.fun cutest-cat-01 entry, v2: the cutest cat we can draw, in code.

Pure Python 3 standard library (no PIL, no numpy, no network).
A soft storybook ginger kitten -- enormous sparkling eyes, a tilted
head with fluffy cheeks, rosy falloff blush, tapered whiskers, toe
beans, a pink bow and one paw resting on its ball of yarn -- built
from signed-distance shapes with analytic anti-aliasing and gentle
radial shading, then written as a deterministic PNG to
/output/entry.png (or $MAKEFUN_OUTPUT_DIR/entry.png locally).

Every shape paints only inside its own tight bounding box, which
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

    def fill_fn(self, fn):
        """Paint every pixel from fn(x, y) -> (color, alpha)."""
        px, w, h = self.px, self.w, self.h
        for y in range(h):
            base = y * w * 3
            for x in range(w):
                color, a = fn(x, y)
                if a >= 1.0:
                    i = base + x * 3
                    px[i] = color[0]
                    px[i + 1] = color[1]
                    px[i + 2] = color[2]
                elif a > 0.0:
                    i = base + x * 3
                    ia = 1.0 - a
                    px[i] = int(color[0] * a + px[i] * ia + 0.5)
                    px[i + 1] = int(color[1] * a + px[i + 1] * ia + 0.5)
                    px[i + 2] = int(color[2] * a + px[i + 2] * ia + 0.5)

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


def sstep(a, b, v):
    """Smoothstep between a and b."""
    t = clamp((v - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def mix(c1, c2, t):
    return (int(c1[0] + (c2[0] - c1[0]) * t + 0.5),
            int(c1[1] + (c2[1] - c1[1]) * t + 0.5),
            int(c1[2] + (c2[2] - c1[2]) * t + 0.5))


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


def quad_pts(p0, p1, p2, n=20):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return pts


def bbox_of(pts, pad):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (int(min(xs) - pad), int(min(ys) - pad),
            int(max(xs) + pad), int(max(ys) + pad))


def shrink(pts, cx, cy, f):
    return [(cx + (x - cx) * f, cy + (y - cy) * f) for (x, y) in pts]


def star_pts(cx, cy, r):
    """A soft four-point sparkle outline."""
    pts = []
    for i in range(8):
        ang = math.pi * i / 4
        rad = r if i % 2 == 0 else r * 0.30
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return pts


# ---------------------------------------------------------------- palette

BG_TOP = (255, 243, 231)
BG_BOT = (255, 205, 186)
GLOW = (255, 253, 246)
FUR = (247, 170, 94)           # warm ginger
FUR_LIGHT = (253, 201, 134)    # sunlit fur for highlights
FUR_DARK = (231, 141, 65)      # soft rim of the fur shapes
FUR_DEEP = (201, 113, 43)      # tabby stripes
BELLY = (255, 242, 222)
MUZZLE = (255, 247, 235)
PINK = (244, 114, 152)
PINK_SOFT = (252, 183, 203)
NOSE = (240, 98, 128)
BLUSH = (251, 148, 156)
LINE = (110, 70, 44)           # mouth line
WHISKER = (133, 94, 62)
IRIS_LT = (150, 236, 210)
IRIS_MID = (66, 199, 168)
IRIS_DEEP = (24, 132, 116)
EYE_DARK = (24, 22, 26)
WHITE = (255, 255, 255)
YARN = (240, 110, 150)
YARN_DARK = (203, 70, 114)
BOW = (238, 82, 128)
BOW_DARK = (203, 52, 100)
GRASS = (146, 201, 138)
GRASS_DARK = (116, 182, 116)


# ------------------------------------------------------------ soft helpers

def soft_ellipse(cv, bbox, cx, cy, rx, ry, color, max_alpha, grow=1.2):
    """An ellipse filled with a radial falloff: full alpha at the
    centre, fading to nothing at a slightly grown ellipse boundary,
    so it can never clip against its own bounding box."""
    grx, gry = rx * grow, ry * grow

    def fn(x, y):
        u = ((x - cx) / grx) ** 2 + ((y - cy) / gry) ** 2
        if u >= 1.0:
            return None
        return (color, max_alpha * (1.0 - u) ** 1.5)
    cv.paint_fn(bbox, fn)


def fur_shade(cv, bbox, cx, cy, rx, ry, paint_fn):
    """Gentle radial shading over a fur ellipse: a sunlit blush toward
    the upper left and a soft deep rim, so flat shapes feel plush.
    paint_fn is cv.paint_fn or a head-space wrapper with same signature."""
    def highlight(x, y):
        d = d_ellipse(x, y, cx, cy, rx, ry)
        if d >= 0.75:
            return None
        lx, ly = cx - rx * 0.40, cy - ry * 0.44
        dl = HYPOT(x - lx, y - ly) / (rx * 1.25)
        a = 0.34 * max(0.0, 1.0 - dl) ** 2
        return (FUR_LIGHT, a) if a > 0.004 else None

    def rim(x, y):
        d = d_ellipse(x, y, cx, cy, rx, ry)
        if d >= 0.75:
            return None
        u = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
        a = 0.15 * sstep(0.52, 1.0, u)
        return (FUR_DEEP, a) if a > 0.004 else None

    paint_fn(bbox, highlight)
    paint_fn(bbox, rim)


def tapered_line(paint, pts, color, r0=3.4):
    """Paint a polyline in three chunks with shrinking radius, so the
    stroke tapers like a real whisker. paint(bbox, dist_fn, color)."""
    n = len(pts)
    cuts = ((0, n // 3 + 1, r0), (n // 3, 2 * n // 3 + 1, r0 * 0.72),
            (2 * n // 3, n, r0 * 0.48))
    for (i0, i1, r) in cuts:
        seg = pts[i0:i1]
        if len(seg) < 2:
            continue
        paint(bbox_of(seg, int(r) + 3),
              lambda x, y, s=seg, rr=r: d_polyline(x, y, s) - rr, color)


# ---------------------------------------------------------------- drawing

def draw():
    cv = Canvas(W, H)

    # ------------------------------------------------------ background
    # warm gradient plus a soft radial glow behind the kitten
    def bg_fn(x, y):
        base = mix(BG_TOP, BG_BOT, y / (H - 1))
        dl = HYPOT(x - 512, y - 420) / 600.0
        g = max(0.0, 1.0 - dl) ** 2
        if g > 0.003:
            base = mix(base, GLOW, 0.5 * g)
        return (base, 1.0)
    cv.fill_fn(bg_fn)

    # tiny sparkles and dots floating in the corners, kept subtle
    for (sx, sy, sr, col, al) in (
        (146, 128, 15, WHITE, 0.85), (884, 116, 12, WHITE, 0.8),
        (922, 470, 10, PINK_SOFT, 0.7), (104, 452, 9, PINK_SOFT, 0.65),
    ):
        pts = star_pts(sx, sy, sr)
        cv.paint(bbox_of(pts, 3),
                 lambda x, y, p=pts: d_polyline(x, y, p + [p[0]]) - 1.0, col)
    for (dx, dy, dr, col) in ((196, 196, 6, PINK_SOFT), (838, 208, 5, WHITE),
                              (120, 560, 5, WHITE), (916, 588, 6, PINK_SOFT)):
        cv.paint((dx - dr - 2, dy - dr - 2, dx + dr + 2, dy + dr + 2),
                 lambda x, y, a=dx, b=dy, r=dr: d_circle(x, y, a, b, r), col)

    # ---------------------------------------------------- ground + rug
    # one soft shadow and one soft mat, both radial-falloff ellipses
    # whose bounding boxes fully contain the faded grown boundary
    soft_ellipse(cv, (70, 796, 954, 936), 512, 866, 342, 46,
                 (226, 158, 124), 0.5, 1.25)
    soft_ellipse(cv, (130, 806, 894, 930), 512, 868, 316, 40,
                 (250, 206, 176), 0.7, 1.15)

    # small grass tufts in the bottom corners
    for gx in (64, 96, 130, 880, 916, 950):
        sway = 10 if gx % 3 == 0 else -6
        blade = [(gx - 11, 1016), (gx + sway, 950 + (gx % 5) * 4), (gx + 11, 1016)]
        cv.paint(bbox_of(blade, 3),
                 lambda x, y, t=blade: d_triangle(x, y, *t[0], *t[1], *t[2]),
                 GRASS if gx % 2 == 0 else GRASS_DARK)

    # ---------------------------------------------------------- tail
    # One tail curls from behind the body around the cat's right side
    # (viewer's right) and lifts at the end with a cream tip.
    tail_path = bezier_pts((640, 800), (836, 802), (884, 690), (838, 592), 30)
    tail_bb = bbox_of(tail_path, 52)
    cv.paint(tail_bb, lambda x, y: d_polyline(x, y, tail_path) - 40, FUR_DARK)
    cv.paint(tail_bb, lambda x, y: d_polyline(x, y, tail_path) - 33, FUR)
    for i in (14, 20):
        a_pt = tail_path[i]
        b_pt = tail_path[i + 1]
        seg = [a_pt, ((a_pt[0] + b_pt[0]) / 2, (a_pt[1] + b_pt[1]) / 2)]
        cv.paint(bbox_of(seg, 44), lambda x, y, s=seg: d_polyline(x, y, s) - 34, FUR_DEEP)
    tip_path = tail_path[-7:]
    cv.paint(bbox_of(tip_path, 45), lambda x, y: d_polyline(x, y, tip_path) - 33, BELLY)

    # --------------------------------------------------------------- body
    BODY = (512, 722, 240, 196)
    cv.paint((264, 516, 760, 910), lambda x, y: d_ellipse(x, y, *BODY), FUR_DARK)
    cv.paint((272, 524, 752, 902), lambda x, y: d_ellipse(x, y, 512, 716, 230, 188), FUR)
    fur_shade(cv, (280, 530, 744, 896), 512, 716, 230, 188, cv.paint_fn)
    # belly patch with a scalloped fluffy top edge
    cv.paint((356, 610, 668, 890), lambda x, y: d_ellipse(x, y, 512, 756, 148, 138), BELLY)
    for k in range(5):
        ang = math.radians(180 + 36 * k + 18)
        scx = 512 + 148 * math.cos(ang) * 0.96
        scy = 756 + 138 * math.sin(ang) * 0.96
        cv.paint((int(scx - 34), int(scy - 34), int(scx + 34), int(scy + 34)),
                 lambda x, y, a=scx, b=scy: d_circle(x, y, a, b, 30), BELLY)
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
    hl = arc_pts(ycx, ycy, yr * 0.86, 3.6, 4.6)
    cv.paint(bbox_of(hl, 7), lambda x, y, p=hl: d_polyline(x, y, p) - 3.5, PINK_SOFT)
    # loose strand curling away on the ground
    strand = bezier_pts((782, 898), (830, 920), (868, 888), (892, 908), 20)
    strand += bezier_pts((892, 908), (912, 922), (926, 900), (910, 884), 10)[1:]
    cv.paint(bbox_of(strand, 9), lambda x, y: d_polyline(x, y, strand) - 5, YARN_DARK)

    # ---------------------------------------------------------- front paws
    # two clumsy oversized front paws with pink toe beans; the right
    # one rests on the yarn ball
    for (pcx, pcy, prx, pry) in ((406, 860, 74, 40), (644, 832, 76, 42)):
        pbb = (pcx - prx - 8, pcy - pry - 8, pcx + prx + 8, pcy + pry + 8)
        cv.paint(pbb, lambda x, y, a=pcx, b=pcy, c=prx, d=pry:
                 d_ellipse(x, y, a, b, c, d), FUR_DARK)
        cv.paint(pbb, lambda x, y, a=pcx, b=pcy, c=prx - 7, d=pry - 7:
                 d_ellipse(x, y, a, b, c, d), FUR)
        # toe beans: three small pads in an arc over one big pad
        for (tx, ty, trx, try_) in ((-30, -8, 11, 9), (0, -15, 12, 10),
                                   (30, -8, 11, 9), (0, 14, 24, 16)):
            cv.paint((pcx + tx - trx - 3, pcy + ty - try_ - 3,
                      pcx + tx + trx + 3, pcy + ty + try_ + 3),
                     lambda x, y, a=pcx + tx, b=pcy + ty, c=trx, d=try_:
                     d_ellipse(x, y, a, b, c, d), PINK_SOFT)

    # --------------------------------------------------------------- head
    # Head group tilted ~7 degrees for charm: shapes are evaluated in
    # head space; each carries its own tight head-space bbox, widened
    # a little to cover the rotation.
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
            out = fn(HX + dx * CT + dy * ST, HY - dx * ST + dy * CT)
            return out
        cv.paint_fn((x0 - pad, y0 - pad, x1 + pad, y1 + pad), wrapped)

    # ears: rounded triangles, fur inset, layered pink inner ear,
    # and a little cream tuft at the base of each inner ear
    for (ex, sgn) in ((356, -1), (668, 1)):
        tri = [(ex - 96, 274), (ex + sgn * 30, 120), (ex + 96, 274)]
        gx = sum(p[0] for p in tri) / 3
        gy = sum(p[1] for p in tri) / 3
        fur_tri = shrink(tri, gx, gy, 0.86)
        in_tri = shrink(tri, gx, gy, 0.54)
        in2_tri = shrink(tri, gx, gy, 0.34)
        ebb = bbox_of(tri, 6)
        head_paint(ebb, lambda x, y, t=tri: d_triangle(x, y, *t[0], *t[1], *t[2]), FUR_DARK)
        head_paint(ebb, lambda x, y, t=fur_tri: d_triangle(x, y, *t[0], *t[1], *t[2]), FUR)
        head_paint(ebb, lambda x, y, t=in_tri: d_triangle(x, y, *t[0], *t[1], *t[2]), PINK_SOFT)
        head_paint(ebb, lambda x, y, t=in2_tri: d_triangle(x, y, *t[0], *t[1], *t[2]), (253, 208, 222))
        tuft = [(gx - 20, gy + 44), (gx + 2, gy + 12), (gx + 22, gy + 44)]
        head_paint(bbox_of(tuft, 4),
                   lambda x, y, t=tuft: d_triangle(x, y, *t[0], *t[1], *t[2]), BELLY)

    # gentle cheek scallops: small bumps sitting right on the head
    # disc's edge, so the silhouette reads fluffy without sticking out
    for fy in (486, 542):
        dx = 242 * math.sqrt(max(0.0, 1.0 - ((fy - HY) / 218.0) ** 2))
        for fx in (HX - dx + 8, HX + dx - 8):
            fbb = (int(fx - 26), fy - 26, int(fx + 26), fy + 26)
            head_paint(fbb, lambda x, y, a=fx, b=fy: d_circle(x, y, a, b, 20), FUR_DARK)
            head_paint(fbb, lambda x, y, a=fx, b=fy: d_circle(x, y, a, b, 14), FUR)

    # head disc: big and round (kitten proportions), softly shaded
    head_paint((262, 176, 762, 628), lambda x, y: d_ellipse(x, y, HX, HY, 252, 228), FUR_DARK)
    head_paint((270, 184, 754, 620), lambda x, y: d_ellipse(x, y, HX, HY, 242, 218), FUR)
    fur_shade(cv, (278, 192, 746, 612), HX, HY, 242, 218, head_fn)

    # tabby stripes on the forehead: three long, two short at the sides
    for pts in (
        [(452, 192), (448, 238), (452, 274)],
        [(512, 182), (512, 230), (512, 268)],
        [(572, 192), (576, 238), (572, 274)],
        [(404, 210), (396, 244), (402, 268)],
        [(620, 210), (628, 244), (622, 268)],
    ):
        head_paint(bbox_of(pts, 14), lambda x, y, p=pts: d_polyline(x, y, p) - 10, FUR_DEEP)

    # muzzle patch
    head_paint((356, 424, 668, 620), lambda x, y: d_ellipse(x, y, HX, 522, 148, 92), MUZZLE)

    # ------------------------------------------------------------- eyes
    # Enormous sparkling eyes, set low on the face (kitten proportions).
    for ecx in (398, 626):
        ebb = (ecx - 82, 330, ecx + 82, 530)
        head_paint(ebb, lambda x, y, c=ecx: d_ellipse(x, y, c, 430, 70, 88), WHITE)

        def iris_fn(x, y, c=ecx):
            d = d_ellipse(x, y, c, 434, 60, 78)
            if d >= 0.75:
                return None
            t = clamp((y - 356) / 156.0, 0.0, 1.0)
            if t < 0.5:
                col = mix(IRIS_LT, IRIS_MID, t * 2.0)
            else:
                col = mix(IRIS_MID, IRIS_DEEP, (t - 0.5) * 2.0)
            return (col, cov(d))
        head_fn(ebb, iris_fn)
        # a soft glow crescent low in the iris, under the pupil
        def glow_fn(x, y, c=ecx):
            d = d_ellipse(x, y, c, 486, 34, 13)
            if d >= 0.75:
                return None
            if d_ellipse(x, y, c, 434, 60, 78) >= 0.0:
                return None
            return (WHITE, 0.20 * cov(d))
        head_fn(ebb, glow_fn)
        # pupil
        head_paint(ebb, lambda x, y, c=ecx: d_ellipse(x, y, c, 438, 28, 50), EYE_DARK)
        # sparkles: one big, one small, one tiny
        head_paint(ebb, lambda x, y, c=ecx: d_circle(x, y, c - 19, 402, 21), WHITE)
        head_paint(ebb, lambda x, y, c=ecx: d_circle(x, y, c + 17, 464, 10), WHITE)
        head_paint(ebb, lambda x, y, c=ecx: d_circle(x, y, c + 23, 390, 5), WHITE)
        # soft dark lash arc over the eye
        lash = arc_pts(ecx, 430, 70, math.radians(195), math.radians(345), 18)
        lash = [(lx, 430 + (ly - 430) * 1.26) for (lx, ly) in lash]
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
    # tiny tongue peeking out under the smile, with a soft rim
    head_paint((486, 550, 538, 594), lambda x, y: d_ellipse(x, y, 512, 573, 22, 17), (222, 90, 130))
    head_paint((488, 552, 536, 592), lambda x, y: d_ellipse(x, y, 512, 572, 19, 14), PINK)
    tline = [(512, 564), (512, 580)]
    head_paint(bbox_of(tline, 5), lambda x, y: d_polyline(x, y, tline) - 2.2, (222, 90, 130))

    # ------------------------------------------------------------- blush
    # soft rosy blush: a radial falloff spot low on each cheek,
    # kept clear of the eyes and the whisker roots
    for bcx in (352, 672):
        def blush_fn(x, y, c=bcx):
            u = ((x - c) / 40.0) ** 2 + ((y - 516) / 23.0) ** 2
            if u >= 1.0:
                return None
            return (BLUSH, 0.45 * (1.0 - u) ** 1.5)
        head_fn((bcx - 58, 480, bcx + 58, 552), blush_fn)

    # ---------------------------------------------------------- whiskers
    # three per side, gently curved and tapered, fanning from the muzzle
    for sgn in (-1, 1):
        for (wy, drop) in ((494, -4), (520, 12), (546, 30)):
            pts = quad_pts((HX + sgn * 98, wy), (HX + sgn * 196, wy + drop * 0.3),
                           (HX + sgn * 292, wy + drop), 20)
            tapered_line(head_paint, pts, WHISKER, 3.2)

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

    # ------------------------------------------- tiny floating hearts
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
    heart(852, 236, 13, PINK, 0.5)

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
