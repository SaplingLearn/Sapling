FROM python:3.12-slim

# tesseract needed by pytesseract (legacy OCR fallback);
# libgl1 + libglib2.0-0 needed by docling/opencv for layout-aware extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.lock ./
COPY scripts/lock_constraints.py scripts/lock_constraints.py
# Install the dependency set CI tests (#694). CI and the E2E lane install
# requirements.lock with --require-hashes; this image cannot, because the lock
# deliberately leaves out the OCR stack (torch/docling/transformers) and
# --require-hashes is all-or-nothing. Installing the bare requirements.txt let
# every transitive dependency float: genai-prices 0.1.x reached the deployed
# image while CI pinned 0.0.66, and every llm_usage row recorded 0 tokens for
# two months (#689).
#
# So the lock is applied as CONSTRAINTS instead (scripts/lock_constraints.py
# strips the hashes; pip turns hash-checking on for any hashed constraint):
#   1. torch from the CPU-only wheel index, so CUDA stays out of the image;
#   2. requirements.txt under `-c` the lock: every package the lock pins,
#      including the OCR stack's transitive dependencies and anything step 1
#      installed, resolves to the locked version or the build FAILS. Packages
#      the lock does not list (the OCR stack itself) install as before;
#   3. `verify` fails the build if any installed package still differs from
#      its lock pin, and `pip check` if the set is inconsistent.
# Guarded by tests/test_docker_lock_install.py.
RUN python scripts/lock_constraints.py constraints requirements.lock > /tmp/lock-constraints.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3" \
    && pip install --no-cache-dir -c /tmp/lock-constraints.txt -r requirements.txt \
    && python scripts/lock_constraints.py verify requirements.lock \
    && pip check \
    && rm /tmp/lock-constraints.txt

COPY . .

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
