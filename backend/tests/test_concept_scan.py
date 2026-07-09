"""Tests for the concept_scan agent migration (/scan-concepts)."""
import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from agents._providers import model_for
from agents.concept_scan import NewConcepts, concept_scan_agent


def test_model_for_concept_scan_defaults_to_flash_lite():
    m = model_for("concept_scan")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-flash-lite"


def test_new_concepts_allows_empty_list():
    assert NewConcepts(concepts=[]).concepts == []


def test_new_concepts_rejects_more_than_15():
    with pytest.raises(ValidationError):
        NewConcepts(concepts=[f"Concept {i}" for i in range(16)])


def test_concept_scan_agent_is_configured():
    assert isinstance(concept_scan_agent, Agent)
    assert concept_scan_agent.output_type is NewConcepts
