"""Optional GOT-OCR through Transformers' native implementation.

No checkpoint Python is executed. Legacy GOT-OCR2_0 remote-code checkpoints
must be converted to the native got_ocr2 format before they can be used here.
"""

import hashlib
import io
import json
import os
import re
import threading


class GotOcrUnavailableError(RuntimeError):
    """Raised when GOT-OCR cannot be loaded (disabled, missing deps or weights)."""


DEFAULT_MODEL_PATH = "stepfun-ai/GOT-OCR-2.0-hf"
DEFAULT_MODEL_REVISION = "d3017ef2c2c1395888c8d635c5e0508bcb0ac78d"
_CACHED_MODEL = None
_CACHED_PROCESSOR = None
_CACHED_CHECKPOINT = None
_MODEL_LOCK = threading.Lock()


def _checkpoint() -> tuple[str, str | None]:
    model_path = os.getenv("GOT_OCR_MODEL_PATH", "").strip() or DEFAULT_MODEL_PATH
    revision = os.getenv("GOT_OCR_MODEL_REVISION", "").strip() or None
    # A revision for the official repo is not a revision of a different repo or
    # a local directory. Custom native checkpoints retain their own identity.
    if revision is None and model_path == DEFAULT_MODEL_PATH:
        revision = DEFAULT_MODEL_REVISION
    return model_path, revision


def got_ocr_cache_identity() -> str:
    """Invalidate transcriptions when the adapter, checkpoint or revision changes.

    Local checkpoints should be immutable directories; replace the path (or set
    a new revision) when replacing their contents, then restart the worker.
    """
    identity = ("native-got-ocr2-v1", *_checkpoint())
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def _load_model():
    if os.getenv("GOT_OCR_ENABLED", "false").lower() != "true":
        raise GotOcrUnavailableError("GOT_OCR_ENABLED is not true")

    global _CACHED_MODEL, _CACHED_PROCESSOR, _CACHED_CHECKPOINT
    checkpoint = _checkpoint()
    with _MODEL_LOCK:
        if (
            _CACHED_CHECKPOINT == checkpoint
            and _CACHED_MODEL is not None
            and _CACHED_PROCESSOR is not None
        ):
            return _CACHED_MODEL, _CACHED_PROCESSOR

        model_path, revision = checkpoint
        if not os.path.isdir(model_path) and not re.fullmatch(r"[0-9a-fA-F]{40}", revision or ""):
            raise GotOcrUnavailableError(
                "GOT_OCR_MODEL_REVISION must be a 40-character commit SHA for a remote "
                f"native got_ocr2 checkpoint. Use {DEFAULT_MODEL_PATH} (pinned by default) "
                "or an existing immutable local directory. Legacy GOT-OCR2_0 checkpoints "
                "requiring remote Python are unsupported."
            )

        try:
            import torch  # noqa: F401
            from transformers import AutoConfig, AutoModelForImageTextToText, AutoProcessor
        except ImportError as e:
            raise GotOcrUnavailableError(
                f"native GOT-OCR requires torch and transformers>=5.10,<6: {e}"
            ) from e

        kwargs = {"trust_remote_code": False}
        if revision is not None:
            kwargs["revision"] = revision
        try:
            config = AutoConfig.from_pretrained(model_path, **kwargs)
            if config.model_type != "got_ocr2":
                raise ValueError(f"expected model_type='got_ocr2', got {config.model_type!r}")
            processor = AutoProcessor.from_pretrained(model_path, **kwargs)
            model = AutoModelForImageTextToText.from_pretrained(
                model_path, use_safetensors=True, **kwargs
            ).eval()
        except Exception as e:
            raise GotOcrUnavailableError(
                "failed to load native GOT-OCR weights; use a native got_ocr2 "
                f"checkpoint with safetensors weights such as {DEFAULT_MODEL_PATH}. Legacy GOT-OCR2_0 "
                f"checkpoints requiring remote Python are unsupported (trust_remote_code=False): {e}"
            ) from e

        # Publish only a complete, successfully loaded pair. A different
        # checkpoint never receives a partially loaded or previously cached pair.
        _CACHED_MODEL = model
        _CACHED_PROCESSOR = processor
        _CACHED_CHECKPOINT = checkpoint
        return model, processor


def extract_page_with_got_ocr(image_bytes: bytes, ocr_type: str = "format") -> str:
    """Return formatted OCR by default; ``ocr_type='ocr'`` requests plain text."""
    if ocr_type not in {"format", "ocr"}:
        raise ValueError("ocr_type must be 'format' or 'ocr'")
    model, processor = _load_model()

    import torch
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    try:
        # BatchFeature.to casts floating image tensors to the model's dtype,
        # while preserving integer token IDs. Do not assume checkpoint dtype.
        inputs = processor(image, return_tensors="pt", format=ocr_type == "format").to(
            device=model.device, dtype=model.dtype
        )
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                tokenizer=processor.tokenizer,
                stop_strings="<|im_end|>",
                max_new_tokens=4096,
            )
        # The native model returns the prompt followed by its answer. Keeping
        # only the suffix prevents internal OCR instructions leaking into text.
        result = processor.decode(
            generated[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )
        return (result or "").strip()
    finally:
        image.close()


def got_ocr_available() -> bool:
    """Check the flag and native API availability without loading any weights."""
    if os.getenv("GOT_OCR_ENABLED", "false").lower() != "true":
        return False
    try:
        import torch  # noqa: F401
        from transformers import AutoConfig, AutoModelForImageTextToText, AutoProcessor  # noqa: F401
        return True
    except ImportError:
        return False


def reset_model_cache():
    """For tests: clear the module-level model cache."""
    global _CACHED_MODEL, _CACHED_PROCESSOR, _CACHED_CHECKPOINT
    with _MODEL_LOCK:
        _CACHED_MODEL = None
        _CACHED_PROCESSOR = None
        _CACHED_CHECKPOINT = None
