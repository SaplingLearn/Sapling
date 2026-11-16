# Keep in step with requirements.lock's `--python-version` and ci.yml's
# python-version: the lock is compiled for this Python and installed here with
# --require-hashes (tests/test_docker_lock_install.py checks all three agree).
#
# Three images from one file (#116, docs/architecture-hardening-plan.md phase 2):
#
#   api     FastAPI only. requirements.lock, hash-checked: no torch, Docling,
#           transformers or Chromium (tests/test_api_image_imports.py proves the
#           app imports and starts without them).
#   worker  `python -m worker`: the api's packages plus requirements-worker.txt
#           (the OCR stack, CPU torch) and Chromium for BU SSO.
#   full    the worker image with the API's command: what Railway has always
#           built, and STILL THE DEFAULT. The api image is only safe to serve
#           once nothing on the API's request path needs OCR or Chromium, i.e.
#           `jobs_queue` is on for everyone and the upload pipeline runs in the
#           worker (docs/deploy/railway.md, "Cut-over order").
#
# Choosing one: `docker build --target api|worker|full backend`, or (Railway,
# which has no build-target setting) the SAPLING_IMAGE_TARGET build argument,
# which the last stage below resolves. Railway passes a service variable of that
# name to the build because it is declared as an ARG here. Unset OR EMPTY =
# `full` (the last FROM uses `${...:-full}`: a service variable set to "" must
# not resolve to `FROM ` and fail, or worse, to some other image). Any other
# value than api|worker|full fails the build in the `target-check` stage with
# a message naming the three.
ARG SAPLING_IMAGE_TARGET=full

# ── target-check: refuse an unknown SAPLING_IMAGE_TARGET early ───────────────
# The last stage copies its one-line marker, so the check is in the graph of
# every default build and records the chosen target in the image
# (/etc/sapling-image-target). Same base as the real stages: nothing new to pull.
FROM python:3.13-slim AS target-check
ARG SAPLING_IMAGE_TARGET
RUN target="${SAPLING_IMAGE_TARGET:-full}"; \
    case "$target" in \
      api|worker|full) echo "$target" > /sapling-image-target ;; \
      *) echo "SAPLING_IMAGE_TARGET='$target' is not a backend image target: use api, worker or full (or leave it unset for full)." >&2; exit 1 ;; \
    esac

# ── api ──────────────────────────────────────────────────────────────────────
# The lock itself, hash-checked, exactly as CI and the E2E lane install it:
# requirements.lock is requirements.txt's full resolution (--universal, so it
# carries the hashes of every platform's wheels, linux amd64/arm64 included),
# and this image installs nothing else. `--require-hashes` makes pip refuse any
# artifact whose sha256 the lock does not list, so a tampered or re-uploaded
# wheel fails the build instead of shipping.
FROM python:3.13-slim AS api

WORKDIR /app

COPY requirements.lock ./
COPY scripts/lock_constraints.py scripts/lock_constraints.py
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python scripts/lock_constraints.py verify requirements.lock \
    && pip check

COPY . .

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]

# ── heavy: everything the worker needs (base of `worker` and `full`) ─────────
FROM python:3.13-slim AS heavy

