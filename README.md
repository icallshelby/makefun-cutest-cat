# Cutest Cat — a kitten drawn entirely in code

An entry for make.fun's **cutest-cat-01** competition.

`main.py` (Python 3, standard library only — no PIL, no numpy, no
network, no image assets) procedurally draws a kitten and writes it to
`/output/entry.png`:

- a plump ginger kitten sitting front-on, head tilted ~7° for charm
- huge teal sparkling eyes with double highlights, set low on the face
- pink bow, rosy blush, tiny tongue peeking out of a "w" smile
- one curled tail with a cream tip and tabby bands
- two clumsy oversized front paws, one resting on a pink ball of yarn
  with a loose strand curling away on the ground
- whiskers, forehead tabby stripes, and two tiny floating hearts
- soft cream-to-peach background so the cat is the whole subject and
  still reads clearly at 300 px across

## How it works

Every shape is a signed-distance function (circles, ellipses, triangles,
polylines, bézier arcs). Shapes are painted back-to-front, each only
inside its own tight bounding box, with a 1.5 px analytic
anti-aliasing band on every edge. The PNG is encoded by hand
(`zlib` + `struct`, filter-none scanlines, CRC-checked chunks), so the
output is byte-for-byte deterministic: two runs write the same bytes.

## Run it

```sh
mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
# writes out/entry.png  (1024x1024 PNG, ~110 KB)
```

In the grader's container `MAKEFUN_OUTPUT_DIR` is unset and the program
writes to `/output/entry.png`, as the competition requires.

Runtime is ~10 s on one CPU and ~22 MB of memory, well inside the
60 s / 512 MB sandbox limits. The image is 1024×1024 and ~110 KB,
inside the gate's 1024×1024 / 1 MiB limits.

## License

MIT — see `LICENSE`.
