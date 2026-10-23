"""Build the images the HTML emails reference (services/email_templates.py).

Email clients (Gmail above all) don't render SVG, so the wordmark is
rasterised here, and the knowledge-tree screenshot is cropped from the
gallery, into frontend/public/email/, which the frontend serves at
{FRONTEND_URL}/email/. Re-run after changing either source:

    cd backend && python scripts/build_email_assets.py

Needs `rsvg-convert` (librsvg) and ImageMagick's `magick` on PATH.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PUBLIC = REPO / "frontend" / "public"
OUT = PUBLIC / "email"


def _run(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # 3x the 26px it's shown at, so it stays sharp on retina screens.
    wordmark = OUT / "wordmark.png"
    _run("rsvg-convert", "-h", "78", str(PUBLIC / "design" / "sapling" / "sapling-wordmark-approved.svg"),
         "-o", str(wordmark))
    _run("magick", str(wordmark), "-strip", str(wordmark))
    # The graph area of the knowledge-tree gallery shot, at 2x the 504px it's shown at.
    _run("magick", str(PUBLIC / "gallery" / "shot-tree.png"), "-crop", "760x600+490+225", "+repage",
         "-resize", "1008x", "-strip", "-quality", "82", str(OUT / "tree-map.jpg"))
    for f in sorted(OUT.iterdir()):
        print(f"{f.relative_to(REPO)}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
