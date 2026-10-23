"""Build the PNG/JPEG assets the HTML emails reference (services/email_templates.py).

Email clients (Gmail above all) don't render SVG, so the brand SVGs are
rasterised here into frontend/public/email/, which the frontend serves at
{FRONTEND_URL}/email/. Re-run after changing a brand SVG or the hero layout:

    cd backend && python scripts/build_email_assets.py

Needs `rsvg-convert` (librsvg) and ImageMagick's `magick` on PATH. Output is
deterministic (fixed random seed), so an unchanged run produces no diff.
"""

from __future__ import annotations

import random
import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC = REPO / "frontend" / "public"
OUT = PUBLIC / "email"

FOREST = "#293c0e"  # sap-800, the email header band
PAPER = "#fdfcf9"   # bg-panel, the email card
DOT_COLORS = ["#a1bc83", "#c5d7b2", "#7ea055", "#e1ecd7", "#d99a4e"]

# Hero canvas, 2x the 600px email width. The illustration sits on the seam
# between the forest band and the paper card.
W, H, SEAM, R = 1200, 520, 260, 196

STAGES = ("seed", "sprout", "sapling")


def _run(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def _inline_svg(path: Path, *, x: float, y: float, size: float) -> str:
    """A growth SVG's markup, re-rooted as a nested <svg> at (x, y)."""
    src = path.read_text()
    src = re.sub(r"<\?xml[^>]*\?>", "", src)
    return re.sub(
        r"<svg\b[^>]*>",
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 120 120" overflow="visible">',
        src,
        count=1,
    )


def _dots(rng: random.Random) -> str:
    out = []
    while len(out) < 70:
        cx, cy = rng.uniform(16, W - 16), rng.uniform(14, SEAM - 14)
        # Keep the porthole clear.
        if (cx - W / 2) ** 2 + (cy - SEAM) ** 2 < (R + 40) ** 2:
            continue
        r = rng.choice([2.5, 3, 3.5, 4, 5, 6])
        out.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{rng.choice(DOT_COLORS)}" '
            f'opacity="{rng.uniform(0.25, 0.85):.2f}"/>'
        )
    return "".join(out)


def hero(stage: str, rng: random.Random, tmp: Path) -> None:
    art = 2 * R * 1.07  # the growth art's circle is r=55 of a 120 box
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        f'<rect width="{W}" height="{SEAM}" fill="{FOREST}"/>'
        f'<rect y="{SEAM}" width="{W}" height="{H - SEAM}" fill="{PAPER}"/>'
        f"{_dots(rng)}"
        f'<circle cx="{W / 2}" cy="{SEAM}" r="{R + 14}" fill="{PAPER}"/>'
        + _inline_svg(PUBLIC / "growth" / f"{stage}.svg", x=W / 2 - art / 2, y=SEAM - art / 2, size=art)
        + "</svg>"
    )
    src = tmp / f"hero-{stage}.svg"
    src.write_text(svg)
    _run("rsvg-convert", str(src), "-o", str(OUT / f"hero-{stage}.png"))
    _run("magick", str(OUT / f"hero-{stage}.png"), "-strip", "-define", "png:compression-level=9",
         str(OUT / f"hero-{stage}.png"))


def band(rng: random.Random, tmp: Path) -> None:
    """The speckled forest strip under the wordmark in emails without a hero."""
    h = 72
    dots = []
    while len(dots) < 40:
        cx, cy = rng.uniform(16, W - 16), rng.uniform(10, h - 10)
        r = rng.choice([2.5, 3, 3.5, 4, 5])
        dots.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{rng.choice(DOT_COLORS)}" '
            f'opacity="{rng.uniform(0.25, 0.85):.2f}"/>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}">'
        f'<rect width="{W}" height="{h}" fill="{FOREST}"/>{"".join(dots)}</svg>'
    )
    src = tmp / "band.svg"
    src.write_text(svg)
    _run("rsvg-convert", str(src), "-o", str(OUT / "band.png"))
    _run("magick", str(OUT / "band.png"), "-strip", str(OUT / "band.png"))


def steps(stage: str) -> None:
    lit = OUT / f"step-{stage}.png"
    _run("rsvg-convert", "-w", "112", "-h", "112", str(PUBLIC / "growth" / f"{stage}.svg"), "-o", str(lit))
    # The "not yet" version: washed out, so the lit step reads as where you are.
    _run("magick", str(lit), "-modulate", "100,10", "-fill", PAPER, "-colorize", "55%",
         "-strip", str(OUT / f"step-{stage}-dim.png"))
    _run("magick", str(lit), "-strip", str(lit))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261023)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        for stage in STAGES:
            hero(stage, rng, tmp)
            steps(stage)
        band(rng, tmp)
    design = PUBLIC / "design" / "sapling"
    _run("rsvg-convert", "-h", "76", str(design / "sapling-wordmark-light.svg"), "-o", str(OUT / "wordmark-light.png"))
    _run("rsvg-convert", "-w", "36", str(design / "sapling-leaf.svg"), "-o", str(OUT / "leaf.png"))
    # The knowledge-tree map from the gallery screenshot, cropped to the graph.
    _run("magick", str(PUBLIC / "gallery" / "shot-tree.png"), "-crop", "760x600+490+225", "+repage",
         "-resize", "1040x", "-strip", "-quality", "82", str(OUT / "tree-map.jpg"))
    for f in sorted(OUT.iterdir()):
        print(f"{f.relative_to(REPO)}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