# tesseract needed by pytesseract (legacy OCR fallback);
# libgl1 + libglib2.0-0 needed by docling/opencv for layout-aware extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies (#694). CI and the E2E lane install requirements.lock with
# --require-hashes. So does this stage (step 2), but it cannot stop there: the
# lock deliberately leaves out the OCR stack (torch/docling/transformers,
# requirements-worker.txt), and --require-hashes is all-or-nothing within one
# pip run, so the OCR stack goes in a second, unhashed run. Installing the
# bare requirements let every transitive dependency float: genai-prices 0.1.x
# reached the deployed image while CI pinned 0.0.66, and every llm_usage row
# recorded 0 tokens for two months (#689). So that second run applies the lock
# as CONSTRAINTS:
#
#   1. torch AND torchvision from the CPU-only wheel index, so CUDA stays out
#      of the image. torchvision is not a direct requirement, but docling
#      needs it; left to step 3 it came from PyPI as the build for PyPI's
#      (CUDA) torch, and `torchvision::nms` did not exist at runtime (#700).
#      `--no-deps`: this step installs only what it names. Their dependencies
#      (numpy, pillow, sympy, ...) come from step 3, at the lock's version
#      where the lock pins one, so nothing is installed twice across layers.
#      Without it this step put pillow 12.3.0 in the image and step 3 swapped
#      in the locked 12.2.0, leaving a dead copy in this layer. The flip side:
#      pip does not cross-check torchvision's `torch==<version>` pin here. If
#      the index ever serves a torch newer than its torchvision (a release-day
#      window), `pip check` in step 4 fails the build; it never ships a
#      mismatched pair. `--report` records exactly what was installed, for
#      step 3. Its own layer, before the lock is copied, so a lock bump does
#      not re-download torch.
#   2. requirements.lock with --require-hashes: the API's whole set (everything
#      requirements.txt resolves to), hash-checked as in the api stage and CI.
#      pip prints a dependency-conflict notice here listing torch's own
#      dependencies (numpy, sympy, ...): step 1 was --no-deps and they arrive
#      in step 3. Expected; `pip check` in step 4 is the gate.
#   3. The lock becomes a hash-free constraints file (a hashed constraint turns
#      pip's all-or-nothing hash checking on). `pin` appends `name==version`
#      for EVERY distribution step 1's report lists, so the install below
#      cannot replace any of them with a PyPI (CUDA) build. The lock never
#      pins those names (tests/dependency_manifest.py OCR_STACK); if it ever
#      did at another version, pip's resolver fails the install rather than
#      picking one. Then requirements-worker.txt under `-c`: every package the
#      lock pins is already installed at its locked (hash-checked) version and
#      must stay there or the build FAILS. Packages the lock does not list
#      install unconstrained and unhashed: the OCR stack itself AND its own
#      dependencies that nothing else pulls in (numpy, scipy, huggingface-hub,
#      tokenizers, safetensors, opencv, ...). Those still float, so for the
#      OCR path this image is NOT exactly what CI tests; CI does not install
#      the OCR stack.
#   4. `verify` fails the build if any installed package differs from its lock
#      pin or any nvidia-*/cuda-* distribution is installed. `cpu-torch` fails
#      it unless torch.version.cuda is None, torch and everything that
#      requires it carry no CUDA build tag or CUDA dependency, and
#      torchvision.ops.nms actually runs. The #700 pair passed `verify` and
#      `pip check` and only broke when torchvision loaded its operators.
#      `pip check` fails it if the set is inconsistent.
# Guarded by tests/test_docker_lock_install.py.
RUN pip install --no-cache-dir --no-deps --index-url https://download.pytorch.org/whl/cpu \
    --report /tmp/cpu-index-report.json "torch>=2.5,<3" torchvision

COPY requirements-worker.txt requirements.lock ./
COPY scripts/lock_constraints.py scripts/lock_constraints.py
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && python scripts/lock_constraints.py constraints requirements.lock > /tmp/lock-constraints.txt \
    && python scripts/lock_constraints.py pin >> /tmp/lock-constraints.txt \
    && pip install --no-cache-dir -c /tmp/lock-constraints.txt -r requirements-worker.txt \
    && python scripts/lock_constraints.py verify requirements.lock \
    && python scripts/lock_constraints.py cpu-torch \
    && pip check \
    && rm /tmp/lock-constraints.txt /tmp/cpu-index-report.json

# BU SSO launches Chromium on the server; the Python wheel alone is insufficient.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 5000

# ── worker ───────────────────────────────────────────────────────────────────
# No port, no healthcheck: it serves nothing (worker/__main__.py).
FROM heavy AS worker

CMD ["python", "-m", "worker"]

# ── full: today's image (the API's command on the heavy image) ───────────────
FROM heavy AS full

# The access log keeps the path only: main.py installs
# services/access_log.py's query-string filter on uvicorn.access at import.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]

# ── the image a plain `docker build` (and Railway) produces ─────────────────
# Must stay LAST: with no --target, the last stage is the result. `:-full`
# makes an EMPTY build argument mean `full`, like an unset one.
FROM ${SAPLING_IMAGE_TARGET:-full}
COPY --from=target-check /sapling-image-target /etc/sapling-image-target
