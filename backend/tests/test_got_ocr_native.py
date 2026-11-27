"""Native GOT public API contract; fake modules, no model weights/network/GPU.

Actual Transformers/Docling image and OCR quality are separate qualification
checks. These tests catch unsafe loader options, prompt echo and gate/cache
regressions even in the normal fast (non-OCR) CI lane.
"""

import io
import socket
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from services.extraction_backends import got_ocr_backend as got


@pytest.fixture(autouse=True)
def _isolated_got(monkeypatch):
    monkeypatch.setenv("GOT_OCR_ENABLED", "true")
    monkeypatch.delenv("GOT_OCR_MODEL_PATH", raising=False)
    monkeypatch.delenv("GOT_OCR_MODEL_REVISION", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("native GOT contract tests must not reach the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    got.reset_model_cache()
    yield
    got.reset_model_cache()


@pytest.fixture
def native_api(monkeypatch):
    state = SimpleNamespace(inference=False, device=None, dtype=None, token_slice=None)
    answer_tokens = object()

    class Batch(dict):
        def to(self, *, device, dtype):
            state.device = device
            state.dtype = dtype
            return self

    batch = Batch(input_ids=SimpleNamespace(shape=(1, 3)), pixel_values=object())

    class Generated:
        def __getitem__(self, key):
            state.token_slice = key
            return answer_tokens

    @contextmanager
    def inference_mode():
        assert not state.inference
        state.inference = True
        try:
            yield
        finally:
            state.inference = False

    def generate(**kwargs):
        assert state.inference, "generation must disable autograd"
        return Generated()

    processor = MagicMock(return_value=batch)
    processor.decode.return_value = "  \\frac{1}{2}  "
    model = MagicMock(device="cpu", dtype="bfloat16")
    model.eval.return_value = model
    model.generate.side_effect = generate
    transformers = SimpleNamespace(
        AutoConfig=SimpleNamespace(from_pretrained=MagicMock(
            return_value=SimpleNamespace(model_type="got_ocr2")
        )),
        AutoProcessor=SimpleNamespace(from_pretrained=MagicMock(return_value=processor)),
        AutoModelForImageTextToText=SimpleNamespace(from_pretrained=MagicMock(return_value=model)),
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=inference_mode))
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    return SimpleNamespace(
        transformers=transformers, model=model, processor=processor, batch=batch,
        answer_tokens=answer_tokens, state=state,
    )


def _image_bytes():
    with Image.new("L", (10, 10), color=255) as image:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()


def _loaders(api):
    return (
        api.transformers.AutoConfig.from_pretrained,
        api.transformers.AutoProcessor.from_pretrained,
        api.transformers.AutoModelForImageTextToText.from_pretrained,
    )


def test_default_native_checkpoint_is_revision_pinned_without_remote_python(native_api):
    model, processor = got._load_model()
    assert (model, processor) == (native_api.model, native_api.processor)
    for loader in _loaders(native_api):
        loader.assert_called_once_with(
            got.DEFAULT_MODEL_PATH,
            trust_remote_code=False,
            revision=got.DEFAULT_MODEL_REVISION,
            **({"use_safetensors": True} if loader is _loaders(native_api)[2] else {}),
        )
    native_api.model.eval.assert_called_once_with()


@pytest.mark.parametrize("path,revision", [
    ("LOCAL", None),
    ("org/custom-native-got", "a" * 40),
    (got.DEFAULT_MODEL_PATH, "b" * 40),
])
def test_custom_native_checkpoint_and_revision_are_honored(monkeypatch, native_api, tmp_path, path, revision):
    if path == "LOCAL":
        path = str(tmp_path)
    monkeypatch.setenv("GOT_OCR_MODEL_PATH", path)
    if revision:
        monkeypatch.setenv("GOT_OCR_MODEL_REVISION", revision)
    got._load_model()
    expected = {"trust_remote_code": False}
    if revision:
        expected["revision"] = revision
    for loader in _loaders(native_api):
        loader.assert_called_once_with(
            path, **expected,
            **({"use_safetensors": True} if loader is _loaders(native_api)[2] else {}),
        )


@pytest.mark.parametrize("path,revision", [
    ("org/native-got", None),
    ("org/native-got", "main"),
    ("org/native-got", "a" * 39),
    (got.DEFAULT_MODEL_PATH, "main"),
    ("stepfun-ai/GOT-OCR2_0", None),
])
def test_remote_checkpoint_requires_commit_before_any_loader(monkeypatch, native_api, path, revision):
    monkeypatch.setenv("GOT_OCR_MODEL_PATH", path)
    if revision is not None:
        monkeypatch.setenv("GOT_OCR_MODEL_REVISION", revision)
    with pytest.raises(got.GotOcrUnavailableError, match="40-character commit SHA.*Legacy GOT-OCR2_0"):
        got._load_model()
    for loader in _loaders(native_api):
        loader.assert_not_called()


def test_disabled_flag_precedes_cached_model_and_optional_imports(monkeypatch, native_api):
    got._load_model()
    monkeypatch.setenv("GOT_OCR_ENABLED", "false")
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    with pytest.raises(got.GotOcrUnavailableError, match="GOT_OCR_ENABLED"):
        got.extract_page_with_got_ocr(b"not an image")
    assert got.got_ocr_available() is False
    for loader in _loaders(native_api):
        assert loader.call_count == 1


def test_missing_native_api_is_unavailable_without_loading_weights(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace())
    with pytest.raises(got.GotOcrUnavailableError, match="transformers>=5.10"):
        got._load_model()
    assert got.got_ocr_available() is False


def test_availability_checks_api_only_without_loading_weights(native_api):
    assert got.got_ocr_available() is True
    for loader in _loaders(native_api):
        loader.assert_not_called()


@pytest.mark.parametrize("model_type", ["GOT", "qwen2", "other"])
def test_non_native_checkpoint_rejected_before_processor_or_weights(native_api, model_type):
    native_api.transformers.AutoConfig.from_pretrained.return_value.model_type = model_type
    with pytest.raises(got.GotOcrUnavailableError, match="native got_ocr2.*Legacy GOT-OCR2_0"):
        got._load_model()
    native_api.transformers.AutoProcessor.from_pretrained.assert_not_called()
    native_api.transformers.AutoModelForImageTextToText.from_pretrained.assert_not_called()
    assert got._CACHED_MODEL is None
    assert got._CACHED_PROCESSOR is None


def test_remote_config_request_does_not_retry_with_remote_code(native_api):
    native_api.transformers.AutoConfig.from_pretrained.side_effect = ValueError("requires remote code")
    with pytest.raises(got.GotOcrUnavailableError, match="trust_remote_code=False"):
        got._load_model()
    native_api.transformers.AutoConfig.from_pretrained.assert_called_once()
    assert native_api.transformers.AutoConfig.from_pretrained.call_args.kwargs["trust_remote_code"] is False
    native_api.transformers.AutoModelForImageTextToText.from_pretrained.assert_not_called()


def test_partial_failed_load_does_not_publish_cache_and_can_retry(native_api):
    loader = native_api.transformers.AutoModelForImageTextToText.from_pretrained
    loader.side_effect = OSError("weights missing")
    with pytest.raises(got.GotOcrUnavailableError, match="weights missing"):
        got._load_model()
    assert got._CACHED_MODEL is None
    assert got._CACHED_PROCESSOR is None
    assert got._CACHED_CHECKPOINT is None
    loader.side_effect = None
    assert got._load_model() == (native_api.model, native_api.processor)
    assert loader.call_count == 2


@pytest.mark.parametrize("changed_env,value", [
    ("GOT_OCR_MODEL_PATH", "org/new-native-checkpoint"),
    ("GOT_OCR_MODEL_REVISION", "c" * 40),
])
def test_cache_reuses_same_pair_and_reloads_changed_checkpoint(monkeypatch, native_api, changed_env, value):
    monkeypatch.setenv("GOT_OCR_MODEL_REVISION", "e" * 40)
    got._load_model()
    got._load_model()
    assert native_api.transformers.AutoConfig.from_pretrained.call_count == 1
    monkeypatch.setenv(changed_env, value)
    got._load_model()
    for loader in _loaders(native_api):
        assert loader.call_count == 2


def test_failed_checkpoint_change_never_returns_old_pair(monkeypatch, native_api):
    got._load_model()
    monkeypatch.setenv("GOT_OCR_MODEL_REVISION", "d" * 40)
    native_api.transformers.AutoConfig.from_pretrained.side_effect = OSError("revision missing")
    with pytest.raises(got.GotOcrUnavailableError, match="revision missing"):
        got._load_model()
    with pytest.raises(got.GotOcrUnavailableError, match="revision missing"):
        got._load_model()
    assert native_api.transformers.AutoConfig.from_pretrained.call_count == 3


@pytest.mark.parametrize("ocr_type,formatted", [("format", True), ("ocr", False)])
def test_native_generation_formats_decodes_suffix_and_disables_autograd(native_api, ocr_type, formatted):
    assert got.extract_page_with_got_ocr(_image_bytes(), ocr_type=ocr_type) == r"\frac{1}{2}"
    args, kwargs = native_api.processor.call_args
    assert args[0].mode == "RGB"
    assert args[0].size == (10, 10)
    assert kwargs == {"return_tensors": "pt", "format": formatted}
    assert native_api.state.device == native_api.model.device
    assert native_api.state.dtype == native_api.model.dtype
    native_api.model.generate.assert_called_once_with(
        **native_api.batch,
        do_sample=False,
        tokenizer=native_api.processor.tokenizer,
        stop_strings="<|im_end|>",
        max_new_tokens=4096,
    )
    assert native_api.state.token_slice == (0, slice(3, None))
    native_api.processor.decode.assert_called_once_with(
        native_api.answer_tokens, skip_special_tokens=True,
    )
    assert not native_api.state.inference
    with pytest.raises(ValueError, match="closed image"):
        args[0].getpixel((0, 0))


def test_empty_result_is_preserved_for_next_rescuer(native_api):
    native_api.processor.decode.return_value = "   "
    assert got.extract_page_with_got_ocr(_image_bytes()) == ""


def test_generation_failure_propagates_without_fabricating_text(native_api):
    error = RuntimeError("out of memory")
    native_api.model.generate.side_effect = error
    with pytest.raises(RuntimeError) as raised:
        got.extract_page_with_got_ocr(_image_bytes())
    assert raised.value is error
    native_api.processor.decode.assert_not_called()
    assert not native_api.state.inference


def test_unknown_ocr_mode_fails_before_loading_weights(native_api):
    with pytest.raises(ValueError, match="ocr_type"):
        got.extract_page_with_got_ocr(b"", ocr_type="unrecognized")
    for loader in _loaders(native_api):
        loader.assert_not_called()


def test_reset_clears_complete_cache(native_api):
    got._load_model()
    got.reset_model_cache()
    assert got._CACHED_CHECKPOINT is None
    assert got._CACHED_MODEL is None
    assert got._CACHED_PROCESSOR is None
    got._load_model()
    for loader in _loaders(native_api):
        assert loader.call_count == 2
