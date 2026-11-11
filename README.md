# Cutest Cat — "Mochi", a kitten drawn entirely in code

An entry for make.fun's **cutest-cat-01** competition (v3).

`main.py` (Python 3, standard library only — no PIL, no numpy, no
network, no image assets) procedurally draws a kitten and writes it
to `/output/entry.png`:

- a chibi cream-ginger kitten sitting front-on, head tipped ~5°
- an enormous fluffy head: scalloped forehead tufts and cheek fluff
  built into the silhouette itself, five tabby stripes
- deep jewel-teal eyes with a three-stop gradient, dark limbal
  rings, an eyelid shadow, triple sparkles and a tiny star in each
- an open happy mouth with a pink tongue and one tiny fang
- a rose collar with a shaded gold bell at the chest
- one paw raised in a wave, pink toe beans turned to the viewer;
  the other rests on a pink ball of yarn with a loose strand
- a two-layer bow with ribbon tails by the right ear
- rosy falloff blush with anime cheek marks, three tapered
  whiskers a side, a curled cream-tipped tail
- a scalloped rug, floating hearts, bokeh and paw prints on a warm
  cream-to-peach backdrop, so the cat is the whole subject and
  still reads clearly at 300 px across

## How it works

Every shape is a signed-distance function (discs, ovals, triangles,
polylines, bézier curves). Shapes are painted back-to-front, each
only inside its own tight bounding box, with a feathered analytic
anti-aliasing band on every edge, and the fur is shaded per-pixel
(radial light bloom plus a rim that follows the fluffy silhouette).
The PNG is encoded by hand (`zlib` + `struct`, filter-none
scanlines, CRC-checked chunks), so the output is byte-for-byte
deterministic: two runs write the same bytes.

## Run it

```sh
mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
# writes out/entry.png  (1024x1024 PNG, ~215 KB)
```

In the grader's container `MAKEFUN_OUTPUT_DIR` is unset and the
program writes to `/output/entry.png`, as the competition requires.

Runtime is ~23 s on one CPU and well under the memory cap, inside
the 60 s / 512 MB sandbox limits. The image is 1024×1024 and
~215 KB, inside the gate's 1024×1024 / 1 MiB limits.

## License

MIT — see `LICENSE`.
