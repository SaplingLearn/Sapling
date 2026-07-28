"""Rasterized math worksheet: no text layer, and content that trips
docling's math-without-LaTeX flag (MATH_WITHOUT_LATEX / MATH_SCRIPT_PATTERN)."""
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
import sys

F = "/usr/share/fonts/TTF/DejaVuSans.ttf"
try:
    title = ImageFont.truetype(F, 44)
    body = ImageFont.truetype(F, 34)
except OSError:
    F = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
    title = ImageFont.truetype(F, 44)
    body = ImageFont.truetype(F, 34)

LINES = [
    ("MATH 210 — Problem Set 4", title),
    ("", body),
    ("1. Evaluate the definite integral:", body),
    ("     ∫ x^2 dx  from 0 to 3", body),
    ("", body),
    ("2. Simplify, assuming n ≥ 1:", body),
    ("     ∑ (2k ± 1)  for k = 1 to n", body),
    ("", body),
    ("3. Solve for x where x ≠ 0:", body),
    ("     √(x^2 + 16) ≤ 5", body),
    ("", body),
    ("4. Compute the partial derivative:", body),
    ("     ∂f/∂x  where f = 3x^2 y − y^3", body),
]

img = Image.new("RGB", (1240, 1000), "white")
d = ImageDraw.Draw(img)
y = 60
for text, font in LINES:
    d.text((70, y), text, fill=(15, 15, 15), font=font)
    y += 62 if font is title else 52

dst = sys.argv[1]
img.save(dst, format="PDF", resolution=150.0)

back = PdfReader(dst)
got = "".join((p.extract_text() or "") for p in back.pages).strip()
print(f"WROTE {dst}")
print(f"text layer: {len(got)} chars -> {'EMPTY (a real scan)' if len(got) < 50 else 'HAS TEXT (bad)'}")
