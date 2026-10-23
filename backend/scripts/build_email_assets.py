"""Build the images the HTML emails reference (services/email_templates.py).

Email clients (Gmail above all) don't render SVG or run canvas, so this
rasterises them into frontend/public/email/, which the frontend serves at
{FRONTEND_URL}/email/:

  header.jpg    the landing page hero, frozen: the pale ground, the point
                cloud (same palette, clusters and link lines as
                frontend/src/components/landing-v5/Hero.tsx), the soft fade
                behind the wordmark, and the wordmark itself
  tree-map.jpg  the graph area of the knowledge-tree gallery screenshot

Re-run after changing the hero, the wordmark or the screenshot:

    cd backend && python scripts/build_email_assets.py

Needs `rsvg-convert` (librsvg) and ImageMagick's `magick` on PATH. The cloud
uses a fixed seed, so an unchanged run produces the same image.
"""

from __future__ import annotations

import math
import random
import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC = REPO / "frontend" / "public"
OUT = PUBLIC / "email"

# The header is shown 600x220 in the email and drawn at 2x.
W, H = 1200, 440
GROUND = "#F2F4F0"   # the landing ground (.landing-v5)
CARD = "#ffffff"     # the email card the header fades into

# Hero.tsx's background-node palette, (colour, weight).
PALETTE = [
    ("#445D22", 0.24), ("#7B9E51", 0.24), ("#D97706", 0.20),
    ("#B1D28B", 0.15), ("#A39E8F", 0.10), ("#D6D1C4", 0.07),
]
# Hero.tsx's cluster centres, in its 3D field.
CLUSTERS = [
    (-600, -250, 80), (-350, -100, -120), (-100, -300, 200), (150, -150, -80),
    (400, -250, 150), (600, -100, -50), (-500, 100, -150), (-200, 200, 100),
    (50, 150, -200), (300, 250, 120), (550, 150, -100), (-400, 350, 60),
    (0, 0, 0), (200, -50, -150),
]
SPREAD = 280
FOCAL = 1000


def _run(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def _colour(rng: random.Random) -> str:
    r, s = rng.random(), 0.0
    for c, w in PALETTE:
        s += w
        if r <= s:
            return c
    return PALETTE[0][0]


def _cloud(rng: random.Random) -> str:
    """Hero.tsx's projection at rest (rotation 0, no mouse), scaled to the header."""
    # The hero fills a ~1440x900 viewport; the header shows its middle band,
    # a little zoomed out so more of the cloud fits the wide, short strip.
    scale, cx, cy = 0.95, W / 2, H / 2
    pts = []
    for _ in range(260):
        ox, oy, oz = CLUSTERS[rng.randrange(len(CLUSTERS))]
        x = ox + (rng.random() - 0.5) * SPREAD
        y = oy + (rng.random() - 0.5) * SPREAD
        z = oz + (rng.random() - 0.5) * SPREAD
        sc = FOCAL / (FOCAL + z)
        px, py = x * sc * scale + cx, y * sc * scale * 0.62 + cy
        if -20 < px < W + 20 and -20 < py < H + 20:
            pts.append((px, py, sc, (1 + rng.random() * 4) * sc * 1.7, _colour(rng)))
    links = []
    for i, (x1, y1, s1, _, _) in enumerate(pts):
        max_d = 70 * s1 * 1.4
        for x2, y2, _, _, _ in pts[i + 1:]:
            d = math.hypot(x1 - x2, y1 - y2)
            if d < max_d:
                a = (1 - d / max_d) * 0.22 * min(1, s1)
                links.append(
                    f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="#A39E8F" stroke-opacity="{a:.3f}" stroke-width="1"/>'
                )
    dots = [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}" fill="{c}"/>'
        for x, y, _, r, c in sorted(pts, key=lambda p: p[2])
    ]
    return "".join(links) + "".join(dots)


def _wordmark(*, width: float) -> str:
    src = (PUBLIC / "design" / "sapling" / "sapling-wordmark-approved.svg").read_text()
    src = re.sub(r"<\?xml[^>]*\?>", "", src)
    height = width * 44.55 / 150
    x, y = (W - width) / 2, (H - height) / 2 - 6
    return re.sub(
        r"<svg\b[^>]*?>",
        f'<svg x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
        'viewBox="0 0 150 44.55" overflow="visible">',
        src,
        count=1,
    )


def header(tmp: Path) -> None:
    rng = random.Random(20261023)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        "<defs>"
        # The hero's legibility glow: ground-coloured, behind the wordmark.
        '<radialGradient id="glow" cx="50%" cy="48%" r="50%" gradientTransform="translate(0.25 0) scale(0.5 1)">'
        f'<stop offset="0" stop-color="{GROUND}" stop-opacity="0.95"/>'
        f'<stop offset="0.5" stop-color="{GROUND}" stop-opacity="0.75"/>'
        f'<stop offset="1" stop-color="{GROUND}" stop-opacity="0"/>'
        "</radialGradient>"
        # Melt into the card below.
        '<linearGradient id="foot" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0.55" stop-color="{CARD}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{CARD}" stop-opacity="1"/>'
        "</linearGradient>"
        "</defs>"
        f'<rect width="{W}" height="{H}" fill="{GROUND}"/>'
        f"{_cloud(rng)}"
        f'<rect width="{W}" height="{H}" fill="url(#glow)"/>'
        f'<rect width="{W}" height="{H}" fill="url(#foot)"/>'
        + _wordmark(width=360)
        + "</svg>"
    )
    src = tmp / "header.svg"
    src.write_text(svg)
    png = tmp / "header.png"
    _run("rsvg-convert", str(src), "-o", str(png))
    # JPEG: the header is opaque and photographic enough that PNG costs 4x.
    _run("magick", str(png), "-strip", "-sampling-factor", "4:4:4", "-quality", "86", str(OUT / "header.jpg"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        header(Path(t))
    # The graph area of the knowledge-tree gallery shot, at 2x the 504px it's shown at.
    _run("magick", str(PUBLIC / "gallery" / "shot-tree.png"), "-crop", "760x600+490+225", "+repage",
         "-resize", "1008x", "-strip", "-quality", "82", str(OUT / "tree-map.jpg"))
    for f in sorted(OUT.iterdir()):
        print(f"{f.relative_to(REPO)}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
