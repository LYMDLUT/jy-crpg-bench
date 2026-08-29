# Paper

ICLR 2027 submission draft for jy-crpg-bench.

- `src/` - LaTeX source (official ICLR 2027 style), `main.pdf` is the build
- `src/figures/make.py` - regenerates every figure from the published catalogue numbers
- `refs/` - the fourteen reference papers read while shaping the structure, by arXiv id
- `iclr2027/` - the official style-file kit as downloaded

Build: `cd src && latexmk -pdf main.tex`

Before submission: comment out `\iclrfinalcopy` (double blind) and replace
the hanxiao.io URLs with an anonymised mirror.
