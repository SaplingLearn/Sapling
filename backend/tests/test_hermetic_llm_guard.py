"""#379: the autouse hermetic LLM guard must make the default lane provably offline.

`conftest._hermetic_llm_transport` patches the google-genai AND anthropic
transport classes so a forgotten stub can never turn into a real, billable
Gemini or Claude call. These tests pin
that contract from both directions: unmarked tests are blocked, and the opt-in
live lanes (`live_llm` / `e2e_staging` / `integration`) are left alone.
"""
import asyncio

import pytest
from google import genai

# A syntactically valid but non-functional key: `genai.Client` validates that a
# key is present at construction, so we can't pass "".
_DUMMY_KEY = "dummy-key-for-import"


def _client() -> genai.Client:
    return genai.Client(api_key=_DUMMY_KEY)


class TestDefaultLaneIsOffline:
    def test_sync_generate_content_raises_unstubbed_llm_egress(self):
        """A forgotten patch must fail loudly, not hit the network."""
        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            _client().models.generate_content(
                model="gemini-2.5-flash-lite", contents="hello",
            )

    def test_sync_embed_content_raises_unstubbed_llm_egress(self):
        """The RAG embedding path (services/rag_service) is covered too."""
        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            _client().models.embed_content(
                model="gemini-embedding-001", contents=["hello"],
            )

    def test_streaming_generate_content_raises_unstubbed_llm_egress(self):
        """The SSE tutor path streams, which uses a different transport method
        than the unary one — both must be blocked."""
        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            list(_client().models.generate_content_stream(
                model="gemini-2.5-flash-lite", contents="hello",
            ))

    def test_async_generate_content_raises_unstubbed_llm_egress(self):
        """Agents run through the async client; that seam must be blocked too."""
        async def _go():
            await _client().aio.models.generate_content(
                model="gemini-2.5-flash-lite", contents="hello",
            )

        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            asyncio.run(_go())

    def test_error_message_names_the_escape_hatch(self):
        """The failure has to tell whoever hits it what to do next."""
        with pytest.raises(RuntimeError) as exc:
            _client().models.generate_content(
                model="gemini-2.5-flash-lite", contents="hello",
            )
        msg = str(exc.value)
        assert "unstubbed LLM egress" in msg
        assert "live_llm" in msg


class TestAnthropicLaneIsOffline:
    """ADR 0030: every agent slot defaults to Claude, so the Anthropic SDK's
    transport must be cut exactly like google-genai's."""

    def test_sync_messages_create_raises_unstubbed_llm_egress(self):
        import anthropic

        client = anthropic.Anthropic(api_key=_DUMMY_KEY)
        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            client.messages.create(
                model="claude-haiku-5-5", max_tokens=16,
                messages=[{"role": "user", "content": "hello"}],
            )

    def test_async_messages_stream_raises_unstubbed_llm_egress(self):
        """The SSE tutor streams through the async client."""
        import anthropic

        async def _go():
            client = anthropic.AsyncAnthropic(api_key=_DUMMY_KEY)
            async with client.messages.stream(
                model="claude-haiku-5-5", max_tokens=16,
                messages=[{"role": "user", "content": "hello"}],
            ) as stream:
                async for _ in stream:
                    pass

        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            asyncio.run(_go())

    def test_a_real_claude_agent_run_is_blocked(self):
        """End to end through a production agent on its default Claude slot:
        a forgotten `patch(...)` fails loudly instead of billing."""
        from agents.classifier import classifier_agent
        from agents.deps import SaplingDeps

        deps = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            asyncio.run(classifier_agent.run("a syllabus", deps=deps))


class TestRealSaplingCallPathsAreBlocked:
    """The synthetic-client tests above prove the seam; these prove it on the
    real, module-level clients Sapling actually builds at import time — the
    exact objects a forgotten `patch(...)` would leave live. (The
    gemini_service client this class also covered was deleted in #151b /
    ADR 0024; rag_service holds the one remaining module-level client.)"""

    def test_rag_service_embedding_is_blocked(self):
        """services/rag_service.py holds its own module-level genai.Client
        (the one #378 fixed the keyless construction of)."""
        from services.rag_service import _embed_query

        with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
            _embed_query("dynamic programming")


