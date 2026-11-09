"""Full-request token preflight for the checklist's Gemini Developer API model.

Pydantic AI 1.107's Google counter omits system instructions and output schemas
on this API. Reuse google-genai 2.9's *generation* converter instead, then pass
the resulting request to the documented countTokens generateContentRequest
field through HttpOptions.extra_body. These deliberately pinned private SDK
conversion seams have wire-level regression tests; failure must stop generation.

The provider's count is an admission estimate, not a billing receipt. Client
timeouts cannot prove remote work stopped, and this is not a spend reservation.
"""

from __future__ import annotations

from copy import deepcopy

from google.genai import _common, models as google_models, types
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model, ModelRequestParameters, check_allow_model_requests
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage


class _ChecklistInputCounter(WrapperModel):
    async def count_tokens(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> RequestUsage:
        model = self.wrapped
        if isinstance(model, FunctionModel):
            # Explicit deterministic, non-billable test/E2E seam. FunctionModel
            # has no native tokenizer. This is never a real-provider fallback;
            # its returned response usage still meets the ordinary run limits.
            return RequestUsage(input_tokens=0)
        if not isinstance(model, GoogleModel) or model.system not in {"google", "google-gla"}:
            raise UserError("Checklist input counting requires the Gemini Developer API model.")

        check_allow_model_requests()
        settings, parameters = model.prepare_request(model_settings, model_request_parameters)
        contents, config = await model._build_content_and_config(
            messages, settings or {}, parameters
        )
        # Resolve the current loop's client once. Do not read the provider's
        # template client: Sapling's GoogleModel subclass is loop-affine.
        client = model.client
        if client._api_client.vertexai:
            raise UserError("Checklist full-request counting does not support Vertex AI.")
        generation = types._GenerateContentParameters(
            model=model.model_name,
            contents=contents,
            config=config,
        )
        wire = google_models._GenerateContentParameters_to_mldev(
            client._api_client,
            generation,
            None,
            generation,
        )
        url = wire.pop("_url")
        wire.pop("config", None)  # Same cleanup as SDK generate_content.
        wire = _common.encode_unserializable_types(_common.convert_to_dict(wire))
        if any(key.startswith("_") for key in wire) or not isinstance(url.get("model"), str):
            raise UnexpectedModelBehavior("Checklist generation envelope could not be counted.")
        wire["model"] = url["model"]

        options = deepcopy(config.get("http_options") or {})
        if options.get("extra_body"):
            # A future SDK adding generation-body patches must be reviewed for
            # equivalence rather than silently counting a different envelope.
            raise UserError("Checklist generation body overrides cannot be counted safely.")
        options["retry_options"] = {"attempts": 1}
        options["extra_body"] = {"contents": None, "generateContentRequest": wire}
        response = await client.aio.models.count_tokens(
            # The pinned SDK's internal parameter permits None; an empty list
            # is rejected before extra_body is applied. The REST request uses
            # generateContentRequest exclusively, not a placeholder prompt.
            model=model.model_name,
            contents=None,
            config={"http_options": options},
        )
        count = response.total_tokens
        # Real checklist requests always have system instructions, a schema,
        # and an evidence payload. A zero oracle result cannot describe them.
        if type(count) is not int or count <= 0:
            raise UnexpectedModelBehavior("Checklist token counter returned no valid token count.")
        return RequestUsage(input_tokens=count)


def wrap_topic_checklist_model(model: Model) -> Model:
    """Wrap only checklist models; generation and provider lifecycle delegate unchanged."""
    if isinstance(model, _ChecklistInputCounter):
        return model
    return _ChecklistInputCounter(model)
