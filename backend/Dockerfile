# Keep in step with requirements.lock's `--python-version` and ci.yml's
# python-version: the lock is compiled for this Python and applied here as hard
# constraints (tests/test_docker_lock_install.py checks all three agree).
FROM python:3.13-slim

# tesseract needed by pytesseract (legacy OCR fallback);
# libgl1 + libglib2.0-0 needed by docling/opencv for layout-aware extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies (#694). CI and the E2E lane install requirements.lock with
# --require-hashes; this image cannot, because the lock deliberately leaves out
# the OCR stack (torch/docling/transformers) and --require-hashes is
# all-or-nothing. Installing the bare requirements.txt let every transitive
# dependency float: genai-prices 0.1.x reached the deployed image while CI
# pinned 0.0.66, and every llm_usage row recorded 0 tokens for two months
# (#689). So the lock is applied as CONSTRAINTS instead:
#
#   1. torch from the CPU-only wheel index, so CUDA stays out of the image. Its
#      own layer, before the lock is copied, so a lock bump does not
#      re-download it.
#   2. The lock becomes a hash-free constraints file (a hashed constraint turns
#      pip's all-or-nothing hash checking on), plus the exact torch just
#      installed, so the next step cannot backtrack onto a PyPI (CUDA) torch.
#   3. requirements.txt under `-c`: every package the lock pins resolves to the
#      locked version or the build FAILS. Packages the lock does not list
#      install unconstrained: the OCR stack itself AND its own dependencies
#      that nothing else pulls in (numpy, scipy, huggingface-hub, tokenizers,
#      safetensors, opencv, ...). Those still float, so for the OCR path this
#      image is NOT exactly what CI tests; CI does not install the OCR stack.
#   4. `verify` fails the build if any installed package differs from its lock
#      pin or any nvidia-*/cuda-* distribution is installed; `pip check` fails
#      it if the set is inconsistent.
# Guarded by tests/test_docker_lock_install.py.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3"

COPY requirements.txt requirements.lock ./
COPY scripts/lock_constraints.py scripts/lock_constraints.py
RUN python scripts/lock_constraints.py constraints requirements.lock > /tmp/lock-constraints.txt \
    && python scripts/lock_constraints.py pin torch >> /tmp/lock-constraints.txt \
    && pip install --no-cache-dir -c /tmp/lock-constraints.txt -r requirements.txt \
    && python scripts/lock_constraints.py verify requirements.lock \
    && pip check \
    && rm /tmp/lock-constraints.txt

COPY . .

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