class TestPydanticAISharesTheSameSeam:
    """The agents run on pydantic-ai's AnthropicModel (or GoogleModel, for a
    slot pointed back at a gemini-* model), each wrapping an SDK client of its
    own. Patching the transport CLASS (rather than a client instance) is what
    makes those already-constructed provider clients blocked as well."""

    def test_agent_provider_client_transport_is_guarded(self):
        """#354/#436: there is no module-level provider singleton anymore
        (`agents._providers._LoopSafeProviderMixin` builds a fresh one per
        event loop) — but the guard patches the transport CLASS, not any one
        instance, so every provider any agent builds is covered regardless.
        Prove that on a model built the same way agents build theirs."""
        from anthropic._base_client import AsyncAPIClient

        from agents._providers import model_for

        client = model_for("classifier").client
        assert isinstance(client, AsyncAPIClient)
        assert getattr(type(client).request, "_sapling_llm_guard", False), (
            "pydantic-ai's Anthropic provider client is not covered by the LLM guard"
        )

    def test_gemini_slot_provider_client_transport_is_guarded(self):
        from google.genai._api_client import BaseApiClient

        from agents._providers import provider_model

        api_client = provider_model("gemini-2.5-flash-lite").client._api_client
        assert isinstance(api_client, BaseApiClient)
        assert getattr(type(api_client).request, "_sapling_llm_guard", False), (
            "pydantic-ai's Google provider client is not covered by the LLM guard"
        )


class TestGuardIsInstalledOnUnmarkedTests:
    def test_transport_methods_are_patched(self):
        from google.genai._api_client import BaseApiClient

        for name in ("request", "async_request", "request_streamed",
                     "async_request_streamed"):
            assert getattr(getattr(BaseApiClient, name), "_sapling_llm_guard", False), (
                f"BaseApiClient.{name} escaped the hermetic LLM guard"
            )

    def test_anthropic_transport_is_patched(self):
        from anthropic._base_client import AsyncAPIClient, SyncAPIClient

        for cls in (SyncAPIClient, AsyncAPIClient):
            assert getattr(cls.request, "_sapling_llm_guard", False), (
                f"{cls.__name__}.request escaped the hermetic LLM guard"
            )


class TestOptInLanesAreExempt:
    """The live lanes deliberately talk to a real model; the guard must step
    aside for them exactly the way the Supabase/auth guards already do."""

    @pytest.mark.live_llm
    def test_live_llm_marker_leaves_the_transport_alone(self):
        from anthropic._base_client import AsyncAPIClient
        from google.genai._api_client import BaseApiClient

        assert not getattr(BaseApiClient.request, "_sapling_llm_guard", False)
        assert not getattr(AsyncAPIClient.request, "_sapling_llm_guard", False)

    @pytest.mark.e2e_staging
    def test_e2e_staging_marker_leaves_the_transport_alone(self):
        from google.genai._api_client import BaseApiClient

        assert not getattr(BaseApiClient.request, "_sapling_llm_guard", False)

    @pytest.mark.integration
    def test_integration_marker_leaves_the_transport_alone(self):
        from google.genai._api_client import BaseApiClient

        assert not getattr(BaseApiClient.request, "_sapling_llm_guard", False)


def test_guard_is_restored_after_an_exempt_test():
    """monkeypatch teardown must put the real transport back, so an exempt test
    can't leave the next test unguarded (or vice versa)."""
    from anthropic._base_client import AsyncAPIClient
    from google.genai._api_client import BaseApiClient

    assert getattr(BaseApiClient.request, "_sapling_llm_guard", False)
    assert getattr(AsyncAPIClient.request, "_sapling_llm_guard", False)
