FROM python:3.12-slim

# tesseract needed by pytesseract (legacy OCR fallback);
# libgl1 + libglib2.0-0 needed by docling/opencv for layout-aware extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# NOTE (#163): this installs requirements.txt, NOT requirements.lock, so the
# image's fast-set versions still float even though CI is reproducible.
# That is deliberate-for-now, and the reason is NOT the lock's
# `--python-version 3.13` vs this 3.12 base — the lock was verified to resolve
# and install cleanly on 3.12 (113 packages, `pip install --require-hashes
# --dry-run`), because it carries no python_full_version markers.
#
# The real blocker: requirements.lock intentionally covers only the fast
# (non-OCR) subset, while this image also needs torch/docling/transformers.
# `--require-hashes` is all-or-nothing, so it cannot span a hashed lock plus an
# unhashed OCR install; and a `-r requirements.lock` + `-r requirements.txt`
# sequence lets the OCR resolve silently upgrade locked pins, which would make
# the reproducibility claim false rather than true.
# Fixing this properly needs a second, OCR-inclusive lock resolved against the
# torch CPU wheel index — tracked as follow-up, out of scope for #163.
# Install torch from the CPU-only wheel index first to avoid pulling CUDA into the image
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3" \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
