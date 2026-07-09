"""Tests for the concept_scan agent migration (/scan-concepts)."""
from pydantic_ai.models.google import GoogleModel

from agents._providers import model_for


def test_model_for_concept_scan_defaults_to_flash_lite():
    m = model_for("concept_scan")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-flash-lite"
