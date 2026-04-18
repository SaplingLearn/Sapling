import io
import os


class GotOcrUnavailableError(RuntimeError):
    """Raised when GOT-OCR 2.0 cannot be loaded (no GPU, missing weights, disabled)."""


_CACHED_MODEL = None
_CACHED_TOKENIZER = None


def _load_model():
    if os.getenv("GOT_OCR_ENABLED", "false").lower() != "true":
        raise GotOcrUnavailableError("GOT_OCR_ENABLED is not true")

    global _CACHED_MODEL, _CACHED_TOKENIZER
    if _CACHED_MODEL is not None and _CACHED_TOKENIZER is not None:
        return _CACHED_MODEL, _CACHED_TOKENIZER

    model_path = os.getenv("GOT_OCR_MODEL_PATH", "stepfun-ai/GOT-OCR2_0")
    try:
        import torch  # noqa: F401
        from transformers import AutoModel, AutoTokenizer
    except ImportError as e:
        raise GotOcrUnavailableError(f"torch/transformers not installed: {e}") from e

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            model_path,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )
        model = model.eval()
    except Exception as e:
        raise GotOcrUnavailableError(f"failed to load GOT-OCR weights: {e}") from e

    _CACHED_MODEL = model
    _CACHED_TOKENIZER = tokenizer
    return model, tokenizer


def extract_page_with_got_ocr(image_bytes: bytes, ocr_type: str = "format") -> str:
    model, tokenizer = _load_model()

    import tempfile
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        img.save(tmp.name, format="PNG")
        tmp_path = tmp.name

    try:
        result = model.chat(tokenizer, tmp_path, ocr_type=ocr_type)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return (result or "").strip()


def got_ocr_available() -> bool:
    if os.getenv("GOT_OCR_ENABLED", "false").lower() != "true":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def reset_model_cache():
    """For tests: clear the module-level model cache."""
    global _CACHED_MODEL, _CACHED_TOKENIZER
    _CACHED_MODEL = None
    _CACHED_TOKENIZER = None
